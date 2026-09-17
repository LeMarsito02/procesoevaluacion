#!/bin/bash
# Crea el rol de la aplicación SIN superusuario ni BYPASSRLS (si no, la
# Row-Level Security entre entidades no se aplicaría) y le da la base.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE ${DB_USUARIO:-mievaluador_app} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB PASSWORD '${DB_CLAVE}';
ALTER DATABASE ${POSTGRES_DB} OWNER TO ${DB_USUARIO:-mievaluador_app};
ALTER SCHEMA public OWNER TO ${DB_USUARIO:-mievaluador_app};
SQL
