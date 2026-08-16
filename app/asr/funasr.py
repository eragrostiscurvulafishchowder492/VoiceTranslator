"""FunASR paraformer-zh-streaming 流式 ASR 引擎（CUDA fp16）。"""
import threading

import numpy as np

from app.asr.base import ASREngine
from app.common import get_logger, now_ms

log = get_logger("asr.funasr")

MODEL_NAME = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
PUNC_MODEL = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
_LOCAL_MODEL = None


def _resolve_model_dir(model_dir: str) -> str:
    global _LOCAL_MODEL
    if model_dir:
        return model_dir
    if _LOCAL_MODEL is None:
        from app.common import ROOT
        cand = ROOT / "models" / "paraformer-streaming"
        _LOCAL_MODEL = str(cand) if (cand / "model.pt").exists() else ""
    return _LOCAL_MODEL or MODEL_NAME


class FunASREngine(ASREngine):
    name = "funasr"

    def __init__(self, device: str = "cuda", model_dir: str = "",
                 chunk_size=None, encoder_look_back: int = 4,
                 decoder_look_back: int = 1, hotwords: str = "",
                 punc_model: bool = False, on_partial=None, on_final=None):
        self.device = device
        self.model_dir = _resolve_model_dir(model_dir)
        self.chunk_size = chunk_size or [0, 10, 5]
        self.enc_lb = encoder_look_back
        self.dec_lb = decoder_look_back
        self.hotwords = hotwords
        self.use_punc = punc_model
        self.on_partial = on_partial    # fn(text, stable_ok)
        self.on_final = on_final        # fn(final_text)
        self._model = None
        self._punc = None
        self._cache = {}
        self._buf = np.zeros(0, dtype=np.float32)
        self._text = ""
        self._lock = threading.Lock()
        self._started = False
        self.partial_count = 0
        self._last_partial_ms = 0

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._started:
            return
        from funasr import AutoModel
        log.info("loading ASR model %s on %s", self.model_dir, self.device)
        kw = {"device": self.device, "disable_update": True}
        if self.hotwords:
            kw["hotword"] = self.hotwords
        self._model = AutoModel(model=self.model_dir, **kw)
        if self.use_punc:
            try:
                self._punc = AutoModel(model=PUNC_MODEL, device="cpu", disable_update=True)
                log.info("punc model loaded")
            except Exception as e:
                log.warning("punc model load failed: %s", e)
                self._punc = None
        self._started = True
        self.reset()
        log.info("ASR ready")

    def unload(self) -> None:
        if self._model is not None:
            try:
                self._model = None
            except Exception:
                pass
        self._started = False

    # ---------- streaming ----------
    def reset(self) -> None:
        with self._lock:
            self._cache = {}
            self._buf = np.zeros(0, dtype=np.float32)
            self._text = ""

    def push_audio(self, audio: np.ndarray) -> None:
        if self._model is None or len(audio) == 0:
            return
        with self._lock:
            self._buf = np.concatenate([self._buf, audio.astype(np.float32)])
            stride = self.chunk_size[1] * 960
            while len(self._buf) >= stride:
                chunk = self._buf[:stride]
                self._buf = self._buf[stride:]
                self._step(chunk, is_final=False)

    def get_partial_text(self) -> str:
        with self._lock:
            return self._text

    def finalize_segment(self) -> str:
        """flush 段尾音频 + is_final=True，返回最终文本。"""
        with self._lock:
            if self._model is None:
                return self._text
            if len(self._buf) > 0:
                self._step(self._buf, is_final=True)
                self._buf = np.zeros(0, dtype=np.float32)
            else:
                self._step(np.zeros(960, dtype=np.float32), is_final=True)
            final = self._text
            if self._punc is not None and final.strip():
                try:
                    res = self._punc.generate(input=final)
                    final = res[0]["text"]
                except Exception as e:
                    log.warning("punc failed: %s", e)
            self._cache = {}
            self._text = ""
            if self.on_final:
                self.on_final(final)
            return final

    def _step(self, chunk: np.ndarray, is_final: bool) -> None:
        t0 = now_ms()
        try:
            res = self._model.generate(
                input=chunk, cache=self._cache, is_final=is_final,
                chunk_size=self.chunk_size,
                encoder_chunk_look_back=self.enc_lb,
                decoder_chunk_look_back=self.dec_lb,
            )
            text = res[0]["text"] or ""
            if text:
                self._text = self._merge(self._text, text)
                self.partial_count += 1
                self._last_partial_ms = now_ms() - t0
                if self.on_partial:
                    try:
                        self.on_partial(self._text)
                    except Exception as e:
                        log.error("on_partial error: %s", e)
        except Exception as e:
            log.error("ASR step error: %s", e)

    @staticmethod
    def _merge(acc: str, new: str) -> str:
        """流式增量文本合并：检测 new 与 acc 尾部的重叠，避免重复与丢字。"""
        if not new:
            return acc
        if acc.endswith(new):
            return acc
        for k in range(min(len(acc), len(new)), 0, -1):
            if acc.endswith(new[:k]):
                return acc + new[k:]
        return acc + new

    @property
    def partial_latency_ms(self) -> int:
        return self._last_partial_ms