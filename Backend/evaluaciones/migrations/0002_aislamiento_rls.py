"""Row-Level Security: cada fila solo es visible para la entidad fijada en la
variable de sesión `app.entidad_id` ('*' = contexto de sistema o superadmin).
FORCE aplica la política también al dueño de las tablas (el usuario de la app)."""
from django.db import migrations

TABLAS = [
    "evaluaciones_proceso",
    "evaluaciones_proponente",
    "evaluaciones_evaluacion",
    "evaluaciones_resultado",
    "evaluaciones_revision",
]

CONDICION = (
    "current_setting('app.entidad_id', true) = '*' "
    "OR entidad_id::text = current_setting('app.entidad_id', true)"
)


def activar():
    return "\n".join(
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
        f"CREATE POLICY aislamiento_entidad ON {t} USING ({CONDICION}) WITH CHECK ({CONDICION});"
        for t in TABLAS
    )


def desactivar():
    return "\n".join(
        f"DROP POLICY IF EXISTS aislamiento_entidad ON {t}; ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY; "
        f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;"
        for t in TABLAS
    )


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0001_initial")]
    operations = [migrations.RunSQL(activar(), desactivar())]
