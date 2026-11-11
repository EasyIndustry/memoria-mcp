"""Memoria granular (hechos, preferencias, decisiones, ...) y registro de delegaciones."""
TIPOS = ("hecho", "preferencia", "decision", "procedimiento", "pendiente", "referencia")
ALCANCES = ("global", "proyecto", "agente", "sesion")


def _etiquetar(db, memoria_id, etiquetas):
    db.ejecutar("DELETE FROM memoria_etiqueta WHERE memoria_id=%s", (memoria_id,))
    for nombre in sorted({e.strip().lower() for e in etiquetas if e.strip()}):
        db.ejecutar("INSERT IGNORE INTO etiquetas (nombre) VALUES (%s)", (nombre,))
        db.ejecutar("INSERT INTO memoria_etiqueta (memoria_id, etiqueta_id) "
                    "SELECT %s, id FROM etiquetas WHERE nombre=%s", (memoria_id, nombre))


def agregar(db, tipo, titulo, contenido, alcance=None, proyecto=None, agente=None, sesion=None,
            importancia=3, etiquetas=(), valida_hasta=None, reemplaza=None):
    """Guarda una memoria. `reemplaza` = id de una memoria que esta corrige (queda no vigente)."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido {tipo!r}; opciones: {', '.join(TIPOS)}")
    proyecto_id = db.id_de("proyectos", proyecto)
    agente_id = db.id_de("agentes", agente)
    sesion_id = (db.valor("SELECT id FROM sesiones WHERE session_uuid=%s", (sesion,))
                 if isinstance(sesion, str) else sesion)
    alcance = alcance or ("agente" if agente_id else "proyecto" if proyecto_id else "global")
    with db.transaccion():
        mid = db.ejecutar("INSERT INTO memorias (tipo, alcance, proyecto_id, agente_id, sesion_origen_id, titulo, "
                          "contenido, importancia, valida_hasta, reemplaza_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                          (tipo, alcance, proyecto_id, agente_id, sesion_id, titulo, contenido, importancia,
                           valida_hasta, reemplaza))
        if reemplaza:
            db.ejecutar("UPDATE memorias SET vigente=FALSE WHERE id=%s", (reemplaza,))
        _etiquetar(db, mid, etiquetas)
        db.auditar("memorias", mid, "crear", tipo=tipo, alcance=alcance, reemplaza=reemplaza)
    return mid


def olvidar(db, memoria_id, motivo=None):
    """Marca la memoria como no vigente (no se borra: queda para auditoría)."""
    with db.transaccion():
        n = db.ejecutar("UPDATE memorias SET vigente=FALSE WHERE id=%s AND vigente", (memoria_id,))
        db.auditar("memorias", memoria_id, "olvidar", motivo=motivo)
    return bool(n)


def listar(db, proyecto=None, agente=None, tipo=None, etiqueta=None, limite=50):
    """Memorias vigentes que aplican: globales + del proyecto + del agente."""
    return db.todos(
        "SELECT * FROM v_memorias_vigentes WHERE "
        "(alcance='global' OR (alcance='proyecto' AND proyecto <=> %s) OR (alcance='agente' AND agente <=> %s)) "
        "AND (%s IS NULL OR tipo=%s) AND (%s IS NULL OR FIND_IN_SET(%s, etiquetas)) "
        "ORDER BY importancia DESC, actualizado DESC LIMIT %s",
        (proyecto, agente, tipo, tipo, etiqueta, etiqueta, limite))


def buscar(db, texto, limite=20):
    """Búsqueda de texto completo; con palabras cortas (< 3 letras) cae a LIKE."""
    filas = db.todos("SELECT v.*, MATCH(m.titulo, m.contenido) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevancia "
                     "FROM memorias m JOIN v_memorias_vigentes v ON v.id=m.id "
                     "WHERE MATCH(m.titulo, m.contenido) AGAINST (%s IN NATURAL LANGUAGE MODE) "
                     "ORDER BY relevancia DESC LIMIT %s", (texto, texto, limite))
    if filas:
        return filas
    patron = f"%{texto}%"
    return db.todos("SELECT * FROM v_memorias_vigentes WHERE titulo LIKE %s OR contenido LIKE %s "
                    "ORDER BY importancia DESC LIMIT %s", (patron, patron, limite))


# ───────── delegaciones ─────────

def delegar(db, destino, objetivo, origen=None, sesion=None, motivo=None, confianza=None):
    with db.transaccion():
        sesion_id = (db.valor("SELECT id FROM sesiones WHERE session_uuid=%s", (sesion,))
                     if isinstance(sesion, str) else sesion)
        did = db.ejecutar("INSERT INTO delegaciones (sesion_id, agente_origen_id, agente_destino_id, objetivo, motivo, "
                          "confianza) VALUES (%s,%s,%s,%s,%s,%s)",
                          (sesion_id, db.id_de("agentes", origen), db.id_de("agentes", destino), objetivo, motivo,
                           confianza))
        db.auditar("delegaciones", did, "crear", destino=destino)
    return did


def cerrar_delegacion(db, delegacion_id, estado="completada", resultado=None):
    with db.transaccion():
        db.ejecutar("UPDATE delegaciones SET estado=%s, resultado=%s, "
                    "terminado=IF(%s IN ('completada','fallida','cancelada'), CURRENT_TIMESTAMP(3), NULL) WHERE id=%s",
                    (estado, resultado, estado, delegacion_id))
        db.auditar("delegaciones", delegacion_id, "estado", estado=estado)
