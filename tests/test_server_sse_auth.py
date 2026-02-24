"""
Tests for SSE server authentication: outbound config and inbound middleware.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Tests for create_config_from_env()
# ---------------------------------------------------------------------------


class TestCreateConfigFromEnv(unittest.TestCase):
    """Tests that create_config_from_env() builds correct ServerConfig for each auth type."""

    def _import(self):
        from servicenow_mcp.server_sse import create_config_from_env
        return create_config_from_env

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_instance_url_raises(self):
        fn = self._import()
        with self.assertRaises(ValueError, msg="Should raise when SERVICENOW_INSTANCE_URL absent"):
            fn()

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "basic",
            "SERVICENOW_USERNAME": "admin",
            "SERVICENOW_PASSWORD": "secret",
        },
        clear=True,
    )
    def test_basic_auth_config(self):
        from servicenow_mcp.utils.config import AuthType
        config = self._import()()
        self.assertEqual(config.auth.type, AuthType.BASIC)
        self.assertEqual(config.auth.basic.username, "admin")
        self.assertEqual(config.auth.basic.password, "secret")
        self.assertEqual(config.instance_url, "https://test.service-now.com")

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "basic",
            # USERNAME and PASSWORD deliberately absent
        },
        clear=True,
    )
    def test_basic_auth_missing_credentials_raises(self):
        fn = self._import()
        with self.assertRaises(ValueError):
            fn()

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "api_key",
            "SERVICENOW_API_KEY": "my-api-key-value",
            "SERVICENOW_API_KEY_HEADER": "X-Custom-Key",
        },
        clear=True,
    )
    def test_api_key_auth_config(self):
        from servicenow_mcp.utils.config import AuthType
        config = self._import()()
        self.assertEqual(config.auth.type, AuthType.API_KEY)
        self.assertEqual(config.auth.api_key.api_key, "my-api-key-value")
        self.assertEqual(config.auth.api_key.header_name, "X-Custom-Key")

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "api_key",
            # SERVICENOW_API_KEY deliberately absent
        },
        clear=True,
    )
    def test_api_key_missing_key_raises(self):
        fn = self._import()
        with self.assertRaises(ValueError):
            fn()

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "api_key",
            "SERVICENOW_API_KEY": "key-with-default-header",
            # SERVICENOW_API_KEY_HEADER absent — should use default
        },
        clear=True,
    )
    def test_api_key_default_header_name(self):
        config = self._import()()
        self.assertEqual(config.auth.api_key.header_name, "X-ServiceNow-API-Key")

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "oauth",
            "SERVICENOW_CLIENT_ID": "cid",
            "SERVICENOW_CLIENT_SECRET": "csecret",
            "SERVICENOW_USERNAME": "user",
            "SERVICENOW_PASSWORD": "pass",
            "SERVICENOW_TOKEN_URL": "https://test.service-now.com/oauth_token.do",
        },
        clear=True,
    )
    def test_oauth_auth_config(self):
        from servicenow_mcp.utils.config import AuthType
        config = self._import()()
        self.assertEqual(config.auth.type, AuthType.OAUTH)
        self.assertEqual(config.auth.oauth.client_id, "cid")
        self.assertEqual(config.auth.oauth.client_secret, "csecret")

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "oauth",
            # Missing client_id / client_secret
        },
        clear=True,
    )
    def test_oauth_missing_credentials_raises(self):
        fn = self._import()
        with self.assertRaises(ValueError):
            fn()

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "invalid_type",
        },
        clear=True,
    )
    def test_invalid_auth_type_raises(self):
        fn = self._import()
        with self.assertRaises(ValueError):
            fn()

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            # SERVICENOW_AUTH_TYPE absent — should default to "basic"
            "SERVICENOW_USERNAME": "u",
            "SERVICENOW_PASSWORD": "p",
        },
        clear=True,
    )
    def test_default_auth_type_is_basic(self):
        from servicenow_mcp.utils.config import AuthType
        config = self._import()()
        self.assertEqual(config.auth.type, AuthType.BASIC)


# ---------------------------------------------------------------------------
# Tests for ApiKeyMiddleware
# ---------------------------------------------------------------------------


def _make_test_client(api_key: str, header_name: str = None) -> TestClient:
    """Build a minimal Starlette app with ApiKeyMiddleware applied."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from servicenow_mcp.server_sse import ApiKeyMiddleware

    async def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(ApiKeyMiddleware, api_key=api_key, header_name=header_name)
    return TestClient(app, raise_server_exceptions=False)


class TestApiKeyMiddleware(unittest.TestCase):
    """Tests for inbound ApiKeyMiddleware accept/reject behaviour."""

    def test_valid_bearer_token_accepted(self):
        client = _make_test_client("secret-key-123")
        response = client.get("/", headers={"Authorization": "Bearer secret-key-123"})
        self.assertEqual(response.status_code, 200)

    def test_invalid_bearer_token_rejected(self):
        client = _make_test_client("secret-key-123")
        response = client.get("/", headers={"Authorization": "Bearer wrong-key"})
        self.assertEqual(response.status_code, 401)

    def test_valid_x_api_key_header_accepted(self):
        client = _make_test_client("secret-key-123")
        response = client.get("/", headers={"X-API-Key": "secret-key-123"})
        self.assertEqual(response.status_code, 200)

    def test_invalid_x_api_key_header_rejected(self):
        client = _make_test_client("secret-key-123")
        response = client.get("/", headers={"X-API-Key": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_missing_auth_header_rejected(self):
        client = _make_test_client("secret-key-123")
        response = client.get("/")
        self.assertEqual(response.status_code, 401)

    def test_custom_header_name_accepted(self):
        client = _make_test_client("mykey", header_name="X-Custom-Auth")
        response = client.get("/", headers={"X-Custom-Auth": "mykey"})
        self.assertEqual(response.status_code, 200)

    def test_custom_header_name_wrong_value_rejected(self):
        client = _make_test_client("mykey", header_name="X-Custom-Auth")
        response = client.get("/", headers={"X-Custom-Auth": "wrongkey"})
        self.assertEqual(response.status_code, 401)

    def test_custom_header_name_bearer_ignored(self):
        """When a custom header is set, Bearer token in Authorization should be ignored."""
        client = _make_test_client("mykey", header_name="X-Custom-Auth")
        # Correct key in Authorization Bearer — should still be rejected
        response = client.get("/", headers={"Authorization": "Bearer mykey"})
        self.assertEqual(response.status_code, 401)

    def test_rejection_response_shape(self):
        client = _make_test_client("secret")
        response = client.get("/")
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"], "Unauthorized")
        self.assertIn("message", data)

    def test_empty_string_api_key_is_not_treated_as_disabled(self):
        """An empty-string key should still reject requests without the key."""
        client = _make_test_client("")
        # The middleware is constructed with api_key="" — any provided key != "" is rejected
        response = client.get("/", headers={"Authorization": "Bearer something"})
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# Tests that middleware is skipped when MCP_SERVER_API_KEY is not set
# ---------------------------------------------------------------------------


class TestMiddlewareDisabledWhenNoKey(unittest.TestCase):
    """Verify that inbound_api_key=None is passed when MCP_SERVER_API_KEY is absent."""

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "basic",
            "SERVICENOW_USERNAME": "u",
            "SERVICENOW_PASSWORD": "p",
            # MCP_SERVER_API_KEY deliberately absent
        },
        clear=True,
    )
    @patch("uvicorn.run")
    @patch("servicenow_mcp.server_sse.create_starlette_app")
    def test_no_inbound_key_passed_when_env_var_absent(self, mock_create_app, mock_uvicorn):
        mock_create_app.return_value = MagicMock()

        from servicenow_mcp.server_sse import ServiceNowSSEMCP, create_config_from_env

        config = create_config_from_env()
        server = ServiceNowSSEMCP(config)
        server.start()

        call_kwargs = mock_create_app.call_args[1]
        self.assertIsNone(call_kwargs.get("inbound_api_key"))

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_AUTH_TYPE": "basic",
            "SERVICENOW_USERNAME": "u",
            "SERVICENOW_PASSWORD": "p",
            "MCP_SERVER_API_KEY": "my-secret",
        },
        clear=True,
    )
    @patch("uvicorn.run")
    @patch("servicenow_mcp.server_sse.create_starlette_app")
    def test_inbound_key_passed_when_env_var_present(self, mock_create_app, mock_uvicorn):
        mock_create_app.return_value = MagicMock()

        from servicenow_mcp.server_sse import ServiceNowSSEMCP, create_config_from_env

        config = create_config_from_env()
        server = ServiceNowSSEMCP(config)
        server.start()

        call_kwargs = mock_create_app.call_args[1]
        self.assertEqual(call_kwargs.get("inbound_api_key"), "my-secret")


if __name__ == "__main__":
    unittest.main()
