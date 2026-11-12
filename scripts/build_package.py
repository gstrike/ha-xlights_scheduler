#!/usr/bin/env python3
"""Build a flat HACS release ZIP, or a separately named development integration.

The dev build is generated from the exact normal source; never edit the staged
copy. No files are installed and no GitHub release is published by this tool.
"""

import argparse
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output, dev=False):
    original = "xlights_scheduler"
    domain = original + "_dev" if dev else original
    source = ROOT / "custom_components" / original
    staged = output / "custom_components" / domain
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(
        source, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    manifest = json.loads((source / "manifest.json").read_text())
    version = manifest["version"] + (".dev2" if dev else "")
    if dev:
        for path in staged.rglob("*"):
            if path.suffix in (".py", ".yaml", ".json"):
                text = path.read_text()
                if path.name != "manifest.json":
                    text = text.replace(original, domain).replace(
                        "xLights Scheduler", "xLights Scheduler Dev"
                    )
                if path.name == "const.py":
                    text = text.replace(
                        'INTEGRATION_VERSION = "' + manifest["version"] + '"',
                        'INTEGRATION_VERSION = "' + version + '"',
                    )
                path.write_text(text)
    manifest.update(
        domain=domain,
        version=version,
        name="xLights Scheduler Dev" if dev else "xLights Scheduler",
    )
    (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = output / f"{domain}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(staged))
    return staged, archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for path in build(args.output, args.dev):
        print(path)
