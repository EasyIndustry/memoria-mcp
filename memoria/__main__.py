"""CLI de memoria. Toda salida es JSON (pensado para scripts, hooks y agentes).

  memoria migrar                                   aplica el esquema
  memoria proyecto alta mi-app --ruta ~/mi-app     | listar | escanear mi-app
  memoria importar ~/mi-app --proyecto mi-app      carga .claude/agents, skills y CLAUDE.md existentes
  memoria agente listar | ver NOMBRE | guardar --archivo x.md | seccion NOMBRE "Título" --contenido ...
  memoria skill listar | ver NOMBRE | guardar --carpeta .claude/skills/x
  memoria contexto listar | agregar "Título" --contenido ... [--proyecto P | --agente A]
  memoria materializar --agente general [--destino DIR | temporal]
  memoria sincronizar DIR                          ediciones de los archivos -> base (versión nueva)
  memoria historial agente NOMBRE | restaurar agente NOMBRE 3
  memoria sesion guardar --session-id UUID | listar | ultima | buscar "texto"
  memoria memorias agregar hecho "título" "contenido" | listar | buscar | olvidar ID
  memoria delegacion crear DESTINO "objetivo" | cerrar ID
  memoria voz guardar NOMBRE '{"base":"grave",...}' | ver NOMBRE | listar   perfil de voz por agente
  memoria hook session-end                         (lo llama Claude Code; ver instalar-hook)
  memoria instalar-hook [--settings ~/.claude/settings.json]
  memoria auditoria [--tabla agentes]
"""
import argparse
import datetime
import decimal
import json
import os
import shlex
import sys
from pathlib import Path

from . import catalogo, esquema, formato, hook, materializar, memorias, proyectos, sesiones, voces
from .config import Config
from .db import DB


def salida(obj):
    def conv(o):
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode(errors="replace")
        return str(o)
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=conv))


def _lista(valor):
    return [v.strip() for v in valor.split(",") if v.strip()] if valor else None


def _texto(args):
    """--contenido literal, o --desde-archivo (o '-' para stdin)."""
    if getattr(args, "desde_archivo", None):
        return sys.stdin.read() if args.desde_archivo == "-" else Path(args.desde_archivo).read_text(encoding="utf-8")
    return args.contenido


def localizar_transcript(session_id):
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    encontrados = sorted(base.glob(f"*/{session_id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not encontrados:
        raise FileNotFoundError(f"no hay transcript para la sesión {session_id} en {base}")
    return encontrados[0]


def crear_parser():
    p = argparse.ArgumentParser(prog="memoria", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrar", help="aplica migraciones pendientes")
    r = sub.add_parser("roles", help="crea roles y usuarios (requiere usuario administrador)")
    r.add_argument("--admin", default="root")
    r.add_argument("--admin-clave", default=os.environ.get("MARIADB_ROOT_PASSWORD", ""))
    r.add_argument("--clave-agente", required=True)
    r.add_argument("--clave-lector", required=True)

    pr = sub.add_parser("proyecto").add_subparsers(dest="accion", required=True)
    a = pr.add_parser("alta")
    a.add_argument("nombre")
    a.add_argument("--ruta")
    a.add_argument("--descripcion")
    a.add_argument("--repo")
    pr.add_parser("listar")
    pr.add_parser("escanear").add_argument("nombre")

    ag = sub.add_parser("agente").add_subparsers(dest="accion", required=True)
    ag.add_parser("listar").add_argument("--todos", action="store_true")
    ag.add_parser("ver").add_argument("nombre")
    g = ag.add_parser("guardar", help="desde un .md con frontmatter o flags sueltos")
    g.add_argument("nombre", nargs="?")
    g.add_argument("--archivo")
    g.add_argument("--descripcion")
    g.add_argument("--modelo")
    g.add_argument("--herramientas", help="coma separadas")
    g.add_argument("--skills", help="coma separadas")
    g.add_argument("--general", action="store_true", help="es el asistente general que deriva")
    g.add_argument("--nota")
    s = ag.add_parser("seccion", help="edita o agrega una sección de instrucciones")
    s.add_argument("nombre")
    s.add_argument("titulo")
    s.add_argument("--contenido")
    s.add_argument("--desde-archivo")
    s.add_argument("--tipo", choices=sorted(formato.TIPOS_SECCION))
    s.add_argument("--orden", type=int)
    s.add_argument("--desactivar", action="store_true")
    s.add_argument("--nota")

    sk = sub.add_parser("skill").add_subparsers(dest="accion", required=True)
    sk.add_parser("listar")
    sk.add_parser("ver").add_argument("nombre")
    g = sk.add_parser("guardar", help="desde una carpeta con SKILL.md")
    g.add_argument("--carpeta", required=True)
    g.add_argument("--nota")

    cx = sub.add_parser("contexto").add_subparsers(dest="accion", required=True)
    l = cx.add_parser("listar")
    l.add_argument("--proyecto")
    l.add_argument("--agente")
    for nombre in ("agregar", "editar"):
        c = cx.add_parser(nombre)
        if nombre == "editar":
            c.add_argument("id", type=int)
        c.add_argument("titulo")
        c.add_argument("--contenido")
        c.add_argument("--desde-archivo")
        c.add_argument("--tipo", default="otro",
                       choices=["reglas", "estilo", "comandos", "arquitectura", "flujo", "restricciones", "otro"])
        c.add_argument("--orden", type=int)
        c.add_argument("--proyecto")
        c.add_argument("--agente")
        c.add_argument("--desactivar", action="store_true")

    i = sub.add_parser("importar")
    i.add_argument("origen")
    i.add_argument("--proyecto")

    m = sub.add_parser("materializar")
    m.add_argument("--agente")
    m.add_argument("--proyecto")
    m.add_argument("--destino", help="carpeta (default: una temporal nueva)")
    grupo = m.add_mutually_exclusive_group()
    grupo.add_argument("--subagentes", dest="subagentes", action="store_true", default=None)
    grupo.add_argument("--sin-subagentes", dest="subagentes", action="store_false")
    m.add_argument("--forzar", action="store_true")
    sub.add_parser("sincronizar").add_argument("destino")

    h = sub.add_parser("historial")
    h.add_argument("entidad", choices=["agente", "skill", "contexto"])
    h.add_argument("ref")
    v = sub.add_parser("version")
    v.add_argument("entidad", choices=["agente", "skill", "contexto"])
    v.add_argument("ref")
    v.add_argument("numero", type=int)
    rs = sub.add_parser("restaurar")
    rs.add_argument("entidad", choices=["agente", "skill", "contexto"])
    rs.add_argument("ref")
    rs.add_argument("numero", type=int)

    se = sub.add_parser("sesion").add_subparsers(dest="accion", required=True)
    g = se.add_parser("guardar")
    fuente = g.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--transcript")
    fuente.add_argument("--session-id")
    g.add_argument("--proyecto")
    g.add_argument("--agente", default=os.environ.get("MEMORIA_AGENTE"))
    g.add_argument("--con-mensajes", action="store_true")
    g.add_argument("--sin-compact", action="store_true", help="guardar aunque no haya /compact nuevo")
    l = se.add_parser("listar")
    l.add_argument("--proyecto")
    l.add_argument("--limite", type=int, default=20)
    u = se.add_parser("ultima")
    u.add_argument("--proyecto")
    u.add_argument("--agente")
    se.add_parser("buscar").add_argument("texto")

    me = sub.add_parser("memorias").add_subparsers(dest="accion", required=True)
    a = me.add_parser("agregar")
    a.add_argument("tipo", choices=memorias.TIPOS)
    a.add_argument("titulo")
    a.add_argument("contenido")
    a.add_argument("--alcance", choices=memorias.ALCANCES)
    a.add_argument("--proyecto")
    a.add_argument("--agente")
    a.add_argument("--sesion")
    a.add_argument("--importancia", type=int, default=3, choices=range(1, 6))
    a.add_argument("--etiquetas", help="coma separadas")
    a.add_argument("--reemplaza", type=int)
    l = me.add_parser("listar")
    l.add_argument("--proyecto")
    l.add_argument("--agente")
    l.add_argument("--tipo", choices=memorias.TIPOS)
    l.add_argument("--etiqueta")
    me.add_parser("buscar").add_argument("texto")
    o = me.add_parser("olvidar")
    o.add_argument("id", type=int)
    o.add_argument("--motivo")

    de = sub.add_parser("delegacion").add_subparsers(dest="accion", required=True)
    c = de.add_parser("crear")
    c.add_argument("destino")
    c.add_argument("objetivo")
    c.add_argument("--origen")
    c.add_argument("--sesion")
    c.add_argument("--motivo")
    c.add_argument("--confianza", type=float)
    c = de.add_parser("cerrar")
    c.add_argument("id", type=int)
    c.add_argument("--estado", default="completada", choices=["en_curso", "completada", "fallida", "cancelada"])
    c.add_argument("--resultado")

    vz = sub.add_parser("voz", help="perfil de voz por agente (vozkit)").add_subparsers(dest="accion", required=True)
    g = vz.add_parser("guardar")
    g.add_argument("nombre")
    g.add_argument("perfil", help="JSON con los parámetros (ver vozkit/voces.py)")
    vz.add_parser("ver").add_argument("nombre")
    vz.add_parser("listar")

    sub.add_parser("hook").add_argument("evento", choices=["session-end"])
    ih = sub.add_parser("instalar-hook")
    ih.add_argument("--settings", default="~/.claude/settings.json",
                    help="settings.json de Claude Code (usuario o .claude/settings.local.json de un proyecto)")
    ih.add_argument("--env", help="ruta al .env de memoria para que el hook encuentre la base")

    au = sub.add_parser("auditoria")
    au.add_argument("--tabla")
    au.add_argument("--limite", type=int, default=50)
    return p


def ejecutar(args, db):
    c, acc = args.cmd, getattr(args, "accion", None)
    if c == "migrar":
        return {"aplicadas": esquema.migrar(db)}
    if c == "proyecto":
        if acc == "alta":
            return {"id": proyectos.alta(db, args.nombre, args.ruta, args.descripcion, args.repo)}
        if acc == "listar":
            return proyectos.listar(db)
        return proyectos.escanear(db, args.nombre)
    if c == "agente":
        if acc == "listar":
            return catalogo.listar_agentes(db, args.todos)
        if acc == "ver":
            return catalogo.obtener_agente(db, args.nombre)
        if acc == "seccion":
            return catalogo.editar_seccion(db, args.nombre, args.titulo, _texto(args), args.tipo, args.orden,
                                           False if args.desactivar else None, nota=args.nota)
        if args.archivo:
            datos, secciones, skills, mcps = formato.parse_agente(Path(args.archivo).read_text(encoding="utf-8"))
            nombre = args.nombre or datos.pop("nombre") or Path(args.archivo).stem
            datos.pop("nombre", None)
        else:
            if not args.nombre:
                raise SystemExit("agente guardar: indicá NOMBRE o --archivo")
            nombre, secciones, mcps = args.nombre, None, None
            datos, skills = {}, _lista(args.skills)
        for campo, valor in (("descripcion", args.descripcion), ("modelo", args.modelo),
                             ("herramientas", _lista(args.herramientas))):
            if valor is not None:
                datos[campo] = valor
        if args.skills is not None:
            skills = _lista(args.skills) or []
        if args.general:
            datos["es_general"] = True
        return catalogo.guardar_agente(db, nombre, datos, secciones, skills, mcps, nota=args.nota)
    if c == "skill":
        if acc == "listar":
            return catalogo.listar_skills(db)
        if acc == "ver":
            return catalogo.obtener_skill(db, args.nombre)
        carpeta = Path(args.carpeta)
        s = formato.parse_skill((carpeta / "SKILL.md").read_text(encoding="utf-8"))
        archivos = {str(f.relative_to(carpeta)): f.read_text(encoding="utf-8") for f in sorted(carpeta.rglob("*"))
                    if f.is_file() and f.name != "SKILL.md"}
        return catalogo.guardar_skill(db, s["nombre"] or carpeta.name, s["descripcion"], s["instrucciones"],
                                      s["herramientas"], archivos=archivos, nota=args.nota)
    if c == "contexto":
        if acc == "listar":
            return catalogo.secciones_contexto(db, args.proyecto, args.agente)
        alcance = "agente" if args.agente else "proyecto" if args.proyecto else "global"
        return catalogo.guardar_contexto(db, args.titulo, _texto(args), alcance, args.proyecto, args.agente,
                                         args.tipo, args.orden, not args.desactivar,
                                         id=getattr(args, "id", None))
    if c == "importar":
        return materializar.importar(db, args.origen, args.proyecto)
    if c == "materializar":
        return materializar.materializar(db, args.destino, args.agente, args.proyecto, args.subagentes, args.forzar)
    if c == "sincronizar":
        return materializar.sincronizar(db, args.destino)
    if c == "historial":
        return catalogo.historial(db, args.entidad, args.ref)
    if c == "version":
        return catalogo.ver_version(db, args.entidad, args.ref, args.numero)
    if c == "restaurar":
        return catalogo.restaurar(db, args.entidad, args.ref, args.numero)
    if c == "sesion":
        if acc == "guardar":
            ruta = args.transcript or localizar_transcript(args.session_id)
            return sesiones.guardar(db, ruta, "manual", args.proyecto, args.agente, args.con_mensajes,
                                    exigir_compact=not args.sin_compact)
        if acc == "listar":
            return sesiones.listar(db, args.proyecto, args.limite)
        if acc == "ultima":
            return sesiones.ultimo_resumen(db, args.proyecto, args.agente)
        return sesiones.buscar_resumenes(db, args.texto)
    if c == "memorias":
        if acc == "agregar":
            return {"id": memorias.agregar(db, args.tipo, args.titulo, args.contenido, args.alcance, args.proyecto,
                                           args.agente, args.sesion, args.importancia,
                                           _lista(args.etiquetas) or (), reemplaza=args.reemplaza)}
        if acc == "listar":
            return memorias.listar(db, args.proyecto, args.agente, args.tipo, args.etiqueta)
        if acc == "buscar":
            return memorias.buscar(db, args.texto)
        return {"olvidada": memorias.olvidar(db, args.id, args.motivo)}
    if c == "delegacion":
        if acc == "crear":
            return {"id": memorias.delegar(db, args.destino, args.objetivo, args.origen, args.sesion, args.motivo,
                                           args.confianza)}
        memorias.cerrar_delegacion(db, args.id, args.estado, args.resultado)
        return {"id": args.id, "estado": args.estado}
    if c == "voz":
        if acc == "guardar":
            return voces.guardar(db, args.nombre, json.loads(args.perfil))
        if acc == "ver":
            return voces.ver(db, args.nombre)
        return voces.listar(db)
    if c == "auditoria":
        return db.todos("SELECT * FROM auditoria WHERE (%s IS NULL OR tabla=%s) ORDER BY id DESC LIMIT %s",
                        (args.tabla, args.tabla, args.limite))
    raise SystemExit(f"comando no soportado: {c}")


def main(argv=None):
    args = crear_parser().parse_args(argv)
    if args.cmd == "hook":
        return hook.main(args.evento, DB)
    if args.cmd == "instalar-hook":
        env = f"MEMORIA_ENV={shlex.quote(str(Path(args.env).resolve()))} " if args.env else ""
        salida(hook.instalar(args.settings, f"{env}{shlex.quote(sys.executable)} -m memoria hook session-end"))
        return 0
    if args.cmd == "roles":
        cfg = Config.desde_entorno()
        admin = Config(**{**cfg.__dict__, "usuario": args.admin, "clave": args.admin_clave})
        with DB(admin) as db:
            esquema.crear_roles(db, cfg.base, args.clave_agente, args.clave_lector)
        salida({"roles": ["memoria_app", "memoria_agente", "memoria_lector"]})
        return 0
    try:
        with DB() as db:
            salida(ejecutar(args, db))
        return 0
    except (LookupError, ValueError, FileExistsError, FileNotFoundError) as e:
        salida({"error": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
