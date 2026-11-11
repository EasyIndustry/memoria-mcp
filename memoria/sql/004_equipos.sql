-- memoria · equipos de agentes: roles, miembros, identidad estable y MCPs base / a pedido.
--
-- Un ROL (es_rol) es una plantilla global: devops, backend, designer, compras...
-- Un MIEMBRO es un agente con rol_id (y en general proyecto_id): devops-str = devops en STR.
-- Al resolver un miembro se hereda lo del rol (secciones, skills, MCPs) y se suma lo propio.
-- uid: id estable que no cambia aunque se renombre; es el que guarda Denis (agents.identity).

ALTER TABLE agentes
  ADD COLUMN uid          CHAR(36) NULL AFTER id,
  ADD COLUMN es_rol       BOOLEAN NOT NULL DEFAULT FALSE AFTER es_general,
  ADD COLUMN es_lider     BOOLEAN NOT NULL DEFAULT FALSE AFTER es_rol,  -- puede crear miembros y repartir trabajo
  ADD COLUMN rol_id       INT UNSIGNED NULL AFTER es_lider,
  ADD COLUMN proyecto_id  INT UNSIGNED NULL AFTER rol_id;

UPDATE agentes SET uid = UUID() WHERE uid IS NULL;

ALTER TABLE agentes
  MODIFY uid CHAR(36) NOT NULL,
  ADD UNIQUE KEY uq_agente_uid (uid),
  ADD CONSTRAINT fk_agente_rol  FOREIGN KEY (rol_id) REFERENCES agentes(id) ON DELETE SET NULL,
  ADD CONSTRAINT fk_agente_proy FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE SET NULL;

-- base: se conecta al arrancar · a_pedido: el agente lo pide cuando lo necesita.
ALTER TABLE agente_mcp
  ADD COLUMN modo ENUM('base','a_pedido') NOT NULL DEFAULT 'base';

CREATE OR REPLACE VIEW v_agentes AS
SELECT a.id, a.uid, a.nombre, a.descripcion, a.modelo, a.es_general, a.es_rol, a.es_lider,
       r.nombre AS rol, p.nombre AS proyecto, a.version,
       (SELECT GROUP_CONCAT(s.nombre ORDER BY s.nombre SEPARATOR ',')
          FROM agente_skill x JOIN skills s ON s.id = x.skill_id
         WHERE x.agente_id = a.id AND s.activo) AS skills,
       a.actualizado
  FROM agentes a
  LEFT JOIN agentes r ON r.id = a.rol_id
  LEFT JOIN proyectos p ON p.id = a.proyecto_id
 WHERE a.activo;
