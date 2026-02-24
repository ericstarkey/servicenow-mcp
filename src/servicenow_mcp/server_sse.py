"""
ServiceNow MCP Server - SSE Transport

This module provides the SSE (Server-Sent Events) based HTTP server for the
ServiceNow MCP server, suitable for deployment as a remote MCP endpoint.
"""

import argparse
import logging
import os
import sys
from typing import Optional, Union

import uvicorn
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
    ServerConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate inbound API keys on all SSE/messages requests.

    Activated only when MCP_SERVER_API_KEY environment variable is set.
    Supports two key detection modes:

    1. If MCP_SERVER_API_KEY_HEADER is set, look for the key in that exact header.
    2. Otherwise, auto-detect:
       - Check Authorization: Bearer <key> first
       - Fall back to X-API-Key header

    Returns 401 JSON if the key is missing or does not match.
    """

    def __init__(self, app, api_key: str, header_name: Optional[str] = None):
        super().__init__(app)
        self.api_key = api_key
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        provided_key = None

        if self.header_name:
            provided_key = request.headers.get(self.header_name)
        else:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided_key = auth_header[7:]
            else:
                provided_key = request.headers.get("X-API-Key")

        if provided_key != self.api_key:
            return JSONResponse(
                {"error": "Unauthorized", "message": "Invalid or missing API key"},
                status_code=401,
            )

        return await call_next(request)


def create_starlette_app(
    mcp_server: Server,
    *,
    debug: bool = False,
    inbound_api_key: Optional[str] = None,
    inbound_api_key_header: Optional[str] = None,
) -> Starlette:
    """
    Create a Starlette application that serves the provided MCP server with SSE.

    Args:
        mcp_server: The MCP server instance to serve.
        debug: Enable Starlette debug mode.
        inbound_api_key: If set, all requests must present this key.
        inbound_api_key_header: Custom header to check for the inbound key.
                                If None, checks Authorization Bearer then X-API-Key.
    """
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    app = Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    if inbound_api_key:
        app.add_middleware(
            ApiKeyMiddleware,
            api_key=inbound_api_key,
            header_name=inbound_api_key_header,
        )

    return app


class ServiceNowSSEMCP(ServiceNowMCP):
    """
    ServiceNow MCP Server with SSE transport.

    Wraps ServiceNowMCP with a Starlette/Uvicorn HTTP server that exposes
    the MCP protocol over Server-Sent Events.
    """

    def __init__(self, config: Union[dict, ServerConfig]):
        super().__init__(config)

    def start(self, host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
        """
        Start the MCP server with SSE transport.

        Args:
            host: Host address to bind to.
            port: Port to listen on.
            debug: Enable debug mode.
        """
        inbound_api_key = os.getenv("MCP_SERVER_API_KEY")
        inbound_api_key_header = os.getenv("MCP_SERVER_API_KEY_HEADER") or None

        if inbound_api_key:
            logger.info("Inbound API key authentication is enabled")
        else:
            logger.warning(
                "MCP_SERVER_API_KEY is not set — the /sse endpoint is unprotected"
            )

        starlette_app = create_starlette_app(
            self.mcp_server,
            debug=debug,
            inbound_api_key=inbound_api_key,
            inbound_api_key_header=inbound_api_key_header,
        )

        uvicorn.run(starlette_app, host=host, port=port)


def create_config_from_env() -> ServerConfig:
    """
    Build a ServerConfig from environment variables.

    Reads SERVICENOW_AUTH_TYPE (basic | oauth | api_key) and constructs
    the appropriate AuthConfig. Raises ValueError for missing required vars.
    """
    instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
    if not instance_url:
        raise ValueError("SERVICENOW_INSTANCE_URL environment variable is required")

    auth_type_str = os.getenv("SERVICENOW_AUTH_TYPE", "basic").lower()
    try:
        auth_type = AuthType(auth_type_str)
    except ValueError:
        raise ValueError(
            f"Invalid SERVICENOW_AUTH_TYPE: '{auth_type_str}'. "
            "Must be one of: basic, oauth, api_key"
        )

    if auth_type == AuthType.BASIC:
        username = os.getenv("SERVICENOW_USERNAME")
        password = os.getenv("SERVICENOW_PASSWORD")
        if not username or not password:
            raise ValueError(
                "SERVICENOW_USERNAME and SERVICENOW_PASSWORD are required for basic auth"
            )
        auth_config = AuthConfig(
            type=auth_type,
            basic=BasicAuthConfig(username=username, password=password),
        )

    elif auth_type == AuthType.API_KEY:
        api_key = os.getenv("SERVICENOW_API_KEY")
        if not api_key:
            raise ValueError("SERVICENOW_API_KEY is required for api_key auth")
        header_name = os.getenv("SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key")
        auth_config = AuthConfig(
            type=auth_type,
            api_key=ApiKeyConfig(api_key=api_key, header_name=header_name),
        )

    elif auth_type == AuthType.OAUTH:
        client_id = os.getenv("SERVICENOW_CLIENT_ID")
        client_secret = os.getenv("SERVICENOW_CLIENT_SECRET")
        username = os.getenv("SERVICENOW_USERNAME")
        password = os.getenv("SERVICENOW_PASSWORD")
        if not client_id or not client_secret or not username or not password:
            raise ValueError(
                "SERVICENOW_CLIENT_ID, SERVICENOW_CLIENT_SECRET, "
                "SERVICENOW_USERNAME, and SERVICENOW_PASSWORD are required for oauth"
            )
        token_url = os.getenv("SERVICENOW_TOKEN_URL")
        if not token_url:
            token_url = f"{instance_url}/oauth_token.do"
            logger.warning("SERVICENOW_TOKEN_URL not set, defaulting to %s", token_url)
        auth_config = AuthConfig(
            type=auth_type,
            oauth=OAuthConfig(
                client_id=client_id,
                client_secret=client_secret,
                username=username,
                password=password,
                token_url=token_url,
            ),
        )

    return ServerConfig(instance_url=instance_url, auth=auth_config)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run ServiceNow MCP SSE-based server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
    args = parser.parse_args()

    try:
        config = create_config_from_env()
        logger.info(
            "Starting SSE server for %s with %s auth",
            config.instance_url,
            config.auth.type.value,
        )
        server = ServiceNowSSEMCP(config)
        server.start(host=args.host, port=args.port, debug=args.debug)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
