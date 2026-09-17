from django.db import migrations

CONDICION = (
    "current_setting('app.entidad_id', true) = '*' "
    "OR entidad_id::text = current_setting('app.entidad_id', true)"
)
TABLAS = ["evaluaciones_personaverificada", "evaluaciones_documentoaportado", "evaluaciones_expediente"]


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0010_personas_aportados_expediente")]
    operations = [
        migrations.RunSQL(
            "\n".join(
                f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
                f"CREATE POLICY aislamiento_entidad ON {t} USING ({CONDICION}) WITH CHECK ({CONDICION});"
                for t in TABLAS
            ),
            "\n".join(
                f"DROP POLICY IF EXISTS aislamiento_entidad ON {t}; ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY; "
                f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;"
                for t in TABLAS
            ),
        )
    ]
