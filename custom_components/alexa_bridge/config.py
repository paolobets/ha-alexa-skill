"""Alexa config for the bridge, driving Home Assistant's built-in Alexa engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from homeassistant.components.alexa.auth import STORAGE_VERSION, Auth
from homeassistant.components.alexa.config import (
    STORE_AUTHORIZED,
    AbstractConfig,
    AlexaConfigStore,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ENDPOINT,
    CONF_LOCALE,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCALE,
    STORE_AUTH,
    STORE_CONFIG,
)
from .ids import stable_alexa_id
from .selection import Selection, is_shared

_LOGGER = logging.getLogger(__name__)


STORE_LINKED = "linked"


class BridgeConfigStore(AlexaConfigStore):
    """Authorization store kept apart from the built-in Alexa integration.

    Besides the engine's flag it remembers whether Alexa ever authorized the
    bridge, so a missing authorization is reported only after a first link.
    """

    _STORAGE_KEY = STORE_CONFIG

    @property
    def linked(self) -> bool:
        """Whether Alexa has authorized the bridge at least once."""
        assert self._data is not None
        return bool(self._data.get(STORE_LINKED) or self.authorized)

    @callback
    def set_authorized(self, authorized: bool) -> None:
        """Set authorization status, remembering the first authorization."""
        if authorized and self._data is not None and not self._data.get(STORE_LINKED):
            self._data[STORE_LINKED] = True
            if self._data[STORE_AUTHORIZED]:
                # The engine saves only on a change: save the new flag here.
                self._store.async_delay_save(lambda: self._data, 1.0)
        super().set_authorized(authorized)


class BridgeAuth(Auth):
    """LWA token handling kept apart from the built-in Alexa integration."""

    def __init__(self, hass: HomeAssistant, client_id: str, client_secret: str) -> None:
        """Initialize auth with the bridge's own token store."""
        # The developer console copy button adds a space around the values.
        super().__init__(hass, client_id.strip(), client_secret.strip())
        self._store = Store(hass, STORAGE_VERSION, STORE_AUTH)


class BridgeConfig(AbstractConfig):
    """Alexa config backed by a config entry."""

    _store: BridgeConfigStore

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the bridge config."""
        super().__init__(hass)
        self._entry = entry
        self._auth = BridgeAuth(hass, entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET])
        # endpointIds already announced to Alexa, filled by the sync manager.
        self.known_ids: dict[str, str] = {}
        self.on_authorized: Callable[[], Awaitable[None]] | None = None

    async def async_initialize(self) -> None:
        """Load the bridge's own authorization store."""
        self._store = BridgeConfigStore(self.hass)
        await self._store.async_load()

    @property
    def supports_auth(self) -> bool:
        """The bridge always holds LWA credentials."""
        return True

    @property
    def linked(self) -> bool:
        """Whether Alexa has authorized the bridge at least once."""
        return self._store.linked

    @property
    def should_report_state(self) -> bool:
        """Report states once Alexa has authorized the bridge."""
        return self.authorized

    @property
    def endpoint(self) -> str:
        """Alexa event gateway endpoint."""
        return self._entry.data.get(CONF_ENDPOINT) or DEFAULT_ENDPOINT

    @property
    def locale(self) -> str:
        """Locale used for names and capabilities."""
        return self._entry.data.get(CONF_LOCALE) or DEFAULT_LOCALE

    @property
    def entity_config(self) -> dict:
        """No per-entity overrides."""
        return {}

    @callback
    def user_identifier(self) -> str:
        """Identify this config by its entry."""
        return self._entry.entry_id

    @property
    def entry(self) -> ConfigEntry:
        """The config entry holding credentials and selection."""
        return self._entry

    @property
    def selection(self) -> Selection:
        """Current user selection from the entry options."""
        return Selection.from_options(self._entry.options)

    @callback
    def should_expose(self, entity_id: str) -> bool:
        """Expose exactly the shared entities."""
        return is_shared(self.hass, entity_id, self.selection)

    def generate_alexa_id(self, entity_id: str) -> str:
        """Prefer the id already announced to Alexa, else the stable id."""
        if (known := self.known_ids.get(entity_id)) is not None:
            return known
        return stable_alexa_id(self.hass, entity_id)

    @callback
    def async_invalidate_access_token(self) -> None:
        """Invalidate the access token."""
        self._auth.async_invalidate_access_token()

    async def async_get_access_token(self) -> str | None:
        """Get an access token."""
        return await self._auth.async_get_access_token()

    async def async_accept_grant(self, code: str) -> str | None:
        """Accept a grant, then schedule on_authorized in the background.

        on_authorized runs only once the LWA token exists (the engine returns
        None, without raising, on a failed exchange), never delays the
        AcceptGrant reply and can never turn it into an error.
        """
        token = await self._auth.async_do_auth(code)
        if token and self.on_authorized is not None:
            self.hass.async_create_task(
                self._async_run_on_authorized(self.on_authorized),
                "alexa_bridge on_authorized",
            )
        return token

    async def _async_run_on_authorized(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run the on_authorized hook, logging any failure."""
        try:
            await hook()
        except Exception:
            _LOGGER.exception("on_authorized hook failed after AcceptGrant")
