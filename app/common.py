import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOGGER_LOCK = threading.Lock()
_initialized = False


def setup_logging(log_dir: Path | None = None, level: str = "INFO") -> None:
    """日志：logs/app.log（含 timestamp/component/level/event/latency）"""
    global _initialized
    with LOGGER_LOCK:
        if _initialized:
            return
        log_dir = log_dir or (ROOT / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        root = logging.getLogger()
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        fmt = logging.Formatter("%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
        _initialized = True
        root.info("=== Voice Realtime session start %s ===", datetime.now().isoformat())


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(component)


def now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def fmt_dur(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000.0:.2f}s"
    return f"{ms:.0f}ms"


def load_json(path: Path, default: dict | None = None) -> dict:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logging.getLogger("config").warning("load %s failed: %s", path, e)
    return default if default is not None else {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
