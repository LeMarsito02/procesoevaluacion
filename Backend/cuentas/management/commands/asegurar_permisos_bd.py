"""Deja los permisos de la base como los exige la bitácora inmodificable
(RF-20 del contrato con el ICCU, M1):

- Las tablas son del rol de mantenimiento (el que corre este comando y las
  migraciones), no del rol de la aplicación. Así la aplicación no puede
  desactivar el trigger que protege la auditoría ni cambiar los permisos.
- La aplicación puede leer y escribir sus tablas, pero en la auditoría solo
  leer y agregar: sin UPDATE, DELETE ni TRUNCATE.

    manage.py asegurar_permisos_bd --rol-app mievaluador_app            # aplica
    manage.py asegurar_permisos_bd --rol-app mievaluador_app --verificar # solo revisa

Es idempotente: el contenedor de migraciones lo corre en cada despliegue,
justo después de `migrate`, y sirve también para pasar una instalación vieja
(donde la aplicación era dueña de todo) al esquema nuevo. Sale con error si
algo no quedó como debe.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql

AUDITORIA = "cuentas_eventoauditoria"


def revisar(rol_app: str) -> list[str]:
    """Lo que no está como debe (vacío = todo bien)."""
    problemas: list[str] = []
    with connection.cursor() as c:
        c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", [rol_app])
        fila = c.fetchone()
        if fila is None:
            return [f"No existe el rol {rol_app}."]
        if fila[0] or fila[1]:
            problemas.append(f"El rol {rol_app} es superusuario o salta la seguridad por fila.")
        c.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner = %s ORDER BY tablename", [rol_app]
        )
        propias = [t for (t,) in c.fetchall()]
        if propias:
            problemas.append(f"El rol {rol_app} es dueño de {len(propias)} tablas (por ejemplo {propias[0]}).")
        for permiso in ("UPDATE", "DELETE", "TRUNCATE"):
            c.execute("SELECT has_table_privilege(%s, %s, %s)", [rol_app, AUDITORIA, permiso])
            if c.fetchone()[0]:
                problemas.append(f"El rol {rol_app} tiene {permiso} sobre la auditoría.")
        for permiso in ("SELECT", "INSERT"):
            c.execute("SELECT has_table_privilege(%s, %s, %s)", [rol_app, AUDITORIA, permiso])
            if not c.fetchone()[0]:
                problemas.append(f"El rol {rol_app} no tiene {permiso} sobre la auditoría: la aplicación no podría registrar.")
        c.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND tgenabled <> 'D' AND NOT tgisinternal",
            [AUDITORIA],
        )
        activos = {t for (t,) in c.fetchall()}
        for trigger in ("auditoria_inmutable", "auditoria_sin_truncate"):
            if trigger not in activos:
                problemas.append(f"El trigger {trigger} no está activo.")
    return problemas


class Command(BaseCommand):
    help = "Quita al rol de la aplicación la propiedad de las tablas y el permiso de alterar la auditoría."

    def add_arguments(self, parser):
        parser.add_argument("--rol-app", required=True)
        parser.add_argument("--verificar", action="store_true", help="Solo revisa; no cambia nada.")

    def handle(self, *args, **o):
        rol = o["rol_app"]
        with connection.cursor() as c:
            c.execute("SELECT current_user")
            actual = c.fetchone()[0]
        if not o["verificar"]:
            if actual == rol:
                raise CommandError(
                    f"Este comando lo corre el rol de mantenimiento, no {rol}: si lo corre la aplicación, sigue siendo dueña de las tablas."
                )
            ident = sql.Identifier(rol)
            with connection.cursor() as c:
                c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [rol])
                if c.fetchone() is None:
                    raise CommandError(f"No existe el rol {rol}.")
                # Una instalación vieja: la aplicación era dueña de todo.
                c.execute(sql.SQL("REASSIGN OWNED BY {} TO CURRENT_USER").format(ident))
                c.execute(sql.SQL("ALTER SCHEMA public OWNER TO CURRENT_USER"))
                for orden in (
                    "GRANT CONNECT ON DATABASE {db} TO {rol}",
                    "GRANT USAGE ON SCHEMA public TO {rol}",
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {rol}",
                    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {rol}",
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {rol}",
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {rol}",
                    "REVOKE UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON " + AUDITORIA + " FROM {rol}",
                ):
                    c.execute(sql.SQL(orden).format(rol=ident, db=sql.Identifier(connection.settings_dict["NAME"])))
            self.stdout.write(f"Permisos aplicados: {rol} ya no es dueño de las tablas y no puede alterar la auditoría.")
        problemas = revisar(rol)
        for p in problemas:
            self.stdout.write(self.style.ERROR(f"  {p}"))
        if problemas:
            raise CommandError("Los permisos de la base no protegen la auditoría.")
        self.stdout.write("Auditoría protegida: la aplicación solo puede leerla y agregar eventos.")
