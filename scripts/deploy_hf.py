"""Deploy the Streamlit app to a Hugging Face Space (Docker), so it stays up when this Mac is off.

    uv run --with huggingface_hub scripts/deploy_hf.py --build-only        # make the bundle in run/hf_bundle, no upload
    uv run --with huggingface_hub scripts/deploy_hf.py                     # upload to <your user>/qtfetcher
    uv run --with huggingface_hub scripts/deploy_hf.py --set-secret        # also send FEATHERLESS_API_KEY from .env

Needs a Hugging Face write token: `hf auth login` once, or HF_TOKEN in the environment.
Only what the app reads at runtime is shipped (no .env, no raw DECP, no model files, no note backups).
A public Space makes these files downloadable by anyone.
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "run" / "hf_bundle"
FILES = [
    "app.py", ".streamlit/config.toml",
    "data/clean/awards.parquet", "data/clean/scored.parquet", "data/clean/scored_boamp.parquet",
    "data/raw/boamp.parquet",
    *[f"artifacts/{n}.json" for n in (
        "notes", "metrics", "metrics_boamp", "calibration", "calibration_boamp", "rules_backtest", "coverage",
        "llm_benchmark", "hemicycle_history", "buyer_sirets", "company_names", "buyers", "amount_edges")],
]
DIRS = {"src": "*.py", "images": "*"}
DEPLOY = {"Dockerfile": "Dockerfile", "README.md": "README.md", "requirements.txt": "requirements.txt"}


def build() -> None:
    shutil.rmtree(BUNDLE, ignore_errors=True)
    for f in FILES:
        (BUNDLE / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, BUNDLE / f)
    for d, pat in DIRS.items():
        (BUNDLE / d).mkdir(parents=True)
        for p in (ROOT / d).glob(pat):
            if p.is_file() and not p.name.startswith("."):
                shutil.copy2(p, BUNDLE / d / p.name)
    for src, dst in DEPLOY.items():
        shutil.copy2(ROOT / "deploy" / src, BUNDLE / dst)
    size = sum(p.stat().st_size for p in BUNDLE.rglob("*") if p.is_file()) / 1e6
    print(f"bundle: {BUNDLE} ({size:.0f} MB, {sum(1 for p in BUNDLE.rglob('*') if p.is_file())} files)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="qtfetcher", help="Space name, or user/name")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--set-secret", action="store_true", help="send FEATHERLESS_API_KEY from .env as a Space secret")
    a = ap.parse_args()
    build()
    if a.build_only:
        return
    from huggingface_hub import HfApi
    api = HfApi()
    repo = a.space if "/" in a.space else f"{api.whoami()['name']}/{a.space}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", private=a.private, exist_ok=True)
    if a.set_secret:
        key = next((l.split("=", 1)[1].strip().strip('"\'') for l in (ROOT / ".env").read_text().splitlines()
                    if l.startswith("FEATHERLESS_API_KEY=")), "")
        if key:
            api.add_space_secret(repo, "FEATHERLESS_API_KEY", key)
            print("secret FEATHERLESS_API_KEY set")
        else:
            print("FEATHERLESS_API_KEY is empty in .env: notes on demand will be unavailable")
    api.upload_folder(folder_path=str(BUNDLE), repo_id=repo, repo_type="space", delete_patterns="*",
                      commit_message="Deploy QtFetcher")
    print(f"Space: https://huggingface.co/spaces/{repo}  (the first build takes a few minutes)")


if __name__ == "__main__":
    main()
