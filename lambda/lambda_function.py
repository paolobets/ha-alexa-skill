"""AWS Lambda bridge: Alexa Smart Home directives -> Home Assistant.

Forwards every directive, unchanged, to the Alexa Bridge custom integration
view in Home Assistant and returns its JSON answer. Standard library only.

Environment variables:
    BASE_URL                 Home Assistant base URL, no trailing slash (required)
    HA_PATH                  view path (default /api/alexa_bridge/smart_home)
    NOT_VERIFY_SSL           "true" to skip TLS verification (testing only)
    DEBUG                    "true" to enable debug logging and the test token
    LONG_LIVED_ACCESS_TOKEN  test token, used only when DEBUG is on and the
                             directive carries no token
"""

import json
import logging
import os
import ssl
import urllib.error
import urllib.request
import uuid

DEFAULT_HA_PATH = "/api/alexa_bridge/smart_home"
TIMEOUT_SECONDS = 8
# Cloudflare answers 403 to the default "Python-urllib" agent.
USER_AGENT = "ha-alexa-bridge/0.1.1"

_LOGGER = logging.getLogger()
_LOGGER.setLevel(logging.INFO)


def _flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _directive_token(directive):
    """Return the bearer token, looking in the places Alexa puts it."""
    candidates = (
        (directive.get("endpoint") or {}).get("scope"),
        (directive.get("payload") or {}).get("grantee"),
        (directive.get("payload") or {}).get("scope"),
    )
    for scope in candidates:
        if isinstance(scope, dict) and scope.get("token"):
            return scope["token"]
    return None


def _error_response(directive, error_type, message):
    header = directive.get("header") or {}
    event = {
        "header": {
            "namespace": "Alexa",
            "name": "ErrorResponse",
            "messageId": str(uuid.uuid4()),
            "payloadVersion": "3",
        },
        "payload": {"type": error_type, "message": message},
    }
    if header.get("correlationToken"):
        event["header"]["correlationToken"] = header["correlationToken"]
    endpoint_id = (directive.get("endpoint") or {}).get("endpointId")
    if endpoint_id:
        event["endpoint"] = {"endpointId": endpoint_id}
    return {"event": event}


def lambda_handler(event, context):
    """Forward an Alexa directive to Home Assistant."""
    debug = _flag("DEBUG")
    if debug:
        _LOGGER.setLevel(logging.DEBUG)

    base_url = os.environ.get("BASE_URL", "")
    if not base_url:
        raise ValueError("BASE_URL is required")
    if base_url.endswith("/"):
        raise ValueError("BASE_URL must not end with '/'")
    path = os.environ.get("HA_PATH") or DEFAULT_HA_PATH

    directive = event.get("directive") or {}
    header = directive.get("header") or {}
    if header.get("payloadVersion") != "3":
        raise ValueError("Only Alexa Smart Home API payloadVersion 3 is supported")

    token = _directive_token(directive)
    if token is None and debug:
        token = os.environ.get("LONG_LIVED_ACCESS_TOKEN") or None
    if token is None:
        return _error_response(
            directive,
            "INVALID_AUTHORIZATION_CREDENTIAL",
            "Missing authorization token",
        )

    _LOGGER.debug(
        "Forwarding %s/%s", header.get("namespace"), header.get("name")
    )

    request = urllib.request.Request(
        base_url + path,
        data=json.dumps(event).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    kwargs = {"timeout": TIMEOUT_SECONDS}
    if _flag("NOT_VERIFY_SSL"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["context"] = ctx

    try:
        with urllib.request.urlopen(request, **kwargs) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        _LOGGER.error("Home Assistant answered HTTP %s", err.code)
        if err.code in (401, 403):
            return _error_response(
                directive,
                "INVALID_AUTHORIZATION_CREDENTIAL",
                "Home Assistant rejected the credentials",
            )
        return _error_response(directive, "INTERNAL_ERROR", f"Home Assistant error {err.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        _LOGGER.error("Home Assistant request failed: %s", type(err).__name__)
        return _error_response(directive, "INTERNAL_ERROR", "Home Assistant unreachable")
