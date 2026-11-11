"""Servidor MCP de memoria por HTTP (streamable) con token Bearer.

Expone las mismas tools que `memoria-mcp` (stdio) pero como servicio HTTP, para
clientes remotos (p. ej. sesiones de Claude en la nube). Variables:

  MEMORIA_MCP_TOKEN   obligatoria; se exige `Authorization: Bearer <token>`
  MEMORIA_MCP_HOST    default 0.0.0.0
  MEMORIA_MCP_PUERTO  default 8080
  MEMORIA_MCP_HOSTS   hosts (host:puerto, coma) que los clientes pueden poner en la cabecera Host,
                      además de localhost: p. ej. la IP de Tailscale o de la LAN de esta PC. Sin
                      esto, un cliente remoto recibe 421 Misdirected Request (anti DNS-rebinding).

La conexión a MariaDB se configura igual que siempre (MEMORIA_DB_*)."""
import hmac
import os

import uvicorn

from .mcp_server import mcp


def _asgi_con_token(app, token):
    esperado = f"Bearer {token}"

    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            ruta = scope.get("path", "")
            if ruta == "/salud":
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"ok"})
                return
            auth = ""
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    auth = v.decode("latin-1")
                    break
            if not hmac.compare_digest(auth, esperado):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"no autorizado"})
                return
        await app(scope, receive, send)

    return wrapper


def main():
    token = os.environ.get("MEMORIA_MCP_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("falta MEMORIA_MCP_TOKEN (mínimo 16 caracteres)")
    host = os.environ.get("MEMORIA_MCP_HOST", "0.0.0.0")
    puerto = int(os.environ.get("MEMORIA_MCP_PUERTO", "8080"))
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = [h.strip() for h in os.environ.get("MEMORIA_MCP_HOSTS", "").split(",") if h.strip()]
    seguridad = None
    if hosts:
        seguridad = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", *hosts])
    app = _asgi_con_token(mcp.streamable_http_app(transport_security=seguridad), token)
    uvicorn.run(app, host=host, port=puerto)


if __name__ == "__main__":
    main()
