"""Servidor MCP para memoria: expone el catálogo de MariaDB (proyectos, agentes, skills,
contexto, sesiones, memorias, delegaciones) como tools para Claude Code. Usa el mismo
usuario admin que el CLI (Config.desde_entorno) — mismo alcance que `memoria ...` a mano.
"""
import datetime
import decimal
import json
import os
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import catalogo, esquema, formato, materializar, memorias, proyectos, sesiones, voces
from .db import DB

mcp = MCPServer("memoria")


def _limpio(o):
    if isinstance(o, dict):
        return {k: _limpio(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_limpio(v) for v in o]
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, bytes):
        return o.decode(errors="replace")
    return o


def _localizar_transcript(session_id):
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    encontrados = sorted(base.glob(f"*/{session_id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not encontrados:
        raise FileNotFoundError(f"no hay transcript para la sesión {session_id} en {base}")
    return encontrados[0]


# --- proyectos ---

@mcp.tool()
def proyecto_alta(nombre: str, ruta: Optional[str] = None, descripcion: Optional[str] = None,
                   repo_url: Optional[str] = None) -> dict:
    """Da de alta un proyecto (o lo actualiza si ya existe)."""
    with DB() as db:
        return {"id": proyectos.alta(db, nombre, ruta, descripcion, repo_url)}


@mcp.tool()
def proyecto_listar() -> list:
    """Lista todos los proyectos registrados."""
    with DB() as db:
        return _limpio(proyectos.listar(db))


@mcp.tool()
def proyecto_escanear(nombre: str) -> dict:
    """Escanea el árbol de archivos del proyecto en disco y actualiza la base (nuevos/modificados/desaparecidos)."""
    with DB() as db:
        return _limpio(proyectos.escanear(db, nombre))


# --- agentes ---

def _lista(texto):
    return [x.strip() for x in texto.split(",") if x.strip()] if texto is not None else None


@mcp.tool()
def agente_listar(incluir_inactivos: bool = False, proyecto: Optional[str] = None,
                  rol: Optional[str] = None) -> list:
    """Lista los agentes guardados: roles (plantillas globales) y miembros (un rol en un proyecto).
    Filtra por proyecto y/o rol."""
    with DB() as db:
        return _limpio(catalogo.listar_agentes(db, incluir_inactivos, proyecto, rol))


@mcp.tool()
def agente_ver(nombre: str, resuelto: bool = False) -> dict:
    """Devuelve un agente completo (por nombre o uid): datos, secciones, skills y mcps (base y a pedido).
    resuelto=true: con lo heredado de su rol ya sumado."""
    with DB() as db:
        return _limpio(catalogo.resolver_agente(db, nombre) if resuelto else catalogo.obtener_agente(db, nombre))


@mcp.tool()
def agente_guardar(nombre: str, descripcion: Optional[str] = None, modelo: Optional[str] = None,
                    herramientas: Optional[str] = None, skills: Optional[str] = None,
                    es_general: bool = False, nota: Optional[str] = None, rol: Optional[str] = None,
                    proyecto: Optional[str] = None, es_rol: Optional[bool] = None,
                    es_lider: Optional[bool] = None, mcps: Optional[str] = None,
                    mcps_a_pedido: Optional[str] = None) -> dict:
    """Crea o actualiza (nueva versión) un agente. Listas separadas por coma.
    Rol = plantilla global (es_rol=true, ej. devops). Miembro = rol en un proyecto (rol=devops,
    proyecto=trabajo-str, nombre devops-str): hereda secciones, skills y MCPs del rol.
    es_lider: puede crear miembros y repartir trabajo. mcps: se conectan al arrancar;
    mcps_a_pedido: los pide cuando los necesita (nombres de mcp_listar). Devuelve el uid estable."""
    datos = {}
    for campo, valor in (("descripcion", descripcion), ("modelo", modelo), ("rol", rol), ("proyecto", proyecto),
                         ("es_rol", es_rol), ("es_lider", es_lider)):
        if valor is not None:
            datos[campo] = valor or None if campo in ("rol", "proyecto") else valor
    if herramientas is not None:
        datos["herramientas"] = _lista(herramientas)
    if es_general:
        datos["es_general"] = True
    with DB() as db:
        return _limpio(catalogo.guardar_agente(db, nombre, datos, None, _lista(skills), _lista(mcps), nota=nota,
                                               mcps_a_pedido=_lista(mcps_a_pedido)))


@mcp.tool()
def agente_despertar(nombre: str) -> dict:
    """Para arrancar (o volver después de /clear) como este agente: identidad con lo heredado del rol,
    prompt armado, MCPs base y a pedido, contexto del proyecto, último resumen de sesión, memorias y
    el id para Denis (agent_register con identity)."""
    with DB() as db:
        return _limpio(catalogo.despertar(db, nombre))


@mcp.tool()
def agente_seccion(nombre: str, titulo: str, contenido: Optional[str] = None, tipo: Optional[str] = None,
                    orden: Optional[int] = None, desactivar: bool = False, nota: Optional[str] = None) -> dict:
    """Agrega o edita una sección de instrucciones de un agente (rol, forma_de_trabajo, restricciones, ...)."""
    with DB() as db:
        return _limpio(catalogo.editar_seccion(db, nombre, titulo, contenido, tipo, orden,
                                               False if desactivar else None, nota=nota))


# --- servidores MCP ---

@mcp.tool()
def mcp_listar() -> list:
    """Servidores MCP registrados (para asignarlos a agentes como base o a pedido). No muestra secretos."""
    with DB() as db:
        return _limpio(catalogo.listar_mcps(db))


@mcp.tool()
def mcp_guardar(nombre: str, config: Optional[dict] = None, descripcion: Optional[str] = None,
                activo: Optional[bool] = None) -> dict:
    """Registra o actualiza un servidor MCP. config = su entrada de .mcp.json ({"command","args","env"}
    o {"type":"http","url"}). La descripción es lo que ve un agente para decidir si lo pide."""
    with DB() as db:
        return _limpio(catalogo.guardar_mcp(db, nombre, config, descripcion, activo))


@mcp.tool()
def mcp_importar(ruta: Optional[str] = None, sobrescribir: bool = False) -> dict:
    """Importa los mcpServers de usuario de ~/.claude.json (u otro archivo con mcpServers).
    Sin sobrescribir, los que ya existen quedan como están."""
    archivo = Path(ruta) if ruta else Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home())) / ".claude.json"
    servidores = json.loads(archivo.read_text(encoding="utf-8")).get("mcpServers") or {}
    nuevos, actualizados, salteados = [], [], []
    with DB() as db:
        existentes = {m["nombre"] for m in catalogo.listar_mcps(db)}
        for nombre, config in sorted(servidores.items()):
            if nombre in existentes and not sobrescribir:
                salteados.append(nombre)
                continue
            catalogo.guardar_mcp(db, nombre, config)
            (actualizados if nombre in existentes else nuevos).append(nombre)
    return {"nuevos": nuevos, "actualizados": actualizados, "salteados": salteados}


# --- skills ---

@mcp.tool()
def skill_listar() -> list:
    """Lista las skills guardadas en la base."""
    with DB() as db:
        return _limpio(catalogo.listar_skills(db))


@mcp.tool()
def skill_ver(nombre: str) -> dict:
    """Devuelve una skill completa (SKILL.md y archivos de apoyo)."""
    with DB() as db:
        return _limpio(catalogo.obtener_skill(db, nombre))


@mcp.tool()
def skill_guardar(carpeta: str, nota: Optional[str] = None) -> dict:
    """Importa una skill desde una carpeta local que contenga SKILL.md (+ archivos de apoyo)."""
    ruta = Path(carpeta)
    s = formato.parse_skill((ruta / "SKILL.md").read_text(encoding="utf-8"))
    archivos = {str(f.relative_to(ruta)): f.read_text(encoding="utf-8") for f in sorted(ruta.rglob("*"))
                if f.is_file() and f.name != "SKILL.md"}
    with DB() as db:
        return _limpio(catalogo.guardar_skill(db, s["nombre"] or ruta.name, s["descripcion"], s["instrucciones"],
                                              s["herramientas"], archivos=archivos, nota=nota))


# --- contexto ---

@mcp.tool()
def contexto_listar(proyecto: Optional[str] = None, agente: Optional[str] = None) -> list:
    """Lista secciones de contexto (lo que va a CLAUDE.md), global o filtrado por proyecto/agente."""
    with DB() as db:
        return _limpio(catalogo.secciones_contexto(db, proyecto, agente))


@mcp.tool()
def contexto_agregar(titulo: str, contenido: str, tipo: str = "otro", orden: Optional[int] = None,
                      proyecto: Optional[str] = None, agente: Optional[str] = None) -> dict:
    """Agrega una sección de contexto nueva. Alcance global si no se pasa proyecto ni agente."""
    alcance = "agente" if agente else "proyecto" if proyecto else "global"
    with DB() as db:
        return _limpio(catalogo.guardar_contexto(db, titulo, contenido, alcance, proyecto, agente, tipo, orden, True))


@mcp.tool()
def contexto_editar(id: int, titulo: str, contenido: Optional[str] = None, tipo: str = "otro",
                     orden: Optional[int] = None, proyecto: Optional[str] = None, agente: Optional[str] = None,
                     desactivar: bool = False) -> dict:
    """Edita una sección de contexto existente por id (crea una versión nueva)."""
    alcance = "agente" if agente else "proyecto" if proyecto else "global"
    with DB() as db:
        return _limpio(catalogo.guardar_contexto(db, titulo, contenido, alcance, proyecto, agente, tipo, orden,
                                                 not desactivar, id=id))


# --- importar / materializar / sincronizar ---

@mcp.tool()
def importar(origen: str, proyecto: Optional[str] = None) -> dict:
    """Carga .claude/agents, skills y CLAUDE.md ya existentes de una carpeta a la base."""
    with DB() as db:
        return _limpio(materializar.importar(db, origen, proyecto))


@mcp.tool()
def materializar_agente(agente: Optional[str] = None, proyecto: Optional[str] = None,
                         destino: Optional[str] = None, subagentes: Optional[bool] = None,
                         forzar: bool = False) -> dict:
    """Genera .claude/agents/*.md, .claude/skills/*/SKILL.md y CLAUDE.md desde la base hacia una carpeta."""
    with DB() as db:
        return _limpio(materializar.materializar(db, destino, agente, proyecto, subagentes, forzar))


@mcp.tool()
def sincronizar(destino: str) -> dict:
    """Detecta archivos generados que Claude editó en `destino` y los guarda como versión nueva."""
    with DB() as db:
        return _limpio(materializar.sincronizar(db, destino))


# --- historial ---

@mcp.tool()
def historial(entidad: str, ref: str) -> list:
    """Historial de versiones de un agente, skill o sección de contexto. entidad: agente|skill|contexto."""
    with DB() as db:
        return _limpio(catalogo.historial(db, entidad, ref))


@mcp.tool()
def version_ver(entidad: str, ref: str, numero: int) -> dict:
    """Devuelve una versión específica del historial."""
    with DB() as db:
        return _limpio(catalogo.ver_version(db, entidad, ref, numero))


@mcp.tool()
def restaurar(entidad: str, ref: str, numero: int) -> dict:
    """Restaura una versión anterior (crea una versión nueva con ese contenido; no borra historia)."""
    with DB() as db:
        return _limpio(catalogo.restaurar(db, entidad, ref, numero))


# --- sesiones ---

@mcp.tool()
def sesion_guardar(transcript: Optional[str] = None, session_id: Optional[str] = None,
                    proyecto: Optional[str] = None, agente: Optional[str] = None,
                    con_mensajes: bool = False, sin_compact: bool = False) -> dict:
    """Guarda resúmenes de /compact (y opcionalmente mensajes) de una sesión de Claude Code.
    Pasá transcript (ruta al .jsonl) o session_id (lo busca en ~/.claude/projects)."""
    if not transcript and not session_id:
        raise ValueError("indicá transcript o session_id")
    ruta = transcript or str(_localizar_transcript(session_id))
    with DB() as db:
        return _limpio(sesiones.guardar(db, ruta, "manual", proyecto, agente, con_mensajes,
                                        exigir_compact=not sin_compact))


@mcp.tool()
def sesion_listar(proyecto: Optional[str] = None, limite: int = 20) -> list:
    """Lista sesiones guardadas, más recientes primero."""
    with DB() as db:
        return _limpio(sesiones.listar(db, proyecto, limite))


@mcp.tool()
def sesion_ultima(proyecto: Optional[str] = None, agente: Optional[str] = None) -> Optional[dict]:
    """El resumen más reciente de una sesión, para retomar un objetivo."""
    with DB() as db:
        return _limpio(sesiones.ultimo_resumen(db, proyecto, agente))


@mcp.tool()
def sesion_buscar(texto: str) -> list:
    """Busca en los resúmenes de sesiones guardadas (full-text search)."""
    with DB() as db:
        return _limpio(sesiones.buscar_resumenes(db, texto))


# --- memorias ---

@mcp.tool()
def memoria_agregar(tipo: str, titulo: str, contenido: str, alcance: Optional[str] = None,
                     proyecto: Optional[str] = None, agente: Optional[str] = None,
                     sesion: Optional[str] = None, importancia: int = 3,
                     etiquetas: Optional[str] = None, reemplaza: Optional[int] = None) -> dict:
    """Agrega un hecho, preferencia, decision, procedimiento, pendiente o referencia a la memoria."""
    lista_etiquetas = tuple(t.strip() for t in etiquetas.split(",") if t.strip()) if etiquetas else ()
    with DB() as db:
        return {"id": memorias.agregar(db, tipo, titulo, contenido, alcance, proyecto, agente, sesion,
                                       importancia, lista_etiquetas, reemplaza=reemplaza)}


@mcp.tool()
def memoria_listar(proyecto: Optional[str] = None, agente: Optional[str] = None, tipo: Optional[str] = None,
                    etiqueta: Optional[str] = None) -> list:
    """Lista memorias vigentes, filtrando por proyecto/agente/tipo/etiqueta."""
    with DB() as db:
        return _limpio(memorias.listar(db, proyecto, agente, tipo, etiqueta))


@mcp.tool()
def memoria_buscar(texto: str) -> list:
    """Busca memorias por texto (full-text search)."""
    with DB() as db:
        return _limpio(memorias.buscar(db, texto))


@mcp.tool()
def memoria_olvidar(id: int, motivo: Optional[str] = None) -> dict:
    """Marca una memoria como no vigente (no la borra, queda en el historial)."""
    with DB() as db:
        return {"olvidada": memorias.olvidar(db, id, motivo)}


# --- delegaciones ---

@mcp.tool()
def delegacion_crear(destino: str, objetivo: str, origen: Optional[str] = None, sesion: Optional[str] = None,
                      motivo: Optional[str] = None, confianza: Optional[float] = None) -> dict:
    """Registra una derivación de una tarea de un agente a otro."""
    with DB() as db:
        return {"id": memorias.delegar(db, destino, objetivo, origen, sesion, motivo, confianza)}


@mcp.tool()
def delegacion_cerrar(id: int, estado: str = "completada", resultado: Optional[str] = None) -> dict:
    """Cierra una delegación (estado: en_curso|completada|fallida|cancelada)."""
    with DB() as db:
        memorias.cerrar_delegacion(db, id, estado, resultado)
        return {"id": id, "estado": estado}


# --- voz de cada agente (vozkit) ---

@mcp.tool()
def voz_agente_ver(nombre: Optional[str] = None) -> dict | list | None:
    """Perfil de voz de un agente por nombre (el que sorteó lanzar_subagente.sh); sin nombre, todos."""
    with DB() as db:
        return _limpio(voces.ver(db, nombre) if nombre else voces.listar(db))


@mcp.tool()
def voz_agente_guardar(nombre: str, perfil: dict) -> dict:
    """Fija el perfil de voz de un agente: {"base": "grave", "tono": -6, "length_scale": 0.92, ...}."""
    with DB() as db:
        return _limpio(voces.guardar(db, nombre, perfil))


# --- mantenimiento ---

@mcp.tool()
def migrar() -> dict:
    """Aplica migraciones de esquema pendientes."""
    with DB() as db:
        return {"aplicadas": esquema.migrar(db)}


@mcp.tool()
def auditoria(tabla: Optional[str] = None, limite: int = 50) -> list:
    """Consulta el log de auditoría (quién hizo qué y cuándo)."""
    with DB() as db:
        return _limpio(db.todos(
            "SELECT * FROM auditoria WHERE (%s IS NULL OR tabla=%s) ORDER BY id DESC LIMIT %s",
            (tabla, tabla, limite)))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
