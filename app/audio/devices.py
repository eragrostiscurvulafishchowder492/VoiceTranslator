"""Windows 音频设备枚举（动态，禁止硬编码）。"""
import re

import sounddevice as sd

from app.common import get_logger

log = get_logger("audio.devices")


def list_input_devices() -> list[dict]:
    return _list("in")


def list_output_devices() -> list[dict]:
    return _list("out")


def _list(direction: str) -> list[dict]:
    devices = []
    try:
        infos = sd.query_devices()
        for i, info in enumerate(infos):
            max_ch = info["max_input_channels"] if direction == "in" else info["max_output_channels"]
            if max_ch <= 0:
                continue
            name = info["name"]
            default_sr = int(info["default_samplerate"])
            devices.append({
                "index": i,
                "name": name,
                "channels": int(max_ch),
                "default_samplerate": default_sr,
                "hostapi": sd.query_hostapis(info["hostapi"])["name"],
            })
    except Exception as e:
        log.error("device enumeration failed: %s", e)
    devices.sort(key=lambda d: (not _is_virtual(d["name"]), d["name"]))
    return devices


def _is_virtual(name: str) -> bool:
    return bool(re.search(r"cable|virtual|vb-audio|wave", name, re.IGNORECASE))


def find_cable_device(direction: str = "out") -> dict | None:
    """VB-CABLE：输出端 'CABLE Input' 对应虚拟声卡，聊天软件选 'CABLE Output'。"""
    pool = list_input_devices() if direction == "in" else list_output_devices()
    for d in pool:
        if re.search(r"cable input", d["name"], re.IGNORECASE):
            return d
    for d in pool:
        if re.search(r"cable", d["name"], re.IGNORECASE):
            return d
    return None


def cable_installed() -> bool:
    return find_cable_device("out") is not None or find_cable_device("in") is not None


def device_by_name(devices: list[dict], name: str) -> dict | None:
    if not name:
        return None
    for d in devices:
        if d["name"] == name:
            return d
    return None


def default_device(direction: str) -> dict | None:
    try:
        if direction == "in":
            i = sd.default.device[0]
        else:
            i = sd.default.device[1]
        if i is None or i < 0:
            return None
        info = sd.query_devices(i)
        max_ch = info["max_input_channels"] if direction == "in" else info["max_output_channels"]
        if max_ch <= 0:
            return None
        return {
            "index": int(i), "name": info["name"], "channels": int(max_ch),
            "default_samplerate": int(info["default_samplerate"]),
            "hostapi": sd.query_hostapis(info["hostapi"])["name"],
        }
    except Exception as e:
        log.error("default %s device query failed: %s", direction, e)
        return None


def refresh_devices() -> dict:
    """GUI 刷新用：返回当前设备集，并检测 VB-CABLE 存在性。"""
    ins = list_input_devices()
    outs = list_output_devices()
    return {
        "inputs": ins,
        "outputs": outs,
        "cable": cable_installed(),
        "default_in": default_device("in"),
        "default_out": default_device("out"),
    }