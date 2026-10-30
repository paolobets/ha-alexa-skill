"""Stable Alexa endpoint ids derived from the entity registry."""

from __future__ import annotations

from homeassistant.components.alexa.entities import TRANSLATION_TABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import STABLE_ID_PREFIX


def legacy_alexa_id(entity_id: str) -> str:
    """Return the id Home Assistant's own Alexa engine derives from an entity_id."""
    return entity_id.replace(".", "#").translate(TRANSLATION_TABLE)


def stable_alexa_id(hass: HomeAssistant, entity_id: str) -> str:
    """Return the endpointId for an entity.

    Registry entries get an id based on the registry entry id, which survives
    entity_id renames; entities outside the registry fall back to the legacy form.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return legacy_alexa_id(entity_id)
    return STABLE_ID_PREFIX + entry.id


def entity_id_from_alexa_id(hass: HomeAssistant, alexa_id: str) -> str | None:
    """Return the entity_id for an endpointId, or None if a stable id is unknown."""
    if alexa_id.startswith(STABLE_ID_PREFIX):
        entry = er.async_get(hass).entities.get_entry(alexa_id[len(STABLE_ID_PREFIX) :])
        return entry.entity_id if entry else None
    return alexa_id.replace("#", ".")
