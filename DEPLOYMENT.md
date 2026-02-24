# Deploying ServiceNow MCP Server to a VPS with Docker Compose

This guide walks through deploying the ServiceNow MCP SSE server on a VPS (e.g. Hostinger)
using Docker Compose with Nginx as an SSL-terminating reverse proxy.

The MCP server will be accessible at `https://<YOUR_VPS_IP>/sse` and protected by an
inbound API key that you provide to the OpenAI API Platform (or any other MCP client).

---

## Prerequisites

On your VPS:
- Docker Engine 20.10 or newer
- Docker Compose v2 (`docker compose` command, or `docker-compose` v1.29+)
- Port **443** open in your firewall / security group
- Git installed

On your local machine (or the VPS):
- OpenSSL (to generate the self-signed certificate)

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/<your-username>/servicenow-mcp.git
cd servicenow-mcp
```

---

## Step 2 — Generate a Self-Signed SSL Certificate

Because no domain name is used, we create a self-signed certificate.
Run this **once** before the first deployment.

```bash
chmod +x nginx/generate-certs.sh
./nginx/generate-certs.sh
```

This creates:
- `nginx/certs/server.key` — private key (kept secret, gitignored)
- `nginx/certs/server.crt` — certificate (valid 365 days)

> **Important:** These files are gitignored. You must re-run this script on each new
> server or after a fresh clone.

---

## Step 3 — Configure Environment Variables

```bash
cp .env.example .env
nano .env      # or your preferred editor
```

At minimum, set the following values:

| Variable | Required | Description |
|---|---|---|
| `SERVICENOW_INSTANCE_URL` | Yes | Your ServiceNow instance, e.g. `https://dev12345.service-now.com` |
| `SERVICENOW_AUTH_TYPE` | Yes | `basic`, `oauth`, or `api_key` |
| `SERVICENOW_USERNAME` | If basic/oauth | ServiceNow username |
| `SERVICENOW_PASSWORD` | If basic/oauth | ServiceNow password |
| `SERVICENOW_API_KEY` | If api_key | ServiceNow API key |
| `MCP_SERVER_API_KEY` | Recommended | Secret key that MCP clients must present |

**Example `.env` for API key authentication to ServiceNow:**

```dotenv
SERVICENOW_INSTANCE_URL=https://dev12345.service-now.com
SERVICENOW_AUTH_TYPE=api_key
SERVICENOW_API_KEY=your-servicenow-api-key

MCP_SERVER_API_KEY=a-very-long-random-secret-you-generate
MCP_TOOL_PACKAGE=full
```

**Generating a strong `MCP_SERVER_API_KEY`:**

```bash
openssl rand -hex 32
```

---

## Step 4 — Build and Deploy

```bash
# Build the MCP container image and start all services
docker compose up -d --build

# Check that both containers are running
docker compose ps
```

Expected output:

```
NAME                    STATUS          PORTS
servicenow-mcp-mcp-1    running         8080/tcp
servicenow-mcp-nginx-1  running         0.0.0.0:443->443/tcp
```

---

## Step 5 — Verify the Deployment

Send a test request to the `/sse` endpoint. The `-k` flag ignores the self-signed
certificate warning.

```bash
curl -k -v https://<YOUR_VPS_IP>/sse \
  -H "Authorization: Bearer <YOUR_MCP_SERVER_API_KEY>"
```

A successful response will:
- Return **HTTP 200**
- Have `Content-Type: text/event-stream`
- Keep the connection open (SSE stream)

Press `Ctrl+C` to close.

**Without the API key (expected 401):**

```bash
curl -k -o - https://<YOUR_VPS_IP>/sse
# → {"error":"Unauthorized","message":"Invalid or missing API key"}
```

---

## Step 6 — Add to the OpenAI API Platform

In the OpenAI API Platform (platform.openai.com), navigate to your project and add a
remote MCP server:

| Field | Value |
|---|---|
| **Server URL** | `https://<YOUR_VPS_IP>/sse` |
| **Authentication** | Header-based |
| **Header name** | `Authorization` |
| **Header value** | `Bearer <YOUR_MCP_SERVER_API_KEY>` |

> **Self-signed certificate note:** Some clients reject self-signed certificates by
> default. If the OpenAI platform does not support accepting self-signed certs, you may
> need to obtain a certificate from a public CA (e.g. Let's Encrypt) using a domain name.

---

## Maintenance

### View logs

```bash
docker compose logs -f mcp        # MCP server logs (auth type, tool calls)
docker compose logs -f nginx      # Nginx access/error logs
```

### Update the MCP server

```bash
git pull
docker compose up -d --build
```

### Renew the self-signed certificate (after 365 days)

```bash
./nginx/generate-certs.sh
docker compose restart nginx
```

### Stop the services

```bash
docker compose down
```

---

## Troubleshooting

### 401 Unauthorized
- Verify that the `Authorization: Bearer <key>` header value exactly matches `MCP_SERVER_API_KEY` in your `.env`.
- Check logs: `docker compose logs mcp`

### SSE connection drops immediately
- Check `proxy_read_timeout` in `nginx/nginx.conf` (set to `3600s`).
- Ensure `proxy_buffering off` is present in the `/sse` location block.

### Certificate errors in MCP client
- The client must either accept self-signed certificates or have the certificate added to its trust store.
- Copy `nginx/certs/server.crt` to the client and add it as a trusted CA, or use `--insecure` / equivalent for testing.

### Container fails to start
- Run `docker compose logs mcp` to see the error.
- Common causes: missing required env vars (`SERVICENOW_INSTANCE_URL`, auth vars).
- Test your `.env` locally: `servicenow-mcp-sse` (after `pip install -e .`).

### Port 443 already in use
- Check what is listening: `ss -tlnp | grep 443`
- Stop the conflicting service or change the Nginx port in `docker-compose.yml`.
