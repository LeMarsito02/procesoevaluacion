from django.db import migrations

CONDICION = (
    "current_setting('app.entidad_id', true) = '*' "
    "OR entidad_id::text = current_setting('app.entidad_id', true)"
)
T = "evaluaciones_analisiscoincidencias"


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0046_coincidencias")]
    operations = [
        migrations.RunSQL(
            f"ALTER TABLE {T} ENABLE ROW LEVEL SECURITY; ALTER TABLE {T} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY aislamiento_entidad ON {T} USING ({CONDICION}) WITH CHECK ({CONDICION});",
            f"DROP POLICY IF EXISTS aislamiento_entidad ON {T}; ALTER TABLE {T} NO FORCE ROW LEVEL SECURITY; ALTER TABLE {T} DISABLE ROW LEVEL SECURITY;",
        )
    ]
