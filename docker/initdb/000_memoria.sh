#!/bin/bash
# Primer arranque del contenedor: esquema + roles + usuarios. Las migraciones posteriores se
# aplican con `memoria migrar` (registra lo aplicado en schema_migraciones).
set -euo pipefail
cliente() { mariadb -uroot -p"${MARIADB_ROOT_PASSWORD}" "$@"; }

for f in /memoria-sql/[0-9][0-9][0-9]_*.sql; do
  echo "memoria: aplicando $(basename "$f")"
  cliente "${MARIADB_DATABASE}" < "$f"
done

# escapa lo que sed interpretaría en el reemplazo (las claves no deben llevar comillas simples)
esc() { printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'; }
sed -e "s|{{DB}}|$(esc "${MARIADB_DATABASE}")|g" \
    -e "s|{{AGENTE_PASS}}|$(esc "${MEMORIA_AGENTE_PASSWORD:?falta MEMORIA_AGENTE_PASSWORD}")|g" \
    -e "s|{{LECTOR_PASS}}|$(esc "${MEMORIA_LECTOR_PASSWORD:?falta MEMORIA_LECTOR_PASSWORD}")|g" \
    /memoria-sql/roles.sql | cliente

# MARIADB_USER (la app/CLI) conserva ALL sobre la base: es quien corre `memoria migrar`.
# Los agentes usan memoria_agente y los tableros memoria_lector (permisos acotados).
echo "memoria: listo"
