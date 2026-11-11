"""Base <-> archivos de Claude Code.

  materializar  genera .claude/agents, .claude/skills y CLAUDE.md en una carpeta (o una temporal)
  sincronizar   trae de vuelta a la base lo que se editó en esos archivos (versión nueva)
  importar      carga archivos existentes escritos a mano

Seguridad: nunca pisa un archivo que no haya generado (o que se editó después de generarlo)
salvo con forzar=True, y en ese caso deja una copia .bak.
"""
import tempfile
from pathlib import Path

from . import catalogo, formato, memorias
from .catalogo import sha256
from .proyectos import por_ruta


def _leer(ruta):
    return Path(ruta).read_text(encoding="utf-8")


def _registro_vigente(db, ruta):
    return db.uno("SELECT * FROM materializaciones WHERE ruta=%s AND estado='vigente' ORDER BY id DESC LIMIT 1",
                  (str(ruta),))


def _verificar_destino(db, ruta, forzar):
    """Lanza FileExistsError si escribir en `ruta` pisaría trabajo ajeno."""
    if not ruta.exists():
        return
    reg = _registro_vigente(db, ruta)
    actual = sha256(_leer(ruta))
    if reg and reg["sha256"] == actual:
        return
    if not forzar:
        motivo = ("se editó después de generarlo: corré `memoria sincronizar` primero" if reg
                  else "no lo generó memoria")
        raise FileExistsError(f"{ruta} ya existe y {motivo} (o usá --forzar, deja copia .bak)")
    ruta.with_name(ruta.name + ".bak").write_text(_leer(ruta), encoding="utf-8")


def _escribir(db, destino, entidad, entidad_id, version, ruta, texto, proyecto_id, agente_id):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    db.ejecutar("UPDATE materializaciones SET estado='reemplazado' WHERE ruta=%s AND estado='vigente'", (str(ruta),))
    db.ejecutar("INSERT INTO materializaciones (entidad, entidad_id, version, destino, ruta, sha256, proyecto_id, "
                "agente_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (entidad, entidad_id, version, str(destino), str(ruta), sha256(texto), proyecto_id, agente_id))


def _archivos_agente(db, nombre, destino):
    a = catalogo.obtener_agente(db, nombre)
    texto = formato.render_agente({"nombre": nombre, "version": a["version"], **a["agente"]},
                                  a["secciones"], a["skills"], a["mcps"])
    return [("agente", a["id"], a["version"], destino / ".claude" / "agents" / f"{nombre}.md", texto)], a["skills"]


def _archivos_skill(db, nombre, destino):
    s = catalogo.obtener_skill(db, nombre)
    carpeta = destino / ".claude" / "skills" / nombre
    salida = [("skill", s["id"], s["version"], carpeta / "SKILL.md", formato.render_skill({**s, "nombre": nombre}))]
    for rel, contenido in s["archivos"].items():
        salida.append(("skill_archivo", s["id"], s["version"], carpeta / rel, contenido))
    return salida


def _archivo_contexto(db, destino, proyecto_id, agente_id):
    secciones = catalogo.secciones_contexto(db, proyecto_id, agente_id)
    if not secciones:
        return []
    return [("contexto", None, None, destino / "CLAUDE.md", formato.render_contexto(secciones))]


def materializar(db, destino=None, agente=None, proyecto=None, subagentes=None, forzar=False):
    """Genera los archivos. Devuelve {destino, archivos, comando}.

    subagentes: materializar también el resto de los agentes activos (para que el agente pueda
    derivarles trabajo). None = sí si el agente es el general.
    """
    destino = Path(destino).expanduser().resolve() if destino else Path(tempfile.mkdtemp(prefix="memoria-"))
    proyecto_id = db.id_de("proyectos", proyecto) if proyecto else (por_ruta(db, destino) or {}).get("id")
    agente_id = db.id_de("agentes", agente) if agente else None

    planes, skills = [], set()
    if agente:
        archivos, sks = _archivos_agente(db, agente, destino)
        planes += archivos
        skills |= set(sks)
        es_general = bool(db.valor("SELECT es_general FROM agentes WHERE id=%s", (agente_id,)))
        if subagentes if subagentes is not None else es_general:
            for otro in catalogo.listar_agentes(db):
                if otro["nombre"] != agente:
                    archivos, sks = _archivos_agente(db, otro["nombre"], destino)
                    planes += archivos
                    skills |= set(sks)
    for sk in sorted(skills):
        planes += _archivos_skill(db, sk, destino)
    planes += _archivo_contexto(db, destino, proyecto_id, agente_id)

    with db.transaccion():
        for _, _, _, ruta, _ in planes:
            _verificar_destino(db, ruta, forzar)
        for entidad, eid, version, ruta, texto in planes:
            _escribir(db, destino, entidad, eid, version, ruta, texto, proyecto_id, agente_id)
        db.auditar("materializaciones", None, "materializar", destino=str(destino), agente=agente,
                   archivos=len(planes))
    comando = f"cd {destino} && MEMORIA_AGENTE={agente} claude --agent {agente}" if agente else f"cd {destino} && claude"
    return {"destino": str(destino), "archivos": [str(p[3]) for p in planes], "comando": comando}


# ───────── sincronizar ─────────

def _sincronizar_uno(db, reg, texto):
    """Aplica a la base el contenido editado. Devuelve (entidad_id, version) resultantes."""
    ruta = Path(reg["ruta"])
    if reg["entidad"] == "agente":
        nombre = db.valor("SELECT nombre FROM agentes WHERE id=%s", (reg["entidad_id"],))
        datos, secciones, skills, mcps = formato.parse_agente(texto)
        datos = {k: v for k, v in datos.items() if k != "nombre"}
        r = catalogo.guardar_agente(db, nombre, datos, secciones, skills, mcps, origen="sincronizado",
                                    nota=f"editado en {ruta}")
        return r["id"], r["version"]
    if reg["entidad"] == "skill":
        nombre = db.valor("SELECT nombre FROM skills WHERE id=%s", (reg["entidad_id"],))
        s = formato.parse_skill(texto)
        r = catalogo.guardar_skill(db, nombre, s["descripcion"], s["instrucciones"], s["herramientas"],
                                   origen="sincronizado", nota=f"editado en {ruta}")
        return r["id"], r["version"]
    if reg["entidad"] == "skill_archivo":
        s = catalogo.obtener_skill(db, db.valor("SELECT nombre FROM skills WHERE id=%s", (reg["entidad_id"],)))
        carpeta = Path(reg["destino"]) / ".claude" / "skills" / s["nombre"]
        archivos = {**s["archivos"], str(ruta.relative_to(carpeta)): texto}
        r = catalogo.guardar_skill(db, s["nombre"], archivos=archivos, origen="sincronizado", nota=f"editado en {ruta}")
        return r["id"], r["version"]
    # contexto: cada sección marcada se actualiza por id; las nuevas se crean en el alcance más específico
    alcance = "proyecto" if reg["proyecto_id"] else "global"
    for s in formato.parse_contexto(texto):
        if s["id"] is not None:
            fila = db.uno("SELECT tipo, orden FROM contexto_secciones WHERE id=%s", (s["id"],))
            if fila:
                catalogo.guardar_contexto(db, s["titulo"], s["contenido"], tipo=fila["tipo"], orden=fila["orden"],
                                          id=s["id"], origen="sincronizado", nota=f"editado en {ruta}")
                continue
        catalogo.guardar_contexto(db, s["titulo"], s["contenido"], alcance=alcance, proyecto=reg["proyecto_id"],
                                  origen="sincronizado", nota=f"agregado en {ruta}")
    return None, None


def sincronizar(db, destino):
    """Revisa los archivos generados en `destino`; lo editado vuelve a la base como versión nueva.

    Después de sincronizar, el archivo se regenera desde la base (así las secciones nuevas
    quedan con su marcador y la próxima sincronización las reconoce).
    """
    destino = Path(destino).expanduser().resolve()
    resultado = {"sin_cambios": 0, "actualizados": [], "borrados": [], "errores": []}
    regs = db.todos("SELECT * FROM materializaciones WHERE destino=%s AND estado='vigente' ORDER BY id", (str(destino),))
    for reg in regs:
        ruta = Path(reg["ruta"])
        if not ruta.exists():
            with db.transaccion():
                db.ejecutar("UPDATE materializaciones SET estado='borrado', revisado=CURRENT_TIMESTAMP(3) WHERE id=%s",
                            (reg["id"],))
            resultado["borrados"].append(str(ruta))
            continue
        texto = _leer(ruta)
        if sha256(texto) == reg["sha256"]:
            resultado["sin_cambios"] += 1
            continue
        try:
            with db.transaccion():
                _sincronizar_uno(db, reg, texto)
                db.ejecutar("UPDATE materializaciones SET estado='sincronizado', revisado=CURRENT_TIMESTAMP(3) "
                            "WHERE id=%s", (reg["id"],))
                # regenerar desde la base
                if reg["entidad"] == "agente":
                    nombre = db.valor("SELECT nombre FROM agentes WHERE id=%s", (reg["entidad_id"],))
                    planes, _ = _archivos_agente(db, nombre, destino)
                elif reg["entidad"] in ("skill", "skill_archivo"):
                    nombre = db.valor("SELECT nombre FROM skills WHERE id=%s", (reg["entidad_id"],))
                    planes = [p for p in _archivos_skill(db, nombre, destino) if p[3] == ruta]
                else:
                    planes = _archivo_contexto(db, destino, reg["proyecto_id"], reg["agente_id"])
                for entidad, eid, version, r, t in planes:
                    _escribir(db, destino, entidad, eid, version, r, t, reg["proyecto_id"], reg["agente_id"])
                db.auditar("materializaciones", reg["id"], "sincronizar", ruta=str(ruta))
            resultado["actualizados"].append(str(ruta))
        except Exception as e:
            resultado["errores"].append({"ruta": str(ruta), "error": f"{type(e).__name__}: {e}"})
    return resultado


# ───────── importar ─────────

def importar(db, origen, proyecto=None):
    """Carga agentes, skills y CLAUDE.md escritos a mano (carpeta de proyecto o ~/.claude)."""
    origen = Path(origen).expanduser().resolve()
    base = origen / ".claude" if (origen / ".claude").is_dir() else origen
    resultado = {"skills": [], "agentes": [], "contexto": [], "memorias": [], "avisos": []}

    # memoria de archivos de Claude Code: memory/*.md con frontmatter (name, description,
    # metadata.type). Puede estar al lado (memory/) o por proyecto (projects/*/memory/).
    tipo_md = {"user": "preferencia", "feedback": "preferencia", "project": "hecho",
               "reference": "referencia"}
    for md in sorted(list(base.glob("memory/*.md")) + list(base.glob("projects/*/memory/*.md"))):
        if md.name == "MEMORY.md":          # índice, no una memoria
            continue
        meta, cuerpo = formato.separar_frontmatter(_leer(md))
        cuerpo = cuerpo.strip()
        if not cuerpo:
            continue
        titulo = (meta.get("description") or meta.get("name") or md.stem).strip()
        if db.uno("SELECT id FROM memorias WHERE titulo=%s", (titulo,)):
            resultado["avisos"].append(f"memoria ya existente, se omite: {titulo}")
            continue
        tipo = tipo_md.get(((meta.get("metadata") or {}).get("type") or "").strip(), "hecho")
        mid = memorias.agregar(db, tipo, titulo, cuerpo, proyecto=proyecto,
                               etiquetas=("importado",))
        resultado["memorias"].append({"titulo": titulo, "tipo": tipo, "id": mid})

    for skill_md in sorted(base.glob("skills/*/SKILL.md")):
        s = formato.parse_skill(_leer(skill_md))
        nombre = s["nombre"] or skill_md.parent.name
        archivos = {str(p.relative_to(skill_md.parent)): _leer(p) for p in sorted(skill_md.parent.rglob("*"))
                    if p.is_file() and p.name != "SKILL.md" and not p.name.endswith(".bak")}
        r = catalogo.guardar_skill(db, nombre, s["descripcion"] or nombre, s["instrucciones"], s["herramientas"],
                                   archivos=archivos, origen="importado", nota=str(skill_md))
        resultado["skills"].append({"nombre": nombre, **r})

    conocidas = {s["nombre"] for s in catalogo.listar_skills(db)}
    mcps_conocidos = {f["nombre"] for f in db.todos("SELECT nombre FROM mcp_servidores")}
    for md in sorted(base.glob("agents/*.md")):
        datos, secciones, skills, mcps = formato.parse_agente(_leer(md))
        nombre = datos.pop("nombre") or md.stem
        faltan = [s for s in skills if s not in conocidas] + [m for m in mcps if m not in mcps_conocidos]
        if faltan:
            resultado["avisos"].append(f"{nombre}: se omiten referencias inexistentes {faltan}")
        r = catalogo.guardar_agente(db, nombre, datos, secciones, [s for s in skills if s in conocidas],
                                    [m for m in mcps if m in mcps_conocidos], origen="importado", nota=str(md))
        resultado["agentes"].append({"nombre": nombre, **r})

    claude_md = next((p for p in (origen / "CLAUDE.md", base / "CLAUDE.md") if p.is_file()), None)
    if claude_md:
        proyecto_id = db.id_de("proyectos", proyecto) if proyecto else None
        alcance = "proyecto" if proyecto_id else "global"
        for s in formato.parse_contexto(_leer(claude_md)):
            previo = db.uno("SELECT id FROM contexto_secciones WHERE alcance=%s AND proyecto_id <=> %s "
                            "AND agente_id IS NULL AND titulo=%s", (alcance, proyecto_id, s["titulo"]))
            r = catalogo.guardar_contexto(db, s["titulo"], s["contenido"], alcance=alcance, proyecto=proyecto_id,
                                          id=previo and previo["id"], origen="importado", nota=str(claude_md))
            resultado["contexto"].append({"titulo": s["titulo"], **r})
    return resultado
