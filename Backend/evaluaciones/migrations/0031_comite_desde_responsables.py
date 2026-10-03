"""Las evaluaciones creadas antes del comité tenían un solo responsable: pasa
a ser el coordinador de su comité (sin documento de designación, que solo se
genera cuando un jefe designa)."""
from django.db import migrations


def pasar(apps, schema_editor):
    Evaluacion = apps.get_model("evaluaciones", "Evaluacion")
    MiembroComite = apps.get_model("evaluaciones", "MiembroComite")
    con_comite = set(MiembroComite.objects.values_list("evaluacion_id", flat=True))
    MiembroComite.objects.bulk_create(
        MiembroComite(
            entidad_id=e.entidad_id, evaluacion_id=e.id, usuario_id=e.responsable_id,
            designado_por_id=e.asignada_por_id or e.responsable_id,
        )
        for e in Evaluacion.objects.filter(responsable__isnull=False).exclude(id__in=con_comite)
    )


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0030_designacion_en_cascada")]
    operations = [migrations.RunPython(pasar, migrations.RunPython.noop)]
