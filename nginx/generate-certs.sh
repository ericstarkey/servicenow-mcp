#!/usr/bin/env bash
# Generate a self-signed SSL certificate for local / VPS deployment.
# Run once before the first `docker-compose up`.
#
# Usage:
#   chmod +x nginx/generate-certs.sh
#   ./nginx/generate-certs.sh
#
# Output:
#   nginx/certs/server.key  (private key — keep secret, gitignored)
#   nginx/certs/server.crt  (self-signed certificate, valid 365 days)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/certs"

mkdir -p "${CERT_DIR}"

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "${CERT_DIR}/server.key" \
  -out    "${CERT_DIR}/server.crt" \
  -subj   "/C=US/ST=State/L=City/O=ServiceNow-MCP/CN=servicenow-mcp"

chmod 600 "${CERT_DIR}/server.key"

echo ""
echo "Certificate generated:"
echo "  ${CERT_DIR}/server.crt"
echo "  ${CERT_DIR}/server.key"
echo ""
echo "Certificate details:"
openssl x509 -in "${CERT_DIR}/server.crt" -noout -subject -dates
echo ""
echo "NOTE: This is a self-signed certificate. Clients connecting to the server"
echo "      must accept the certificate (e.g. curl -k, or add it to trusted store)."
