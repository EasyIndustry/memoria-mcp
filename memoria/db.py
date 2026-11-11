"""Conexión a MariaDB, transacciones y auditoría."""
import json
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from .config import Config


def a_json(valor):
    return None if valor is None else json.dumps(valor, ensure_ascii=False, default=str)


def de_json(valor):
    if valor is None or isinstance(valor, (list, dict)):
        return valor
    return json.loads(valor)


class DB:
    """Envoltorio fino sobre PyMySQL. Todas las escrituras van dentro de `transaccion()`."""

    def __init__(self, config=None, conexion=None):
        self.config = config or Config.desde_entorno()
        self.cx = conexion or pymysql.connect(
            host=self.config.host, port=self.config.puerto, user=self.config.usuario,
            password=self.config.clave, database=self.config.base, charset="utf8mb4",
            unix_socket=self.config.socket or None,
            cursorclass=DictCursor, autocommit=False)
        self._profundidad = 0

    @property
    def actor(self):
        return self.config.actor

    def cerrar(self):
        self.cx.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()

    @contextmanager
    def transaccion(self):
        """Anidable: solo la más externa hace commit/rollback."""
        self._profundidad += 1
        try:
            yield self
            if self._profundidad == 1:
                self.cx.commit()
        except Exception:
            if self._profundidad == 1:
                self.cx.rollback()
            raise
        finally:
            self._profundidad -= 1

    def ejecutar(self, sql, args=None):
        """Devuelve lastrowid (INSERT) o filas afectadas si no hay id."""
        with self.cx.cursor() as c:
            n = c.execute(sql, args)
            return c.lastrowid or n

    def todos(self, sql, args=None):
        with self.cx.cursor() as c:
            c.execute(sql, args)
            return list(c.fetchall())

    def uno(self, sql, args=None):
        with self.cx.cursor() as c:
            c.execute(sql, args)
            return c.fetchone()

    def valor(self, sql, args=None):
        fila = self.uno(sql, args)
        return next(iter(fila.values())) if fila else None

    def auditar(self, tabla, registro_id, accion, **detalle):
        self.ejecutar("INSERT INTO auditoria (tabla, registro_id, accion, actor, detalle) VALUES (%s,%s,%s,%s,%s)",
                      (tabla, registro_id, accion, self.actor, a_json(detalle) if detalle else None))

    # --- búsquedas por nombre usadas en todos los módulos ---
    def id_de(self, tabla, nombre, obligatorio=True):
        if nombre is None:
            return None
        if isinstance(nombre, int):
            return nombre
        fila = self.uno(f"SELECT id FROM {tabla} WHERE nombre=%s", (nombre,))
        if fila is None and obligatorio:
            raise LookupError(f"no existe en {tabla}: {nombre!r}")
        return fila and fila["id"]
