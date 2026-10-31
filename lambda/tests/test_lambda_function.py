"""Tests for the Alexa Smart Home -> Home Assistant bridge Lambda."""

import io
import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lambda_function  # noqa: E402

BASE = "https://ha.example.test"
PATH = "/api/alexa_bridge/smart_home"
HA_RESPONSE = {"event": {"header": {"namespace": "Alexa.Discovery", "name": "Discover.Response"}}}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("BASE_URL", "HA_PATH", "NOT_VERIFY_SSL", "DEBUG", "LONG_LIVED_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BASE_URL", BASE)


def _event(name="Discover", namespace="Alexa.Discovery", **directive_extra):
    directive = {
        "header": {
            "namespace": namespace,
            "name": name,
            "payloadVersion": "3",
            "messageId": "m-1",
            "correlationToken": "c-1",
        },
        "endpoint": {"endpointId": "light#x", "scope": {"type": "BearerToken", "token": "tok-endpoint"}},
        "payload": {},
    }
    directive.update(directive_extra)
    return {"directive": directive}


def _ok_response(body=None):
    resp = MagicMock()
    resp.read.return_value = json.dumps(body or HA_RESPONSE).encode()
    resp.__enter__.return_value = resp
    return resp


def _http_error(code):
    return urllib.error.HTTPError(BASE + PATH, code, "err", {}, io.BytesIO(b"{}"))


def test_forwards_to_bridge_path_with_bearer():
    event = _event()
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        result = lambda_function.lambda_handler(event, None)

    assert result == HA_RESPONSE
    request = urlopen.call_args.args[0]
    assert request.full_url == BASE + PATH
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tok-endpoint"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == event
    assert urlopen.call_args.kwargs.get("timeout")


def test_sends_own_user_agent():
    # Cloudflare blocks the default "Python-urllib" agent with HTTP 403.
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(_event(), None)

    agent = urlopen.call_args.args[0].get_header("User-agent")
    assert agent == lambda_function.USER_AGENT
    assert not agent.startswith("Python-urllib")


def test_token_from_grantee_for_accept_grant():
    event = _event("AcceptGrant", "Alexa.Authorization")
    del event["directive"]["endpoint"]
    event["directive"]["payload"] = {"grant": {"code": "c"}, "grantee": {"type": "BearerToken", "token": "tok-grantee"}}
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(event, None)

    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer tok-grantee"


def test_token_from_payload_scope():
    event = _event()
    del event["directive"]["endpoint"]
    event["directive"]["payload"] = {"scope": {"type": "BearerToken", "token": "tok-scope"}}
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(event, None)

    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer tok-scope"


@pytest.mark.parametrize("code", [401, 403])
def test_401_maps_to_invalid_authorization_credential(code):
    with patch("urllib.request.urlopen", side_effect=_http_error(code)):
        result = lambda_function.lambda_handler(_event(), None)

    header = result["event"]["header"]
    assert header["namespace"] == "Alexa"
    assert header["name"] == "ErrorResponse"
    assert header["correlationToken"] == "c-1"
    assert result["event"]["payload"]["type"] == "INVALID_AUTHORIZATION_CREDENTIAL"
    assert result["event"]["endpoint"]["endpointId"] == "light#x"


@pytest.mark.parametrize(
    "error",
    [_http_error(500), urllib.error.URLError("boom"), TimeoutError()],
)
def test_other_errors_map_to_internal_error(error):
    with patch("urllib.request.urlopen", side_effect=error):
        result = lambda_function.lambda_handler(_event(), None)

    assert result["event"]["header"]["name"] == "ErrorResponse"
    assert result["event"]["payload"]["type"] == "INTERNAL_ERROR"


def test_long_lived_token_only_with_debug(monkeypatch):
    monkeypatch.setenv("LONG_LIVED_ACCESS_TOKEN", "test-token")
    event = _event()
    del event["directive"]["endpoint"]

    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        result = lambda_function.lambda_handler(event, None)
    urlopen.assert_not_called()
    assert result["event"]["payload"]["type"] == "INVALID_AUTHORIZATION_CREDENTIAL"

    monkeypatch.setenv("DEBUG", "true")
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(event, None)
    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer test-token"


def test_directive_token_wins_over_long_lived_token(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LONG_LIVED_ACCESS_TOKEN", "test-token")
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(_event(), None)
    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer tok-endpoint"


def test_base_url_trailing_slash_rejected(monkeypatch):
    monkeypatch.setenv("BASE_URL", BASE + "/")
    with patch("urllib.request.urlopen") as urlopen, pytest.raises(ValueError):
        lambda_function.lambda_handler(_event(), None)
    urlopen.assert_not_called()


def test_base_url_missing_rejected(monkeypatch):
    monkeypatch.delenv("BASE_URL")
    with pytest.raises(ValueError):
        lambda_function.lambda_handler(_event(), None)


def test_payload_version_other_than_3_rejected():
    event = _event()
    event["directive"]["header"]["payloadVersion"] = "2"
    with patch("urllib.request.urlopen") as urlopen, pytest.raises(ValueError):
        lambda_function.lambda_handler(event, None)
    urlopen.assert_not_called()


def test_custom_ha_path(monkeypatch):
    monkeypatch.setenv("HA_PATH", "/api/other")
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(_event(), None)
    assert urlopen.call_args.args[0].full_url == BASE + "/api/other"


def test_not_verify_ssl_passes_unverified_context(monkeypatch):
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(_event(), None)
    assert urlopen.call_args.kwargs.get("context") is None

    monkeypatch.setenv("NOT_VERIFY_SSL", "true")
    with patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen:
        lambda_function.lambda_handler(_event(), None)
    context = urlopen.call_args.kwargs["context"]
    assert context.check_hostname is False


def _load_template():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def tag(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {suffix: loader.construct_scalar(node)}
        return {suffix: loader.construct_sequence(node)}

    Loader.add_multi_constructor("!", tag)
    path = os.path.join(os.path.dirname(__file__), "..", "template.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.load(handle, Loader)


def test_template_grants_alexa_smart_home_principal_for_skill_only():
    resources = _load_template()["Resources"]

    permissions = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Permission"]
    assert len(permissions) == 1
    props = permissions[0]["Properties"]
    assert props["Principal"] == "alexa-connectedhome.amazon.com"
    assert props["Action"] == "lambda:InvokeFunction"
    assert props["EventSourceToken"] == {"Ref": "SkillId"}

    function = next(r for r in resources.values() if r["Type"] == "AWS::Serverless::Function")
    assert "Events" not in function["Properties"]
    assert "AlexaSkill" not in json.dumps(resources)
