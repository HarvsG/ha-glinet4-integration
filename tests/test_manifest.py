"""Tests for integration manifest and metadata consistency."""

import json
from pathlib import Path
import re
import tomllib

MANIFEST_PATH = (
    Path(__file__).parent.parent / "custom_components" / "glinet" / "manifest.json"
)
HACS_PATH = Path(__file__).parent.parent / "hacs.json"
PYPROJECT_PATH = Path(__file__).parent.parent / "pyproject.toml"

REQUIRED_MANIFEST_KEYS = {
    "domain",
    "name",
    "codeowners",
    "config_flow",
    "documentation",
    "integration_type",
    "iot_class",
    "issue_tracker",
    "requirements",
    "version",
}


def test_manifest_structure() -> None:
    """Test that manifest.json has valid structure and required fields."""
    assert MANIFEST_PATH.is_file()

    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        manifest: dict[str, object] = json.load(file)

    missing_keys = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
    assert not missing_keys, f"Manifest is missing required keys: {missing_keys}"

    assert manifest["domain"] == "glinet"
    assert manifest["name"] == "GL-iNet"
    assert isinstance(manifest["codeowners"], list)
    assert len(manifest["codeowners"]) > 0
    assert manifest["config_flow"] is True


def test_manifest_version_format() -> None:
    """Test that manifest version follows semantic versioning."""
    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        manifest: dict[str, object] = json.load(file)

    version = str(manifest["version"])
    # Match standard semver with optional pre-release e.g. 0.1.11, 0.1.11-beta.1, 0.1.11.dev0
    semver_pattern = r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
    assert re.match(semver_pattern, version), f"Invalid version format: {version}"


def test_manifest_requirements_match_pyproject() -> None:
    """Test that requirements pinned in manifest.json match pyproject.toml."""
    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        manifest: dict[str, object] = json.load(file)

    with PYPROJECT_PATH.open("rb") as file:
        pyproject: dict[str, object] = tomllib.load(file)

    dependency_groups = pyproject["dependency-groups"]
    dev_deps: list[str] = dependency_groups["dev"]  # type: ignore[index]

    manifest_requirements = manifest["requirements"]
    assert isinstance(manifest_requirements, list)

    for req in manifest_requirements:
        assert isinstance(req, str)
        pkg_name = re.split(r"[=<>]", req)[0].strip().lower()
        matching_dev_deps = [
            dep for dep in dev_deps if dep.lower().startswith(pkg_name)
        ]
        assert matching_dev_deps, (
            f"Requirement {req} from manifest.json not found in pyproject.toml dev group"
        )
        normalized_matching_dev_deps = [
            re.sub(r"\[.*?\]", "", dep) for dep in matching_dev_deps
        ]
        assert req in normalized_matching_dev_deps, (
            f"Requirement '{req}' in manifest.json does not match '{matching_dev_deps[0]}' in pyproject.toml"
        )


def test_hacs_metadata() -> None:
    """Test that hacs.json has valid structure."""
    assert HACS_PATH.is_file()

    with HACS_PATH.open("r", encoding="utf-8") as file:
        hacs_data: dict[str, object] = json.load(file)

    assert "name" in hacs_data
    assert hacs_data["content_in_root"] is False
