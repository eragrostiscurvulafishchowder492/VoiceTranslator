"""CosyVoice 3 TTS 后端（zero-shot voice cloning，日语参考 → 中文输出）。

- 模型：Fun-CosyVoice3-0.5B-2512（本地目录或 modelscope id）
- 仓库：deps/CosyVoice（含 third_party/Matcha-TTS），通过 COSYVOICE_REPO 环境变量/参数指定
- 参考音频 embedding 在 load_reference 时用 add_zero_shot_spk 预计算缓存
- 流式：stream=True 逐 chunk 产出；speed != 1.0 时退回非流式（模型限制）
"""
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from app.common import ROOT, get_logger, now_ms
from app.tts.base import TTSEngine, TTSStyle

log = get_logger("tts.cosyvoice")

DEFAULT_REPO = ROOT / "deps" / "CosyVoice"
DEFAULT_MODEL = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
_LOCAL_MODEL = ROOT / "models" / "CosyVoice3-0.5B"


def _resolve_model_dir(model_dir: str) -> str:
    """本地模型存在则优先用本地路径（避免 modelscope 缓存重复下载）。"""
    if model_dir:
        return model_dir
    if _LOCAL_MODEL.exists() and (_LOCAL_MODEL / "llm.pt").exists():
        return str(_LOCAL_MODEL)
    return DEFAULT_MODEL


def _setup_syspath(repo: Path) -> None:
    repo = Path(repo)
    matcha = repo / "third_party" / "Matcha-TTS"
    for p in (repo, matcha):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    if str(repo.parent) not in sys.path:
        sys.path.insert(0, str(repo.parent))


class CosyVoiceEngine(TTSEngine):
    name = "cosyvoice"
    sample_rate = 24000
    streaming = True

    def __init__(self, model_dir: str = "", repo_dir: str = "", device: str = "cuda",
                 fp16: bool = True, flow_steps: int = 10, fast_llm: bool = True):
        self.model_dir = _resolve_model_dir(model_dir)
        self.repo_dir = Path(repo_dir or DEFAULT_REPO)
        self.device = device
        self.fp16 = fp16 and device == "cuda"
        self.flow_steps = flow_steps
        self.fast_llm = fast_llm and device == "cuda"
        self._patched = False
        self._model = None
        self._lock = threading.Lock()
        self._interrupt = threading.Event()
        self._spk_id = ""
        self._ref_path = ""
        self._ref_text = ""
        self.ttfa_ms = 0
        self.gen_ms = 0

    # ---------------- lifecycle ----------------
    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            _setup_syspath(self.repo_dir)
            from cosyvoice.cli.cosyvoice import AutoModel
            if not self._patched:
                self._patch_flow_steps()
            log.info("loading CosyVoice3 model %s (fp16=%s) on %s", self.model_dir, self.fp16, self.device)
            t0 = now_ms()
            model = AutoModel(model_dir=self.model_dir, fp16=self.fp16)
            self._apply_flow_steps(model)
            self._apply_fast_llm(model)
            log.info("CosyVoice3 loaded in %d ms", now_ms() - t0)
            self._model = model
            return model

    def load_reference(self, ref_path: str, ref_text: str = "", profile: str = "default") -> None:
        model = self._ensure_model()
        ref_path = str(ref_path)
        if ref_path == self._ref_path and ref_text == self._ref_text and self._spk_id:
            return
        spk_id = f"user_{profile}"
        t0 = now_ms()
        # CosyVoice3 prompt 模板（官方 example）：
        # prompt_text 格式 'You are a helpful assistant.<|endofprompt|><转写文本>'
        # 无转写时走 cross_lingual（仅用音色 embedding，无需参考文本，适合日语参考→中文输出）
        if ref_text.strip():
            prompt_text = f"You are a helpful assistant.<|endofprompt|>{ref_text.strip()}"
        else:
            prompt_text = "You are a helpful assistant.<|endofprompt|>"
        try:
            model.add_zero_shot_spk(prompt_text=prompt_text, prompt_wav=ref_path, zero_shot_spk_id=spk_id)
        except Exception as e:
            log.warning("add_zero_shot_spk failed (%s), will recompute per utterance", e)
            spk_id = ""
        self._spk_id = spk_id
        self._ref_path = ref_path
        self._ref_text = ref_text
        log.info("reference cached in %d ms (spk=%s)", now_ms() - t0, spk_id or "none")

    def reload_reference(self) -> None:
        if self._ref_path:
            self.load_reference(self._ref_path, self._ref_text)

    def interrupt(self) -> None:
        self._interrupt.set()

    def unload(self) -> None:
        with self._lock:
            self._model = None
            import gc
            gc.collect()
            if self.device == "cuda":
                import torch
                torch.cuda.empty_cache()

    # ---------------- synthesis ----------------
    def _patch_flow_steps(self) -> None:
        """运行时包装 flow 采样步数（不修改 deps 仓库，避免影响 git 状态）。"""
        try:
            import cosyvoice.flow.flow_matching as fm
            for cls in (fm.ConditionalCFM, fm.CausalConditionalCFM):
                if "_mcp_patched" in cls.__dict__:
                    continue
                orig = cls.forward

                def _patched(self_cfm, *a, **k):
                    steps = getattr(self_cfm, "_mcp_flow_steps", None)
                    if steps is not None and "n_timesteps" in k:
                        k["n_timesteps"] = steps
                    return orig(self_cfm, *a, **k)

                cls.forward = _patched
                cls._mcp_patched = True
            self._patched = True
            log.info("flow steps patched (default %d)", self.flow_steps)
        except Exception as e:
            log.warning("flow steps patch failed: %s", e)

    def _apply_flow_steps(self, model) -> None:
        try:
            cfm = getattr(getattr(model, "model", None), "flow", None) or getattr(model, "flow", None)
            if cfm is None:
                return
            cfm = cfm.decoder
            if hasattr(cfm, "_mcp_flow_steps") and cfm._mcp_flow_steps == self.flow_steps:
                return
            cfm._mcp_flow_steps = self.flow_steps
            log.info("flow steps set to %d", self.flow_steps)
        except Exception as e:
            log.warning("apply flow steps failed: %s", e)

    def _apply_fast_llm(self, model) -> None:
        """用精简版 Qwen2 解码器替换 transformers eager 路径（绕过 Windows 上高 CPU 分派开销）。

        输出与原生 forward_one_step 逐位一致（实测 max_abs_diff=0）；失败时回退原生。
        """
        if not self.fast_llm:
            return
        try:
            from app.tts.fast_llm import install_fast_llm
            encoder = getattr(getattr(model, "model", None), "llm", None)
            if encoder is None or not hasattr(encoder, "llm"):
                encoder = getattr(model, "llm", None)
            if encoder is None:
                return
            install_fast_llm(encoder.llm, fp16=True)
            log.info("fast llm decoder installed")
        except Exception as e:
            log.warning("fast llm install failed, fallback to eager: %s", e)

    def synthesize_stream(self, text: str, style: TTSStyle | None = None, _force_stream: bool | None = None):
        style = style or TTSStyle()
        model = self._ensure_model()
        self._interrupt.clear()
        speed = float(style.speed)
        stream = self.streaming and abs(speed - 1.0) < 1e-3
        if _force_stream is not None:
            stream = _force_stream

        def _iter():
            t0 = now_ms()
            try:
                if self._ref_text.strip():
                    # 有参考转写：zero-shot 模式（含 prompt text 引导）
                    gen = model.inference_zero_shot(
                        text,
                        self._ref_text,
                        self._ref_path or "",
                        zero_shot_spk_id=self._spk_id,
                        stream=stream,
                        speed=speed,
                        text_frontend=True,
                    )
                else:
                    # 无参考转写（如日语参考）：cross-lingual 模式，仅音色 embedding
                    gen = model.inference_cross_lingual(
                        text,
                        self._ref_path or "",
                        zero_shot_spk_id=self._spk_id,
                        stream=stream,
                        speed=speed,
                        text_frontend=True,
                    )
                first = True
                for out in gen:
                    if self._interrupt.is_set():
                        break
                    speech = out["tts_speech"].squeeze(0).float().cpu().numpy()
                    if first:
                        self.ttfa_ms = now_ms() - t0
                        first = False
                    yield speech.astype(np.float32)
                self.gen_ms = now_ms() - t0
            except Exception as e:
                log.error("cosyvoice synthesis error: %s", e, exc_info=True)
                raise

        return _iter()

    def synth_to_wav(self, text: str, style: TTSStyle | None, out_path: str) -> None:
        """Voice Lab / benchmark 用：生成并保存 wav。"""
        import torchaudio
        audio = self.synthesize(text, style)
        torchaudio.save(out_path, torch.from_numpy(audio).unsqueeze(0), self.sample_rate)
        return out_path