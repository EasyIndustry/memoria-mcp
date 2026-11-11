-- memoria · vistas de lectura para agentes (acceso granular sin exponer tablas crudas)

CREATE OR REPLACE VIEW v_agentes AS
SELECT a.id, a.nombre, a.descripcion, a.modelo, a.es_general, a.version,
       (SELECT GROUP_CONCAT(s.nombre ORDER BY s.nombre SEPARATOR ',')
          FROM agente_skill x JOIN skills s ON s.id = x.skill_id
         WHERE x.agente_id = a.id AND s.activo) AS skills,
       a.actualizado
  FROM agentes a
 WHERE a.activo;

CREATE OR REPLACE VIEW v_memorias_vigentes AS
SELECT m.id, m.tipo, m.alcance, p.nombre AS proyecto, a.nombre AS agente,
       m.titulo, m.contenido, m.importancia, m.sesion_origen_id,
       (SELECT GROUP_CONCAT(e.nombre ORDER BY e.nombre SEPARATOR ',')
          FROM memoria_etiqueta me JOIN etiquetas e ON e.id = me.etiqueta_id
         WHERE me.memoria_id = m.id) AS etiquetas,
       m.creado, m.actualizado
  FROM memorias m
  LEFT JOIN proyectos p ON p.id = m.proyecto_id
  LEFT JOIN agentes a ON a.id = m.agente_id
 WHERE m.vigente AND (m.valida_hasta IS NULL OR m.valida_hasta > NOW());

CREATE OR REPLACE VIEW v_resumenes AS
SELECT r.id, s.session_uuid, s.titulo, p.nombre AS proyecto, a.nombre AS agente,
       r.disparador, r.tokens_antes, r.tokens_despues, r.compactado, r.contenido
  FROM resumenes r
  JOIN sesiones s ON s.id = r.sesion_id
  LEFT JOIN proyectos p ON p.id = s.proyecto_id
  LEFT JOIN agentes a ON a.id = s.agente_id;

CREATE OR REPLACE VIEW v_delegaciones AS
SELECT d.id, o.nombre AS origen, t.nombre AS destino, d.objetivo, d.motivo, d.confianza,
       d.estado, d.resultado, d.creado, d.terminado
  FROM delegaciones d
  LEFT JOIN agentes o ON o.id = d.agente_origen_id
  JOIN agentes t ON t.id = d.agente_destino_id;

INSERT IGNORE INTO schema_migraciones (version) VALUES ('002_vistas');
