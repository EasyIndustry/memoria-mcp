# memoria

Base de datos **MariaDB** para organizar el entorno de trabajo con Claude Code: proyectos, agentes,
skills, contexto (`CLAUDE.md`), conversaciones guardadas y memoria granular. La base es la **fuente
de verdad**. Los archivos que lee Claude Code se **generan** desde ella, y lo que Claude edita en esos
archivos **vuelve** a la base como una versión nueva.

```
            ┌──────────── MariaDB (fuente de verdad) ────────────┐
            │ proyectos · agentes + secciones · skills · contexto │
            │ sesiones · resúmenes · memorias · delegaciones      │
            │ versiones · materializaciones · auditoría           │
            └───────┬─────────────────────────────▲──────────────┘
      materializar  │                             │ sincronizar / hook SessionEnd
                    ▼                             │
   .claude/agents/*.md · .claude/skills/*/SKILL.md · CLAUDE.md ──► Claude Code
                                                                     │ /compact → /clear
                                     resumen del compact ◄───────────┘ (hook)
```

## Arranque

```bash
cd memoria
cp .env.ejemplo .env            # cambiar las claves
docker compose up -d            # MariaDB 11.4 en 127.0.0.1:3307, esquema + roles en el primer arranque
pip install -e .                # CLI `memoria` (PyMySQL + PyYAML)
memoria migrar                  # aplica migraciones nuevas (idempotente)
```

Sin Docker sirve cualquier MariaDB 10.6+. Creá la base y el usuario, corré `memoria migrar` y después
`memoria roles --clave-agente … --clave-lector …` (como administrador). La configuración se toma de
`.env` o de variables `MEMORIA_DB_*`; `MEMORIA_ENV` apunta a otro `.env`.

## Flujo de trabajo

```bash
memoria proyecto alta mi-app --ruta ~/mi-app
memoria importar ~/mi-app --proyecto mi-app          # si ya tenés .claude/agents, skills o CLAUDE.md
memoria agente guardar general --descripcion "Asistente general: resuelve o deriva" --general
memoria agente seccion general "Rol" --tipo rol --contenido "Sos el asistente general…"
memoria agente seccion general "Cómo trabajar" --tipo forma_de_trabajo --desde-archivo flujo.md
memoria contexto agregar "Comandos" --proyecto mi-app --tipo comandos --contenido "pytest -q"

memoria materializar --agente general --destino ~/mi-app   # o sin --destino: carpeta temporal
# → imprime: cd ~/mi-app && MEMORIA_AGENTE=general claude --agent general
memoria instalar-hook --env ~/open-source-home-assistant/memoria/.env
```

### Guardar una conversación: `/compact` → `/clear`

1. `/compact` genera el resumen de la conversación dentro del transcript.
2. `/clear` vacía la memoria del agente. Ahí se dispara el hook `SessionEnd` (motivo `clear`), que:
   - guarda en `resumenes` los resúmenes de compact que todavía no estén en la base, redactando secretos
     y vinculándolos al proyecto (según la carpeta) y al agente (`MEMORIA_AGENTE`);
   - sincroniza los archivos generados que Claude haya editado.
3. Un `/clear` **sin** `/compact` previo no guarda nada: se toma como descartar la conversación.

Para retomar un objetivo: `memoria sesion ultima --proyecto mi-app` o `memoria sesion buscar "tema"`.
Con `MEMORIA_CON_MENSAJES=1` también se guardan los mensajes previos al compact (tablas `mensajes` y
`bloques`, sin el razonamiento interno del modelo, redactados y recortados a `MEMORIA_MAX_BLOQUE`
caracteres). En modo headless, `claude -p "/compact" --resume ID` y después
`memoria sesion guardar --session-id ID`.

### Editar desde la base o desde Claude

- **Base:** `memoria agente seccion …`, `memoria contexto editar ID …`, `memoria skill guardar --carpeta …`.
  Después, `memoria materializar` de nuevo.
- **Claude:** edita los archivos generados; `memoria sincronizar DIR`, o el hook al cerrar la sesión, lo
  guarda como versión nueva y regenera el archivo con sus marcadores.
- **Historial:** `memoria historial agente general`, `memoria version agente general 2`,
  `memoria restaurar agente general 2` (crea una versión nueva; la historia no se borra).
- `materializar` nunca pisa un archivo que no generó (o que se editó después sin sincronizar): falla
  con un aviso, o con `--forzar` deja copia `.bak`.

Los archivos generados llevan marcadores HTML invisibles (`<!-- seccion: rol -->`, `<!-- contexto: 12 -->`)
para reconstruir cada sección. Un `## Título` nuevo sin marcador se toma como sección nueva; para
subtítulos dentro de una sección se usa `###`.

## Esquema

| grupo | tablas | qué guarda |
|---|---|---|
| proyectos | `proyectos`, `directorios`, `archivos` | árbol del proyecto con metadatos y sha256, no el contenido (`memoria proyecto escanear`) |
| agentes | `agentes`, `agente_secciones`, `agente_skill`, `agente_mcp` | frontmatter en columnas; instrucciones por sección (rol, forma de trabajo, restricciones, formato de salida, contexto, ejemplos…) |
| skills | `skills`, `skill_archivos` | `SKILL.md` y archivos de apoyo |
| contexto | `contexto_secciones` | lo que va a `CLAUDE.md`, con alcance global, de proyecto o de agente |
| historial | `versiones` | foto completa de cada cambio de agente, skill o contexto |
| archivos generados | `materializaciones` | ruta, hash y versión de cada archivo generado (para detectar ediciones) |
| conversaciones | `sesiones`, `resumenes`, `mensajes`, `bloques` | resúmenes de compact con búsqueda de texto completo; mensajes opcionales |
| derivaciones | `delegaciones` | origen → destino, objetivo, motivo, confianza, estado y resultado |
| memoria | `memorias`, `etiquetas`, `memoria_etiqueta` | hechos, preferencias, decisiones, procedimientos, pendientes y referencias; con alcance, importancia 1-5, vigencia, reemplazos y etiquetas |
| control | `auditoria`, `schema_migraciones` | quién hizo qué y cuándo, y migraciones aplicadas |

Vistas para lectura acotada: `v_agentes`, `v_memorias_vigentes`, `v_resumenes`, `v_delegaciones`.

## Acceso granular

| usuario / rol | puede |
|---|---|
| `MARIADB_USER` (app/CLI) | todo sobre la base, incluidas las migraciones |
| `memoria_agente` | leer vistas y catálogo; escribir memorias, etiquetas y delegaciones. No toca agentes, skills ni sesiones |
| `memoria_lector` | solo lectura (tableros, análisis) |

Es la base para el MCP: el agente general se conecta como `memoria_agente` y solo puede hacer lo que su
rol permite.

## Memoria y derivaciones

```bash
memoria memorias agregar preferencia "Idioma" "Responder en español rioplatense" --importancia 5 --etiquetas estilo
memoria memorias agregar hecho "Puerto DB" "MariaDB en 3307" --proyecto mi-app
memoria memorias listar --proyecto mi-app          # globales + del proyecto, por importancia
memoria memorias buscar "mariadb"
memoria memorias agregar preferencia "Idioma" "Neutro" --reemplaza 1   # la 1 deja de estar vigente
memoria delegacion crear investigador "Encontrar dónde se valida el token" --origen general --confianza 0.9
memoria delegacion cerrar 1 --resultado "auth/jwt.py:42"
memoria auditoria --tabla agentes
```

## Seguridad

- Los resúmenes y mensajes se **redactan** antes de guardarse: claves de Anthropic, OpenAI, GitHub,
  AWS, Slack y Google, JWT, `Bearer`, URLs con clave, claves privadas y asignaciones del tipo
  `PASSWORD=…`, `TOKEN: …`, `API_KEY=…`.
- El puerto de Docker queda publicado solo en `127.0.0.1`.
- El hook nunca corta a Claude Code: los errores van a `~/.local/state/memoria/hook.log` (o `MEMORIA_LOG`).

## Pruebas

```bash
MEMORIA_TEST_SOCKET=/run/mysqld/mysqld.sock python -m unittest discover -s tests
# o MEMORIA_TEST_HOST/PORT/USER/PASSWORD; crea y borra una base temporal
```
