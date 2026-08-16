# diagnose.py — 一键诊断：环境、CUDA/VRAM、设备、依赖可导入性
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check_import(name: str) -> str:
    try:
        importlib.import_module(name)
        return "OK"
    except Exception as e:
        return f"FAIL: {e}"


def main():
    report = {}
    print("=" * 60)
    print("Voice Translator 一键诊断")
    print("=" * 60)

    print("\n[1] Python")
    print(f"  {sys.version.split()[0]} @ {sys.executable}")
    report["python"] = sys.version.split()[0]

    print("\n[2] CUDA / GPU")
    try:
        import torch
        print(f"  torch={torch.__version__} cuda={torch.version.cuda}")
        print(f"  available={torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  device={torch.cuda.get_device_name(0)}")
            props = torch.cuda.get_device_properties(0)
            print(f"  vram_total={props.total_memory/1e9:.1f}GB")
            print(f"  alloc={torch.cuda.memory_allocated()/1e9:.2f}GB "
                  f"reserved={torch.cuda.memory_reserved()/1e9:.2f}GB")
        report["cuda"] = torch.cuda.is_available()
    except Exception as e:
        print(f"  torch 不可用: {e}")
        report["cuda"] = False

    print("\n[3] 依赖可导入性")
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "deps" / "CosyVoice"))
    sys.path.insert(0, str(root / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))
    sys.path.insert(0, str(root / "deps" / "fish-speech"))
    mods = ["sounddevice", "soundfile", "numpy", "funasr", "modelscope", "silero_vad",
            "torchaudio", "PySide6", "keyboard", "psutil", "scipy", "soxr",
            "cosyvoice", "fish_speech", "transformers", "einx", "whisper"]
    for m in mods:
        r = check_import(m)
        print(f"  {m:20s} {r}")
        report[m] = r.startswith("OK")

    print("\n[4] 模型文件")
    models_dir = Path(__file__).resolve().parent.parent / "models"
    expected = {
        "paraformer-streaming": "model.pt",
        "CosyVoice3-0.5B": ["llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx", "campplus.onnx"],
        "fish-speech-1.5": ["firefly-gan-vq-fsq-8x1024-21hz-generator.pth"],
    }
    for name, files in expected.items():
        d = models_dir / name
        if not d.exists():
            print(f"  {name:20s} 缺失（目录不存在）")
            report[name] = False
            continue
        missing = [f for f in (files if isinstance(files, list) else [files]) if not (d / f).exists()]
        print(f"  {name:20s} {'OK' if not missing else '缺: ' + ','.join(missing)}")
        report[name] = not missing

    print("\n[5] VB-CABLE")
    from app.audio import devices
    print(f"  cable_installed={devices.cable_installed()}")
    report["vb_cable"] = devices.cable_installed()

    out = Path("logs")
    out.mkdir(exist_ok=True)
    (out / "diagnose.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n报告写入 logs/diagnose.json")


if __name__ == "__main__":
    main()