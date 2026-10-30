"""Tests for keeping Alexa's device list equal to the selection."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.alexa.errors import NoTokenAvailable
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.alexa_bridge.config import BridgeAuth
from custom_components.alexa_bridge.const import (
    DEFAULT_ENDPOINT,
    DOMAIN,
    STORE_AUTH,
    STORE_CONFIG,
    STORE_SYNC,
)
from custom_components.alexa_bridge.sync import SyncManager

PROACTIVE = "homeassistant.components.alexa.config.async_enable_proactive_mode"
ISSUE = "proactive_not_authorized"


@pytest.fixture(autouse=True)
def proactive() -> Iterator[AsyncMock]:
    """Never enable real proactive reporting."""
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())) as mock:
        yield mock


@pytest.fixture
def token() -> Iterator[AsyncMock]:
    """LWA access token available."""
    with patch.object(BridgeAuth, "async_get_access_token", AsyncMock(return_value="tok")) as mock:
        yield mock


@pytest.fixture
def gateway(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Alexa event gateway accepting every event."""
    aioclient_mock.post(DEFAULT_ENDPOINT, status=202)
    return aioclient_mock


def _authorized(hass_storage: dict[str, Any]) -> None:
    hass_storage[STORE_CONFIG] = {"version": 1, "key": STORE_CONFIG, "data": {"authorized": True}}


def _synced(hass_storage: dict[str, Any], synced: dict[str, str]) -> None:
    hass_storage[STORE_SYNC] = {"version": 1, "key": STORE_SYNC, "data": {"synced": synced}}


def _light(hass: HomeAssistant, name: str) -> str:
    """Registry entry plus state; return the stable Alexa id."""
    entry = er.async_get(hass).async_get_or_create(
        "light", "test", name, suggested_object_id=name
    )
    hass.states.async_set(entry.entity_id, "off", {"friendly_name": name})
    return f"ha-{entry.id}"


def _entry(
    hass: HomeAssistant, domains: list[str] | None = None, **options: list[str]
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CLIENT_ID: "client-id", CONF_CLIENT_SECRET: "client-secret"},
        options={"domains": ["light"] if domains is None else domains, **options},
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _events(aioclient_mock: AiohttpClientMocker, name: str) -> list[list[str]]:
    """endpointIds of each event of the given name sent to Alexa."""
    return [
        [ep["endpointId"] for ep in call[2]["event"]["payload"]["endpoints"]]
        for call in aioclient_mock.mock_calls
        if call[2]["event"]["header"]["name"] == name
    ]


def _store(hass_storage: dict[str, Any]) -> dict[str, str]:
    return hass_storage[STORE_SYNC]["data"]["synced"]


def _issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def test_first_reconcile_adds_selected(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    id_cucina = _light(hass, "cucina")
    entry = _entry(hass)

    await _setup(hass, entry)

    assert isinstance(entry.runtime_data.sync, SyncManager)
    adds = _events(gateway, "AddOrUpdateReport")
    assert len(adds) == 1
    assert sorted(adds[0]) == sorted([id_sala, id_cucina])
    assert _store(hass_storage) == {"light.sala": id_sala, "light.cucina": id_cucina}
    assert _issue(hass) is None


async def test_deselect_sends_delete(hass: HomeAssistant, hass_storage, token, gateway) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    id_cucina = _light(hass, "cucina")
    entry = _entry(hass)
    await _setup(hass, entry)
    gateway.mock_calls.clear()

    hass.config_entries.async_update_entry(entry, options={"domains": []})
    await hass.async_block_till_done()

    deletes = _events(gateway, "DeleteReport")
    assert len(deletes) == 1
    assert sorted(deletes[0]) == sorted([id_sala, id_cucina])
    assert _store(hass_storage) == {}
    assert entry.runtime_data.config.known_ids == {}


async def test_startup_missing_state_not_deleted(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    # switch is not a selected domain: only the "state or registry" guard keeps it.
    _authorized(hass_storage)
    _synced(hass_storage, {"switch.lenta": "ha-lenta"})
    entry = _entry(hass)

    await _setup(hass, entry)

    assert _events(gateway, "DeleteReport") == []
    assert entry.runtime_data.config.known_ids == {"switch.lenta": "ha-lenta"}
    assert STORE_SYNC not in hass_storage or _store(hass_storage) == {"switch.lenta": "ha-lenta"}


async def test_registry_remove_sends_delete_with_saved_id(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    _synced(hass_storage, {"light.sala": "ha-saved"})
    entry = _entry(hass)
    await _setup(hass, entry)
    assert gateway.mock_calls == []

    er.async_get(hass).async_remove("light.sala")
    await hass.async_block_till_done()

    assert _events(gateway, "DeleteReport") == [["ha-saved"]]
    assert _store(hass_storage) == {}


async def test_rename_keeps_id(hass: HomeAssistant, hass_storage, token, gateway) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    entry = _entry(hass)
    await _setup(hass, entry)
    gateway.mock_calls.clear()

    er.async_get(hass).async_update_entity("light.sala", new_entity_id="light.salotto")
    hass.states.async_set("light.salotto", "off", {"friendly_name": "salotto"})
    await hass.async_block_till_done()

    assert _events(gateway, "DeleteReport") == []
    assert _events(gateway, "AddOrUpdateReport") == [[id_sala]]
    assert _store(hass_storage) == {"light.salotto": id_sala}


async def test_never_linked_sends_nothing_and_no_repair_issue(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _light(hass, "sala")
    entry = _entry(hass)

    await _setup(hass, entry)

    assert gateway.mock_calls == []
    assert _issue(hass) is None
    assert STORE_SYNC not in hass_storage or _store(hass_storage) == {}


async def test_unauthorized_after_link_creates_repair_issue(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    # Linked once, then the engine dropped the authorization (e.g. 401/403).
    hass_storage[STORE_CONFIG] = {
        "version": 1,
        "key": STORE_CONFIG,
        "data": {"authorized": False, "linked": True},
    }
    _light(hass, "sala")
    entry = _entry(hass)

    await _setup(hass, entry)

    assert gateway.mock_calls == []
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_key == ISSUE
    assert STORE_SYNC not in hass_storage or _store(hass_storage) == {}


async def test_reconcile_after_stop_does_nothing(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    entry = _entry(hass)
    with patch.object(SyncManager, "async_start"):
        await _setup(hass, entry)
    sync = entry.runtime_data.sync

    sync.async_stop()
    await sync.async_reconcile()

    assert gateway.mock_calls == []
    assert STORE_SYNC not in hass_storage


async def test_forbidden_response_creates_repair_issue(
    hass: HomeAssistant, hass_storage, token, aioclient_mock: AiohttpClientMocker
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    aioclient_mock.post(
        DEFAULT_ENDPOINT,
        status=403,
        json={"header": {}, "payload": {"code": "SKILL_DISABLED_EXCEPTION"}},
    )
    entry = _entry(hass)

    await _setup(hass, entry)

    assert len(aioclient_mock.mock_calls) == 1
    assert _issue(hass) is not None
    assert STORE_SYNC not in hass_storage or _store(hass_storage) == {}


async def test_remove_entry_deletes_all_and_clears_stores(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    hass_storage[STORE_AUTH] = {"version": 1, "key": STORE_AUTH, "data": {"refresh_token": "r"}}
    _light(hass, "sala")
    _synced(hass_storage, {"light.sala": "ha-sala", "light.lenta": "ha-lenta"})
    entry = _entry(hass)
    await _setup(hass, entry)
    gateway.mock_calls.clear()

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    deletes = _events(gateway, "DeleteReport")
    assert len(deletes) == 1
    assert sorted(deletes[0]) == ["ha-lenta", "ha-sala"]
    for key in (STORE_CONFIG, STORE_AUTH, STORE_SYNC):
        assert key not in hass_storage


async def test_remove_entry_without_token_does_not_raise(
    hass: HomeAssistant, hass_storage, gateway
) -> None:
    _authorized(hass_storage)
    _synced(hass_storage, {"light.lenta": "ha-lenta"})
    entry = _entry(hass)
    with patch.object(
        BridgeAuth, "async_get_access_token", AsyncMock(side_effect=RuntimeError("no token"))
    ):
        await _setup(hass, entry)
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    assert gateway.mock_calls == []
    for key in (STORE_CONFIG, STORE_AUTH, STORE_SYNC):
        assert key not in hass_storage


async def test_authorization_triggers_reconcile(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    id_sala = _light(hass, "sala")
    entry = _entry(hass)
    await _setup(hass, entry)
    assert _issue(hass) is None  # never linked: nothing to report yet
    config = entry.runtime_data.config

    # Alexa's first message flips the flag; that alone sends nothing.
    await config.set_authorized(True)
    await hass.async_block_till_done()
    assert gateway.mock_calls == []

    with patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")):
        assert await config.async_accept_grant("code") == "tok"
        await hass.async_block_till_done()

    assert _events(gateway, "AddOrUpdateReport") == [[id_sala]]
    assert _issue(hass) is None
    assert _store(hass_storage) == {"light.sala": id_sala}


async def test_rename_included_entity_keeps_id_and_not_deleted(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    entry = _entry(hass, [], include_entities=["light.sala"])
    await _setup(hass, entry)
    assert _store(hass_storage) == {"light.sala": id_sala}
    gateway.mock_calls.clear()

    er.async_get(hass).async_update_entity("light.sala", new_entity_id="light.salotto")
    hass.states.async_remove("light.sala")
    hass.states.async_set("light.salotto", "off", {"friendly_name": "salotto"})
    await hass.async_block_till_done()
    await entry.runtime_data.sync.async_reconcile()

    assert entry.options["include_entities"] == ["light.salotto"]
    assert _events(gateway, "DeleteReport") == []
    assert _events(gateway, "AddOrUpdateReport") == [[id_sala]]
    assert _store(hass_storage) == {"light.salotto": id_sala}


async def test_rename_excluded_entity_stays_excluded(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    entry = _entry(hass, exclude_entities=["light.cucina"])
    _light(hass, "cucina")
    await _setup(hass, entry)
    assert _store(hass_storage) == {"light.sala": id_sala}
    gateway.mock_calls.clear()

    er.async_get(hass).async_update_entity("light.cucina", new_entity_id="light.dispensa")
    hass.states.async_remove("light.cucina")
    hass.states.async_set("light.dispensa", "off", {"friendly_name": "dispensa"})
    await hass.async_block_till_done()
    await entry.runtime_data.sync.async_reconcile()

    assert entry.options["exclude_entities"] == ["light.dispensa"]
    assert gateway.mock_calls == []
    assert _store(hass_storage) == {"light.sala": id_sala}


async def test_registry_create_sends_add_or_update(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    entry = _entry(hass)
    await _setup(hass, entry)
    assert gateway.mock_calls == []

    new = er.async_get(hass).async_get_or_create("light", "test", "nuova", suggested_object_id="nuova")
    await hass.async_block_till_done()
    assert gateway.mock_calls == []  # no state yet
    hass.states.async_set("light.nuova", "off", {"friendly_name": "nuova"})
    await hass.async_block_till_done()

    assert _events(gateway, "AddOrUpdateReport") == [[f"ha-{new.id}"]]
    assert _store(hass_storage) == {"light.nuova": f"ha-{new.id}"}


async def test_alias_change_sends_add_or_update(
    hass: HomeAssistant, hass_storage, token, gateway
) -> None:
    _authorized(hass_storage)
    id_sala = _light(hass, "sala")
    entry = _entry(hass)
    await _setup(hass, entry)
    gateway.mock_calls.clear()

    er.async_get(hass).async_update_entity("light.sala", aliases=["lampada grande"])
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity("light.sala", name="Sala grande")
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity("light.sala", icon="mdi:lamp")
    await hass.async_block_till_done()

    assert _events(gateway, "AddOrUpdateReport") == [[id_sala], [id_sala]]
    assert _events(gateway, "DeleteReport") == []


async def test_unexpected_error_logged_without_repair_issue(
    hass: HomeAssistant, hass_storage, gateway, caplog: pytest.LogCaptureFixture
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    entry = _entry(hass)
    with patch.object(
        BridgeAuth, "async_get_access_token", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        await _setup(hass, entry)

    assert _issue(hass) is None
    assert "Unexpected error sending event to Alexa" in caplog.text
    assert STORE_SYNC not in hass_storage or _store(hass_storage) == {}


async def test_missing_token_creates_repair_issue(
    hass: HomeAssistant, hass_storage, gateway
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    entry = _entry(hass)
    with patch.object(
        BridgeAuth, "async_get_access_token", AsyncMock(side_effect=NoTokenAvailable)
    ):
        await _setup(hass, entry)

    assert gateway.mock_calls == []
    assert _issue(hass) is not None


async def test_failed_registry_delete_retried_on_reconcile(
    hass: HomeAssistant, hass_storage, token, aioclient_mock: AiohttpClientMocker
) -> None:
    _authorized(hass_storage)
    _light(hass, "sala")
    _synced(hass_storage, {"light.sala": "ha-saved"})
    aioclient_mock.post(DEFAULT_ENDPOINT, status=500, json={"payload": {}})
    entry = _entry(hass)
    await _setup(hass, entry)

    er.async_get(hass).async_remove("light.sala")
    hass.states.async_remove("light.sala")
    await hass.async_block_till_done()
    assert _events(aioclient_mock, "DeleteReport") == [["ha-saved"]]
    data = hass_storage[STORE_SYNC]["data"]
    assert data == {"synced": {}, "pending_delete": {"light.sala": "ha-saved"}}

    aioclient_mock.clear_requests()
    aioclient_mock.post(DEFAULT_ENDPOINT, status=202)
    await entry.runtime_data.sync.async_reconcile()

    assert _events(aioclient_mock, "DeleteReport") == [["ha-saved"]]
    assert hass_storage[STORE_SYNC]["data"] == {"synced": {}, "pending_delete": {}}
