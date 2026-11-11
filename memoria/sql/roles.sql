-- memoria · roles y usuarios (se ejecuta como root; no es una migración).
-- {{DB}}, {{AGENTE_PASS}}, {{LECTOR_PASS}} se reemplazan al aplicar
-- (docker/initdb/900_roles.sh o `memoria roles`).
--
--   memoria_app     la librería/CLI: lee y escribe todo (lo usa el usuario de MARIADB_USER)
--   memoria_agente  lo que puede tocar un agente: leer catálogo, escribir memorias y delegaciones
--   memoria_lector  solo lectura (dashboards, análisis)

CREATE ROLE IF NOT EXISTS memoria_app;
CREATE ROLE IF NOT EXISTS memoria_agente;
CREATE ROLE IF NOT EXISTS memoria_lector;

GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW ON `{{DB}}`.* TO memoria_app;

GRANT SELECT ON `{{DB}}`.* TO memoria_lector;

GRANT SELECT ON `{{DB}}`.v_agentes TO memoria_agente;
GRANT SELECT ON `{{DB}}`.v_memorias_vigentes TO memoria_agente;
GRANT SELECT ON `{{DB}}`.v_resumenes TO memoria_agente;
GRANT SELECT ON `{{DB}}`.v_delegaciones TO memoria_agente;
GRANT SELECT ON `{{DB}}`.proyectos TO memoria_agente;
GRANT SELECT ON `{{DB}}`.agentes TO memoria_agente;
GRANT SELECT ON `{{DB}}`.etiquetas TO memoria_agente;
GRANT SELECT, INSERT, UPDATE ON `{{DB}}`.memorias TO memoria_agente;
GRANT SELECT, INSERT, DELETE ON `{{DB}}`.memoria_etiqueta TO memoria_agente;
GRANT INSERT ON `{{DB}}`.etiquetas TO memoria_agente;
GRANT SELECT, INSERT, UPDATE ON `{{DB}}`.delegaciones TO memoria_agente;
GRANT INSERT ON `{{DB}}`.auditoria TO memoria_agente;
GRANT SELECT, INSERT, UPDATE ON `{{DB}}`.voces_agente TO memoria_agente;

CREATE USER IF NOT EXISTS 'memoria_agente'@'%' IDENTIFIED BY '{{AGENTE_PASS}}';
CREATE USER IF NOT EXISTS 'memoria_lector'@'%' IDENTIFIED BY '{{LECTOR_PASS}}';
GRANT memoria_agente TO 'memoria_agente'@'%';
GRANT memoria_lector TO 'memoria_lector'@'%';
SET DEFAULT ROLE memoria_agente FOR 'memoria_agente'@'%';
SET DEFAULT ROLE memoria_lector FOR 'memoria_lector'@'%';
