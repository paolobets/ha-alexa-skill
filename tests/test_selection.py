"""Tests for the entity selection rule."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory

from custom_components.alexa_bridge.selection import (
    Selection,
    is_shared,
    selectable_domains,
    shared_entity_ids,
)


def _sel(domains=(), include=(), exclude=()):
    return Selection(frozenset(domains), frozenset(include), frozenset(exclude))


def test_from_options_tolerates_missing_keys():
    sel = Selection.from_options({})
    assert sel == _sel()
    sel = Selection.from_options(
        {"domains": ["light"], "include_entities": ["a.b"], "exclude_entities": ["c.d"]}
    )
    assert sel == _sel({"light"}, {"a.b"}, {"c.d"})


async def test_domain_selected_shares_entity(hass: HomeAssistant):
    hass.states.async_set("light.sala", "on")
    assert is_shared(hass, "light.sala", _sel({"light"}))


async def test_domain_not_selected(hass: HomeAssistant):
    hass.states.async_set("switch.x", "on")
    assert not is_shared(hass, "switch.x", _sel({"light"}))


async def test_include_overrides_domain(hass: HomeAssistant):
    hass.states.async_set("switch.x", "on")
    assert is_shared(hass, "switch.x", _sel({"light"}, include={"switch.x"}))


async def test_exclude_wins_over_include_and_domain(hass: HomeAssistant):
    hass.states.async_set("light.sala", "on")
    sel = _sel({"light"}, {"light.sala"}, {"light.sala"})
    assert not is_shared(hass, "light.sala", sel)


async def test_blocked_domains_never_shared(hass: HomeAssistant):
    hass.states.async_set("automation.a", "on")
    hass.states.async_set("alarm_control_panel.b", "disarmed")
    sel = _sel({"automation", "alarm_control_panel"}, {"automation.a", "alarm_control_panel.b"})
    assert not is_shared(hass, "automation.a", sel)
    assert not is_shared(hass, "alarm_control_panel.b", sel)


async def test_echo_never_shared(hass: HomeAssistant):
    er.async_get(hass).async_get_or_create("media_player", "alexa_media", "echo1", suggested_object_id="echo")
    hass.states.async_set("media_player.echo", "idle")
    assert not is_shared(hass, "media_player.echo", _sel({"media_player"}, {"media_player.echo"}))


async def test_hidden_and_diagnostic_excluded_unless_included(hass: HomeAssistant):
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "light", "test", "d1", suggested_object_id="diag", entity_category=EntityCategory.DIAGNOSTIC
    )
    reg.async_get_or_create(
        "light", "test", "h1", suggested_object_id="hid", hidden_by=er.RegistryEntryHider.USER
    )
    for eid in ("light.diag", "light.hid"):
        hass.states.async_set(eid, "on")
        assert not is_shared(hass, eid, _sel({"light"}))
        assert is_shared(hass, eid, _sel({"light"}, include={eid}))


async def test_binary_sensor_classes(hass: HomeAssistant):
    sel = _sel({"binary_sensor"})
    for name, cls, expected in (
        ("door", "door", True),
        ("motion", "motion", True),
        ("battery", "battery", False),
        ("presence", "presence", False),
    ):
        eid = f"binary_sensor.{name}"
        hass.states.async_set(eid, "on", {"device_class": cls})
        assert is_shared(hass, eid, sel) is expected


async def test_binary_sensor_class_from_registry_without_state(hass: HomeAssistant):
    er.async_get(hass).async_get_or_create(
        "binary_sensor", "test", "w1", suggested_object_id="win", original_device_class="window"
    )
    assert is_shared(hass, "binary_sensor.win", _sel({"binary_sensor"}))


async def test_selectable_domains_excludes_blocked():
    domains = selectable_domains()
    assert "automation" not in domains
    assert "alarm_control_panel" not in domains
    assert "light" in domains
    assert "script" in domains
    assert domains == sorted(domains)


async def test_shared_entity_ids_counts(hass: HomeAssistant):
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "light", "test", "h", suggested_object_id="c", hidden_by=er.RegistryEntryHider.USER
    )
    for eid in ("light.a", "light.b", "light.c", "switch.x"):
        hass.states.async_set(eid, "on")
    assert shared_entity_ids(hass, _sel({"light"})) == {"light.a", "light.b"}
