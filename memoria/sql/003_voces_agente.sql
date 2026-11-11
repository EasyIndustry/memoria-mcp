-- Perfil de voz de cada sesión/agente lanzado por el orquestador de voz (vozkit).
-- Tabla aparte y no `agentes`: esos son definiciones versionadas que se materializan a
-- .claude/agents (nombre slug); acá van sesiones efímeras con el nombre tal cual lo ve
-- ListAgents ("Agente-Voces"), un dato chico que no necesita versionado ni secciones.

CREATE TABLE IF NOT EXISTS voces_agente (
  nombre       VARCHAR(100) PRIMARY KEY,           -- nombre de la sesión (lanzar_subagente.sh)
  perfil       JSON NOT NULL,                       -- {"base":"grave","tono":-6,...} (vozkit/voces.py)
  creado       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  actualizado  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
