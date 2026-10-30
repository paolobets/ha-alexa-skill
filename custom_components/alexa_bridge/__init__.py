"""Expose chosen Home Assistant entities to Alexa."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .config import BridgeConfig
from .const import DOMAIN, STORE_AUTH, STORE_CONFIG, STORE_SYNC
from .sync import ISSUE_NOT_AUTHORIZED, SyncManager
from .view import BridgeSmartHomeView

_LOGGER = logging.getLogger(__name__)

DATA_CONFIG = "config"
DATA_VIEW_REGISTERED = "view_registered"
ISSUE_STOCK_ALEXA = "stock_alexa_configured"
STOCK_ALEXA_DOMAIN = "alexa"


@dataclass
class BridgeRuntime:
    """Runtime objects of a loaded entry."""

    config: BridgeConfig
    sync: SyncManager | None = None


type BridgeConfigEntry = ConfigEntry[BridgeRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    """Set up Alexa Bridge from a config entry."""
    config = BridgeConfig(hass, entry)
    await config.async_initialize()

    data = hass.data.setdefault(DOMAIN, {})
    data[DATA_CONFIG] = config
    # HA views cannot be unregistered: register once per process and let the
    # view read the current config, None while no entry is loaded.
    if not data.get(DATA_VIEW_REGISTERED):
        hass.http.register_view(
            BridgeSmartHomeView(lambda: hass.data[DOMAIN].get(DATA_CONFIG))
        )
        data[DATA_VIEW_REGISTERED] = True

    sync = SyncManager(hass, config)
    await sync.async_load()
    config.on_authorized = sync.async_reconcile
    entry.runtime_data = BridgeRuntime(config=config, sync=sync)

    if config.should_report_state:
        # Authorization persisted from an earlier run: nothing else turns it on.
        try:
            await config.async_enable_proactive_mode()
        except Exception:
            _LOGGER.exception("Could not enable proactive state reporting to Alexa")

    _async_check_stock_alexa(hass)
    sync.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: BridgeConfigEntry) -> None:
    """Apply a new selection without reloading the integration."""
    if (sync := entry.runtime_data.sync) is not None:
        await sync.async_reconcile()


async def async_unload_entry(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    """Unload a config entry."""
    config = entry.runtime_data.config
    if (sync := entry.runtime_data.sync) is not None:
        sync.async_stop()
    config.on_authorized = None
    hass.data[DOMAIN][DATA_CONFIG] = None
    await config.async_disable_proactive_mode()
    config.async_deinitialize()
    ir.async_delete_issue(hass, DOMAIN, ISSUE_STOCK_ALEXA)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BridgeConfigEntry) -> None:
    """Delete every synced device from Alexa, then the bridge's stores."""
    config = BridgeConfig(hass, entry)
    try:
        await config.async_initialize()
        sync = SyncManager(hass, config)
        await sync.async_load()
        await sync.async_delete_all()
    except Exception:
        _LOGGER.exception("Could not delete the devices from Alexa")
    for key in (STORE_CONFIG, STORE_AUTH, STORE_SYNC):
        await Store(hass, 1, key).async_remove()
    ir.async_delete_issue(hass, DOMAIN, ISSUE_NOT_AUTHORIZED)


def _async_check_stock_alexa(hass: HomeAssistant) -> None:
    """Warn when the built-in Alexa integration would answer too."""
    if STOCK_ALEXA_DOMAIN in hass.config.components:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_STOCK_ALEXA,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_STOCK_ALEXA,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_STOCK_ALEXA)
