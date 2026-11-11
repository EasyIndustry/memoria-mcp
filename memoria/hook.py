"""Hooks de Claude Code.

SessionEnd (stdin: {"session_id", "transcript_path", "cwd", "reason", ...}):
  1. sincroniza a la base los archivos materializados que se editaron en la carpeta de trabajo;
  2. si el motivo está en MEMORIA_HOOK_MOTIVOS (default "clear"), guarda los resúmenes de /compact
     nuevos. Un /clear sin /compact previo no guarda nada.
Nunca corta a Claude Code: cualquier error se registra en el log y el hook sale con 0.
"""
import datetime
import json
import os
import sys
from pathlib import Path

LOG = Path(os.environ.get("MEMORIA_LOG", Path.home() / ".local" / "state" / "memoria" / "hook.log"))


def registrar(evento):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"), **evento},
                               ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def session_end(db, evento, entorno=os.environ):
    from . import materializar, sesiones
    resultado = {"hook": "SessionEnd", "motivo": evento.get("reason"), "session_id": evento.get("session_id")}
    destinos = {str(Path(d).resolve()) for d in (evento.get("cwd"), entorno.get("CLAUDE_PROJECT_DIR")) if d}
    resultado["sincronizacion"] = {d: materializar.sincronizar(db, d) for d in sorted(destinos)
                                   if db.valor("SELECT 1 FROM materializaciones WHERE destino=%s LIMIT 1", (d,))}
    transcript = evento.get("transcript_path")
    if evento.get("reason") in db.config.hook_motivos and transcript and Path(transcript).is_file():
        resultado["sesion"] = sesiones.guardar(db, transcript, motivo=evento.get("reason"),
                                               agente=entorno.get("MEMORIA_AGENTE"),
                                               con_mensajes=entorno.get("MEMORIA_CON_MENSAJES") == "1")
    return resultado


def main(nombre, crear_db):
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        registrar({"hook": nombre, "error": f"stdin inválido: {e}"})
        return 0
    try:
        with crear_db() as db:
            resultado = {"session-end": session_end}[nombre](db, evento)
        registrar(resultado)
    except Exception as e:
        registrar({"hook": nombre, "error": f"{type(e).__name__}: {e}", "evento": evento})
    return 0


def instalar(settings, comando):
    """Agrega el hook SessionEnd a un settings.json de Claude Code sin pisar lo que haya."""
    settings = Path(settings).expanduser()
    datos = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    entradas = datos.setdefault("hooks", {}).setdefault("SessionEnd", [])
    ya = any(h.get("command") == comando for e in entradas for h in e.get("hooks", []))
    if not ya:
        entradas.append({"hooks": [{"type": "command", "command": comando, "timeout": 60}]})
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"settings": str(settings), "comando": comando, "instalado": not ya, "ya_estaba": ya}
