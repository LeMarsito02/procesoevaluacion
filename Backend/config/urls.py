from django.contrib import admin
from django.urls import path

from api.api import api

admin.site.site_header = "MiEvaluador · Administración"
admin.site.site_title = "MiEvaluador"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
