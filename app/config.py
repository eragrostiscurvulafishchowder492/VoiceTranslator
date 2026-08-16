"""全局配置：config/settings.json，自动保存 GUI 修改。"""
from dataclasses import dataclass, field, asdict
from pathlib import Path

from app.common import ROOT, get_logger, load_json, save_json

log = get_logger("config")

CONFIG_PATH = ROOT / "config" / "settings.json"

DEFAULT_HOTKEYS = {
    "ptt": "F8",
    "mute": "F9",
    "clear_queue": "F10",
    "interrupt": "F11",
}


@dataclass
class AppSettings:
    # --- devices ---
    mic_device: str = ""
    virtual_output: str = ""
    monitor_output: str = ""
    output_sample_rate: int = 48000
    input_block_ms: int = 20
    input_gain_db: float = 0.0
    monitor_enabled: bool = False
    monitor_gain_db: float = -6.0

    # --- engine ---
    asr_engine: str = "funasr"
    tts_engine: str = "cosyvoice"          # cosyvoice | fish
    tts_model_dir: str = ""                # cosyvoice 模型目录（本地路径）
    vram_mode: str = "balanced"            # balanced | asr_cpu
    asr_device: str = "cuda"               # cuda | cpu
    tts_device: str = "cuda"

    # --- reference ---
    reference_profile: str = ""            # profiles.json 中的 key

    # --- mode / hotkeys ---
    listen_mode: str = "ptt"               # ptt | always
    hotkeys: dict = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    # --- vad ---
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 180
    vad_silence_end_ms: int = 700
    vad_pre_speech_ms: int = 250

    # --- segmentation ---
    stable_rounds: int = 4
    max_segment_chars: int = 26
    flush_timeout_ms: int = 1500
    punctuation_pause: dict = field(default_factory=lambda: {
        "comma": 0.15, "sentence": 0.35, "question": 0.4, "ellipsis": 0.6, "between": 0.5,
    })

    # --- voice (Mutsumi-like style profile) ---
    speaking_speed: float = 0.95
    emotion: str = "calm"                  # calm | neutral | soft
    energy: float = 0.9
    pitch: float = 0.0
    breathiness: float = 0.0
    text_mode: str = "gaming"              # gaming | normal

    # --- asr advanced ---
    asr_hotwords: str = ""
    asr_chunk_size: list = field(default_factory=lambda: [0, 10, 5])
    asr_punc_model: bool = False

    # --- tts advanced ---
    tts_stream_chunk: int = 4
    tts_max_retries: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AppSettings":
        known = {f for f in cls.__dataclass_fields__}
        merged = {k: v for k, v in d.items() if k in known}
        s = cls(**merged)
        s.hotkeys = {**DEFAULT_HOTKEYS, **d.get("hotkeys", {})}
        return s

    def save(self) -> None:
        try:
            save_json(CONFIG_PATH, self.to_dict())
        except Exception as e:
            log.error("save settings failed: %s", e)

    @staticmethod
    def load() -> "AppSettings":
        s = AppSettings.from_dict(load_json(CONFIG_PATH, {}))
        log.info("settings loaded from %s", CONFIG_PATH)
        return s
