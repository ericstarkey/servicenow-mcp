# ServiceNow MCP Server — Claude Project Guide

This file provides context and instructions for Claude (and other AI assistants) working
on this codebase.

---

## Project Overview

This is a Python **Model Context Protocol (MCP) server** that wraps the ServiceNow REST
API and exposes ServiceNow capabilities as MCP tools. It can run in two transport modes:

- **Stdio mode** — used with Claude Desktop and local MCP clients
- **SSE mode** — runs as an HTTPS server, used with remote clients like the OpenAI API Platform

---

## Architecture

```
MCP Client (OpenAI Platform / Claude Desktop / etc.)
       |
       |  HTTPS + SSE  (server_sse.py)
       |  OR
       |  stdio        (cli.py)
       v
ServiceNowSSEMCP / ServiceNowMCP   (server.py)
       |
       |  ServerConfig + AuthConfig
       v
AuthManager   (auth/auth_manager.py)
       |
       |  HTTP with auth headers
       v
ServiceNow REST API   (/api/now/...)
```

**Key modules:**

| File | Purpose |
|---|---|
| `src/servicenow_mcp/server.py` | Transport-agnostic MCP server core. Registers tools, holds config + auth manager. |
| `src/servicenow_mcp/server_sse.py` | SSE HTTP server (Starlette + Uvicorn). Includes inbound `ApiKeyMiddleware`. |
| `src/servicenow_mcp/cli.py` | Stdio transport wrapper with full argparse CLI. |
| `src/servicenow_mcp/auth/auth_manager.py` | Builds HTTP headers for each auth type. |
| `src/servicenow_mcp/utils/config.py` | Pydantic models: `ServerConfig`, `AuthConfig`, `BasicAuthConfig`, `OAuthConfig`, `ApiKeyConfig`. |
| `src/servicenow_mcp/tools/` | Individual tool modules (one per ServiceNow area). |
| `src/servicenow_mcp/utils/tool_utils.py` | Tool registration and metadata helpers. |
| `config/tool_packages.yaml` | Named tool subsets (e.g. `service_desk`, `full`). |

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `SERVICENOW_INSTANCE_URL` | Full URL of the ServiceNow instance, e.g. `https://dev12345.service-now.com` |
| `SERVICENOW_AUTH_TYPE` | Auth type: `basic` \| `oauth` \| `api_key` (default: `basic`) |

### Basic Auth (`SERVICENOW_AUTH_TYPE=basic`)

| Variable | Description |
|---|---|
| `SERVICENOW_USERNAME` | ServiceNow username |
| `SERVICENOW_PASSWORD` | ServiceNow password |

### API Key Auth (`SERVICENOW_AUTH_TYPE=api_key`)

| Variable | Description |
|---|---|
| `SERVICENOW_API_KEY` | API key sent to ServiceNow |
| `SERVICENOW_API_KEY_HEADER` | Header name (default: `X-ServiceNow-API-Key`) |

### OAuth (`SERVICENOW_AUTH_TYPE=oauth`)

| Variable | Description |
|---|---|
| `SERVICENOW_CLIENT_ID` | OAuth client ID |
| `SERVICENOW_CLIENT_SECRET` | OAuth client secret |
| `SERVICENOW_USERNAME` | Username (for password grant) |
| `SERVICENOW_PASSWORD` | Password (for password grant) |
| `SERVICENOW_TOKEN_URL` | Token endpoint (default: `<instance_url>/oauth_token.do`) |

### Inbound Protection (SSE mode)

| Variable | Description |
|---|---|
| `MCP_SERVER_API_KEY` | Secret key that MCP clients must send. If unset, `/sse` is unprotected. |
| `MCP_SERVER_API_KEY_HEADER` | Custom header name for the inbound key (default: auto-detect `Authorization Bearer` then `X-API-Key`) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `MCP_TOOL_PACKAGE` | `full` | Tool package to load (see `config/tool_packages.yaml`) |
| `SERVICENOW_DEBUG` | `false` | Enable debug logging |
| `SERVICENOW_TIMEOUT` | `30` | HTTP timeout in seconds |
| `SCRIPT_EXECUTION_API_RESOURCE_PATH` | — | Custom API path for script execution |
| `TOOL_PACKAGE_CONFIG_PATH` | `config/tool_packages.yaml` | Path to tool package config |

---

## Running in Development

### Install dependencies

```bash
pip install -e ".[dev]"
# or with uv:
uv sync
```

### Stdio mode (local MCP client)

```bash
servicenow-mcp
# or:
python -m servicenow_mcp.cli
```

### SSE mode (HTTP server on port 8080)

```bash
servicenow-mcp-sse --host 0.0.0.0 --port 8080
# or:
python -m servicenow_mcp.server_sse
```

With a `.env` file present, `python-dotenv` loads it automatically on startup.

### Quick test with API key auth to ServiceNow

```bash
SERVICENOW_INSTANCE_URL=https://dev12345.service-now.com \
SERVICENOW_AUTH_TYPE=api_key \
SERVICENOW_API_KEY=your-key \
MCP_SERVER_API_KEY=my-secret \
servicenow-mcp-sse
```

---

## Running Tests

```bash
# All tests
pytest

# SSE auth tests only (the new tests for API key fix)
pytest tests/test_server_sse_auth.py -v

# With coverage
pytest --cov=servicenow_mcp tests/

# Single test class
pytest tests/test_server_sse_auth.py::TestApiKeyMiddleware -v
```

Tests use `unittest.TestCase` style discovered by pytest. Auth is isolated using
`@patch.dict(os.environ, {...}, clear=True)` to prevent local `.env` from leaking.

---

## How to Add a New Tool

1. **Create the tool module** at `src/servicenow_mcp/tools/your_tool.py`:

   ```python
   from servicenow_mcp.utils.config import ServerConfig
   from servicenow_mcp.auth.auth_manager import AuthManager

   def your_tool_function(
       config: ServerConfig,
       auth_manager: AuthManager,
       params: YourParamsModel,
   ) -> dict:
       headers = auth_manager.get_headers()
       response = requests.get(
           f"{config.api_url}/table/your_table",
           headers=headers,
       )
       ...
   ```

2. **Register the tool** in `src/servicenow_mcp/utils/tool_utils.py` — add it to the
   tool registry list following the existing pattern.

3. **Add the tool name** to one or more packages in `config/tool_packages.yaml`:

   ```yaml
   full:
     tools:
       - your_tool_function
   ```

4. **Write tests** in `tests/test_your_tool.py` following the existing test patterns
   (mock `requests.get/post` via `@patch`).

---

## Authentication Flow

### Outbound (MCP server → ServiceNow)

`create_config_from_env()` in `server_sse.py` reads `SERVICENOW_AUTH_TYPE` and builds
`AuthConfig`. `AuthManager.get_headers()` converts this into HTTP headers at request time:

- `basic` → `Authorization: Basic <base64(user:pass)>`
- `api_key` → `<header_name>: <api_key>`
- `oauth` → fetches token, then `Authorization: Bearer <token>`

### Inbound (MCP client → this server)

`ApiKeyMiddleware` in `server_sse.py` intercepts all requests. It is only active when
`MCP_SERVER_API_KEY` is set. Key detection order (when no custom header is configured):

1. `Authorization: Bearer <key>`
2. `X-API-Key: <key>`

Returns `401 {"error": "Unauthorized"}` on mismatch.

---

## Docker Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full step-by-step guide.

**Quick summary:**

```bash
./nginx/generate-certs.sh          # generate self-signed SSL cert (once)
cp .env.example .env && nano .env  # configure environment
docker compose up -d --build       # start MCP + Nginx containers
```

The server is then reachable at `https://<VPS_IP>/sse`.

---

## Project Structure

```
servicenow-mcp/
├── src/servicenow_mcp/
│   ├── server.py               # Core MCP server (transport-agnostic)
│   ├── server_sse.py           # SSE HTTP server + inbound middleware
│   ├── cli.py                  # Stdio CLI entry point
│   ├── auth/
│   │   └── auth_manager.py     # Builds auth headers per auth type
│   ├── tools/                  # One module per ServiceNow area
│   └── utils/
│       ├── config.py           # Pydantic config models
│       └── tool_utils.py       # Tool registration helpers
├── tests/                      # pytest test suite
├── config/
│   └── tool_packages.yaml      # Named tool subsets
├── nginx/
│   ├── nginx.conf              # Nginx reverse proxy config (SSE-aware)
│   ├── generate-certs.sh       # Self-signed cert generator
│   └── certs/                  # Generated certs (gitignored)
├── docker-compose.yml          # MCP + Nginx services
├── Dockerfile                  # MCP container image
├── .env.example                # Environment variable template
├── DEPLOYMENT.md               # VPS deployment guide
└── pyproject.toml              # Project metadata and dependencies
```
