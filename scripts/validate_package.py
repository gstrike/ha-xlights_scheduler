#!/usr/bin/env python3
"""Validate the normal HACS ZIP without starting or installing Home Assistant."""

import argparse
import ast
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "xlights_scheduler"


def validate(archive):
    source = ROOT / "custom_components" / DOMAIN
    manifest = json.loads((source / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    constants = ast.parse((source / "const.py").read_text())
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in constants.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in ("DOMAIN", "INTEGRATION_VERSION")
    }
    assert manifest["domain"] == values["DOMAIN"] == DOMAIN
    assert manifest["version"] == values["INTEGRATION_VERSION"]
    assert manifest["config_flow"] is True
    assert hacs["zip_release"] is True and hacs["filename"] == archive.name
    assert hacs["homeassistant"]
    expected = {
        str(p.relative_to(source))
        for p in source.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names)), "Duplicate ZIP entries"
        assert set(names) == expected, "ZIP contents differ from source files"
        assert all(
            not Path(name).is_absolute() and ".." not in Path(name).parts
            for name in names
        )
        assert not any(
            "_acceptance" in name or "xlights_scheduler_dev" in name for name in names
        )
        assert json.loads(bundle.read("manifest.json")) == manifest
        for name in names:
            assert bundle.read(name) == (source / name).read_bytes(), (
                f"Changed payload: {name}"
            )
        assert bundle.testzip() is None
    print(
        f"VALID {archive.name}: {manifest['version']}, domain {DOMAIN}, {len(names)} source files"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive", nargs="?", type=Path, default=ROOT / "dist" / "xlights_scheduler.zip"
    )
    validate(parser.parse_args().archive)
