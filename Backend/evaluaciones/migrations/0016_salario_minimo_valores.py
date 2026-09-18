from django.db import migrations

# Valores oficiales (decretos del Gobierno Nacional).
VALORES = [
    (2024, 1_300_000, "Decreto 2292 de 2023"),
    (2025, 1_423_500, "Decreto 1572 de 2024"),
    (2026, 1_750_905, "Decreto 1469 de 2025"),
]


def cargar(apps, schema_editor):
    SalarioMinimo = apps.get_model("evaluaciones", "SalarioMinimo")
    for ano, valor, norma in VALORES:
        SalarioMinimo.objects.update_or_create(ano=ano, defaults={"valor": valor, "norma": norma})


class Migration(migrations.Migration):
    dependencies = [("evaluaciones", "0015_salario_minimo")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
