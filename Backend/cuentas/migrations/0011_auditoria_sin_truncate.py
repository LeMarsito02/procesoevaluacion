"""TRUNCATE no dispara los triggers por fila: uno aparte lo rechaza también
(RF-20, bitácora inmodificable). Lo que falta para que ni siquiera el dueño de
la tabla pueda saltárselo lo hace `manage.py asegurar_permisos_bd`."""
from django.db import migrations

CREAR = """
CREATE TRIGGER auditoria_sin_truncate
    BEFORE TRUNCATE ON cuentas_eventoauditoria
    FOR EACH STATEMENT EXECUTE FUNCTION auditoria_inmutable();
"""
QUITAR = "DROP TRIGGER IF EXISTS auditoria_sin_truncate ON cuentas_eventoauditoria;"


class Migration(migrations.Migration):
    dependencies = [("cuentas", "0010_ops")]
    operations = [migrations.RunSQL(CREAR, QUITAR)]
