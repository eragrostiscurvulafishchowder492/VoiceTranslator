"""GPU 诊断：VRAM 监控（nvidia-smi）、CUDA 检查。"""
import json
import re
import subprocess
import threading

import psutil

from app.common import get_logger

log = get_logger("diagnostics.gpu")

_lru = {"vram": -1, "t": 0.0}
_lru_lock = threading.Lock()


def query_vram_mb() -> int:
    """当前进程 CUDA 显存占用（MB）。"""
    try:
        import torch
        if torch.cuda.is_available():
            used = torch.cuda.memory_allocated() + torch.cuda.memory_reserved()
            return int(used / (1024 * 1024))
    except Exception:
        pass
    return 0


def query_gpu_total_used_mb() -> int:
    """整卡显存占用（MB），用 nvidia-smi。"""
    now = __import__("time").time()
    with _lru_lock:
        if _lru["vram"] > 0 and now - _lru["t"] < 1.0:
            return _lru["vram"]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
        v = int(out.splitlines()[0].strip()) if out.strip() else -1
        with _lru_lock:
            _lru["vram"] = v
            _lru["t"] = now
        return v
    except Exception:
        return -1


def cuda_info() -> dict:
    info = {"cuda_available": False}
    try:
        import torch
        info["cuda_available"] = torch.cuda.is_available()
        if info["cuda_available"]:
            info["device"] = torch.cuda.get_device_name(0)
            info["capability"] = torch.cuda.get_device_capability(0)
            info["vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
            props = torch.cuda.get_device_properties(0)
            info["vram_free_gb"] = round((props.total_memory - torch.cuda.memory_reserved()) / 1e9, 1)
    except Exception as e:
        info["error"] = str(e)
    return info


def vram_profile_summary() -> str:
    """返回一键诊断文本（benchmark/diagnose 用）。"""
    try:
        import torch
        lines = []
        lines.append(f"CUDA: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            alloc = torch.cuda.memory_allocated() / 1e9
            resv = torch.cuda.memory_reserved() / 1e9
            total = props.total_memory / 1e9
            lines.append(f"Device: {torch.cuda.get_device_name(0)}")
            lines.append(f"VRAM: total={total:.1f}GB allocated={alloc:.2f}GB reserved={resv:.2f}GB")
        lines.append(f"Whole-GPU used: {query_gpu_total_used_mb()} MB (nvidia-smi)")
        return "\n".join(lines)
    except Exception as e:
        return f"vram profile error: {e}"


def system_snapshot() -> dict:
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_used_gb": round(vm.used / 1e9, 1),
        "ram_total_gb": round(vm.total / 1e9, 1),
        "threads": len(psutil.Process().threads()),
    }