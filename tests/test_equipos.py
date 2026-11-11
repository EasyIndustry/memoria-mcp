"""Equipos de agentes: roles, miembros, uid estable, MCPs base / a pedido y despertar.

Misma base temporal que test_memoria (MEMORIA_TEST_* para apuntar al servidor).
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymysql  # noqa: E402

from memoria import catalogo, esquema, memorias, proyectos  # noqa: E402
from memoria.db import DB  # noqa: E402
from test_memoria import config_test  # noqa: E402

BASE = f"memoria_test_equipos_{os.getpid()}"


def setUpModule():
    try:
        cx = DB(config_test())
    except pymysql.err.OperationalError as e:
        raise unittest.SkipTest(f"sin MariaDB: {e}")
    cx.ejecutar(f"CREATE DATABASE {BASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cx.cerrar()
    with DB(config_test(BASE)) as db:
        esquema.migrar(db)


def tearDownModule():
    try:
        with DB(config_test()) as db:
            db.ejecutar(f"DROP DATABASE IF EXISTS {BASE}")
    except pymysql.err.OperationalError:
        pass


class EquiposTest(unittest.TestCase):
    def setUp(self):
        self.db = DB(config_test(BASE))
        for t in ("agente_mcp", "agente_skill", "agente_secciones", "versiones", "memorias", "agentes",
                  "mcp_servidores", "proyectos"):
            self.db.ejecutar(f"DELETE FROM {t}")
        self.db.cx.commit()

    def tearDown(self):
        self.db.cerrar()

    def test_rol_y_miembro(self):
        db = self.db
        proyectos.alta(db, "str", "/tmp/str", "ERP")
        catalogo.guardar_mcp(db, "denis", {"command": "denis"}, "tickets")
        catalogo.guardar_mcp(db, "vercel", {"type": "http", "url": "https://x", "env": {"TOKEN": "s3cr3t"}}, "deploys")
        catalogo.guardar_mcp(db, "slack", {"command": "slack"}, "chat")
        rol = catalogo.guardar_agente(
            db, "devops", {"descripcion": "DevOps", "modelo": "opus", "es_rol": True},
            [{"tipo": "rol", "titulo": "Rol", "contenido": "Integrás y deployás."},
             {"tipo": "restricciones", "titulo": "Límites", "contenido": "Nunca deployás sin OK."}],
            mcps=["denis"], mcps_a_pedido=["vercel"])
        m = catalogo.guardar_agente(
            db, "devops-str", {"descripcion": "DevOps de STR", "rol": "devops", "proyecto": "str", "es_lider": True},
            [{"tipo": "restricciones", "titulo": "límites", "contenido": "Deployás a QA sin OK."}],
            mcps_a_pedido=["slack", "denis"])
        self.assertEqual(len(m["uid"]), 36)
        self.assertNotEqual(rol["uid"], m["uid"])

        r = catalogo.resolver_agente(db, "devops-str")
        self.assertEqual((r["rol"], r["proyecto"], r["modelo"], r["es_lider"]), ("devops", "str", "opus", True))
        self.assertEqual([(s["titulo"], s["heredada"]) for s in r["secciones"]], [("Rol", True), ("límites", False)])
        self.assertEqual(r["mcps"], {"base": ["denis"], "a_pedido": ["slack", "vercel"]})
        # se encuentra también por uid, y el uid no cambia al actualizar
        self.assertEqual(catalogo.obtener_agente(db, m["uid"])["nombre"], "devops-str")
        self.assertEqual(catalogo.guardar_agente(db, "devops-str", {"modelo": "sonnet"})["uid"], m["uid"])

        filas = catalogo.listar_agentes(db, proyecto="str")
        self.assertEqual([f["nombre"] for f in filas], ["devops-str"])
        self.assertEqual(filas[0]["rol"], "devops")

        mcps = catalogo.listar_mcps(db)
        self.assertNotIn("config", mcps[0])
        self.assertEqual(next(x for x in mcps if x["nombre"] == "vercel")["env"], ["TOKEN"])
        self.assertEqual(catalogo.config_mcps(db, ["denis"]), {"denis": {"command": "denis"}})
        with DB(config_test(BASE)) as otra:  # quedó confirmado, no solo en esta transacción
            self.assertEqual(len(catalogo.listar_mcps(otra)), 3)

    def test_validaciones(self):
        db = self.db
        catalogo.guardar_agente(db, "backend", {"descripcion": "Backend"})  # no es rol
        with self.assertRaises(ValueError):
            catalogo.guardar_agente(db, "backend-x", {"descripcion": "x", "rol": "backend"})
        with self.assertRaises(ValueError):
            catalogo.guardar_agente(db, "rolx", {"descripcion": "x", "es_rol": True, "rol": "backend"})
        with self.assertRaises(LookupError):
            catalogo.guardar_agente(db, "y", {"descripcion": "y", "proyecto": "no-existe"})

    def test_despertar(self):
        db = self.db
        proyectos.alta(db, "str", "/tmp/str", "ERP")
        catalogo.guardar_mcp(db, "denis", {"command": "denis", "env": {"CLAVE": "x"}}, "tickets")
        catalogo.guardar_agente(db, "devops", {"descripcion": "DevOps", "es_rol": True},
                                [{"tipo": "rol", "titulo": "Rol", "contenido": "Integrás."}], mcps=["denis"])
        catalogo.guardar_agente(db, "devops-str", {"descripcion": "DevOps de STR", "rol": "devops",
                                                   "proyecto": "str"})
        memorias.agregar(db, "decision", "QA primero", "Todo pasa por QA.", "proyecto", "str")
        memorias.agregar(db, "hecho", "Global", "No va.", "global")
        memorias.agregar(db, "procedimiento", "Mi deploy", "Así deployo.", "agente", None, "devops-str")
        d = catalogo.despertar(db, "devops-str")
        self.assertIn("# Sos devops-str (rol devops, proyecto str)", d["prompt"])
        self.assertIn("Integrás.", d["prompt"])
        self.assertEqual(d["mcps"]["base"], [{"nombre": "denis", "descripcion": "tickets"}])
        self.assertNotIn("CLAVE", str(d))
        self.assertEqual(d["proyecto"]["ruta_raiz"], "/tmp/str")
        self.assertEqual([m["titulo"] for m in d["memorias"]], ["Mi deploy", "QA primero"])
        self.assertEqual(d["denis"]["identity"], d["identidad"]["uid"])

    def test_restaurar_version_vieja_sin_campos_nuevos(self):
        db = self.db
        catalogo.guardar_agente(db, "a", {"descripcion": "uno"})
        catalogo.guardar_agente(db, "a", {"descripcion": "dos"}, mcps_a_pedido=[])
        # una foto anterior a 004 no trae es_rol / rol / mcps_a_pedido
        db.ejecutar("UPDATE versiones SET snapshot=JSON_REMOVE(snapshot, '$.mcps_a_pedido', '$.agente.es_rol', "
                    "'$.agente.rol') WHERE entidad='agente' AND version=1")
        r = catalogo.restaurar(db, "agente", "a", 1)
        self.assertTrue(r["cambiado"])
        self.assertEqual(catalogo.obtener_agente(db, "a")["agente"]["descripcion"], "uno")


if __name__ == "__main__":
    unittest.main()
