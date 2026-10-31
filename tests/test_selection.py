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


def _sel(domains=(), include=(), exclude=(), areas=()):
    return Selection(frozenset(domains), frozenset(include), frozenset(exclude), frozenset(areas))


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
    for platform in ("alexa_media", "alexa_devices"):
        er.async_get(hass).async_get_or_create(
            "media_player", platform, "echo1", suggested_object_id=f"echo_{platform}"
        )
        eid = f"media_player.echo_{platform}"
        hass.states.async_set(eid, "idle")
        assert not is_shared(hass, eid, _sel({"media_player"}, {eid}))


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


def _area_setup(hass: HomeAssistant):
    """Soggiorno: a light by entity area, a switch by device area, plus others."""
    from homeassistant.helpers import area_registry as ar, device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    soggiorno = ar.async_get(hass).async_create("Soggiorno").id
    cucina = ar.async_get(hass).async_create("Cucina").id
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("test", "presa")}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=soggiorno)
    reg = er.async_get(hass)
    reg.async_get_or_create("light", "test", "l1", suggested_object_id="divano")
    reg.async_update_entity("light.divano", area_id=soggiorno)
    reg.async_get_or_create("switch", "test", "s1", suggested_object_id="presa", device_id=device.id)
    reg.async_get_or_create("light", "test", "l2", suggested_object_id="tavolo", device_id=device.id)
    # entity area wins; HA wants an own name for an own area
    reg.async_update_entity("light.tavolo", area_id=cucina, name="Tavolo")
    reg.async_get_or_create("alarm_control_panel", "test", "a1", suggested_object_id="casa", device_id=device.id)
    reg.async_get_or_create(
        "sensor", "test", "d1", suggested_object_id="segnale", device_id=device.id,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for eid in ("light.divano", "switch.presa", "light.tavolo", "alarm_control_panel.casa", "sensor.segnale"):
        hass.states.async_set(eid, "on")
    return soggiorno, cucina


async def test_area_shares_every_supported_entity_in_it(hass: HomeAssistant):
    soggiorno, _ = _area_setup(hass)
    sel = _sel(areas={soggiorno})
    assert shared_entity_ids(hass, sel) == {"light.divano", "switch.presa"}


async def test_area_respects_exclude(hass: HomeAssistant):
    soggiorno, _ = _area_setup(hass)
    sel = _sel(exclude={"switch.presa"}, areas={soggiorno})
    assert shared_entity_ids(hass, sel) == {"light.divano"}


async def test_entity_area_overrides_device_area(hass: HomeAssistant):
    soggiorno, cucina = _area_setup(hass)
    assert not is_shared(hass, "light.tavolo", _sel(areas={soggiorno}))
    assert is_shared(hass, "light.tavolo", _sel(areas={cucina}))


async def test_area_and_domain_add_up(hass: HomeAssistant):
    _, cucina = _area_setup(hass)
    hass.states.async_set("light.senza_area", "on")
    sel = _sel({"switch"}, areas={cucina})
    assert shared_entity_ids(hass, sel) == {"switch.presa", "light.tavolo"}


def test_from_options_reads_areas():
    assert Selection.from_options({"areas": ["soggiorno"]}).areas == frozenset({"soggiorno"})


def _device_of(hass: HomeAssistant, entity_id: str) -> str:
    return er.async_get(hass).async_get(entity_id).device_id


async def test_excluded_domain_leaves_area_and_domain(hass: HomeAssistant):
    soggiorno, _ = _area_setup(hass)
    sel = Selection(
        frozenset({"switch"}), frozenset(), frozenset(), frozenset({soggiorno}),
        exclude_domains=frozenset({"switch"}),
    )
    assert shared_entity_ids(hass, sel) == {"light.divano"}


async def test_excluded_device_takes_all_its_entities_out(hass: HomeAssistant):
    soggiorno, cucina = _area_setup(hass)
    sel = Selection(
        frozenset(), frozenset(), frozenset(), frozenset({soggiorno, cucina}),
        exclude_devices=frozenset({_device_of(hass, "switch.presa")}),
    )
    # light.tavolo has its own area but still belongs to the excluded device
    assert shared_entity_ids(hass, sel) == {"light.divano"}


async def test_include_beats_excluded_domain_and_device(hass: HomeAssistant):
    soggiorno, _ = _area_setup(hass)
    sel = Selection(
        frozenset(), frozenset({"switch.presa", "light.divano"}), frozenset(), frozenset({soggiorno}),
        exclude_domains=frozenset({"light"}),
        exclude_devices=frozenset({_device_of(hass, "switch.presa")}),
    )
    assert shared_entity_ids(hass, sel) == {"switch.presa", "light.divano"}


def test_from_options_reads_exclusions():
    sel = Selection.from_options({"exclude_domains": ["valve"], "exclude_devices": ["dev1"]})
    assert sel.exclude_domains == frozenset({"valve"})
    assert sel.exclude_devices == frozenset({"dev1"})
