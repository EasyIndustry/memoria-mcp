"""Perfil de voz por agente (lo sortea orquestador/voces_agentes.py; lo usa vozkit POST /decir)."""
from .db import a_json, de_json


def guardar(db, nombre, perfil):
    with db.transaccion():
        db.ejecutar("INSERT INTO voces_agente (nombre, perfil) VALUES (%s,%s) "
                    "ON DUPLICATE KEY UPDATE perfil=VALUES(perfil)", (nombre, a_json(perfil)))
        db.auditar("voces_agente", None, "guardar", nombre=nombre, perfil=perfil)
    return ver(db, nombre)


def ver(db, nombre):
    fila = db.uno("SELECT nombre, perfil, creado FROM voces_agente WHERE nombre=%s", (nombre,))
    if fila:
        fila["perfil"] = de_json(fila["perfil"])
    return fila


def listar(db):
    filas = db.todos("SELECT nombre, perfil, creado FROM voces_agente ORDER BY creado")
    for f in filas:
        f["perfil"] = de_json(f["perfil"])
    return filas
