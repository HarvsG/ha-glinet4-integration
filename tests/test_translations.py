"""Tests for translation files validity and completeness."""

import json
from pathlib import Path

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
