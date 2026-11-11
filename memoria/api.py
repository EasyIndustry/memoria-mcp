"""API HTTP de solo lectura (GET) sobre el catálogo de memoria, con Swagger en /docs.
Reusa las mismas funciones que el MCP; no expone ninguna escritura. Uso:  memoria-api [--puerto 8090]
"""
import argparse
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from . import catalogo, memorias, proyectos, sesiones, voces
from .db import DB
from .mcp_server import _limpio

app = FastAPI(title="memoria", description="Lectura del catálogo de memoria (MariaDB). Solo GET.",
              version="0.1.0")


def _o_404(valor, que):
    if valor is None:
        raise HTTPException(404, f"no existe: {que}")
    return _limpio(valor)


def _consultar(fn, *args):
    try:
        with DB() as db:
            return _limpio(fn(db, *args))
    except LookupError as e:
        raise HTTPException(404, str(e))


# --- proyectos ---

@app.get("/proyectos", tags=["proyectos"])
def proyecto_listar():
    return _consultar(proyectos.listar)


# --- agentes ---

@app.get("/agentes", tags=["agentes"])
def agente_listar(incluir_inactivos: bool = False):
    return _consultar(catalogo.listar_agentes, incluir_inactivos)


@app.get("/agentes/{nombre}", tags=["agentes"], summary="Agente completo: datos, secciones, skills y mcps")
def agente_ver(nombre: str):
    return _o_404(_consultar(catalogo.obtener_agente, nombre), nombre)


# --- skills ---

@app.get("/skills", tags=["skills"])
def skill_listar():
    return _consultar(catalogo.listar_skills)


@app.get("/skills/{nombre}", tags=["skills"], summary="Skill completa (SKILL.md y archivos de apoyo)")
def skill_ver(nombre: str):
    return _o_404(_consultar(catalogo.obtener_skill, nombre), nombre)


# --- contexto ---

@app.get("/contexto", tags=["contexto"], summary="Secciones de contexto (lo que va a CLAUDE.md)")
def contexto_listar(proyecto: Optional[str] = None, agente: Optional[str] = None):
    return _consultar(catalogo.secciones_contexto, proyecto, agente)


# --- historial ---

@app.get("/historial/{entidad}/{ref}", tags=["historial"], summary="Versiones de un agente, skill o contexto")
def historial(entidad: str, ref: str):
    return _consultar(catalogo.historial, entidad, ref)


@app.get("/historial/{entidad}/{ref}/{numero}", tags=["historial"])
def version_ver(entidad: str, ref: str, numero: int):
    return _o_404(_consultar(catalogo.ver_version, entidad, ref, numero), f"{entidad} {ref} v{numero}")


# --- sesiones ---

@app.get("/sesiones", tags=["sesiones"])
def sesion_listar(proyecto: Optional[str] = None, limite: int = 20):
    return _consultar(sesiones.listar, proyecto, limite)


@app.get("/sesiones/ultima", tags=["sesiones"], summary="Resumen más reciente")
def sesion_ultima(proyecto: Optional[str] = None, agente: Optional[str] = None):
    return _consultar(sesiones.ultimo_resumen, proyecto, agente)


@app.get("/sesiones/buscar", tags=["sesiones"], summary="Full-text en resúmenes (devuelve extractos)")
def sesion_buscar(texto: str):
    return _consultar(sesiones.buscar_resumenes, texto)


@app.get("/sesiones/{id}", tags=["sesiones"], summary="Sesión completa con resúmenes enteros")
def sesion_ver(id: int, con_mensajes: bool = Query(False, description="incluye mensajes y bloques guardados")):
    with DB() as db:
        s = db.uno("SELECT * FROM sesiones WHERE id=%s", (id,))
        if s is None:
            raise HTTPException(404, f"no existe la sesión {id}")
        s["resumenes"] = db.todos("SELECT * FROM resumenes WHERE sesion_id=%s ORDER BY compactado", (id,))
        if con_mensajes:
            s["mensajes"] = db.todos("SELECT * FROM mensajes WHERE sesion_id=%s ORDER BY orden", (id,))
            for m in s["mensajes"]:
                m["bloques"] = db.todos("SELECT * FROM bloques WHERE mensaje_id=%s ORDER BY orden", (m["id"],))
        return _limpio(s)


# --- memorias ---

@app.get("/memorias", tags=["memorias"], summary="Memorias vigentes que aplican")
def memoria_listar(proyecto: Optional[str] = None, agente: Optional[str] = None, tipo: Optional[str] = None,
                   etiqueta: Optional[str] = None, limite: int = 50):
    return _consultar(memorias.listar, proyecto, agente, tipo, etiqueta, limite)


@app.get("/memorias/buscar", tags=["memorias"])
def memoria_buscar(texto: str):
    return _consultar(memorias.buscar, texto)


@app.get("/memorias/{id}", tags=["memorias"], summary="Memoria completa (también las no vigentes)")
def memoria_ver(id: int):
    with DB() as db:
        m = db.uno("SELECT * FROM memorias WHERE id=%s", (id,))
        if m is None:
            raise HTTPException(404, f"no existe la memoria {id}")
        m["etiquetas"] = [f["nombre"] for f in db.todos(
            "SELECT e.nombre FROM memoria_etiqueta me JOIN etiquetas e ON e.id=me.etiqueta_id "
            "WHERE me.memoria_id=%s ORDER BY e.nombre", (id,))]
        return _limpio(m)


# --- delegaciones / voces / auditoría ---

@app.get("/delegaciones", tags=["delegaciones"])
def delegacion_listar(estado: Optional[str] = None, limite: int = 50):
    with DB() as db:
        return _limpio(db.todos("SELECT * FROM v_delegaciones WHERE (%s IS NULL OR estado=%s) "
                                "ORDER BY id DESC LIMIT %s", (estado, estado, limite)))


@app.get("/voces", tags=["voces"])
def voz_listar():
    return _consultar(voces.listar)


@app.get("/voces/{nombre}", tags=["voces"])
def voz_ver(nombre: str):
    return _o_404(_consultar(voces.ver, nombre), nombre)


@app.get("/auditoria", tags=["auditoria"], summary="Quién hizo qué y cuándo")
def auditoria(tabla: Optional[str] = None, limite: int = 50):
    with DB() as db:
        return _limpio(db.todos("SELECT * FROM auditoria WHERE (%s IS NULL OR tabla=%s) ORDER BY id DESC LIMIT %s",
                                (tabla, tabla, limite)))


# --- explorador genérico: filas completas de cualquier tabla o vista ---

def _tablas(db):
    return {f["nombre"]: f for f in db.todos(
        "SELECT t.table_name AS nombre, t.table_type AS tipo, "
        "EXISTS(SELECT 1 FROM information_schema.columns c WHERE c.table_schema=t.table_schema "
        "AND c.table_name=t.table_name AND c.column_name='id') AS tiene_id "
        "FROM information_schema.tables t WHERE t.table_schema=DATABASE() ORDER BY 1")}


def _tabla_valida(db, tabla):
    info = _tablas(db).get(tabla)
    if info is None:
        raise HTTPException(404, f"no existe la tabla {tabla}")
    return info


@app.get("/tablas", tags=["tablas"], summary="Tablas y vistas de la base")
def tablas():
    with DB() as db:
        return [{"nombre": n, "tipo": i["tipo"], "filas": db.valor(f"SELECT COUNT(*) FROM `{n}`")}
                for n, i in _tablas(db).items()]


@app.get("/tablas/{tabla}", tags=["tablas"], summary="Filas completas de una tabla o vista")
def tabla_filas(tabla: str, limite: int = Query(50, le=500), desde: int = 0):
    with DB() as db:
        info = _tabla_valida(db, tabla)   # el nombre sale del catálogo, no del usuario, antes de interpolarlo
        orden = "ORDER BY id DESC " if info["tiene_id"] else ""
        return _limpio(db.todos(f"SELECT * FROM `{tabla}` {orden}LIMIT %s OFFSET %s", (limite, desde)))


@app.get("/tablas/{tabla}/{id}", tags=["tablas"], summary="Una fila por id")
def tabla_fila(tabla: str, id: int):
    with DB() as db:
        if not _tabla_valida(db, tabla)["tiene_id"]:
            raise HTTPException(400, f"{tabla} no tiene columna id")
        return _o_404(db.uno(f"SELECT * FROM `{tabla}` WHERE id=%s", (id,)), f"{tabla} {id}")


def main():
    import uvicorn
    p = argparse.ArgumentParser(description="API de solo lectura de memoria (Swagger en /docs)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--puerto", type=int, default=8090)
    a = p.parse_args()
    uvicorn.run(app, host=a.host, port=a.puerto)


if __name__ == "__main__":
    main()
