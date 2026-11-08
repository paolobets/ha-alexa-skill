"""Heating thermostats: Alexa may set temperature and mode, never power or OFF.

A room command ("Alexa, turn off the study") acts on every device with
Alexa.PowerController in that room: a heating thermostat must not be one of
them, nor accept the OFF mode (antifreeze) by voice.
"""

from typing import Any
from unittest.mock import MagicMock

from homeassistant.components.alexa.entities import ENTITY_ADAPTERS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from tests.test_sync import _authorized, _entry, _setup as _setup_entry, gateway, token  # noqa: F401
from tests.test_view import _config, _message, _post, no_proactive_mode  # noqa: F401

HEATING = {
    "hvac_modes": ["auto", "heat", "off"],
    "supported_features": 401,
    "preset_modes": ["none", "programma", "forzatura", "manuale"],
    "current_temperature": 18.4,
    "temperature": 17.5,
    "min_temp": 5,
    "max_temp": 30,
}
COOLING = {**HEATING, "hvac_modes": ["cool", "heat", "off"]}


def _climate(hass: HomeAssistant, name: str, attrs: dict[str, Any], state: str = "auto") -> str:
    """Registry entry plus state; return the stable Alexa id."""
    entry = er.async_get(hass).async_get_or_create(
        "climate", "test", name, suggested_object_id=name
    )
    hass.states.async_set(entry.entity_id, state, {"friendly_name": name, **attrs})
    return f"ha-{entry.id}"


def _directive(namespace: str, name: str, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = _message("turn_on", endpoint_id)
    message["directive"]["header"].update(namespace=namespace, name=name)
    message["directive"]["payload"] = payload
    return message


def _interfaces(endpoint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["interface"]: c for c in endpoint["capabilities"]}


async def _discover(hass: HomeAssistant, hass_client) -> dict[str, dict[str, Any]]:
    body = await _post(await hass_client(), _message("discover"))
    return {e["endpointId"]: e for e in body["event"]["payload"]["endpoints"]}


async def test_heating_thermostat_discovered_without_power_or_off(
    hass: HomeAssistant, hass_client
) -> None:
    studio = _climate(hass, "studio", HEATING)
    await _config(hass, {"domains": ["climate"]})

    caps = _interfaces((await _discover(hass, hass_client))[studio])

    assert "Alexa.PowerController" not in caps
    modes = caps["Alexa.ThermostatController"]["configuration"]["supportedModes"]
    assert modes == ["AUTO", "HEAT"]
    assert "Alexa.TemperatureSensor" in caps


async def test_cooling_climate_keeps_power_and_off(hass: HomeAssistant, hass_client) -> None:
    clima = _climate(hass, "clima", COOLING)
    await _config(hass, {"domains": ["climate"]})

    caps = _interfaces((await _discover(hass, hass_client))[clima])

    assert "Alexa.PowerController" in caps
    assert "OFF" in caps["Alexa.ThermostatController"]["configuration"]["supportedModes"]


async def test_turn_off_heating_thermostat_rejected(hass: HomeAssistant, hass_client) -> None:
    studio = _climate(hass, "studio", HEATING)
    await _config(hass, {"domains": ["climate"]})
    calls = async_mock_service(hass, "climate", "turn_off")

    body = await _post(
        await hass_client(), _directive("Alexa.PowerController", "TurnOff", studio, {})
    )

    assert body["event"]["header"]["name"] == "ErrorResponse"
    assert body["event"]["payload"]["type"] == "INVALID_DIRECTIVE"
    assert body["event"]["endpoint"]["endpointId"] == studio
    assert calls == []


async def test_turn_on_heating_thermostat_rejected(hass: HomeAssistant, hass_client) -> None:
    studio = _climate(hass, "studio", HEATING, state="off")
    await _config(hass, {"domains": ["climate"]})
    calls = async_mock_service(hass, "climate", "turn_on")

    body = await _post(
        await hass_client(), _directive("Alexa.PowerController", "TurnOn", studio, {})
    )

    assert body["event"]["payload"]["type"] == "INVALID_DIRECTIVE"
    assert calls == []


async def test_set_mode_off_heating_thermostat_rejected(hass: HomeAssistant, hass_client) -> None:
    studio = _climate(hass, "studio", HEATING)
    await _config(hass, {"domains": ["climate"]})
    calls = async_mock_service(hass, "climate", "set_hvac_mode")

    body = await _post(
        await hass_client(),
        _directive(
            "Alexa.ThermostatController", "SetThermostatMode", studio,
            {"thermostatMode": {"value": "OFF"}},
        ),
    )

    assert body["event"]["header"]["namespace"] == "Alexa.ThermostatController"
    assert body["event"]["payload"]["type"] == "UNSUPPORTED_THERMOSTAT_MODE"
    assert calls == []


async def test_set_mode_auto_heating_thermostat_allowed(hass: HomeAssistant, hass_client) -> None:
    studio = _climate(hass, "studio", HEATING, state="heat")
    await _config(hass, {"domains": ["climate"]})
    calls = async_mock_service(hass, "climate", "set_hvac_mode")

    body = await _post(
        await hass_client(),
        _directive(
            "Alexa.ThermostatController", "SetThermostatMode", studio,
            {"thermostatMode": {"value": "AUTO"}},
        ),
    )

    assert body["event"]["header"]["name"] == "Response"
    assert [(c.data["entity_id"], c.data["hvac_mode"]) for c in calls] == [
        ("climate.studio", "auto")
    ]


async def test_turn_off_cooling_climate_still_allowed(hass: HomeAssistant, hass_client) -> None:
    clima = _climate(hass, "clima", COOLING)
    await _config(hass, {"domains": ["climate"]})
    calls = async_mock_service(hass, "climate", "turn_off")

    body = await _post(
        await hass_client(), _directive("Alexa.PowerController", "TurnOff", clima, {})
    )

    assert body["event"]["header"]["name"] == "Response"
    assert [c.data["entity_id"] for c in calls] == ["climate.clima"]


async def test_report_state_heating_thermostat_has_no_power_state(
    hass: HomeAssistant, hass_client
) -> None:
    studio = _climate(hass, "studio", HEATING)
    await _config(hass, {"domains": ["climate"]})

    body = await _post(await hass_client(), _message("report_state", studio))

    names = {p["name"] for p in body["context"]["properties"]}
    assert "powerState" not in names
    assert "thermostatMode" in names


async def test_add_or_update_heating_thermostat_without_power(
    hass: HomeAssistant, hass_storage, token, gateway  # noqa: F811
) -> None:
    _authorized(hass_storage)
    studio = _climate(hass, "studio", HEATING)

    await _setup_entry(hass, _entry(hass, ["climate"]))

    adds = [
        call[2]["event"]["payload"]["endpoints"]
        for call in gateway.mock_calls
        if call[2]["event"]["header"]["name"] == "AddOrUpdateReport"
    ]
    endpoint = next(e for batch in adds for e in batch if e["endpointId"] == studio)
    assert "Alexa.PowerController" not in _interfaces(endpoint)


async def test_other_alexa_configs_unchanged(hass: HomeAssistant) -> None:
    """Only the bridge filters: the stock Alexa integration sees HA's default."""
    _climate(hass, "studio", HEATING)
    adapter = ENTITY_ADAPTERS["climate"](hass, MagicMock(), hass.states.get("climate.studio"))

    names = {i.name() for i in adapter.interfaces()}

    assert "Alexa.PowerController" in names
