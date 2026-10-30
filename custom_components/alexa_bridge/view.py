"""HTTP view receiving Alexa Smart Home directives from the Lambda."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from aiohttp import web

from homeassistant.auth.models import User
from homeassistant.components.alexa.errors import AlexaBridgeUnreachableError
from homeassistant.components.alexa.smart_home import async_handle_message
from homeassistant.components.alexa.state_report import AlexaDirective
from homeassistant.components.http import KEY_HASS, HomeAssistantRequest, HomeAssistantView
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .config import BridgeConfig
from .const import DOMAIN, VIEW_URL
from .ids import entity_id_from_alexa_id, legacy_alexa_id
from .sync import ISSUE_NOT_AUTHORIZED, async_create_not_authorized_issue

_LOGGER = logging.getLogger(__name__)

ACCEPT_GRANT = ("Alexa.Authorization", "AcceptGrant")


def _bridge_unreachable(message: dict[str, Any]) -> dict[str, Any]:
    """Answer any directive with BRIDGE_UNREACHABLE.

    Not via async_handle_message(enabled=False): for directives carrying an
    endpoint it asserts directive.entity_id, which is never loaded when
    disabled, so it raises instead of answering.
    """
    error = AlexaBridgeUnreachableError("Alexa Bridge is not configured")
    return (
        AlexaDirective(message)
        .error(error_type=str(error.error_type), error_message=error.error_message)
        .serialize()
    )


async def _async_accept_grant(
    hass: HomeAssistant, config: BridgeConfig, message: dict[str, Any]
) -> dict[str, Any]:
    """Answer AcceptGrant here, never through the engine.

    The engine's handler enables proactive mode with the module-level
    function, adding a second state listener that the config does not track:
    duplicate ChangeReports, one more per relink, still running after unload.
    It also answers success when the LWA exchange failed. Here the only
    listener is the config's own (idempotent, removed on unload), and a failed
    exchange is reported to Alexa and to the user.
    """
    directive = AlexaDirective(message)
    token: str | None = None
    try:
        code: str = directive.payload["grant"]["code"]
        await config.set_authorized(True)
        token = await config.async_accept_grant(code)
    except Exception:
        _LOGGER.exception("AcceptGrant failed")
        token = None

    if token:
        try:
            # Tracked by the config and idempotent: never a second listener.
            await config.async_enable_proactive_mode()
        except Exception:
            # The grant itself succeeded: report it as such to Alexa.
            _LOGGER.exception("Could not enable proactive state reporting to Alexa")
    else:
        _LOGGER.error(
            "Alexa account linking failed: no token from Login with Amazon. Check the"
            " skill's Alexa Skill Messaging Client ID/Secret and 'Send Alexa Events'"
        )
        try:
            # No token: the state listener could only fail, keep it off.
            await config.set_authorized(False)
        except Exception:
            _LOGGER.exception("Could not reset the Alexa authorization")
        async_create_not_authorized_issue(hass)
        return (
            directive.error(
                namespace="Alexa.Authorization",
                error_type="ACCEPT_GRANT_FAILED",
                error_message="Failed to retrieve the LWA tokens from the authorization code",
            )
            .serialize()
        )

    ir.async_delete_issue(hass, DOMAIN, ISSUE_NOT_AUTHORIZED)
    return directive.response(
        name="AcceptGrant.Response", namespace="Alexa.Authorization", payload={}
    ).serialize()


class BridgeSmartHomeView(HomeAssistantView):
    """Alexa Smart Home v3 endpoint speaking stable endpointIds."""

    url = VIEW_URL
    name = "api:alexa_bridge:smart_home"
    requires_auth = True

    def __init__(self, get_config: Callable[[], BridgeConfig | None]) -> None:
        """Initialize with a getter, so the view outlives config reloads."""
        self._get_config = get_config

    async def post(self, request: HomeAssistantRequest) -> web.Response | bytes:
        """Translate the stable id, run the built-in engine, restore the id."""
        hass = request.app[KEY_HASS]
        user: User = request["hass_user"]
        message: dict[str, Any] = await request.json()

        endpoint = message.get("directive", {}).get("endpoint")
        received_id = endpoint.get("endpointId") if isinstance(endpoint, dict) else None

        header = message.get("directive", {}).get("header", {})
        config = self._get_config()
        if config is None:
            response = _bridge_unreachable(message)
        elif (header.get("namespace"), header.get("name")) == ACCEPT_GRANT:
            response = await _async_accept_grant(hass, config, message)
        else:
            if isinstance(received_id, str):
                # Unknown ids stay as received: the engine answers NO_SUCH_ENDPOINT.
                if (entity_id := entity_id_from_alexa_id(hass, received_id)) is not None:
                    endpoint["endpointId"] = legacy_alexa_id(entity_id)
            response = await async_handle_message(
                hass, config, message, context=Context(user_id=user.id)
            )

        if response is None:
            return b""
        response_endpoint = response.get("event", {}).get("endpoint")
        if received_id is not None and isinstance(response_endpoint, dict):
            response_endpoint["endpointId"] = received_id
        return self.json(response)
