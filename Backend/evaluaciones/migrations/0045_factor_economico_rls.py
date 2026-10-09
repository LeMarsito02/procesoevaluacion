from django.db import migrations

CONDICION = (
    "current_setting('app.entidad_id', true) = '*' "
    "OR entidad_id::text = current_setting('app.entidad_id', true)"
)
TABLAS = ("evaluaciones_factoreconomico", "evaluaciones_ofertaeconomica")


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0044_factor_economico")]
    operations = [
        migrations.RunSQL(
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY aislamiento_entidad ON {t} USING ({CONDICION}) WITH CHECK ({CONDICION});",
            f"DROP POLICY IF EXISTS aislamiento_entidad ON {t}; ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY; "
            f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;",
        )
        for t in TABLAS
    ]
