"""Sanity checks on the integration metadata."""

import json
from pathlib import Path

from custom_components.alexa_bridge.const import DOMAIN

ROOT = Path(__file__).parent.parent


def test_manifest_matches_domain():
    manifest = json.loads(
        (ROOT / "custom_components" / "alexa_bridge" / "manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert "http" in manifest["dependencies"]
    assert manifest["config_flow"] is True
    assert manifest["version"]

    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"]
    assert hacs["homeassistant"]
