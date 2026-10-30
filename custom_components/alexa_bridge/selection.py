"""Rule deciding which Home Assistant entities are shared with Alexa."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.alexa.entities import ENTITY_ADAPTERS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    BINARY_SENSOR_CLASSES,
    BLOCKED_DOMAINS,
    CONF_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    ECHO_PLATFORM,
)


@dataclass(frozen=True)
class Selection:
    """User choice: whole domains plus per-entity overrides."""

    domains: frozenset[str]
    include: frozenset[str]
    exclude: frozenset[str]

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Selection:
        """Build a selection from entry options; missing keys mean empty."""
        return cls(
            frozenset(options.get(CONF_DOMAINS) or ()),
            frozenset(options.get(CONF_INCLUDE_ENTITIES) or ()),
            frozenset(options.get(CONF_EXCLUDE_ENTITIES) or ()),
        )


def selectable_domains() -> list[str]:
    """Domains the user may pick: those Alexa supports minus blocked ones."""
    return sorted(set(ENTITY_ADAPTERS) - BLOCKED_DOMAINS)


def is_shared(hass: HomeAssistant, entity_id: str, selection: Selection) -> bool:
    """Return True if the entity is shared with Alexa."""
    domain = entity_id.partition(".")[0]
    if domain in BLOCKED_DOMAINS or domain not in ENTITY_ADAPTERS:
        return False
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.platform == ECHO_PLATFORM:
        return False
    if entity_id in selection.exclude:
        return False
    if entity_id in selection.include:
        return True
    if domain not in selection.domains:
        return False
    if entry is not None and (entry.entity_category or entry.hidden_by):
        return False
    if domain == "binary_sensor":
        device_class = None
        if entry is not None:
            device_class = entry.device_class or entry.original_device_class
        if device_class is None:
            state = hass.states.get(entity_id)
            device_class = state.attributes.get("device_class") if state else None
        if device_class not in BINARY_SENSOR_CLASSES:
            return False
    return True


def shared_entity_ids(hass: HomeAssistant, selection: Selection) -> set[str]:
    """All current states that are shared with Alexa."""
    return {
        state.entity_id
        for state in hass.states.async_all()
        if state.domain in ENTITY_ADAPTERS and is_shared(hass, state.entity_id, selection)
    }
