"""Keep Alexa's device list equal to the user's selection.

Deleting a device on Alexa also loses the rooms and routines the user built
around it, so a device is deleted only on clear evidence: the entity still
exists in Home Assistant (state or registry entry) but is no longer shared,
or it was removed from the registry. Startup, unavailable entities and
reloads never delete anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from http import HTTPStatus
import logging
from typing import Any

import aiohttp

from homeassistant.components.alexa.errors import NoTokenAvailable, RequireRelink
from homeassistant.components.alexa.state_report import (
    async_send_add_or_update_message,
    async_send_delete_message,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .config import BridgeConfig
from .const import CONF_EXCLUDE_ENTITIES, CONF_INCLUDE_ENTITIES, DOMAIN, STORE_SYNC
from .selection import is_shared, shared_entity_ids

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
SEND_TIMEOUT = 10
ISSUE_NOT_AUTHORIZED = "proactive_not_authorized"
_AUTH_REFUSED = frozenset({HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN})
# Registry changes that alter the name Alexa announces.
_NAME_CHANGES = frozenset({"name", "aliases"})
# Registry changes that can move an entity into or out of a shared area.
_AREA_CHANGES = frozenset({"area_id", "device_id"})

type _Sender = Callable[[HomeAssistant, Any, list[str]], Awaitable[aiohttp.ClientResponse]]


@callback
def async_create_not_authorized_issue(hass: HomeAssistant) -> None:
    """Tell the user Alexa does not accept the bridge's events."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_NOT_AUTHORIZED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_NOT_AUTHORIZED,
    )


class _SavedIds:
    """Config view whose endpointIds are the given ones, for DeleteReport."""

    def __init__(self, config: BridgeConfig, ids: Mapping[str, str]) -> None:
        self._config = config
        self._ids = ids

    def generate_alexa_id(self, entity_id: str) -> str:
        return self._ids[entity_id]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._config, name)


class SyncManager:
    """Send AddOrUpdate/Delete reports from the last synced set."""

    def __init__(self, hass: HomeAssistant, config: BridgeConfig) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.config = config
        self._store: Store[dict[str, dict[str, str]]] = Store(hass, STORE_VERSION, STORE_SYNC)
        # Same dict as config.known_ids: the ids Alexa knows are the synced ones.
        self._synced = config.known_ids
        # Removed from the registry, DeleteReport not yet accepted by Alexa.
        self._pending_delete: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._waiting_state: dict[str, CALLBACK_TYPE] = {}
        self._stopped = False

    async def async_load(self) -> None:
        """Load the last synced set into config.known_ids."""
        data = await self._store.async_load() or {}
        self._synced.clear()
        self._synced.update(data.get("synced", {}))
        self._pending_delete = dict(data.get("pending_delete", {}))

    @callback
    def async_start(self) -> None:
        """Reconcile and follow the registry once Home Assistant has started."""
        self._unsubs.append(async_at_started(self.hass, self._async_started))

    async def _async_started(self, hass: HomeAssistant) -> None:
        if self._stopped:
            return
        self._unsubs.append(
            hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_updated)
        )
        self._unsubs.append(
            hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, self._async_device_updated)
        )
        await self.async_reconcile()

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        self._stopped = True
        for unsub in (*self._unsubs, *self._waiting_state.values()):
            unsub()
        self._unsubs.clear()
        self._waiting_state.clear()

    async def async_reconcile(self) -> None:
        """Bring Alexa's device list in line with the selection."""
        if self._stopped:
            # e.g. on_authorized scheduled just before the entry was unloaded.
            return
        async with self._lock:
            if self._pending_delete and await self._async_delete(dict(self._pending_delete)):
                self._pending_delete.clear()
                await self._async_save()
            selection = self.config.selection
            registry = er.async_get(self.hass)
            added = sorted(shared_entity_ids(self.hass, selection) - self._synced.keys())
            gone = sorted(
                entity_id
                for entity_id in self._synced
                if not is_shared(self.hass, entity_id, selection)
                and (
                    self.hass.states.get(entity_id) is not None
                    or registry.async_get(entity_id) is not None
                )
            )
            if added:
                await self._async_add(added)
            if gone and await self._async_delete({e: self._synced[e] for e in gone}):
                for entity_id in gone:
                    del self._synced[entity_id]
                await self._async_save()

    async def async_delete_all(self) -> None:
        """Delete every synced device from Alexa; never raises."""
        async with self._lock:
            for ids in (dict(self._synced), dict(self._pending_delete)):
                if ids:
                    await self._async_delete(ids, raise_issue=False)

    async def _async_add(self, entity_ids: Iterable[str]) -> None:
        # The engine silently skips entities without a state.
        to_send = [e for e in entity_ids if self.hass.states.get(e) is not None]
        if not to_send:
            return
        ids = {entity_id: self.config.generate_alexa_id(entity_id) for entity_id in to_send}
        if await self._async_send(async_send_add_or_update_message, self.config, to_send):
            self._synced.update(ids)
            await self._async_save()

    async def _async_delete(self, ids: Mapping[str, str], *, raise_issue: bool = True) -> bool:
        """Send DeleteReport for the given {entity_id: endpointId}."""
        return await self._async_send(
            async_send_delete_message, _SavedIds(self.config, ids), list(ids), raise_issue=raise_issue
        )

    async def _async_send(
        self, sender: _Sender, config: Any, entity_ids: list[str], *, raise_issue: bool = True
    ) -> bool:
        """Send one report; True only when Alexa accepted it."""
        if raise_issue and not self.config.authorized:
            self._async_not_authorized()
            return False
        try:
            async with asyncio.timeout(SEND_TIMEOUT):
                response = await sender(self.hass, config, entity_ids)
                text = await response.text()
        except (NoTokenAvailable, RequireRelink) as err:
            _LOGGER.warning("No Alexa access token for %s: %r", entity_ids, err)
            if raise_issue:
                self._async_not_authorized()
            return False
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("Could not reach Alexa for %s: %r", entity_ids, err)
            return False
        except Exception:
            _LOGGER.exception("Unexpected error sending event to Alexa for %s", entity_ids)
            return False
        if response.status in _AUTH_REFUSED:
            _LOGGER.warning("Alexa refused events (%s): %s", response.status, text)
            if raise_issue:
                self._async_not_authorized()
            return False
        if not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
            _LOGGER.warning("Alexa rejected event (%s): %s", response.status, text)
            return False
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_NOT_AUTHORIZED)
        return True

    @callback
    def _async_not_authorized(self) -> None:
        # Before the first account link nothing is wrong yet: stay silent.
        if self.config.linked:
            async_create_not_authorized_issue(self.hass)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"synced": dict(self._synced), "pending_delete": dict(self._pending_delete)}
        )

    async def _async_registry_updated(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        # Let the entity's own registry callback rewrite its state first, so
        # the AddOrUpdate below carries the new name.
        await asyncio.sleep(0)
        data = event.data
        entity_id = data["entity_id"]
        if data["action"] == "remove":
            await self._async_removed(entity_id)
        elif data["action"] == "create":
            # Entities outside the registry are picked up by the next reconcile.
            if entity_id not in self._synced and is_shared(
                self.hass, entity_id, self.config.selection
            ):
                await self._async_add_now_or_later(entity_id)
        elif old := data.get("old_entity_id"):
            await self._async_renamed(old, entity_id)
        elif _AREA_CHANGES & data["changes"].keys() and self.config.selection.areas:
            await self.async_reconcile()
        elif entity_id in self._synced and _NAME_CHANGES & data["changes"].keys():
            await self._async_add_now_or_later(entity_id)

    async def _async_device_updated(self, event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        # A device moved to or out of a shared area takes its entities along.
        data = event.data
        if (
            data["action"] == "update"
            and "area_id" in data["changes"]
            and self.config.selection.areas
        ):
            await self.async_reconcile()

    async def _async_removed(self, entity_id: str) -> None:
        async with self._lock:
            if entity_id not in self._synced:
                return
            ids = {entity_id: self._synced.pop(entity_id)}
            if not await self._async_delete(ids):
                # Retried by the next reconcile, never forgotten.
                self._pending_delete.update(ids)
            await self._async_save()

    async def _async_renamed(self, old: str, new: str) -> None:
        async with self._lock:
            # The selection names entities by entity_id: follow the rename,
            # under the lock so the reconcile it triggers sees both changes.
            self._async_rename_in_options(old, new)
            if old not in self._synced:
                return
            self._synced[new] = self._synced.pop(old)
            await self._async_save()
        await self._async_add_now_or_later(new)

    @callback
    def _async_rename_in_options(self, old: str, new: str) -> None:
        entry = self.config.entry
        options = dict(entry.options)
        changed = False
        for key in (CONF_INCLUDE_ENTITIES, CONF_EXCLUDE_ENTITIES):
            entity_ids = list(options.get(key) or ())
            if old in entity_ids:
                options[key] = [new if e == old else e for e in entity_ids]
                changed = True
        if changed:
            self.hass.config_entries.async_update_entry(entry, options=options)

    async def _async_add_now_or_later(self, entity_id: str) -> None:
        """AddOrUpdate a shared entity once it has a state."""
        if self.hass.states.get(entity_id) is None:
            self._async_add_when_state(entity_id)
            return
        async with self._lock:
            if is_shared(self.hass, entity_id, self.config.selection):
                await self._async_add([entity_id])

    @callback
    def _async_add_when_state(self, entity_id: str) -> None:
        if entity_id in self._waiting_state:
            return

        async def _state_changed(event: Event[EventStateChangedData]) -> None:
            if event.data["new_state"] is None:
                return
            if unsub := self._waiting_state.pop(entity_id, None):
                unsub()
            await self._async_add_now_or_later(entity_id)

        self._waiting_state[entity_id] = async_track_state_change_event(
            self.hass, entity_id, _state_changed
        )
