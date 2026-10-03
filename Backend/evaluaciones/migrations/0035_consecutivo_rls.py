from django.db import migrations

CONDICION = (
    "current_setting('app.entidad_id', true) = '*' "
    "OR entidad_id::text = current_setting('app.entidad_id', true)"
)
TABLA = "evaluaciones_consecutivo"


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0034_consecutivo_documentos")]
    operations = [
        migrations.RunSQL(
            f"ALTER TABLE {TABLA} ENABLE ROW LEVEL SECURITY; ALTER TABLE {TABLA} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY aislamiento_entidad ON {TABLA} USING ({CONDICION}) WITH CHECK ({CONDICION});",
            f"DROP POLICY IF EXISTS aislamiento_entidad ON {TABLA}; ALTER TABLE {TABLA} NO FORCE ROW LEVEL SECURITY; "
            f"ALTER TABLE {TABLA} DISABLE ROW LEVEL SECURITY;",
        )
    ]
