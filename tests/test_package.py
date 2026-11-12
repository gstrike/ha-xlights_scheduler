import importlib.util
import json
import zipfile
from conftest import ROOT

spec = importlib.util.spec_from_file_location(
    "package_builder", ROOT / "scripts/build_package.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_development_build_is_isolated_and_source_is_unchanged(tmp_path):
    original = (ROOT / "custom_components/xlights_scheduler/const.py").read_bytes()
    staged, archive = builder.build(tmp_path, dev=True)
    metadata = json.loads((staged / "manifest.json").read_text())
    assert metadata["domain"] == "xlights_scheduler_dev"
    assert metadata["name"] == "xLights Scheduler Dev"
    assert metadata["version"] == "1.1.0.dev2"
    assert 'DOMAIN = "xlights_scheduler_dev"' in (staged / "const.py").read_text()
    assert (
        'REFERENCE_PREFIX = "ha:xlights_scheduler_dev"'
        in (staged / "const.py").read_text()
    )
    assert (
        ROOT / "custom_components/xlights_scheduler/const.py"
    ).read_bytes() == original
    assert "ha-xlights_scheduler#readme" in metadata["documentation"]
    assert not list(staged.rglob("*.pyc"))
    with zipfile.ZipFile(archive) as bundle:
        assert "manifest.json" in bundle.namelist()


def test_release_build_keeps_original_domain_and_flat_hacs_zip(tmp_path):
    staged, archive = builder.build(tmp_path)
    assert archive.name == "xlights_scheduler.zip"
    with zipfile.ZipFile(archive) as bundle:
        metadata = json.loads(bundle.read("manifest.json"))
        assert metadata["domain"] == "xlights_scheduler"
        assert metadata["version"] == "1.1.0"
        assert "__init__.py" in bundle.namelist()
