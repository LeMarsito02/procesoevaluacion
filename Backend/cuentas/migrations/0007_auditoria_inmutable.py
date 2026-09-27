"""La auditoría no se puede modificar ni borrar tampoco desde la base de datos
(expediente LEG-004, numeral 4.1).

- Un trigger rechaza todo UPDATE y DELETE sobre la tabla de auditoría, venga
  de la aplicación, de una consulta masiva o de una consola SQL con el rol de
  la aplicación. (TRUNCATE no dispara el trigger: queda reservado al
  administrador de la base, que además deja la cadena de huellas rota.)
- Los eventos que ya existían reciben su huella encadenada, en orden de id.
"""
import hashlib
import json

from django.db import migrations

CREAR = """
CREATE OR REPLACE FUNCTION auditoria_inmutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Los eventos de auditoría no se pueden modificar ni eliminar.';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER auditoria_inmutable
    BEFORE UPDATE OR DELETE ON cuentas_eventoauditoria
    FOR EACH ROW EXECUTE FUNCTION auditoria_inmutable();
"""
QUITAR = """
DROP TRIGGER IF EXISTS auditoria_inmutable ON cuentas_eventoauditoria;
DROP FUNCTION IF EXISTS auditoria_inmutable();
"""


def encadenar_existentes(apps, schema_editor):
    """Huella de los eventos anteriores a esta versión (antes del trigger)."""
    Evento = apps.get_model("cuentas", "EventoAuditoria")
    anterior = ""
    for e in Evento.objects.order_by("id").iterator():
        contenido = json.dumps(
            [e.fecha.isoformat(), str(e.entidad_id or ""), str(e.usuario_id or ""), e.accion, e.objeto_tipo,
             e.objeto_id, e.detalles, e.ip or ""],
            sort_keys=True, ensure_ascii=False, default=str,
        )
        anterior = hashlib.sha256(f"{anterior}|{contenido}".encode()).hexdigest()
        Evento.objects.filter(pk=e.pk).update(huella=anterior)


class Migration(migrations.Migration):
    dependencies = [("cuentas", "0006_cumplimiento_legal")]
    operations = [
        migrations.RunPython(encadenar_existentes, migrations.RunPython.noop),
        migrations.RunSQL(CREAR, QUITAR),
    ]
