"""Fish Speech 1.5 TTS 后端（zero-shot voice cloning，对照音质用）。

- 模型：fishaudio/fish-speech-1.5（LLM）+ firefly-gan-vq-fsq-8x1024-21hz-generator.pth
- 代码：deps/fish-speech（Apache-2.0），pip install -e --no-deps + 最小依赖
- 非流式生成（整句），适合 Voice Lab A/B 与对照使用
- 注：Fish Audio S2 官方要求 >=24GB VRAM，RTX 4060 Laptop 不可行；
      S1-mini 需要整套仓库安装，留作后续升级选项。
"""
import sys
import threading
import time
from pathlib import Path

import numpy as np

from app.common import ROOT, get_logger, now_ms
from app.tts.base import TTSEngine, TTSStyle

log = get_logger("tts.fish")

DEFAULT_REPO = ROOT / "deps" / "fish-speech"
MODEL_DIR = ROOT / "models" / "fish-speech-1.5"
CODEGEN_URL = "https://github.com/fishaudio/fish-speech/releases/download/v1.5.1/firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
CODEGEN_PATH = ROOT / "models" / "fish-speech-1.5" / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"


class FishSpeechEngine(TTSEngine):
    name = "fish"
    sample_rate = 44100
    streaming = False

    def __init__(self, model_dir: str = "", repo_dir: str = "", device: str = "cuda", fp16: bool = False):
        self.model_dir = Path(model_dir or MODEL_DIR)
        self.repo_dir = Path(repo_dir or DEFAULT_REPO)
        self.device = device
        self.fp16 = fp16
        self._llm = None
        self._decode = None
        self._vq = None
        self._lock = threading.Lock()
        self._codes = None
        self._ref_path = ""
        self._ref_text = ""
        self.ttfa_ms = 0
        self.gen_ms = 0

    def _ensure_syspath(self) -> None:
        rp = str(self.repo_dir)
        if rp not in sys.path:
            sys.path.insert(0, rp)

    # ---------------- lifecycle ----------------
    def _ensure_model(self):
        if self._llm is not None:
            return
        with self._lock:
            if self._llm is not None:
                return
            import torch
            self._ensure_syspath()
            from fish_speech.models.text2semantic.inference import load_model
            precision = torch.float16 if self.fp16 else torch.bfloat16
            log.info("loading fish-speech-1.5 LLM from %s (%s)", self.model_dir, "fp16" if self.fp16 else "bf16")
            t0 = now_ms()
            model, decode = load_model(str(self.model_dir), self.device, precision, compile=False)
            with torch.device(self.device):
                model.setup_caches(
                    max_batch_size=1,
                    max_seq_len=model.config.max_seq_len,
                    dtype=next(model.parameters()).dtype,
                )
            self._llm = model
            self._decode = decode
            log.info("fish LLM loaded in %d ms", now_ms() - t0)
            self._ensure_vq()

    def _ensure_vq(self):
        if self._vq is not None:
            return
        import torch
        from fish_speech.models.vqgan.modules.firefly import FireflyArchitecture
        from fish_speech.models.vqgan.modules.firefly import ConvNeXtEncoder, HiFiGANGenerator
        from fish_speech.models.vqgan.modules.fsq import DownsampleFiniteScalarQuantize
        from fish_speech.utils.spectrogram import LogMelSpectrogram

        if not CODEGEN_PATH.exists():
            raise FileNotFoundError(
                f"缺少 VQGAN 权重: {CODEGEN_PATH}\n请运行 scripts/setup.ps1 或手动下载:\n{CODEGEN_URL}"
            )
        arch = FireflyArchitecture(
            spec_transform=LogMelSpectrogram(sample_rate=44100, n_mels=160, n_fft=2048,
                                             hop_length=512, win_length=2048),
            backbone=ConvNeXtEncoder(input_channels=160, depths=[3, 3, 9, 3],
                                     dims=[128, 256, 384, 512], drop_path_rate=0.2, kernel_size=7),
            head=HiFiGANGenerator(hop_length=512, upsample_rates=[8, 8, 2, 2, 2],
                                  upsample_kernel_sizes=[16, 16, 4, 4, 4],
                                  resblock_kernel_sizes=[3, 7, 11],
                                  resblock_dilation_sizes=[[1, 3, 5], [1, 3, 5], [1, 3, 5]],
                                  num_mels=512, upsample_initial_channel=512,
                                  pre_conv_kernel_size=13, post_conv_kernel_size=13),
            quantizer=DownsampleFiniteScalarQuantize(input_dim=512, n_groups=8, n_codebooks=1,
                                                     levels=[8, 5, 5, 5], downsample_factor=[2, 2]),
        )
        state = torch.load(CODEGEN_PATH, map_location=self.device, weights_only=True)
        if "state_dict" in state:
            state = state["state_dict"]
        if any("generator" in k for k in state):
            state = {k.replace("generator.", ""): v for k, v in state.items() if "generator." in k}
        arch.load_state_dict(state, strict=False, assign=True)
        arch.eval().to(self.device)
        self._vq = arch
        log.info("fish VQGAN loaded")

    def load_reference(self, ref_path: str, ref_text: str = "", profile: str = "default") -> None:
        self._ensure_model()
        ref_path = str(ref_path)
        if ref_path == self._ref_path and ref_text == self._ref_text and self._codes is not None:
            return
        import torch
        import torchaudio
        from fish_speech.utils.spectrogram import LogMelSpectrogram

        t0 = now_ms()
        audio, sr = torchaudio.load(ref_path)
        if audio.shape[0] > 1:
            audio = audio.mean(0, keepdim=True)
        audio = torchaudio.functional.resample(audio, sr, 44100)
        audio = audio[None].to(self.device)
        lengths = torch.tensor([audio.shape[2]], device=self.device, dtype=torch.long)
        with torch.inference_mode():
            indices = self._vq.encode(audio, lengths)[0][0]
        self._codes = indices.cpu()
        self._ref_path = ref_path
        self._ref_text = ref_text
        log.info("fish reference VQ codes cached in %d ms (shape=%s)", now_ms() - t0, tuple(self._codes.shape))

    def reload_reference(self) -> None:
        if self._ref_path:
            self.load_reference(self._ref_path, self._ref_text)

    def interrupt(self) -> None:
        pass  # 非流式生成不中断（由调度层丢弃结果）

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._decode = None
            self._vq = None
            import gc
            gc.collect()
            if self.device == "cuda":
                import torch
                torch.cuda.empty_cache()

    # ---------------- synthesis ----------------
    def synthesize_stream(self, text: str, style: TTSStyle | None = None):
        style = style or TTSStyle()
        self._ensure_model()
        if self._codes is None:
            raise RuntimeError("请先加载参考音频 (load_reference)")

        import torch
        from fish_speech.models.text2semantic.inference import generate_long
        from fish_speech.models.text2semantic.inference import GenerateResponse

        prompt_tokens = self._codes.to(self.device)
        prompt_text = self._ref_text or ""

        def _iter():
            t0 = now_ms()
            first = True
            try:
                gen = generate_long(
                    model=self._llm,
                    device=self.device,
                    decode_one_token=self._decode,
                    text=text,
                    num_samples=1,
                    max_new_tokens=0,
                    top_p=0.7,
                    repetition_penalty=1.2,
                    temperature=0.7,
                    compile=False,
                    iterative_prompt=False,
                    max_length=2048,
                    chunk_length=200,
                    prompt_text=prompt_text if prompt_text.strip() else None,
                    prompt_tokens=prompt_tokens if prompt_text.strip() else None,
                )
                codes = []
                for resp in gen:
                    if resp.action == "sample":
                        codes.append(resp.codes)
                if codes:
                    all_codes = torch.cat(codes, dim=1).cpu()
                    feature_lengths = torch.tensor([all_codes.shape[1]], device=self.device)
                    with torch.inference_mode():
                        fake, _ = self._vq.decode(indices=all_codes.to(self.device).unsqueeze(0),
                                                  feature_lengths=feature_lengths)
                    audio = fake[0, 0].float().cpu().numpy()
                    if first:
                        self.ttfa_ms = now_ms() - t0
                        first = False
                    yield audio.astype(np.float32)
                self.gen_ms = now_ms() - t0
            except Exception as e:
                log.error("fish synthesis error: %s", e, exc_info=True)
                raise

        return _iter()

    def synth_to_wav(self, text: str, style: TTSStyle | None, out_path: str) -> None:
        import soundfile as sf
        audio = self.synthesize(text, style)
        sf.write(out_path, audio, self.sample_rate)
        return out_path