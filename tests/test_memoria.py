"""Pruebas contra un MariaDB real (crea y borra una base temporal).

    MEMORIA_TEST_SOCKET=/run/mysqld/mysqld.sock python -m unittest discover -s tests
    # o MEMORIA_TEST_HOST / MEMORIA_TEST_PORT / MEMORIA_TEST_USER / MEMORIA_TEST_PASSWORD
El usuario necesita CREATE/DROP DATABASE. Sin servidor accesible, las pruebas se saltean.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql  # noqa: E402

from memoria import catalogo, esquema, formato, hook, materializar, memorias, proyectos, sesiones  # noqa: E402
from memoria.config import Config  # noqa: E402
from memoria.db import DB  # noqa: E402
from memoria.redaccion import redactar  # noqa: E402

BASE_TEST = f"memoria_test_{os.getpid()}"


def config_test(base=""):
    e = os.environ.get
    return Config(host=e("MEMORIA_TEST_HOST", "127.0.0.1"), puerto=int(e("MEMORIA_TEST_PORT", "3306")),
                  usuario=e("MEMORIA_TEST_USER", "root"), clave=e("MEMORIA_TEST_PASSWORD", ""),
                  socket=e("MEMORIA_TEST_SOCKET", ""), base=base, actor="pruebas")


def setUpModule():
    try:
        cx = DB(config_test())
    except pymysql.err.OperationalError as e:
        raise unittest.SkipTest(f"sin MariaDB: {e}")
    cx.ejecutar(f"CREATE DATABASE {BASE_TEST} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cx.cerrar()
    with DB(config_test(BASE_TEST)) as db:
        esquema.migrar(db)


def tearDownModule():
    try:
        with DB(config_test()) as db:
            db.ejecutar(f"DROP DATABASE IF EXISTS {BASE_TEST}")
    except pymysql.err.OperationalError:
        pass


def resumen_compact(texto, uuid="11111111-1111-1111-1111-111111111111"):
    return [{"type": "system", "subtype": "compact_boundary", "sessionId": "s",
             "compactMetadata": {"trigger": "manual", "preTokens": 40000, "postTokens": 2000},
             "timestamp": "2026-09-24T12:00:00.000Z"},
            {"type": "user", "isCompactSummary": True, "uuid": uuid, "timestamp": "2026-09-24T12:00:01.000Z",
             "message": {"role": "user", "content": texto}}]


def escribir_transcript(carpeta, entradas, session="aaaaaaaa-0000-0000-0000-000000000001"):
    ruta = Path(carpeta) / f"{session}.jsonl"
    with ruta.open("w", encoding="utf-8") as f:
        for e in entradas:
            f.write(json.dumps({"sessionId": session, **e}) + "\n")
    return ruta


class Base(unittest.TestCase):
    def setUp(self):
        self.db = DB(config_test(BASE_TEST))
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.db.cerrar()
        self.tmp.cleanup()


class TestEsquema(Base):
    def test_migrar_es_idempotente(self):
        self.assertEqual(esquema.migrar(self.db), [])
        self.assertIn("001_esquema", {f["version"] for f in self.db.todos("SELECT version FROM schema_migraciones")})

    def test_roles_sustituye_marcadores(self):
        sql = esquema.sql_roles("mi_base", "a1", "l1")
        self.assertNotIn("{{", sql)
        self.assertIn("`mi_base`.memorias", sql)


class TestCatalogo(Base):
    def test_versiones_secciones_y_restaurar(self):
        catalogo.guardar_skill(self.db, "git-flujo", "Cuando hay que commitear", "Usá ramas cortas.")
        secciones = [{"tipo": "rol", "titulo": "Rol", "contenido": "Sos el asistente general."},
                     {"tipo": "forma_de_trabajo", "titulo": "Cómo trabajar", "contenido": "Derivá cuando convenga."}]
        r1 = catalogo.guardar_agente(self.db, "general-v", {"descripcion": "Asistente que deriva", "es_general": True},
                                     secciones, ["git-flujo"])
        self.assertEqual((r1["version"], r1["cambiado"]), (1, True))
        # mismo contenido: no crea versión
        r = catalogo.guardar_agente(self.db, "general-v", {"descripcion": "Asistente que deriva"}, secciones)
        self.assertFalse(r["cambiado"])
        r2 = catalogo.editar_seccion(self.db, "general-v", "Cómo trabajar", contenido="Primero preguntá.")
        self.assertEqual(r2["version"], 2)
        catalogo.editar_seccion(self.db, "general-v", "Restricciones", contenido="No borres nada.", tipo="restricciones")
        a = catalogo.obtener_agente(self.db, "general-v")
        self.assertEqual([s["titulo"] for s in a["secciones"]], ["Rol", "Cómo trabajar", "Restricciones"])
        self.assertEqual(a["skills"], ["git-flujo"])
        self.assertEqual([h["version"] for h in catalogo.historial(self.db, "agente", "general-v")], [3, 2, 1])
        r4 = catalogo.restaurar(self.db, "agente", "general-v", 1)
        self.assertEqual(r4["version"], 4)
        self.assertEqual(catalogo.obtener_agente(self.db, "general-v")["secciones"][1]["contenido"],
                         "Derivá cuando convenga.")
        self.assertTrue(self.db.valor("SELECT COUNT(*) FROM auditoria WHERE tabla='agentes'"))

    def test_nombre_invalido_rechazado_por_la_base(self):
        with self.assertRaises(pymysql.err.OperationalError):
            catalogo.guardar_agente(self.db, "Con Espacios", {"descripcion": "x"})

    def test_contexto_por_alcance(self):
        proyectos.alta(self.db, "ctx-proy", str(self.dir))
        catalogo.guardar_contexto(self.db, "Global", "Respondé en español.")
        catalogo.guardar_contexto(self.db, "Del proyecto", "Usá pytest.", alcance="proyecto", proyecto="ctx-proy")
        titulos = [s["titulo"] for s in catalogo.secciones_contexto(self.db, "ctx-proy")]
        self.assertLess(titulos.index("Global"), titulos.index("Del proyecto"))
        self.assertNotIn("Del proyecto", [s["titulo"] for s in catalogo.secciones_contexto(self.db)])


class TestFormato(unittest.TestCase):
    def test_ida_y_vuelta_agente(self):
        agente = {"nombre": "x", "descripcion": "Para X", "modelo": "sonnet", "herramientas": ["Read", "Grep"]}
        secciones = [{"tipo": "rol", "titulo": "Rol", "contenido": "Hacé X.\n\n### Detalle\nsub"},
                     {"tipo": "restricciones", "titulo": "Límites", "contenido": "Nada de Y."}]
        texto = formato.render_agente(agente, secciones, ["s1"])
        self.assertTrue(texto.startswith("---\nname: x\n"))
        datos, secs, skills, _ = formato.parse_agente(texto)
        self.assertEqual((datos["herramientas"], skills), (["Read", "Grep"], ["s1"]))
        self.assertEqual([(s["tipo"], s["titulo"], s["contenido"]) for s in secs],
                         [(s["tipo"], s["titulo"], s["contenido"]) for s in secciones])

    def test_agente_escrito_a_mano(self):
        _, secs, _, _ = formato.parse_agente("---\nname: y\ndescription: d\n---\nIntro.\n\n## Workflow\nPaso 1.\n")
        self.assertEqual([(s["tipo"], s["titulo"]) for s in secs], [("rol", "General"), ("forma_de_trabajo", "Workflow")])


class TestMaterializar(Base):
    def setUp(self):
        super().setUp()
        catalogo.guardar_skill(self.db, "revisar", "Revisar código", "Leé el diff.", archivos={"guia.md": "# Guía\n"})
        catalogo.guardar_agente(self.db, "jefe", {"descripcion": "Asistente general", "es_general": True},
                                [{"tipo": "rol", "titulo": "Rol", "contenido": "Coordinás."}], ["revisar"])
        catalogo.guardar_agente(self.db, "revisor", {"descripcion": "Revisa PRs", "herramientas": ["Read"]},
                                [{"tipo": "rol", "titulo": "Rol", "contenido": "Revisás."}])
        proyectos.alta(self.db, "mat-proy", str(self.dir))
        catalogo.guardar_contexto(self.db, "Reglas", "Nada de secretos en git.", alcance="proyecto", proyecto="mat-proy")

    def test_materializar_editar_y_sincronizar(self):
        r = materializar.materializar(self.db, self.dir, agente="jefe")
        rutas = {Path(p).relative_to(self.dir).as_posix() for p in r["archivos"]}
        self.assertTrue({".claude/agents/jefe.md", ".claude/agents/revisor.md", ".claude/skills/revisar/SKILL.md",
                         ".claude/skills/revisar/guia.md", "CLAUDE.md"} <= rutas)
        self.assertIn("claude --agent jefe", r["comando"])

        # Claude edita: cambia una sección, agrega otra; y agrega una sección al CLAUDE.md
        agente_md = self.dir / ".claude/agents/jefe.md"
        agente_md.write_text(agente_md.read_text().replace("Coordinás.", "Coordinás y resumís.")
                             + "\n## Formato de salida\nViñetas cortas.\n")
        claude_md = self.dir / "CLAUDE.md"
        claude_md.write_text(claude_md.read_text() + "\n## Comandos\n`pytest -q`\n")
        (self.dir / ".claude/skills/revisar/guia.md").write_text("# Guía v2\n")

        res = materializar.sincronizar(self.db, self.dir)
        self.assertEqual(res["errores"], [])
        self.assertEqual(len(res["actualizados"]), 3)
        a = catalogo.obtener_agente(self.db, "jefe")
        self.assertEqual(a["version"], 2)
        self.assertEqual(a["secciones"][0]["contenido"], "Coordinás y resumís.")
        self.assertEqual(a["secciones"][1]["tipo"], "formato_salida")
        self.assertEqual(catalogo.obtener_skill(self.db, "revisar")["archivos"]["guia.md"], "# Guía v2\n")
        self.assertIn("Comandos", [s["titulo"] for s in catalogo.secciones_contexto(self.db, "mat-proy")])
        # el archivo se regeneró con marcadores: la segunda pasada no ve cambios
        self.assertIn("<!-- seccion: formato_salida -->", agente_md.read_text())
        res2 = materializar.sincronizar(self.db, self.dir)
        self.assertEqual((res2["actualizados"], res2["errores"]), ([], []))

    def test_no_pisa_archivos_ajenos(self):
        (self.dir / "CLAUDE.md").write_text("mío\n")
        with self.assertRaises(FileExistsError):
            materializar.materializar(self.db, self.dir, agente="revisor")
        materializar.materializar(self.db, self.dir, agente="revisor", forzar=True)
        self.assertEqual((self.dir / "CLAUDE.md.bak").read_text(), "mío\n")

    def test_temporal_sin_subagentes(self):
        r = materializar.materializar(self.db, agente="jefe", subagentes=False)
        self.assertTrue(r["destino"].startswith(tempfile.gettempdir()))
        self.assertFalse(any("revisor" in p for p in r["archivos"]))

    def test_importar(self):
        origen = self.dir / "otro"
        (origen / ".claude/agents").mkdir(parents=True)
        (origen / ".claude/skills/dibujar").mkdir(parents=True)
        (origen / ".claude/skills/dibujar/SKILL.md").write_text("---\nname: dibujar\ndescription: Diagramas\n---\nUsá mermaid.\n")
        (origen / ".claude/agents/disenador.md").write_text(
            "---\nname: disenador\ndescription: Diseña\nskills: dibujar, inexistente\n---\n## Rol\nDiseñás.\n")
        (origen / "CLAUDE.md").write_text("# Proyecto\n\n## Estilo\nCorto.\n")
        r = materializar.importar(self.db, origen)
        self.assertEqual([a["nombre"] for a in r["agentes"]], ["disenador"])
        self.assertTrue(r["avisos"])
        self.assertEqual(catalogo.obtener_agente(self.db, "disenador")["skills"], ["dibujar"])
        self.assertEqual(materializar.importar(self.db, origen)["agentes"][0]["cambiado"], False)

    def test_importar_memory_md(self):
        origen = self.dir / "convencional"
        (origen / ".claude/memory").mkdir(parents=True)
        (origen / ".claude/memory/MEMORY.md").write_text("- [Stack](stack.md) — índice, no importa\n")
        (origen / ".claude/memory/stack.md").write_text(
            "---\nname: stack\ndescription: Stack preferido\nmetadata:\n  type: user\n---\n\nNode y Postgres.\n")
        (origen / ".claude/projects/-home-x/memory").mkdir(parents=True)
        (origen / ".claude/projects/-home-x/memory/deploy.md").write_text(
            "---\nname: deploy\ndescription: Cómo deployar\nmetadata:\n  type: project\n---\n\nPush a main.\n")
        r = materializar.importar(self.db, origen)
        self.assertEqual({(m["titulo"], m["tipo"]) for m in r["memorias"]},
                         {("Stack preferido", "preferencia"), ("Cómo deployar", "hecho")})
        # el índice MEMORY.md no entra, y la segunda corrida no duplica
        self.assertEqual(len(memorias.listar(self.db, etiqueta="importado")), 2)
        r2 = materializar.importar(self.db, origen)
        self.assertEqual(r2["memorias"], [])
        self.assertEqual(len(memorias.listar(self.db, etiqueta="importado")), 2)


class TestSesiones(Base):
    def test_guardar_compact_redacta_y_no_duplica(self):
        clave = "sk-ant-api03-" + "x" * 40
        entradas = [{"type": "ai-title", "aiTitle": "Armar backend"},
                    {"type": "user", "uuid": "u1", "cwd": str(self.dir), "gitBranch": "main", "version": "2.1",
                     "timestamp": "2026-09-24T11:00:00.000Z",
                     "message": {"role": "user", "content": f"usá esta clave {clave}"}},
                    {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "timestamp": "2026-09-24T11:00:05.000Z",
                     "message": {"role": "assistant", "model": "m", "content": [
                         {"type": "thinking", "thinking": "..."}, {"type": "text", "text": "Listo"},
                         {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
                    *resumen_compact(f"Resumen: se configuró MariaDB con password=supersecreta123 y {clave}.")]
        proyectos.alta(self.db, "ses-proy", str(self.dir))
        ruta = escribir_transcript(self.dir, entradas)
        r = sesiones.guardar(self.db, ruta, motivo="clear", con_mensajes=True)
        self.assertTrue(r["guardado"])
        self.assertEqual((r["resumenes"], r["mensajes"]), (1, 2))
        res = self.db.uno("SELECT * FROM v_resumenes WHERE session_uuid=%s", (r["session_uuid"],))
        self.assertEqual((res["titulo"], res["proyecto"], res["tokens_antes"]), ("Armar backend", "ses-proy", 40000))
        self.assertNotIn(clave, res["contenido"])
        self.assertNotIn("supersecreta123", res["contenido"])
        tipos = [f["tipo"] for f in self.db.todos(
            "SELECT b.tipo FROM bloques b JOIN mensajes m ON m.id=b.mensaje_id ORDER BY m.orden, b.orden")]
        self.assertEqual(tipos, ["texto", "texto", "tool_use"])
        self.assertFalse(sesiones.guardar(self.db, ruta, motivo="clear")["guardado"])   # ya guardado
        self.assertTrue(sesiones.buscar_resumenes(self.db, "MariaDB"))
        self.assertEqual(sesiones.ultimo_resumen(self.db, "ses-proy")["session_uuid"], r["session_uuid"])

    def test_clear_sin_compact_no_guarda(self):
        ruta = escribir_transcript(self.dir, [{"type": "user", "uuid": "z1", "message": {"role": "user", "content": "hola"}}],
                                   session="aaaaaaaa-0000-0000-0000-000000000002")
        self.assertFalse(sesiones.guardar(self.db, ruta, motivo="clear")["guardado"])
        self.assertTrue(sesiones.guardar(self.db, ruta, exigir_compact=False)["guardado"])

    def test_hook_session_end(self):
        ruta = escribir_transcript(self.dir, resumen_compact("Resumen del hook.", uuid="22222222-2222-2222-2222-222222222222"),
                                   session="aaaaaaaa-0000-0000-0000-000000000003")
        evento = {"session_id": "aaaaaaaa-0000-0000-0000-000000000003", "transcript_path": str(ruta),
                  "cwd": str(self.dir), "reason": "clear", "hook_event_name": "SessionEnd"}
        log = self.dir / "hook.log"
        hook.LOG = log
        sys.stdin = io.StringIO(json.dumps(evento))
        try:
            self.assertEqual(hook.main("session-end", lambda: DB(config_test(BASE_TEST))), 0)
        finally:
            sys.stdin = sys.__stdin__
        registro = json.loads(log.read_text().splitlines()[-1])
        self.assertTrue(registro["sesion"]["guardado"], registro)
        # motivo que no guarda
        r = hook.session_end(self.db, {**evento, "reason": "logout"})
        self.assertNotIn("sesion", r)


class TestMemorias(Base):
    def test_agregar_listar_buscar_reemplazar(self):
        proyectos.alta(self.db, "mem-proy")
        m1 = memorias.agregar(self.db, "preferencia", "Idioma", "Responder en español rioplatense",
                              etiquetas=["Estilo", "idioma"], importancia=5)
        memorias.agregar(self.db, "hecho", "Base de datos", "El proyecto usa MariaDB en el puerto 3307",
                         proyecto="mem-proy")
        self.assertEqual(self.db.valor("SELECT etiquetas FROM v_memorias_vigentes WHERE id=%s", (m1,)), "estilo,idioma")
        titulos = {m["titulo"] for m in memorias.listar(self.db, proyecto="mem-proy")}
        self.assertTrue({"Idioma", "Base de datos"} <= titulos)
        self.assertNotIn("Base de datos", {m["titulo"] for m in memorias.listar(self.db)})  # es del proyecto
        self.assertEqual(len(memorias.listar(self.db, etiqueta="idioma")), 1)
        self.assertEqual(memorias.buscar(self.db, "MariaDB")[0]["titulo"], "Base de datos")
        m3 = memorias.agregar(self.db, "preferencia", "Idioma", "Responder en español neutro", reemplaza=m1)
        vigentes = {m["id"] for m in memorias.listar(self.db)}
        self.assertIn(m3, vigentes)
        self.assertNotIn(m1, vigentes)
        self.assertTrue(memorias.olvidar(self.db, m3))

    def test_delegaciones(self):
        catalogo.guardar_agente(self.db, "general-d", {"descripcion": "general", "es_general": True})
        catalogo.guardar_agente(self.db, "codigo-d", {"descripcion": "escribe código"})
        d = memorias.delegar(self.db, "codigo-d", "Implementar endpoint", origen="general-d", confianza=0.91)
        memorias.cerrar_delegacion(self.db, d, resultado="PR abierto")
        fila = self.db.uno("SELECT * FROM v_delegaciones WHERE id=%s", (d,))
        self.assertEqual((fila["origen"], fila["destino"], fila["estado"]), ("general-d", "codigo-d", "completada"))
        self.assertIsNotNone(fila["terminado"])


class TestProyectos(Base):
    def test_escanear_detecta_cambios(self):
        (self.dir / "src").mkdir()
        (self.dir / "src/a.py").write_text("print(1)\n")
        (self.dir / "README.md").write_text("hola\n")
        (self.dir / "node_modules").mkdir()
        (self.dir / "node_modules/x.js").write_text("x")
        proyectos.alta(self.db, "esc-proy", str(self.dir))
        self.assertEqual(proyectos.escanear(self.db, "esc-proy")["nuevos"], 2)
        (self.dir / "src/a.py").write_text("print(2)\n")
        (self.dir / "README.md").unlink()
        r = proyectos.escanear(self.db, "esc-proy")
        self.assertEqual((r["modificados"], r["desaparecidos"], r["nuevos"]), (1, 1, 0))
        self.assertEqual(proyectos.por_ruta(self.db, self.dir / "src")["nombre"], "esc-proy")


class TestRedaccion(unittest.TestCase):
    def test_patrones(self):
        texto = ("ghp_" + "a" * 36 + " AKIAABCDEFGHIJKLMNOP Authorization: Bearer abcdefghijklmnopqrstuvwxyz123 "
                 "mysql://yo:clave123@host/db API_KEY=abcd1234efgh")
        limpio, n = redactar(texto)
        self.assertEqual(n, 5)
        for secreto in ("ghp_", "AKIA", "abcdefghijklmnop", "clave123", "abcd1234efgh"):
            self.assertNotIn(secreto, limpio)
        self.assertIn("mysql://yo:«REDACTADO:url_con_clave»@host/db", limpio)


class TestCLI(Base):
    def test_salida_json(self):
        os.environ.update({"MEMORIA_DB_NAME": BASE_TEST, "MEMORIA_DB_USER": config_test().usuario,
                           "MEMORIA_DB_PASSWORD": config_test().clave, "MEMORIA_DB_SOCKET": config_test().socket,
                           "MEMORIA_DB_HOST": config_test().host, "MEMORIA_DB_PORT": str(config_test().puerto)})
        from memoria.__main__ import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["memorias", "agregar", "hecho", "CLI", "desde la CLI", "--etiquetas", "cli"]), 0)
            self.assertEqual(main(["agente", "ver", "no-existe"]), 1)
        salidas = buf.getvalue()
        self.assertIn('"id"', salidas)
        self.assertIn("LookupError", salidas)

    def test_instalar_hook_no_duplica(self):
        settings = self.dir / "settings.json"
        settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": []}]}}))
        self.assertTrue(hook.instalar(settings, "memoria hook session-end")["instalado"])
        self.assertTrue(hook.instalar(settings, "memoria hook session-end")["ya_estaba"])
        datos = json.loads(settings.read_text())
        self.assertEqual((datos["model"], len(datos["hooks"]["SessionEnd"])), ("x", 1))
        self.assertIn("Stop", datos["hooks"])


if __name__ == "__main__":
    unittest.main()
