"""Tests for stable Alexa endpoint ids."""

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.alexa_bridge.ids import (
    entity_id_from_alexa_id,
    legacy_alexa_id,
    stable_alexa_id,
)


def _register(hass: HomeAssistant, entity_id: str = "light.sala") -> er.RegistryEntry:
    domain, object_id = entity_id.split(".")
    return er.async_get(hass).async_get_or_create(
        domain, "test", f"uid_{object_id}", suggested_object_id=object_id
    )


async def test_registry_entity_gets_stable_id(hass: HomeAssistant):
    entry = _register(hass)
    assert entry.entity_id == "light.sala"
    assert stable_alexa_id(hass, "light.sala") == "ha-" + entry.id
    assert entity_id_from_alexa_id(hass, "ha-" + entry.id) == "light.sala"


async def test_stable_id_survives_rename(hass: HomeAssistant):
    entry = _register(hass)
    before = stable_alexa_id(hass, "light.sala")
    er.async_get(hass).async_update_entity(
        "light.sala", new_entity_id="light.nuovo"
    )
    assert stable_alexa_id(hass, "light.nuovo") == before
    assert entity_id_from_alexa_id(hass, before) == "light.nuovo"
    assert before == "ha-" + entry.id


async def test_entity_without_registry_uses_legacy(hass: HomeAssistant):
    alexa_id = stable_alexa_id(hass, "light.yaml_only")
    assert alexa_id == "light#yaml_only"
    assert legacy_alexa_id("light.yaml_only") == "light#yaml_only"
    assert entity_id_from_alexa_id(hass, alexa_id) == "light.yaml_only"


async def test_unknown_stable_id_returns_none(hass: HomeAssistant):
    assert entity_id_from_alexa_id(hass, "ha-doesnotexist") is None


async def test_stable_id_is_valid_alexa_endpoint_id(hass: HomeAssistant):
    _register(hass)
    pattern = re.compile(r"^[A-Za-z0-9_\-=#;:?@&]{1,256}$")
    assert pattern.match(stable_alexa_id(hass, "light.sala"))
    assert pattern.match(stable_alexa_id(hass, "light.yaml_only"))
