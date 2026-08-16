# download_models.py — 下载三个模型到 models/（modelscope 优先，HF 回退）
#  - paraformer-streaming (modelscope iic)
#  - CosyVoice3-0.5B (HF FunAudioLLM; modelscope 回退)
#  - fish-speech-1.5 LLM + firefly-gan-vq-fsq-8x1024-21hz-generator.pth
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MODELS.mkdir(exist_ok=True)

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "")


def dl_modelscope(model_id: str, local: Path) -> bool:
    try:
        from modelscope import snapshot_download
        snapshot_download(model_id, local_dir=str(local))
        return True
    except Exception as e:
        print(f"[modelscope] {model_id} 失败: {e}")
        return False


def dl_hf(repo_id: str, local: Path) -> bool:
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id, local_dir=str(local))
        return True
    except Exception as e:
        print(f"[hf] {repo_id} 失败: {e}")
        return False


def main():
    jobs = [
        # (name, modelscope_id, hf_id, subpath_for_vq_skip)
        ("paraformer-streaming", "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online", None, None),
        ("CosyVoice3-0.5B", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512", None),
        ("fish-speech-1.5", None, "fishaudio/fish-speech-1.5", None),
    ]
    for name, ms_id, hf_id, _ in jobs:
        local = MODELS / name
        done = local.exists() and ((local / ".completed").exists() or any(local.iterdir()))
        if done:
            print(f"[skip] {name} 已存在")
            continue
        print(f"[download] {name} ...")
        ok = False
        if ms_id:
            ok = dl_modelscope(ms_id, local)
        if not ok and hf_id:
            ok = dl_hf(hf_id, local)
        if ok:
            (local / ".completed").write_text("ok", encoding="utf-8")
            print(f"[done] {name}")
        else:
            print(f"[FAIL] {name} 下载失败")

    # fish VQGAN generator（不在 HF repo 内，单独下载）
    vq = MODELS / "fish-speech-1.5" / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
    if not vq.exists():
        import requests
        url = "https://huggingface.co/fishaudio/fish-speech-1.5/resolve/main/firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
        print(f"[download] fish VQGAN ({vq.name}) ...")
        try:
            r = requests.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with open(vq, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            print("[done] fish VQGAN")
        except Exception as e:
            print(f"[FAIL] fish VQGAN: {e}")

    print("\n全部完成。缺失项请手动下载后放入 models/。")


if __name__ == "__main__":
    main()