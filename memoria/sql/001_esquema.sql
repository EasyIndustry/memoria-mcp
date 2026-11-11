-- memoria · esquema base (MariaDB 10.6+, InnoDB, utf8mb4)
-- MySQL 8 no sirve tal cual: prohíbe CHECK sobre columnas con acciones de FK.
-- Fuente de verdad de proyectos, agentes, skills, contextos, sesiones y memorias.
-- Los archivos .claude/ y CLAUDE.md se GENERAN desde acá (ver `memoria materializar`).

CREATE TABLE IF NOT EXISTS schema_migraciones (
  version     VARCHAR(64) PRIMARY KEY,
  aplicada    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ───────────────────────── proyectos y archivos ─────────────────────────

CREATE TABLE IF NOT EXISTS proyectos (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre        VARCHAR(100) NOT NULL UNIQUE,
  descripcion   TEXT,
  ruta_raiz     VARCHAR(1024),
  repo_url      VARCHAR(512),
  archivado     BOOLEAN NOT NULL DEFAULT FALSE,
  creado        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  actualizado   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS directorios (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  proyecto_id    INT UNSIGNED NOT NULL,
  padre_id       INT UNSIGNED NULL,
  ruta_relativa  VARCHAR(768) NOT NULL,            -- '' = raíz del proyecto
  descripcion    TEXT,
  creado         DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_dir (proyecto_id, ruta_relativa),
  CONSTRAINT fk_dir_proy  FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
  CONSTRAINT fk_dir_padre FOREIGN KEY (padre_id) REFERENCES directorios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Solo metadatos y hash: el contenido del proyecto vive en el disco / git.
CREATE TABLE IF NOT EXISTS archivos (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  proyecto_id     INT UNSIGNED NOT NULL,
  directorio_id   INT UNSIGNED NOT NULL,
  ruta_relativa   VARCHAR(768) NOT NULL,
  nombre          VARCHAR(255) NOT NULL,
  extension       VARCHAR(32),
  tamano_bytes    BIGINT UNSIGNED NOT NULL,
  sha256          CHAR(64) NOT NULL,
  modificado_fs   DATETIME(3),
  descripcion     TEXT,
  presente        BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE si desapareció en el último escaneo
  escaneado       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_arch (proyecto_id, ruta_relativa),
  KEY ix_arch_sha (sha256),
  CONSTRAINT fk_arch_proy FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
  CONSTRAINT fk_arch_dir  FOREIGN KEY (directorio_id) REFERENCES directorios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ───────────────────────── agentes, skills, contextos ─────────────────────────

-- Campos del frontmatter de .claude/agents/<nombre>.md. El cuerpo sale de agente_secciones.
CREATE TABLE IF NOT EXISTS agentes (
  id                    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre                VARCHAR(64) NOT NULL UNIQUE,     -- slug: minúsculas y guiones
  descripcion           TEXT NOT NULL,                   -- CUÁNDO usarlo: lo lee el agente que deriva
  modelo                VARCHAR(64),                     -- sonnet | opus | haiku | inherit | id completo
  color                 VARCHAR(32),
  herramientas          JSON,                            -- ["Read","Grep","Bash(git *)"]; NULL = hereda todas
  herramientas_negadas  JSON,
  modo_permisos         VARCHAR(32),                     -- default | acceptEdits | plan | ...
  es_general            BOOLEAN NOT NULL DEFAULT FALSE,  -- el asistente que deriva a los demás
  activo                BOOLEAN NOT NULL DEFAULT TRUE,
  version               INT UNSIGNED NOT NULL DEFAULT 1,
  creado                DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  actualizado           DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  CONSTRAINT ck_agente_nombre CHECK (nombre REGEXP '^[a-z0-9][a-z0-9-]*$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Instrucciones del agente, granuladas: cada sección se edita y versiona por separado.
CREATE TABLE IF NOT EXISTS agente_secciones (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  agente_id   INT UNSIGNED NOT NULL,
  tipo        ENUM('rol','forma_de_trabajo','restricciones','formato_salida','contexto',
                   'ejemplos','herramientas','otro') NOT NULL DEFAULT 'otro',
  titulo      VARCHAR(200) NOT NULL,
  orden       SMALLINT NOT NULL DEFAULT 0,
  contenido   MEDIUMTEXT NOT NULL,
  activo      BOOLEAN NOT NULL DEFAULT TRUE,
  actualizado DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_sec_agente (agente_id, orden),
  CONSTRAINT fk_sec_agente FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- .claude/skills/<nombre>/SKILL.md (+ archivos de apoyo en skill_archivos).
CREATE TABLE IF NOT EXISTS skills (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre         VARCHAR(64) NOT NULL UNIQUE,
  descripcion    TEXT NOT NULL,                   -- cuándo se activa
  instrucciones  MEDIUMTEXT NOT NULL,             -- cuerpo de SKILL.md
  herramientas   JSON,                            -- allowed-tools
  activo         BOOLEAN NOT NULL DEFAULT TRUE,
  version        INT UNSIGNED NOT NULL DEFAULT 1,
  creado         DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  actualizado    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  CONSTRAINT ck_skill_nombre CHECK (nombre REGEXP '^[a-z0-9][a-z0-9-]*$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skill_archivos (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  skill_id       INT UNSIGNED NOT NULL,
  ruta_relativa  VARCHAR(512) NOT NULL,           -- relativa a la carpeta de la skill, ej: scripts/x.py
  contenido      MEDIUMTEXT NOT NULL,
  sha256         CHAR(64) NOT NULL,
  UNIQUE KEY uq_skill_arch (skill_id, ruta_relativa),
  CONSTRAINT fk_skarch_skill FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agente_skill (
  agente_id  INT UNSIGNED NOT NULL,
  skill_id   INT UNSIGNED NOT NULL,
  PRIMARY KEY (agente_id, skill_id),
  CONSTRAINT fk_as_agente FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE CASCADE,
  CONSTRAINT fk_as_skill  FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mcp_servidores (
  id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre       VARCHAR(64) NOT NULL UNIQUE,
  descripcion  TEXT,
  config       JSON NOT NULL,                     -- entrada de .mcp.json: {"command": ..., "args": [...]}
  activo       BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agente_mcp (
  agente_id  INT UNSIGNED NOT NULL,
  mcp_id     INT UNSIGNED NOT NULL,
  PRIMARY KEY (agente_id, mcp_id),
  CONSTRAINT fk_am_agente FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE CASCADE,
  CONSTRAINT fk_am_mcp    FOREIGN KEY (mcp_id) REFERENCES mcp_servidores(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lo que va a CLAUDE.md: reglas globales, de un proyecto o de un agente. Se arma por secciones.
CREATE TABLE IF NOT EXISTS contexto_secciones (
  id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  alcance      ENUM('global','proyecto','agente') NOT NULL,
  proyecto_id  INT UNSIGNED NULL,
  agente_id    INT UNSIGNED NULL,
  tipo         ENUM('reglas','estilo','comandos','arquitectura','flujo','restricciones','otro')
                 NOT NULL DEFAULT 'otro',
  titulo       VARCHAR(200) NOT NULL,
  orden        SMALLINT NOT NULL DEFAULT 0,
  contenido    MEDIUMTEXT NOT NULL,
  activo       BOOLEAN NOT NULL DEFAULT TRUE,
  version      INT UNSIGNED NOT NULL DEFAULT 1,
  actualizado  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_ctx (alcance, proyecto_id, agente_id, orden),
  CONSTRAINT fk_ctx_proy   FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
  CONSTRAINT fk_ctx_agente FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE CASCADE,
  CONSTRAINT ck_ctx_alcance CHECK (
    (alcance = 'global'   AND proyecto_id IS NULL     AND agente_id IS NULL) OR
    (alcance = 'proyecto' AND proyecto_id IS NOT NULL AND agente_id IS NULL) OR
    (alcance = 'agente'   AND agente_id IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Historial inmutable: cada cambio de agente, skill o sección de contexto deja una foto completa.
CREATE TABLE IF NOT EXISTS versiones (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  entidad     ENUM('agente','skill','contexto') NOT NULL,
  entidad_id  INT UNSIGNED NOT NULL,
  version     INT UNSIGNED NOT NULL,
  snapshot    JSON NOT NULL,
  origen      ENUM('manual','importado','sincronizado','restaurado','api') NOT NULL,
  actor       VARCHAR(100),
  nota        VARCHAR(500),
  creado      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_version (entidad, entidad_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Cada archivo generado desde la base, con su hash, para detectar ediciones y traerlas de vuelta.
CREATE TABLE IF NOT EXISTS materializaciones (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  entidad       ENUM('agente','skill','skill_archivo','contexto') NOT NULL,
  entidad_id    INT UNSIGNED NULL,                -- contexto: NULL (el CLAUDE.md agrupa varias secciones)
  version       INT UNSIGNED NULL,
  destino       VARCHAR(1024) NOT NULL,           -- carpeta raíz donde se materializó
  ruta          VARCHAR(1024) NOT NULL,           -- ruta absoluta del archivo
  sha256        CHAR(64) NOT NULL,
  proyecto_id   INT UNSIGNED NULL,
  agente_id     INT UNSIGNED NULL,
  estado        ENUM('vigente','sincronizado','reemplazado','borrado') NOT NULL DEFAULT 'vigente',
  creado        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  revisado      DATETIME(3) NULL,
  KEY ix_mat_destino (destino(255), estado),
  KEY ix_mat_ruta (ruta(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ───────────────────────── sesiones y conversaciones ─────────────────────────

CREATE TABLE IF NOT EXISTS sesiones (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_uuid    CHAR(36) NOT NULL UNIQUE,       -- sessionId de Claude Code
  proyecto_id     INT UNSIGNED NULL,
  agente_id       INT UNSIGNED NULL,
  titulo          VARCHAR(300),
  cwd             VARCHAR(1024),
  rama_git        VARCHAR(255),
  version_cli     VARCHAR(32),
  iniciada        DATETIME(3),
  terminada       DATETIME(3),
  motivo_fin      VARCHAR(32),                    -- clear | logout | prompt_input_exit | other | manual
  transcript      VARCHAR(1024),
  creado          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_ses_proy   FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE SET NULL,
  CONSTRAINT fk_ses_agente FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Resúmenes de /compact (uno por compactación guardada). Es lo que se recupera en otra sesión.
CREATE TABLE IF NOT EXISTS resumenes (
  id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  sesion_id          BIGINT UNSIGNED NOT NULL,
  mensaje_uuid       CHAR(36) NOT NULL UNIQUE,    -- uuid del mensaje isCompactSummary
  disparador         VARCHAR(16),                 -- manual | auto
  tokens_antes       INT UNSIGNED,
  tokens_despues     INT UNSIGNED,
  contenido          MEDIUMTEXT NOT NULL,         -- ya redactado (sin secretos)
  redacciones        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  compactado         DATETIME(3),
  creado             DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  FULLTEXT KEY ft_resumen (contenido),
  CONSTRAINT fk_res_ses FOREIGN KEY (sesion_id) REFERENCES sesiones(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Opcional (`--con-mensajes`): la conversación previa al compact, mensaje por mensaje.
CREATE TABLE IF NOT EXISTS mensajes (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  sesion_id     BIGINT UNSIGNED NOT NULL,
  uuid          CHAR(36) NOT NULL UNIQUE,
  padre_uuid    CHAR(36),
  rol           ENUM('user','assistant') NOT NULL,
  orden         INT UNSIGNED NOT NULL,
  modelo        VARCHAR(64),
  lateral       BOOLEAN NOT NULL DEFAULT FALSE,   -- isSidechain: conversación de un subagente
  creado        DATETIME(3),
  KEY ix_msg_ses (sesion_id, orden),
  CONSTRAINT fk_msg_ses FOREIGN KEY (sesion_id) REFERENCES sesiones(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bloques (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  mensaje_id    BIGINT UNSIGNED NOT NULL,
  orden         SMALLINT UNSIGNED NOT NULL,
  tipo          ENUM('texto','tool_use','tool_result','otro') NOT NULL,
  herramienta   VARCHAR(128),
  tool_use_id   VARCHAR(64),
  contenido     MEDIUMTEXT NOT NULL,              -- redactado y recortado (ver config)
  recortado     BOOLEAN NOT NULL DEFAULT FALSE,
  redacciones   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  KEY ix_bloque_msg (mensaje_id, orden),
  KEY ix_bloque_tool (herramienta),
  FULLTEXT KEY ft_bloque (contenido),
  CONSTRAINT fk_bloque_msg FOREIGN KEY (mensaje_id) REFERENCES mensajes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Derivaciones del agente general a otros agentes.
CREATE TABLE IF NOT EXISTS delegaciones (
  id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  sesion_id           BIGINT UNSIGNED NULL,
  agente_origen_id    INT UNSIGNED NULL,
  agente_destino_id   INT UNSIGNED NOT NULL,
  objetivo            TEXT NOT NULL,
  motivo              TEXT,                        -- por qué se eligió ese agente
  confianza           DECIMAL(4,3),                -- 0-1, si la decidió un clasificador
  estado              ENUM('pendiente','en_curso','completada','fallida','cancelada')
                        NOT NULL DEFAULT 'pendiente',
  resultado           MEDIUMTEXT,
  creado              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  terminado           DATETIME(3),
  KEY ix_del_estado (estado),
  CONSTRAINT fk_del_ses     FOREIGN KEY (sesion_id) REFERENCES sesiones(id) ON DELETE SET NULL,
  CONSTRAINT fk_del_origen  FOREIGN KEY (agente_origen_id) REFERENCES agentes(id) ON DELETE SET NULL,
  CONSTRAINT fk_del_destino FOREIGN KEY (agente_destino_id) REFERENCES agentes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ───────────────────────── memoria granular ─────────────────────────

CREATE TABLE IF NOT EXISTS memorias (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tipo              ENUM('hecho','preferencia','decision','procedimiento','pendiente','referencia')
                      NOT NULL,
  alcance           ENUM('global','proyecto','agente','sesion') NOT NULL DEFAULT 'global',
  proyecto_id       INT UNSIGNED NULL,
  agente_id         INT UNSIGNED NULL,
  sesion_origen_id  BIGINT UNSIGNED NULL,          -- de qué conversación salió
  titulo            VARCHAR(200) NOT NULL,
  contenido         TEXT NOT NULL,
  importancia       TINYINT UNSIGNED NOT NULL DEFAULT 3,   -- 1 (baja) a 5 (crítica)
  vigente           BOOLEAN NOT NULL DEFAULT TRUE,
  valida_hasta      DATETIME NULL,
  reemplaza_id      BIGINT UNSIGNED NULL,          -- memoria que esta corrige/actualiza
  creado            DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  actualizado       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_mem_alcance (alcance, proyecto_id, agente_id, vigente),
  FULLTEXT KEY ft_mem (titulo, contenido),
  CONSTRAINT ck_mem_importancia CHECK (importancia BETWEEN 1 AND 5),
  CONSTRAINT ck_mem_alcance CHECK (
    (alcance = 'global') OR
    (alcance = 'proyecto' AND proyecto_id IS NOT NULL) OR
    (alcance = 'agente'   AND agente_id IS NOT NULL) OR
    (alcance = 'sesion')),                          -- sesion_origen_id puede quedar NULL si se borra
  CONSTRAINT fk_mem_proy    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
  CONSTRAINT fk_mem_agente  FOREIGN KEY (agente_id) REFERENCES agentes(id) ON DELETE CASCADE,
  CONSTRAINT fk_mem_ses     FOREIGN KEY (sesion_origen_id) REFERENCES sesiones(id) ON DELETE SET NULL,
  CONSTRAINT fk_mem_reempl  FOREIGN KEY (reemplaza_id) REFERENCES memorias(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS etiquetas (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(64) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memoria_etiqueta (
  memoria_id   BIGINT UNSIGNED NOT NULL,
  etiqueta_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (memoria_id, etiqueta_id),
  CONSTRAINT fk_me_mem FOREIGN KEY (memoria_id) REFERENCES memorias(id) ON DELETE CASCADE,
  CONSTRAINT fk_me_eti FOREIGN KEY (etiqueta_id) REFERENCES etiquetas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ───────────────────────── auditoría ─────────────────────────

-- Toda escritura hecha por la librería deja rastro: quién, qué, cuándo y el detalle.
CREATE TABLE IF NOT EXISTS auditoria (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tabla        VARCHAR(64) NOT NULL,
  registro_id  BIGINT UNSIGNED NULL,
  accion       VARCHAR(32) NOT NULL,              -- crear | actualizar | borrar | guardar_sesion | ...
  actor        VARCHAR(100) NOT NULL,
  detalle      JSON,
  creado       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY ix_aud (tabla, registro_id),
  KEY ix_aud_fecha (creado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migraciones (version) VALUES ('001_esquema');
