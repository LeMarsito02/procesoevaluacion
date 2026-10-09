"""Almacenamiento de los archivos subidos, cifrado en reposo (RF-21).

Cifra al guardar y descifra al abrir: el resto de la aplicación usa
`archivo.open()` como siempre. Las plantillas de informe no llevan datos
personales y se leen por su ruta (openpyxl), así que se guardan en claro.
"""
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from motor import cifrado


def _en_claro(nombre: str) -> bool:
    return "/plantillas/" in f"/{nombre}"


class AlmacenamientoCifrado(FileSystemStorage):
    def _save(self, name, content):
        if _en_claro(name) or not cifrado.activo():
            return super()._save(name, content)
        if hasattr(content, "seek"):
            content.seek(0)
        return super()._save(name, ContentFile(cifrado.cifrar(content.read())))

    def _open(self, name, mode="rb"):
        if "w" in mode or "a" in mode:
            raise ValueError("Los archivos cifrados no se abren para escribir: guárdelos de nuevo.")
        with open(self.path(name), "rb") as f:
            datos = f.read()
        return ContentFile(cifrado.descifrar(datos), name=name)

    def size(self, name):
        with open(self.path(name), "rb") as f:
            cabecera = f.read(len(cifrado.MAGIA))
        if cabecera != cifrado.MAGIA:
            return super().size(name)
        return len(self._open(name).read())
