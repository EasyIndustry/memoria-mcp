"""Configuración por variables de entorno (o un archivo .env)."""
import getpass
import os
import socket as _socket
from dataclasses import dataclass
from pathlib import Path


def cargar_env(ruta=None):
    """Carga KEY=valor de un .env sin pisar variables ya definidas."""
    candidatos = [Path(ruta)] if ruta else [Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"]
    for p in candidatos:
        if p.is_file():
            for linea in p.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    k, v = linea.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


@dataclass
class Config:
    host: str = "127.0.0.1"
    puerto: int = 3307
    usuario: str = "memoria"
    clave: str = ""
    base: str = "memoria"
    socket: str = ""               # socket unix (opcional, en lugar de host/puerto)
    actor: str = ""
    max_bloque: int = 20000        # caracteres por bloque de mensaje guardado (--con-mensajes)
    hook_motivos: tuple = ("clear",)

    @classmethod
    def desde_entorno(cls):
        cargar_env(os.environ.get("MEMORIA_ENV"))
        e = os.environ.get
        return cls(
            host=e("MEMORIA_DB_HOST", cls.host),
            puerto=int(e("MEMORIA_DB_PORT", cls.puerto)),
            usuario=e("MEMORIA_DB_USER", cls.usuario),
            clave=e("MEMORIA_DB_PASSWORD", ""),
            base=e("MEMORIA_DB_NAME", cls.base),
            socket=e("MEMORIA_DB_SOCKET", ""),
            actor=e("MEMORIA_ACTOR") or f"{getpass.getuser()}@{_socket.gethostname()}",
            max_bloque=int(e("MEMORIA_MAX_BLOQUE", cls.max_bloque)),
            hook_motivos=tuple(m.strip() for m in e("MEMORIA_HOOK_MOTIVOS", "clear").split(",") if m.strip()),
        )
