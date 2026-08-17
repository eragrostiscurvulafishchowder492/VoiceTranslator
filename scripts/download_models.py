"""Download model snapshots only when every mutable upstream ref is pinned.

Large model downloads are intentionally opt-in. Run with --help first; this
script exits before creating models/ when any required revision is missing.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
FISH_VQ_NAME = "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
FISH_VQ_URL = (
    "https://github.com/fishaudio/fish-speech/releases/download/v1.5.1/"
    + FISH_VQ_NAME
)


def pinned_provider_revision(value: str) -> str:
    if not value or value.strip() != value or value.lower() in {"main", "master", "head", "latest"}:
        raise argparse.ArgumentTypeError(
            "revision 必须是非空明确 pin，不能是 main/master/HEAD/latest"
        )
    return value


def hf_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("Hugging Face revision 必须是 40 位 commit SHA")
    return value.lower()


def sha256_value(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise argparse.ArgumentTypeError("SHA-256 必须是 64 位十六进制")
    return value.lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Voice Studio models at owner-approved immutable revisions."
    )
    parser.add_argument("--paraformer-ms-revision", required=True, type=pinned_provider_revision)
    parser.add_argument("--cosyvoice-ms-revision", required=True, type=pinned_provider_revision)
    parser.add_argument("--cosyvoice-hf-revision", required=True, type=hf_commit)
    parser.add_argument("--fish-hf-revision", type=hf_commit)
    parser.add_argument("--fish-vq-sha256", type=sha256_value)
    args = parser.parse_args()
    if bool(args.fish_hf_revision) != bool(args.fish_vq_sha256):
        parser.error("--fish-hf-revision 与 --fish-vq-sha256 必须同时提供")
    return args


def marker_path(local: Path) -> Path:
    return local / ".completed"


def required_files_exist(local: Path, required_files: tuple[str, ...]) -> bool:
    return all((local / relative).is_file() for relative in required_files)


def marker_matches(
    local: Path, provenance: dict[str, str], required_files: tuple[str, ...]
) -> bool:
    marker = marker_path(local)
    if not marker.exists():
        return False
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value == provenance and required_files_exist(local, required_files)


def refuse_unverified_existing(local: Path, description: str) -> None:
    if local.exists() and any(local.iterdir()):
        raise RuntimeError(
            f"{local} 已有内容，但 .completed 与必需文件未验证为 {description}；"
            "不覆盖或假定现有大模型的来源"
        )


def write_marker(local: Path, provenance: dict[str, str]) -> None:
    temporary_marker = local / ".completed.tmp"
    temporary_marker.write_text(
        json.dumps(provenance, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_marker.replace(marker_path(local))


def staging_path(name: str, provenance: dict[str, str]) -> Path:
    identity = json.dumps(provenance, sort_keys=True).encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:16]
    return MODELS / f".{name}.partial-{suffix}"


def promote_snapshot(stage: Path, local: Path) -> None:
    if local.exists():
        if any(local.iterdir()):
            raise RuntimeError(f"{local} 在下载期间出现内容；不覆盖并停止提升")
        local.rmdir()
    stage.replace(local)


def dl_modelscope(model_id: str, revision: str, local: Path) -> bool:
    try:
        from modelscope import snapshot_download

        snapshot_download(model_id, revision=revision, local_dir=str(local))
        return True
    except Exception as exc:
        print(f"[modelscope] {model_id}@{revision} 失败: {exc}", file=sys.stderr)
        return False


def dl_hf(repo_id: str, revision: str, local: Path) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id, revision=revision, local_dir=str(local))
        return True
    except Exception as exc:
        print(f"[hf] {repo_id}@{revision} 失败: {exc}", file=sys.stderr)
        return False


def download_snapshot(
    *,
    name: str,
    provenance: dict[str, str],
    required_files: tuple[str, ...],
    downloader,
) -> bool:
    local = MODELS / name
    description = "@".join((provenance["source"], provenance["revision"]))
    if marker_matches(local, provenance, required_files):
        print(f"[skip] {name} 已验证为 {description}")
        return True
    refuse_unverified_existing(local, description)
    stage = staging_path(name, provenance)
    if marker_matches(stage, provenance, required_files):
        print(f"[resume] {name} 使用已验证 staging {stage.name}")
    else:
        print(f"[download] {name} <- {description}（staging: {stage.name}）")
        if not downloader(stage):
            print(f"[partial] {name} 保留在 {stage}，未写完成 marker", file=sys.stderr)
            return False
        missing = [relative for relative in required_files if not (stage / relative).is_file()]
        if missing:
            print(
                f"[FAIL] {description} 缺少必需文件: {', '.join(missing)}；未写完成 marker",
                file=sys.stderr,
            )
            return False
        write_marker(stage, provenance)
    promote_snapshot(stage, local)
    print(f"[done] {name}")
    return True


def dl_fish(revision: str, expected_vq_sha256: str, local: Path) -> bool:
    if not dl_hf("fishaudio/fish-speech-1.5", revision, local):
        return False
    vq = local / FISH_VQ_NAME
    partial = local / f".{FISH_VQ_NAME}.partial"
    try:
        import requests

        with requests.get(FISH_VQ_URL, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            with partial.open("wb") as stream:
                for chunk in response.iter_content(1 << 20):
                    if chunk:
                        digest.update(chunk)
                        stream.write(chunk)
        actual = digest.hexdigest()
        if actual != expected_vq_sha256:
            partial.unlink(missing_ok=True)
            print(
                f"[FAIL] Fish VQGAN SHA-256 为 {actual}，期望 {expected_vq_sha256}",
                file=sys.stderr,
            )
            return False
        partial.replace(vq)
        return True
    except Exception as exc:
        print(f"[fish-vq] {FISH_VQ_URL} 失败: {exc}", file=sys.stderr)
        return False


def main() -> int:
    args = parse_args()
    MODELS.mkdir(exist_ok=True)

    paraformer_provenance = {
        "source": "modelscope:iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
        "revision": args.paraformer_ms_revision,
    }
    ok = download_snapshot(
        name="paraformer-streaming",
        provenance=paraformer_provenance,
        required_files=("model.pt", "config.yaml"),
        downloader=lambda local: dl_modelscope(
            "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
            args.paraformer_ms_revision,
            local,
        ),
    )

    cosy_local = MODELS / "CosyVoice3-0.5B"
    cosy_required = (
        "llm.pt",
        "flow.pt",
        "hift.pt",
        "speech_tokenizer_v3.onnx",
        "campplus.onnx",
    )
    cosy_ms_provenance = {
        "source": "modelscope:FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "revision": args.cosyvoice_ms_revision,
    }
    cosy_hf_provenance = {
        "source": "hf:FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "revision": args.cosyvoice_hf_revision,
    }
    if marker_matches(cosy_local, cosy_ms_provenance, cosy_required):
        print("[skip] CosyVoice3-0.5B 已验证为锁定 ModelScope snapshot")
        cosy_ok = True
    elif marker_matches(cosy_local, cosy_hf_provenance, cosy_required):
        print("[skip] CosyVoice3-0.5B 已验证为锁定 Hugging Face snapshot")
        cosy_ok = True
    else:
        refuse_unverified_existing(cosy_local, "任一锁定 CosyVoice provider snapshot")
        cosy_ok = download_snapshot(
            name="CosyVoice3-0.5B",
            provenance=cosy_ms_provenance,
            required_files=cosy_required,
            downloader=lambda local: dl_modelscope(
                "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                args.cosyvoice_ms_revision,
                local,
            ),
        )
        if not cosy_ok:
            print("[fallback] CosyVoice3-0.5B 改用独立 Hugging Face staging")
            cosy_ok = download_snapshot(
                name="CosyVoice3-0.5B",
                provenance=cosy_hf_provenance,
                required_files=cosy_required,
                downloader=lambda local: dl_hf(
                    "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                    args.cosyvoice_hf_revision,
                    local,
                ),
            )
    ok = cosy_ok and ok

    if args.fish_hf_revision:
        fish_provenance = {
            "source": "hf:fishaudio/fish-speech-1.5",
            "revision": args.fish_hf_revision,
            "vq_source": FISH_VQ_URL,
            "vq_sha256": args.fish_vq_sha256,
        }
        fish_ok = download_snapshot(
            name="fish-speech-1.5",
            provenance=fish_provenance,
            required_files=("model.pth", "config.json", FISH_VQ_NAME),
            downloader=lambda local: dl_fish(
                args.fish_hf_revision, args.fish_vq_sha256, local
            ),
        )
        ok = fish_ok and ok
    else:
        print("[skip] 可选 Fish Speech 未请求")

    if not ok:
        print("\n一个或多个锁定模型下载失败。", file=sys.stderr)
        return 1
    print("\n所有锁定模型均已就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
