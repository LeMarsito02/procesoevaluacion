from django.apps import AppConfig


class CuentasConfig(AppConfig):
    name = 'cuentas'

    def ready(self):
        from cuentas import aislamiento  # noqa: F401  (registra la señal de conexión)
