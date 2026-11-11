"""Agentes, skills y secciones de contexto, con historial de versiones.

Cada `guardar_*` compara contra la foto actual: si no cambió nada no toca la base; si cambió,
sube la versión y deja la foto completa en `versiones` (se puede restaurar cualquiera).
"""
import hashlib

from .db import a_json, de_json

CAMPOS_AGENTE = ("descripcion", "modelo", "color", "herramientas", "herramientas_negadas",
                 "modo_permisos", "es_general", "activo", "es_rol", "es_lider")
CAMPOS_JSON = {"herramientas", "herramientas_negadas"}
CAMPOS_BOOL = ("es_general", "activo", "es_rol", "es_lider")
# Referencias por nombre que se guardan como FK (rol_id → agentes, proyecto_id → proyectos).
CAMPOS_REF = {"rol": ("rol_id", "agentes"), "proyecto": ("proyecto_id", "proyectos")}
AGENTE_VACIO = {"descripcion": "", "modelo": None, "color": None, "herramientas": None,
                "herramientas_negadas": None, "modo_permisos": None, "es_general": False, "activo": True,
                "es_rol": False, "es_lider": False, "rol": None, "proyecto": None}


def sha256(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _registrar_version(db, entidad, entidad_id, version, snapshot, origen, nota):
    db.ejecutar("INSERT INTO versiones (entidad, entidad_id, version, snapshot, origen, actor, nota) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (entidad, entidad_id, version, a_json(snapshot), origen, db.actor, nota))


def _normalizar_secciones(secciones):
    return [{"tipo": s.get("tipo", "otro"), "titulo": s["titulo"], "orden": int(s.get("orden", (i + 1) * 10)),
             "contenido": s["contenido"].strip(), "activo": bool(s.get("activo", True))}
            for i, s in enumerate(secciones)]


# ───────── agentes ─────────

def snapshot_agente(db, agente_id):
    a = db.uno("SELECT * FROM agentes WHERE id=%s", (agente_id,))
    if a is None:
        return None
    datos = {k: (de_json(a[k]) if k in CAMPOS_JSON else a[k]) for k in CAMPOS_AGENTE}
    for k in CAMPOS_BOOL:
        datos[k] = bool(datos[k])
    for campo, (col, tabla) in CAMPOS_REF.items():
        datos[campo] = a[col] and db.valor(f"SELECT nombre FROM {tabla} WHERE id=%s", (a[col],))
    secciones = db.todos("SELECT tipo, titulo, orden, contenido, activo FROM agente_secciones "
                         "WHERE agente_id=%s ORDER BY orden, id", (agente_id,))
    for s in secciones:
        s["activo"] = bool(s["activo"])
    skills = [f["nombre"] for f in db.todos(
        "SELECT s.nombre FROM agente_skill x JOIN skills s ON s.id=x.skill_id WHERE x.agente_id=%s "
        "ORDER BY s.nombre", (agente_id,))]
    mcps = {"base": [], "a_pedido": []}
    for f in db.todos("SELECT m.nombre, x.modo FROM agente_mcp x JOIN mcp_servidores m ON m.id=x.mcp_id "
                      "WHERE x.agente_id=%s ORDER BY m.nombre", (agente_id,)):
        mcps[f["modo"]].append(f["nombre"])
    return {"nombre": a["nombre"], "agente": datos, "secciones": secciones, "skills": skills,
            "mcps": mcps["base"], "mcps_a_pedido": mcps["a_pedido"]}


def obtener_agente(db, nombre):
    fila = db.uno("SELECT id, uid, version FROM agentes WHERE nombre=%s OR uid=%s", (nombre, nombre))
    if fila is None:
        raise LookupError(f"no existe el agente {nombre!r}")
    return {"id": fila["id"], "uid": fila["uid"], "version": fila["version"], **snapshot_agente(db, fila["id"])}


def guardar_agente(db, nombre, datos=None, secciones=None, skills=None, mcps=None,
                   origen="manual", nota=None, mcps_a_pedido=None):
    """Crea o actualiza. Lo que se pasa como None se conserva. Devuelve {id, uid, version, cambiado}.

    datos puede traer `rol` y `proyecto` por nombre (un miembro: devops-str = rol devops en STR).
    mcps son los que se conectan al arrancar; mcps_a_pedido, los que el agente pide cuando los necesita.
    """
    datos = dict(datos or {})
    with db.transaccion():
        fila = db.uno("SELECT id, uid, version FROM agentes WHERE nombre=%s FOR UPDATE", (nombre,))
        actual = snapshot_agente(db, fila["id"]) if fila else None
        base = actual or {"agente": AGENTE_VACIO, "secciones": [], "skills": [], "mcps": [], "mcps_a_pedido": []}
        nuevo = {
            "nombre": nombre,
            "agente": {**base["agente"],
                       **{k: v for k, v in datos.items() if k in CAMPOS_AGENTE or k in CAMPOS_REF}},
            "secciones": _normalizar_secciones(secciones) if secciones is not None else base["secciones"],
            "skills": sorted(set(skills)) if skills is not None else base["skills"],
            "mcps": sorted(set(mcps)) if mcps is not None else base["mcps"],
            "mcps_a_pedido": sorted(set(mcps_a_pedido)) if mcps_a_pedido is not None else base["mcps_a_pedido"],
        }
        a = nuevo["agente"]
        for k in CAMPOS_BOOL:
            a[k] = bool(a[k])
        for k in CAMPOS_REF:
            a[k] = a[k] or None
        nuevo["mcps_a_pedido"] = [m for m in nuevo["mcps_a_pedido"] if m not in nuevo["mcps"]]
        if actual == nuevo:
            return {"id": fila["id"], "uid": fila["uid"], "version": fila["version"], "cambiado": False}
        if not a["descripcion"]:
            raise ValueError(f"el agente {nombre!r} necesita descripción (cuándo usarlo)")
        if a["es_rol"] and (a["rol"] or a["proyecto"]):
            raise ValueError(f"{nombre!r} es un rol (plantilla global): no lleva rol ni proyecto")
        if a["rol"]:
            if a["rol"] == nombre:
                raise ValueError(f"{nombre!r} no puede ser su propio rol")
            if not db.valor("SELECT es_rol FROM agentes WHERE nombre=%s", (a["rol"],)):
                raise ValueError(f"{a['rol']!r} no existe o no es un rol (agente_guardar con es_rol)")

        columnas = [*CAMPOS_AGENTE, *(col for col, _ in CAMPOS_REF.values())]
        valores = [a_json(a[k]) if k in CAMPOS_JSON else a[k] for k in CAMPOS_AGENTE]
        valores += [db.id_de(tabla, a[campo]) for campo, (_, tabla) in CAMPOS_REF.items()]
        if fila:
            agente_id, uid, version = fila["id"], fila["uid"], fila["version"] + 1
            db.ejecutar(f"UPDATE agentes SET {', '.join(f'{k}=%s' for k in columnas)}, version=%s "
                        f"WHERE id=%s", (*valores, version, agente_id))
            db.ejecutar("DELETE FROM agente_secciones WHERE agente_id=%s", (agente_id,))
            db.ejecutar("DELETE FROM agente_skill WHERE agente_id=%s", (agente_id,))
            db.ejecutar("DELETE FROM agente_mcp WHERE agente_id=%s", (agente_id,))
        else:
            version = 1
            uid = db.valor("SELECT UUID()")
            agente_id = db.ejecutar(f"INSERT INTO agentes (uid, nombre, {', '.join(columnas)}) "
                                    f"VALUES (%s, %s, {', '.join(['%s'] * len(columnas))})", (uid, nombre, *valores))
        for s in nuevo["secciones"]:
            db.ejecutar("INSERT INTO agente_secciones (agente_id, tipo, titulo, orden, contenido, activo) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (agente_id, s["tipo"], s["titulo"], s["orden"], s["contenido"], s["activo"]))
        for sk in nuevo["skills"]:
            db.ejecutar("INSERT INTO agente_skill (agente_id, skill_id) VALUES (%s,%s)",
                        (agente_id, db.id_de("skills", sk)))
        for modo, lista in (("base", nuevo["mcps"]), ("a_pedido", nuevo["mcps_a_pedido"])):
            for m in lista:
                db.ejecutar("INSERT INTO agente_mcp (agente_id, mcp_id, modo) VALUES (%s,%s,%s)",
                            (agente_id, db.id_de("mcp_servidores", m), modo))
        _registrar_version(db, "agente", agente_id, version, nuevo, origen, nota)
        db.auditar("agentes", agente_id, "actualizar" if fila else "crear", version=version, origen=origen)
        return {"id": agente_id, "uid": uid, "version": version, "cambiado": True}


def editar_seccion(db, agente, titulo, contenido=None, tipo=None, orden=None, activo=None,
                   nuevo_titulo=None, origen="manual", nota=None):
    """Edita (o agrega, si no existe) una sección del agente por título."""
    actual = obtener_agente(db, agente)
    secciones = [dict(s) for s in actual["secciones"]]
    objetivo = next((s for s in secciones if s["titulo"].lower() == titulo.lower()), None)
    if objetivo is None:
        if contenido is None:
            raise LookupError(f"el agente {agente!r} no tiene la sección {titulo!r}")
        objetivo = {"tipo": tipo or "otro", "titulo": titulo, "contenido": contenido, "activo": True,
                    "orden": orden if orden is not None else (max((s["orden"] for s in secciones), default=0) + 10)}
        secciones.append(objetivo)
    for campo, valor in (("contenido", contenido), ("tipo", tipo), ("orden", orden), ("activo", activo),
                         ("titulo", nuevo_titulo)):
        if valor is not None:
            objetivo[campo] = valor
    secciones.sort(key=lambda s: s["orden"])
    return guardar_agente(db, agente, secciones=secciones, origen=origen, nota=nota)


def listar_agentes(db, incluir_inactivos=False, proyecto=None, rol=None):
    """Roles primero, después los miembros. Filtra por proyecto y/o rol (por nombre)."""
    return db.todos(
        "SELECT a.uid, a.nombre, a.descripcion, a.modelo, a.es_general, a.es_rol, a.es_lider, r.nombre AS rol, "
        "p.nombre AS proyecto, a.activo, a.version, a.actualizado FROM agentes a "
        "LEFT JOIN agentes r ON r.id=a.rol_id LEFT JOIN proyectos p ON p.id=a.proyecto_id "
        "WHERE (%s OR a.activo) AND (%s IS NULL OR p.nombre=%s) AND (%s IS NULL OR r.nombre=%s) "
        "ORDER BY a.es_general DESC, a.es_rol DESC, p.nombre, a.nombre",
        (bool(incluir_inactivos), proyecto, proyecto, rol, rol))


def resolver_agente(db, nombre):
    """El agente con lo heredado de su rol: secciones del rol y luego las propias (una propia con el
    mismo título reemplaza a la del rol), skills y MCPs sumados; modelo y herramientas del miembro o,
    si no tiene, del rol."""
    a = obtener_agente(db, nombre)
    datos = a["agente"]
    rol = obtener_agente(db, datos["rol"]) if datos["rol"] else None
    propias = [s for s in a["secciones"] if s["activo"]]
    titulos = {s["titulo"].lower() for s in propias}
    heredadas = [s for s in (rol["secciones"] if rol else []) if s["activo"] and s["titulo"].lower() not in titulos]
    base = sorted(set(a["mcps"]) | set(rol["mcps"] if rol else []))
    a_pedido = sorted((set(a["mcps_a_pedido"]) | set(rol["mcps_a_pedido"] if rol else [])) - set(base))

    def de_rol(k):
        return datos[k] if datos[k] is not None or not rol else rol["agente"][k]

    return {"uid": a["uid"], "nombre": a["nombre"], "descripcion": datos["descripcion"],
            "rol": datos["rol"], "proyecto": datos["proyecto"], "es_rol": datos["es_rol"],
            "es_lider": datos["es_lider"], "es_general": datos["es_general"], "activo": datos["activo"],
            "modelo": de_rol("modelo"), "herramientas": de_rol("herramientas"),
            "herramientas_negadas": de_rol("herramientas_negadas"), "modo_permisos": de_rol("modo_permisos"),
            "secciones": [{**s, "heredada": True} for s in heredadas] + [{**s, "heredada": False} for s in propias],
            "skills": sorted(set(a["skills"]) | set(rol["skills"] if rol else [])),
            "mcps": {"base": base, "a_pedido": a_pedido}}


def prompt_identidad(r):
    """Las instrucciones del agente en markdown, listas para el system prompt de una sesión nueva."""
    partes = [f"# Sos {r['nombre']}" + (f" (rol {r['rol']}" + (f", proyecto {r['proyecto']})" if r["proyecto"] else ")")
                                         if r["rol"] else ""), r["descripcion"]]
    if r["es_lider"]:
        partes.append("Sos líder: podés crear miembros nuevos y repartirles trabajo.")
    partes += [f"## {s['titulo']}\n\n{s['contenido']}" for s in r["secciones"]]
    return "\n\n".join(p for p in partes if p)


def despertar(db, nombre, memorias_max=30):
    """Todo lo que necesita una sesión nueva (después de /clear) para volver a ser este agente:
    identidad resuelta, prompt, MCPs base y a pedido, contexto del proyecto y del agente, el último
    resumen de sesión y sus memorias. No incluye la config de los MCPs (puede tener secretos)."""
    r = resolver_agente(db, nombre)
    proyecto = db.uno("SELECT nombre, ruta_raiz, descripcion FROM proyectos WHERE nombre=%s", (r["proyecto"],)) \
        if r["proyecto"] else None
    descripciones = {m["nombre"]: m["descripcion"] for m in db.todos(
        "SELECT nombre, descripcion FROM mcp_servidores WHERE activo")}
    contexto = [{"alcance": c["alcance"], "titulo": c["titulo"], "contenido": c["contenido"]}
                for c in secciones_contexto(db, r["proyecto"], r["nombre"]) if c["alcance"] != "global"]
    nombres = [n for n in (r["nombre"], r["rol"]) if n]
    memorias = db.todos(
        "SELECT id, tipo, alcance, proyecto, agente, titulo, contenido, importancia, actualizado "
        "FROM v_memorias_vigentes WHERE agente IN (" + ",".join(["%s"] * len(nombres)) + ") "
        "OR (alcance='proyecto' AND proyecto <=> %s AND tipo IN ('pendiente','decision')) "
        "ORDER BY alcance='agente' DESC, importancia DESC, actualizado DESC LIMIT %s",
        (*nombres, r["proyecto"], memorias_max))
    sesion = db.uno("SELECT session_uuid, titulo, compactado, contenido FROM v_resumenes WHERE agente=%s "
                    "ORDER BY compactado DESC LIMIT 1", (r["nombre"],))
    return {"identidad": r, "prompt": prompt_identidad(r), "proyecto": proyecto, "contexto": contexto,
            "mcps": {modo: [{"nombre": m, "descripcion": descripciones.get(m)} for m in lista]
                     for modo, lista in r["mcps"].items()},
            "ultima_sesion": sesion, "memorias": memorias,
            "denis": {"agent": r["nombre"], "identity": r["uid"]}}


# ───────── servidores MCP ─────────

def guardar_mcp(db, nombre, config=None, descripcion=None, activo=None):
    """Alta o actualización de un servidor MCP (config = entrada de .mcp.json)."""
    with db.transaccion():
        fila = db.uno("SELECT * FROM mcp_servidores WHERE nombre=%s", (nombre,))
        if fila is None:
            if config is None:
                raise ValueError(f"el MCP {nombre!r} es nuevo: falta config")
            id_ = db.ejecutar("INSERT INTO mcp_servidores (nombre, descripcion, config, activo) VALUES (%s,%s,%s,%s)",
                              (nombre, descripcion, a_json(config), True if activo is None else activo))
            db.auditar("mcp_servidores", id_, "crear")
            return {"id": id_, "nombre": nombre, "creado": True}
        db.ejecutar("UPDATE mcp_servidores SET descripcion=COALESCE(%s, descripcion), config=COALESCE(%s, config), "
                    "activo=COALESCE(%s, activo) WHERE id=%s",
                    (descripcion, a_json(config) if config is not None else None, activo, fila["id"]))
        db.auditar("mcp_servidores", fila["id"], "actualizar")
        return {"id": fila["id"], "nombre": nombre, "creado": False}


def listar_mcps(db, con_config=False):
    """Sin con_config solo muestra qué variables de entorno usa cada uno, no sus valores."""
    filas = db.todos("SELECT id, nombre, descripcion, config, activo FROM mcp_servidores ORDER BY nombre")
    for f in filas:
        f["config"] = de_json(f["config"])
        f["activo"] = bool(f["activo"])
        if not con_config:
            cfg = f.pop("config") or {}
            f["tipo"] = cfg.get("type") or ("http" if "url" in cfg else "stdio")
            f["env"] = sorted((cfg.get("env") or {}).keys())
    return filas


def config_mcps(db, nombres):
    """{nombre: config} listo para mcpServers (lo usa quien lanza la sesión, no el agente)."""
    if not nombres:
        return {}
    filas = db.todos("SELECT nombre, config FROM mcp_servidores WHERE activo AND nombre IN ("
                     + ",".join(["%s"] * len(nombres)) + ")", tuple(nombres))
    return {f["nombre"]: de_json(f["config"]) for f in filas}


# ───────── skills ─────────

def snapshot_skill(db, skill_id):
    s = db.uno("SELECT * FROM skills WHERE id=%s", (skill_id,))
    if s is None:
        return None
    archivos = {f["ruta_relativa"]: f["contenido"] for f in db.todos(
        "SELECT ruta_relativa, contenido FROM skill_archivos WHERE skill_id=%s ORDER BY ruta_relativa", (skill_id,))}
    return {"nombre": s["nombre"], "descripcion": s["descripcion"], "instrucciones": s["instrucciones"],
            "herramientas": de_json(s["herramientas"]), "activo": bool(s["activo"]), "archivos": archivos}


def obtener_skill(db, nombre):
    fila = db.uno("SELECT id, version FROM skills WHERE nombre=%s", (nombre,))
    if fila is None:
        raise LookupError(f"no existe la skill {nombre!r}")
    return {"id": fila["id"], "version": fila["version"], **snapshot_skill(db, fila["id"])}


def guardar_skill(db, nombre, descripcion=None, instrucciones=None, herramientas=None, activo=None,
                  archivos=None, origen="manual", nota=None):
    with db.transaccion():
        fila = db.uno("SELECT id, version FROM skills WHERE nombre=%s FOR UPDATE", (nombre,))
        actual = snapshot_skill(db, fila["id"]) if fila else None
        base = actual or {"nombre": nombre, "descripcion": "", "instrucciones": "", "herramientas": None,
                          "activo": True, "archivos": {}}
        nuevo = {**base}
        for campo, valor in (("descripcion", descripcion), ("instrucciones", instrucciones),
                             ("herramientas", herramientas), ("activo", activo), ("archivos", archivos)):
            if valor is not None:
                nuevo[campo] = valor
        nuevo["instrucciones"] = nuevo["instrucciones"].strip()
        if actual == nuevo:
            return {"id": fila["id"], "version": fila["version"], "cambiado": False}
        if not nuevo["descripcion"] or not nuevo["instrucciones"]:
            raise ValueError(f"la skill {nombre!r} necesita descripción e instrucciones")
        valores = (nuevo["descripcion"], nuevo["instrucciones"], a_json(nuevo["herramientas"]), nuevo["activo"])
        if fila:
            skill_id, version = fila["id"], fila["version"] + 1
            db.ejecutar("UPDATE skills SET descripcion=%s, instrucciones=%s, herramientas=%s, activo=%s, version=%s "
                        "WHERE id=%s", (*valores, version, skill_id))
            db.ejecutar("DELETE FROM skill_archivos WHERE skill_id=%s", (skill_id,))
        else:
            version = 1
            skill_id = db.ejecutar("INSERT INTO skills (nombre, descripcion, instrucciones, herramientas, activo) "
                                   "VALUES (%s,%s,%s,%s,%s)", (nombre, *valores))
        for ruta, contenido in sorted(nuevo["archivos"].items()):
            db.ejecutar("INSERT INTO skill_archivos (skill_id, ruta_relativa, contenido, sha256) VALUES (%s,%s,%s,%s)",
                        (skill_id, ruta, contenido, sha256(contenido)))
        _registrar_version(db, "skill", skill_id, version, nuevo, origen, nota)
        db.auditar("skills", skill_id, "actualizar" if fila else "crear", version=version, origen=origen)
        return {"id": skill_id, "version": version, "cambiado": True}


def listar_skills(db):
    return db.todos("SELECT nombre, descripcion, activo, version, actualizado FROM skills ORDER BY nombre")


# ───────── contexto (CLAUDE.md) ─────────

def _snapshot_contexto(fila):
    return {k: fila[k] for k in ("alcance", "proyecto_id", "agente_id", "tipo", "titulo", "orden", "contenido")} | \
        {"activo": bool(fila["activo"])}


def guardar_contexto(db, titulo, contenido, alcance="global", proyecto=None, agente=None, tipo="otro",
                     orden=None, activo=True, id=None, origen="manual", nota=None):
    """Crea (id=None) o actualiza una sección de contexto."""
    with db.transaccion():
        proyecto_id = db.id_de("proyectos", proyecto)
        agente_id = db.id_de("agentes", agente)
        if id is not None:
            fila = db.uno("SELECT * FROM contexto_secciones WHERE id=%s FOR UPDATE", (id,))
            if fila is None:
                raise LookupError(f"no existe la sección de contexto {id}")
            nuevo = {**_snapshot_contexto(fila), "titulo": titulo, "contenido": contenido.strip(),
                     "tipo": tipo or fila["tipo"], "orden": fila["orden"] if orden is None else orden,
                     "activo": bool(activo)}
            if nuevo == _snapshot_contexto(fila):
                return {"id": id, "version": fila["version"], "cambiado": False}
            version = fila["version"] + 1
            db.ejecutar("UPDATE contexto_secciones SET tipo=%s, titulo=%s, orden=%s, contenido=%s, activo=%s, "
                        "version=%s WHERE id=%s",
                        (nuevo["tipo"], titulo, nuevo["orden"], nuevo["contenido"], nuevo["activo"], version, id))
        else:
            if orden is None:
                orden = (db.valor("SELECT COALESCE(MAX(orden), 0) FROM contexto_secciones WHERE alcance=%s "
                                  "AND proyecto_id <=> %s AND agente_id <=> %s",
                                  (alcance, proyecto_id, agente_id)) or 0) + 10
            version = 1
            id = db.ejecutar("INSERT INTO contexto_secciones (alcance, proyecto_id, agente_id, tipo, titulo, orden, "
                             "contenido, activo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (alcance, proyecto_id, agente_id, tipo, titulo, orden, contenido.strip(), activo))
            nuevo = {"alcance": alcance, "proyecto_id": proyecto_id, "agente_id": agente_id, "tipo": tipo,
                     "titulo": titulo, "orden": orden, "contenido": contenido.strip(), "activo": bool(activo)}
        _registrar_version(db, "contexto", id, version, nuevo, origen, nota)
        db.auditar("contexto_secciones", id, "crear" if version == 1 else "actualizar", version=version, origen=origen)
        return {"id": id, "version": version, "cambiado": True}


def secciones_contexto(db, proyecto=None, agente=None):
    """Global + del proyecto + del agente, en ese orden (lo que se arma en CLAUDE.md)."""
    return db.todos(
        "SELECT * FROM contexto_secciones WHERE activo AND ("
        " alcance='global' OR (alcance='proyecto' AND proyecto_id <=> %s) OR (alcance='agente' AND agente_id <=> %s))"
        " ORDER BY FIELD(alcance,'global','proyecto','agente'), orden, id",
        (db.id_de("proyectos", proyecto), db.id_de("agentes", agente)))


# ───────── historial ─────────

def _id_entidad(db, entidad, ref):
    return int(ref) if entidad == "contexto" else db.id_de({"agente": "agentes", "skill": "skills"}[entidad], ref)


def historial(db, entidad, ref):
    return db.todos("SELECT version, origen, actor, nota, creado FROM versiones WHERE entidad=%s AND entidad_id=%s "
                    "ORDER BY version DESC", (entidad, _id_entidad(db, entidad, ref)))


def ver_version(db, entidad, ref, version):
    fila = db.uno("SELECT snapshot FROM versiones WHERE entidad=%s AND entidad_id=%s AND version=%s",
                  (entidad, _id_entidad(db, entidad, ref), version))
    if fila is None:
        raise LookupError(f"no existe la versión {version} de {entidad} {ref}")
    return de_json(fila["snapshot"])


def restaurar(db, entidad, ref, version):
    """Vuelve al contenido de una versión anterior (crea una versión nueva, no borra historia)."""
    foto = ver_version(db, entidad, ref, version)
    nota = f"restaurada la versión {version}"
    if entidad == "agente":
        return guardar_agente(db, foto["nombre"], foto["agente"], foto["secciones"], foto["skills"], foto["mcps"],
                              origen="restaurado", nota=nota, mcps_a_pedido=foto.get("mcps_a_pedido", []))
    if entidad == "skill":
        return guardar_skill(db, foto["nombre"], foto["descripcion"], foto["instrucciones"], foto["herramientas"],
                             foto["activo"], foto["archivos"], origen="restaurado", nota=nota)
    return guardar_contexto(db, foto["titulo"], foto["contenido"], tipo=foto["tipo"], orden=foto["orden"],
                            activo=foto["activo"], id=int(ref), origen="restaurado", nota=nota)
