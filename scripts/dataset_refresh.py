"""Monthly dataset refresh: re-publish the CC-BY cost dataset when upstream changes.

Source of truth: https://projectcostestimator.com/api/cost-data (public, CC BY 4.0).
Published targets (created 2026-08-06):
  Kaggle       https://www.kaggle.com/datasets/florinflorea/website-project-cost-benchmarks
  Hugging Face https://huggingface.co/datasets/zimzum1984/website-project-cost-benchmarks

Flow: fetch the live JSON, canonical-hash it, compare against
data/DATASET-PUBLISH-STATE.json. Unchanged -> clean no-op. Changed -> rebuild the
package (raw JSON + 2 mechanically derived CSVs + README + LICENSE) and push a new
version to both platforms, then record the new hash in the state file (the workflow
commits it).

Credentials come ONLY from env: KAGGLE_USERNAME, KAGGLE_KEY, HF_TOKEN (repo secrets
in CI). Nothing secret is ever written to disk or logged.

Flags:
  --dry-run  fetch + hash + build the package, report what WOULD happen, publish
             nothing, write no state
  --force    publish even if the hash is unchanged (e.g. README-only fix)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://projectcostestimator.com/api/cost-data"
STATE_FILE = ROOT / "data" / "DATASET-PUBLISH-STATE.json"
ASSETS = ROOT / "dataset"

KAGGLE_ID = "florinflorea/website-project-cost-benchmarks"
HF_REPO = "zimzum1984/website-project-cost-benchmarks"

HF_FRONT_MATTER = """---
license: cc-by-4.0
language:
- en
tags:
- cost-estimation
- web-development
- benchmarks
pretty_name: Website & App Project Cost Benchmarks 2026
size_categories:
- n<1K
---
"""

KAGGLE_METADATA = {
    "title": "Website & App Project Cost Benchmarks 2026",
    "id": KAGGLE_ID,
    "licenses": [{"name": "CC-BY-4.0"}],
}


def fetch_api() -> tuple[bytes, dict]:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "pce-ops dataset-refresh"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"API returned HTTP {r.status}")
        raw = r.read()
    return raw, json.loads(raw)


def canonical_hash(doc: dict) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def flatten(obj, prefix=()):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            rows.extend(flatten(v, prefix + (str(k),)))
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            rows.append((prefix, "|".join(str(x) for x in obj)))
        else:
            for i, v in enumerate(obj):
                rows.extend(flatten(v, prefix + (str(i),)))
    else:
        rows.append((prefix, obj))
    return rows


def build_package(raw: bytes, doc: dict, out: Path) -> None:
    """Write the shared data files into out/kaggle and out/hf."""
    data = doc["data"]
    kag, hf = out / "kaggle", out / "hf"
    kag.mkdir(parents=True)
    hf.mkdir(parents=True)

    readme_body = (ASSETS / "README_body.md").read_text(encoding="utf-8")
    license_text = (ASSETS / "LICENSE").read_text(encoding="utf-8")

    for d in (kag, hf):
        (d / "cost-data.json").write_bytes(raw)
        (d / "LICENSE").write_text(license_text, encoding="utf-8")

        rates = data["hourly_rate_database"]["rates"]
        with (d / "hourly_rates.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["platform", "region", "tier", "low_usd_per_hour",
                        "median_usd_per_hour", "high_usd_per_hour"])
            for platform, regions in rates.items():
                for region, tiers in regions.items():
                    for tier, band in tiers.items():
                        w.writerow([platform, region, tier,
                                    band["low"], band["median"], band["high"]])

        with (d / "cost_benchmarks_flat.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["category", "item", "attribute", "value"])
            for parts, value in flatten(data):
                w.writerow([parts[0],
                            parts[1] if len(parts) >= 2 else "",
                            ".".join(parts[2:]) if len(parts) >= 3 else "",
                            value])

    (kag / "README.md").write_text(readme_body, encoding="utf-8")
    (kag / "dataset-metadata.json").write_text(
        json.dumps(KAGGLE_METADATA, indent=2), encoding="utf-8")
    (hf / "README.md").write_text(HF_FRONT_MATTER + readme_body, encoding="utf-8")


def publish_kaggle(pkg_dir: Path, message: str) -> None:
    for var in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        if not os.environ.get(var):
            raise RuntimeError(f"missing env {var}")
    subprocess.run(
        [sys.executable, "-m", "kaggle", "datasets", "version",
         "-p", str(pkg_dir), "-m", message],
        check=True,
    )


def publish_hf(pkg_dir: Path, message: str) -> str:
    if not os.environ.get("HF_TOKEN"):
        raise RuntimeError("missing env HF_TOKEN")
    from huggingface_hub import HfApi  # deferred: not needed on the no-op path
    api = HfApi()
    res = api.upload_folder(folder_path=str(pkg_dir), repo_id=HF_REPO,
                            repo_type="dataset", commit_message=message)
    return getattr(res, "commit_url", str(res))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    raw, doc = fetch_api()
    new_hash = canonical_hash(doc)
    date_modified = doc.get("dateModified", "?")
    print(f"fetched {API_URL}: {len(raw)} bytes, dateModified={date_modified}, "
          f"hash={new_hash[:16]}...")

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    old_hash = state.get("content_hash")

    if new_hash == old_hash and not args.force:
        print(f"no change since last publish ({state.get('published_utc', '?')}) - nothing to do")
        return 0

    print("upstream changed" if old_hash else "no previous state",
          "- building package" + (" (dry-run)" if args.dry_run else ""))

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        build_package(raw, doc, out)
        built = sorted(p.name for p in (out / "kaggle").iterdir())
        print("package files:", ", ".join(built))

        if args.dry_run:
            print("dry-run: would publish new version to Kaggle "
                  f"({KAGGLE_ID}) and Hugging Face ({HF_REPO}); state not written")
            return 0

        message = f"Refresh from live API (upstream dateModified {date_modified})"
        publish_kaggle(out / "kaggle", message)
        print("kaggle: new version pushed")
        commit_url = publish_hf(out / "hf", message)
        print("huggingface: uploaded,", commit_url)

    STATE_FILE.write_text(json.dumps({
        "content_hash": new_hash,
        "date_modified_upstream": date_modified,
        "published_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kaggle": f"https://www.kaggle.com/datasets/{KAGGLE_ID}",
        "huggingface": f"https://huggingface.co/datasets/{HF_REPO}",
    }, indent=2) + "\n", encoding="utf-8")
    print("state written:", STATE_FILE.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
