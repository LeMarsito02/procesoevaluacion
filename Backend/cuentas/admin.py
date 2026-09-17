from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cuentas.models import Entidad, Usuario


@admin.register(Entidad)
class EntidadAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit", "activa", "creada_en")
    search_fields = ("nombre", "nit")
    list_filter = ("activa",)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    ordering = ("nombre_completo",)
    list_display = ("nombre_completo", "email", "entidad", "rol", "is_active")
    list_filter = ("rol", "entidad", "is_active")
    search_fields = ("nombre_completo", "email")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos", {"fields": ("nombre_completo", "entidad", "rol")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "creado_en")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "nombre_completo", "entidad", "rol", "password1", "password2")}),
    )
