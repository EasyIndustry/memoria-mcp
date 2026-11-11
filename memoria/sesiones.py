"""Conversaciones de Claude Code -> base: resúmenes de /compact y, opcionalmente, mensajes.

Formato del transcript (~/.claude/projects/<carpeta>/<sessionId>.jsonl), una entrada JSON por línea.
Tras un /compact aparecen:
  {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger", "preTokens", "postTokens"}}
  {"type": "user", "isCompactSummary": true, "message": {"content": "<resumen>"}, "uuid": ...}

Flujo "guardar esta conversación": /compact -> /clear. El hook de SessionEnd (motivo "clear")
guarda los resúmenes que todavía no estén en la base; si no hubo /compact nuevo, no guarda nada.
"""
import json
from pathlib import Path

from .proyectos import por_ruta
from .redaccion import redactar

def leer_transcript(ruta):
    entradas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                try:
                    entradas.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue  # línea a medio escribir
    return entradas


def _texto(contenido):
    if isinstance(contenido, str):
        return contenido
    return "\n".join(b.get("text", "") for b in contenido or [] if isinstance(b, dict) and b.get("type") == "text")


def analizar(entradas):
    """Metadatos de la sesión, resúmenes de compact y mensajes (previos al último compact)."""
    meta = {"session_uuid": None, "cwd": None, "rama_git": None, "version_cli": None,
            "iniciada": None, "terminada": None, "titulo": None}
    resumenes, mensajes, frontera = [], [], None
    for e in entradas:
        for k_json, k in (("sessionId", "session_uuid"), ("cwd", "cwd"), ("gitBranch", "rama_git"),
                          ("version", "version_cli")):
            if e.get(k_json) and not meta[k]:
                meta[k] = e[k_json]
        if e.get("timestamp"):
            meta["iniciada"] = meta["iniciada"] or e["timestamp"]
            meta["terminada"] = e["timestamp"]
        if e.get("type") == "ai-title" and e.get("aiTitle"):
            meta["titulo"] = e["aiTitle"]
        if e.get("type") == "summary" and e.get("summary") and not meta["titulo"]:
            meta["titulo"] = e["summary"]
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            frontera = e.get("compactMetadata") or {}
            continue
        if e.get("type") == "user" and e.get("isCompactSummary"):
            f = frontera or {}
            resumenes.append({"mensaje_uuid": e["uuid"], "contenido": _texto(e["message"]["content"]),
                              "disparador": f.get("trigger"), "tokens_antes": f.get("preTokens"),
                              "tokens_despues": f.get("postTokens"), "compactado": e.get("timestamp")})
            frontera = None
            continue
        if e.get("type") in ("user", "assistant") and not e.get("isMeta") and isinstance(e.get("message"), dict):
            mensajes.append(e)
    return meta, resumenes, mensajes


def _fecha(iso):
    return iso.replace("T", " ").rstrip("Z")[:23] if iso else None


def _bloques(mensaje, max_chars):
    contenido = mensaje["message"].get("content")
    if isinstance(contenido, str):
        contenido = [{"type": "text", "text": contenido}]
    salida = []
    for b in contenido or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            salida.append(("texto", None, None, b.get("text", "")))
        elif t == "tool_use":
            salida.append(("tool_use", b.get("name"), b.get("id"), json.dumps(b.get("input"), ensure_ascii=False)))
        elif t == "tool_result":
            c = b.get("content")
            texto = c if isinstance(c, str) else _texto(c) if isinstance(c, list) else json.dumps(c, ensure_ascii=False)
            salida.append(("tool_result", None, b.get("tool_use_id"), texto or ""))
        # thinking e imágenes no se guardan
    resultado = []
    for tipo, herramienta, tool_id, texto in salida:
        texto, n = redactar(texto)
        recortado = len(texto) > max_chars
        resultado.append((tipo, herramienta, tool_id, texto[:max_chars], recortado, n))
    return resultado


def guardar(db, transcript, motivo="manual", proyecto=None, agente=None, con_mensajes=False,
            exigir_compact=True):
    """Guarda la sesión del transcript. Devuelve un resumen de lo guardado.

    exigir_compact: si no hay ningún resumen de /compact nuevo, no guarda nada (el /clear
    sin /compact previo se toma como "descartar la conversación").
    """
    entradas = leer_transcript(transcript)
    meta, resumenes, mensajes = analizar(entradas)
    if not meta["session_uuid"]:
        meta["session_uuid"] = Path(transcript).stem
    with db.transaccion():
        ya = {f["mensaje_uuid"] for f in db.todos(
            "SELECT r.mensaje_uuid FROM resumenes r JOIN sesiones s ON s.id=r.sesion_id WHERE s.session_uuid=%s",
            (meta["session_uuid"],))}
        nuevos = [r for r in resumenes if r["mensaje_uuid"] not in ya]
        if exigir_compact and not nuevos:
            return {"guardado": False, "motivo": "sin /compact nuevo", "session_uuid": meta["session_uuid"]}

        proyecto_id = db.id_de("proyectos", proyecto) if proyecto else (por_ruta(db, meta["cwd"]) or {}).get("id")
        agente_id = db.id_de("agentes", agente, obligatorio=False) if agente else None
        fila = db.uno("SELECT id FROM sesiones WHERE session_uuid=%s", (meta["session_uuid"],))
        valores = (proyecto_id, agente_id, meta["titulo"], meta["cwd"], meta["rama_git"], meta["version_cli"],
                   _fecha(meta["iniciada"]), _fecha(meta["terminada"]), motivo, str(transcript))
        if fila:
            sesion_id = fila["id"]
            db.ejecutar("UPDATE sesiones SET proyecto_id=COALESCE(%s, proyecto_id), agente_id=COALESCE(%s, agente_id), "
                        "titulo=COALESCE(%s, titulo), cwd=%s, rama_git=%s, version_cli=%s, iniciada=COALESCE(iniciada, %s), "
                        "terminada=%s, motivo_fin=%s, transcript=%s WHERE id=%s", (*valores, sesion_id))
        else:
            sesion_id = db.ejecutar("INSERT INTO sesiones (proyecto_id, agente_id, titulo, cwd, rama_git, version_cli, "
                                    "iniciada, terminada, motivo_fin, transcript, session_uuid) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*valores, meta["session_uuid"]))

        for r in nuevos:
            contenido, n = redactar(r["contenido"])
            db.ejecutar("INSERT INTO resumenes (sesion_id, mensaje_uuid, disparador, tokens_antes, tokens_despues, "
                        "contenido, redacciones, compactado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (sesion_id, r["mensaje_uuid"], r["disparador"], r["tokens_antes"], r["tokens_despues"],
                         contenido, n, _fecha(r["compactado"])))

        n_mensajes = 0
        if con_mensajes:
            existentes = {f["uuid"] for f in db.todos("SELECT uuid FROM mensajes WHERE sesion_id=%s", (sesion_id,))}
            orden = db.valor("SELECT COALESCE(MAX(orden), 0) FROM mensajes WHERE sesion_id=%s", (sesion_id,)) or 0
            for m in mensajes:
                if m["uuid"] in existentes:
                    continue
                bloques = _bloques(m, db.config.max_bloque)
                if not bloques:
                    continue
                orden += 1
                mid = db.ejecutar("INSERT INTO mensajes (sesion_id, uuid, padre_uuid, rol, orden, modelo, lateral, creado) "
                                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                  (sesion_id, m["uuid"], m.get("parentUuid"), m["message"].get("role", m["type"]),
                                   orden, m["message"].get("model"), bool(m.get("isSidechain")),
                                   _fecha(m.get("timestamp"))))
                for i, (tipo, herr, tool_id, texto, recortado, n) in enumerate(bloques):
                    db.ejecutar("INSERT INTO bloques (mensaje_id, orden, tipo, herramienta, tool_use_id, contenido, "
                                "recortado, redacciones) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (mid, i, tipo, herr, tool_id, texto, recortado, n))
                n_mensajes += 1
        db.auditar("sesiones", sesion_id, "guardar_sesion", motivo=motivo, resumenes=len(nuevos),
                   mensajes=n_mensajes, transcript=str(transcript))
    return {"guardado": True, "session_uuid": meta["session_uuid"], "sesion_id": sesion_id,
            "resumenes": len(nuevos), "mensajes": n_mensajes, "proyecto_id": proyecto_id, "agente_id": agente_id}


def listar(db, proyecto=None, limite=20):
    return db.todos("SELECT s.id, s.session_uuid, s.titulo, p.nombre AS proyecto, a.nombre AS agente, "
                    "s.terminada, (SELECT COUNT(*) FROM resumenes r WHERE r.sesion_id=s.id) AS resumenes "
                    "FROM sesiones s LEFT JOIN proyectos p ON p.id=s.proyecto_id LEFT JOIN agentes a ON a.id=s.agente_id "
                    "WHERE (%s IS NULL OR p.nombre=%s) ORDER BY s.terminada DESC LIMIT %s", (proyecto, proyecto, limite))


def ultimo_resumen(db, proyecto=None, agente=None):
    """El resumen más reciente, para retomar un objetivo en una sesión nueva."""
    return db.uno("SELECT * FROM v_resumenes WHERE (%s IS NULL OR proyecto=%s) AND (%s IS NULL OR agente=%s) "
                  "ORDER BY compactado DESC LIMIT 1", (proyecto, proyecto, agente, agente))


def buscar_resumenes(db, texto, limite=10):
    return db.todos("SELECT r.id, s.session_uuid, s.titulo, r.compactado, "
                    "MATCH(r.contenido) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevancia, "
                    "LEFT(r.contenido, 400) AS extracto FROM resumenes r JOIN sesiones s ON s.id=r.sesion_id "
                    "WHERE MATCH(r.contenido) AGAINST (%s IN NATURAL LANGUAGE MODE) "
                    "ORDER BY relevancia DESC LIMIT %s", (texto, texto, limite))
