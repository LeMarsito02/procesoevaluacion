#!/bin/bash
# Crea el rol de la aplicación SIN superusuario ni BYPASSRLS (si no, la
# Row-Level Security entre entidades no se aplicaría) y SIN ser dueño de nada:
# las tablas son del rol de mantenimiento (POSTGRES_USER), que corre las
# migraciones. Así la aplicación no puede desactivar el trigger de la
# auditoría (RF-20). Los permisos finos los deja `manage.py asegurar_permisos_bd`.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE ${DB_USUARIO:-mievaluador_app} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '${DB_CLAVE}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${DB_USUARIO:-mievaluador_app};
GRANT USAGE ON SCHEMA public TO ${DB_USUARIO:-mievaluador_app};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${DB_USUARIO:-mievaluador_app};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ${DB_USUARIO:-mievaluador_app};
SQL
