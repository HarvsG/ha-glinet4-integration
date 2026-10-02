"""Tests for translation files validity and completeness."""

import json
from pathlib import Path

import yaml

STRINGS_PATH = (
    Path(__file__).parent.parent / "custom_components" / "glinet" / "strings.json"
)
EN_JSON_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "glinet"
    / "translations"
    / "en.json"
)
ICONS_PATH = (
    Path(__file__).parent.parent / "custom_components" / "glinet" / "icons.json"
)
QUALITY_SCALE_PATH = (
    Path(__file__).parent.parent / "custom_components" / "glinet" / "quality_scale.yaml"
)
DOCS_GLINET_PATH = Path(__file__).parent.parent / "docs" / "glinet.markdown"


def test_strings_and_en_files_exist() -> None:
    """Test that both strings.json and translations/en.json exist."""
    assert STRINGS_PATH.is_file(), "strings.json is missing"
    assert EN_JSON_PATH.is_file(), "translations/en.json is missing"


def test_strings_and_en_valid_json() -> None:
    """Test that translation files are valid JSON."""
    with STRINGS_PATH.open("r", encoding="utf-8") as file:
        strings = json.load(file)
    assert isinstance(strings, dict)

    with EN_JSON_PATH.open("r", encoding="utf-8") as file:
        en_json = json.load(file)
    assert isinstance(en_json, dict)


def test_translations_cover_all_strings_keys() -> None:
    """Test that all top-level sections in strings.json exist in en.json."""
    with STRINGS_PATH.open("r", encoding="utf-8") as file:
        strings: dict[str, object] = json.load(file)

    with EN_JSON_PATH.open("r", encoding="utf-8") as file:
        en_json: dict[str, object] = json.load(file)

    missing_sections = set(strings.keys()) - set(en_json.keys())
    assert not missing_sections, f"en.json is missing sections: {missing_sections}"

    for section_name, section_content in strings.items():
        if isinstance(section_content, dict):
            en_section = en_json.get(section_name)
            assert isinstance(en_section, dict), (
                f"Section '{section_name}' in en.json is not a dict"
            )
            missing_keys = set(section_content.keys()) - set(en_section.keys())
            assert not missing_keys, (
                f"en.json is missing keys in '{section_name}': {missing_keys}"
            )


def test_wan_status_translation_has_name() -> None:
    """Test that wan_status sensor has a name defined in strings.json and en.json."""
    with STRINGS_PATH.open("r", encoding="utf-8") as file:
        strings = json.load(file)
    with EN_JSON_PATH.open("r", encoding="utf-8") as file:
        en_json = json.load(file)

    assert "name" in strings["entity"]["sensor"]["wan_status"], (
        "wan_status in strings.json is missing 'name'"
    )
    assert "name" in en_json["entity"]["sensor"]["wan_status"], (
        "wan_status in en.json is missing 'name'"
    )


def test_icons_json_exists_and_valid() -> None:
    """Test that icons.json exists and is valid JSON matching strings.json entity keys."""
    assert ICONS_PATH.is_file(), "icons.json is missing"
    with ICONS_PATH.open("r", encoding="utf-8") as file:
        icons = json.load(file)
    assert isinstance(icons, dict)
    assert "entity" in icons, "icons.json missing 'entity' root section"


def test_quality_scale_zero_todos() -> None:
    """Test that quality_scale.yaml has zero remaining todo rules across all tiers."""
    assert QUALITY_SCALE_PATH.is_file(), "quality_scale.yaml is missing"
    with QUALITY_SCALE_PATH.open("r", encoding="utf-8") as file:
        qs = yaml.safe_load(file)

    rules = qs.get("rules", {})
    todos = [
        rule
        for rule, val in rules.items()
        if (val.get("status") if isinstance(val, dict) else val) == "todo"
    ]
    assert not todos, f"quality_scale.yaml still contains todo rules: {todos}"


def test_glinet_markdown_documentation_exists() -> None:
    """Test that docs/glinet.markdown exists and is non-empty."""
    assert DOCS_GLINET_PATH.is_file(), "docs/glinet.markdown is missing"
    assert DOCS_GLINET_PATH.stat().st_size > 100, (
        "docs/glinet.markdown is empty or too short"
    )
