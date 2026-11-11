"""Migraciones (sql/NNN_*.sql) y roles."""
import re
from pathlib import Path

SQL = Path(__file__).parent / "sql"


def sentencias(texto):
    """Parte un archivo SQL simple (sin DELIMITER) en sentencias."""
    sin_comentarios = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", sin_comentarios) if s.strip()]


def pendientes(db):
    try:
        hechas = {f["version"] for f in db.todos("SELECT version FROM schema_migraciones")}
    except Exception:  # tabla inexistente: base vacía
        db.cx.rollback()
        hechas = set()
    return [p for p in sorted(SQL.glob("[0-9][0-9][0-9]_*.sql")) if p.stem not in hechas]


def migrar(db):
    """Aplica las migraciones pendientes. Devuelve las aplicadas."""
    aplicadas = []
    for p in pendientes(db):
        for s in sentencias(p.read_text(encoding="utf-8")):
            db.ejecutar(s)
        db.ejecutar("INSERT IGNORE INTO schema_migraciones (version) VALUES (%s)", (p.stem,))
        db.cx.commit()
        aplicadas.append(p.stem)
    return aplicadas


def sql_roles(base, clave_agente, clave_lector):
    texto = (SQL / "roles.sql").read_text(encoding="utf-8")
    return texto.replace("{{DB}}", base).replace("{{AGENTE_PASS}}", clave_agente).replace("{{LECTOR_PASS}}", clave_lector)


def crear_roles(db_root, base, clave_agente, clave_lector):
    for s in sentencias(sql_roles(base, clave_agente, clave_lector)):
        db_root.ejecutar(s)
    db_root.cx.commit()
