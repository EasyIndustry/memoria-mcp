"""Ida y vuelta entre filas de la base y los archivos que lee Claude Code.

  agente   -> .claude/agents/<nombre>.md     frontmatter + secciones
  skill    -> .claude/skills/<nombre>/SKILL.md (+ archivos de apoyo)
  contexto -> CLAUDE.md                        secciones global, proyecto y agente

Cada sección lleva un marcador HTML invisible para poder reconstruirla al sincronizar:
  <!-- seccion: rol -->          (agentes)
  <!-- contexto: 12 -->          (CLAUDE.md, id de contexto_secciones)
Dentro de una sección, un "## " sin marcador se toma como sección nueva: para subtítulos, "###".
"""
import re

import yaml

MARCA_AGENTE = re.compile(r"^<!-- seccion: (\w+) -->\n## (.+?)\n", re.M)
MARCA_CONTEXTO = re.compile(r"^<!-- contexto: (\d+|nuevo) -->\n## (.+?)\n", re.M)
CABECERA = re.compile(r"^<!-- memoria:.*?-->\n*", re.M)
TIPOS_SECCION = {"rol", "forma_de_trabajo", "restricciones", "formato_salida", "contexto",
                 "ejemplos", "herramientas", "otro"}
# títulos habituales -> tipo, para importar archivos escritos a mano (sin marcadores)
TITULOS = {"rol": "rol", "role": "rol", "forma de trabajo": "forma_de_trabajo", "workflow": "forma_de_trabajo",
           "cómo trabajar": "forma_de_trabajo", "como trabajar": "forma_de_trabajo",
           "restricciones": "restricciones", "constraints": "restricciones", "reglas": "restricciones",
           "formato de salida": "formato_salida", "output format": "formato_salida", "salida": "formato_salida",
           "contexto": "contexto", "context": "contexto", "ejemplos": "ejemplos", "examples": "ejemplos",
           "herramientas": "herramientas", "tools": "herramientas"}


def _lista(valor):
    if valor in (None, "", []):
        return None
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return list(valor)


def separar_frontmatter(texto):
    if texto.startswith("---\n"):
        fin = texto.find("\n---", 4)
        if fin != -1:
            meta = yaml.safe_load(texto[4:fin]) or {}
            cuerpo = texto[fin + 4:].lstrip("\n")
            return meta, cuerpo
    return {}, texto


def _frontmatter(meta):
    limpio = {k: v for k, v in meta.items() if v not in (None, "", [])}
    return "---\n" + yaml.safe_dump(limpio, allow_unicode=True, sort_keys=False, width=1000) + "---\n"


def _cabecera(entidad, nombre, version):
    return (f"<!-- memoria: {entidad}={nombre} version={version} · generado desde la base; "
            f"las ediciones se guardan con `memoria sincronizar` -->\n\n")


# ───────── agentes ─────────

def render_agente(agente, secciones, skills=(), mcps=()):
    meta = {"name": agente["nombre"], "description": agente["descripcion"], "model": agente.get("modelo"),
            "color": agente.get("color"),
            "tools": ", ".join(agente.get("herramientas") or []) or None,
            "disallowedTools": ", ".join(agente.get("herramientas_negadas") or []) or None,
            "permissionMode": agente.get("modo_permisos"),
            "skills": ", ".join(skills) or None,
            "mcpServers": list(mcps) or None}
    partes = [_frontmatter(meta), _cabecera("agente", agente["nombre"], agente.get("version", 1))]
    for s in secciones:
        if s.get("activo", True):
            partes.append(f"<!-- seccion: {s['tipo']} -->\n## {s['titulo']}\n\n{s['contenido'].strip()}\n\n")
    return "".join(partes).rstrip() + "\n"


def _secciones_por_titulo(cuerpo):
    """Archivos sin marcadores: parte en '## Título'; lo previo al primer título es 'General'."""
    trozos = re.split(r"^## (.+?)\n", cuerpo, flags=re.M)
    secciones = []
    if trozos[0].strip():
        secciones.append({"tipo": "rol", "titulo": "General", "contenido": trozos[0].strip()})
    for titulo, contenido in zip(trozos[1::2], trozos[2::2]):
        tipo = TITULOS.get(titulo.strip().lower(), "otro")
        secciones.append({"tipo": tipo, "titulo": titulo.strip(), "contenido": contenido.strip()})
    return secciones


def parse_agente(texto):
    """Devuelve (datos_agente, secciones, skills, mcps)."""
    meta, cuerpo = separar_frontmatter(texto)
    cuerpo = CABECERA.sub("", cuerpo)
    if MARCA_AGENTE.search(cuerpo):
        trozos = MARCA_AGENTE.split(cuerpo)
        secciones = _secciones_por_titulo(trozos[0]) if trozos[0].strip() else []
        for tipo, titulo, contenido in zip(trozos[1::3], trozos[2::3], trozos[3::3]):
            # un '## ' sin marcador dentro de una sección es una sección nueva (usar ### para subtítulos)
            sub = re.split(r"^## (.+?)\n", contenido, flags=re.M)
            secciones.append({"tipo": tipo if tipo in TIPOS_SECCION else "otro", "titulo": titulo.strip(),
                              "contenido": sub[0].strip()})
            for t, c in zip(sub[1::2], sub[2::2]):
                secciones.append({"tipo": TITULOS.get(t.strip().lower(), "otro"), "titulo": t.strip(),
                                  "contenido": c.strip()})
    else:
        secciones = _secciones_por_titulo(cuerpo)
    for i, s in enumerate(secciones):
        s["orden"] = (i + 1) * 10
    datos = {"nombre": meta.get("name"), "descripcion": meta.get("description") or "",
             "modelo": meta.get("model"), "color": meta.get("color"),
             "herramientas": _lista(meta.get("tools")), "herramientas_negadas": _lista(meta.get("disallowedTools")),
             "modo_permisos": meta.get("permissionMode")}
    return datos, secciones, _lista(meta.get("skills")) or [], _lista(meta.get("mcpServers")) or []


# ───────── skills ─────────

def render_skill(skill):
    meta = {"name": skill["nombre"], "description": skill["descripcion"],
            "allowed-tools": ", ".join(skill.get("herramientas") or []) or None}
    return (_frontmatter(meta) + _cabecera("skill", skill["nombre"], skill.get("version", 1))
            + skill["instrucciones"].strip() + "\n")


def parse_skill(texto):
    meta, cuerpo = separar_frontmatter(texto)
    return {"nombre": meta.get("name"), "descripcion": meta.get("description") or "",
            "instrucciones": CABECERA.sub("", cuerpo).strip(), "herramientas": _lista(meta.get("allowed-tools"))}


# ───────── CLAUDE.md ─────────

def render_contexto(secciones, titulo="CLAUDE.md"):
    partes = [f"<!-- memoria: contexto={titulo} · generado desde la base; "
              f"las ediciones se guardan con `memoria sincronizar` -->\n\n"]
    for s in secciones:
        partes.append(f"<!-- contexto: {s['id']} -->\n## {s['titulo']}\n\n{s['contenido'].strip()}\n\n")
    return "".join(partes).rstrip() + "\n"


def parse_contexto(texto):
    """Devuelve [{id|None, titulo, contenido}]. Secciones '## ' sin marcador -> id None (nuevas)."""
    cuerpo = CABECERA.sub("", texto)
    if not MARCA_CONTEXTO.search(cuerpo):
        return [{"id": None, **s} for s in _secciones_por_titulo(cuerpo)]
    trozos = MARCA_CONTEXTO.split(cuerpo)
    resultado = []
    if trozos[0].strip():
        resultado += [{"id": None, **s} for s in _secciones_por_titulo(trozos[0])]
    for id_, titulo, contenido in zip(trozos[1::3], trozos[2::3], trozos[3::3]):
        # dentro de una sección marcada, un '## ' nuevo sin marcador es una sección nueva
        sub = re.split(r"^## (.+?)\n", contenido, flags=re.M)
        resultado.append({"id": None if id_ == "nuevo" else int(id_), "titulo": titulo.strip(),
                          "contenido": sub[0].strip()})
        for t, c in zip(sub[1::2], sub[2::2]):
            resultado.append({"id": None, "titulo": t.strip(), "contenido": c.strip()})
    return resultado
