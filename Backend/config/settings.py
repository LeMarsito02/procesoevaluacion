"""Configuración de Django para MiEvaluador.

Todo valor sensible o que cambia entre entornos se lee de variables de entorno
(archivo `.env` en desarrollo, fuera de git). Los valores por defecto son los
seguros para producción: si falta una variable, falla en vez de quedar abierto.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _lista(variable: str, defecto: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(variable, defecto).split(",") if v.strip()]


def _ips_locales() -> list[str]:
    """IPs del equipo en la red local (para el entorno de desarrollo, donde la
    dirección cambia según la red a la que esté conectado)."""
    import socket

    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 1))  # no envía nada: solo resuelve la interfaz de salida
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = _lista("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "cuentas",
    "api",
    "evaluaciones",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "cuentas.aislamiento.AislamientoMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NOMBRE", "mievaluador"),
        "USER": os.environ.get("DB_USUARIO", "mievaluador"),
        "PASSWORD": os.environ.get("DB_CLAVE", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PUERTO", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

# --- Usuarios y contraseñas ---
AUTH_USER_MODEL = "cuentas.Usuario"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Sesión y cookies ---
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 10  # jornada laboral
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = _lista("CORS_ORIGENES")

# --- CORS (frontend en otro puerto/dominio) ---
CORS_ALLOWED_ORIGINS = _lista("CORS_ORIGENES")

# En desarrollo, si se expone el entorno a la red local, se aceptan también las
# direcciones del equipo (cambian según la red). En producción no aplica.
if DEBUG and os.environ.get("EXPONER_EN_RED") == "1":
    _PUERTO_APP = os.environ.get("PUERTO_APP", "5173")
    for _ip in _ips_locales():
        if _ip not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_ip)
        _origen = f"http://{_ip}:{_PUERTO_APP}"
        if _origen not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(_origen)
            CSRF_TRUSTED_ORIGINS.append(_origen)
CORS_ALLOW_CREDENTIALS = True
# Cabeceras propias que el frontend necesita leer (la fecha que el
# programa alcanzó a leer en la cédula y el nombre del archivo).
CORS_EXPOSE_HEADERS = ["X-Fecha-Sugerida", "X-Archivo"]

# --- Seguridad en producción ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

# Los Documentos Base y las ofertas pueden pesar decenas de MB.
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
PLANTILLA_MAX_BYTES = 20 * 1024 * 1024
# --- Límites de peticiones (por usuario o por IP) ---
# Caché en archivos: la comparten todos los procesos del servidor y funciona en
# vistas asíncronas (la de base de datos no). Con varios servidores: Redis.
_EN_PRUEBAS = len(sys.argv) > 1 and sys.argv[1] == "test"
CACHES = {
    "default": (
        # Las pruebas no deben compartir contadores con el servidor en marcha.
        {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        if _EN_PRUEBAS
        else {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": os.environ.get("CACHE_LIMITES_DIR", str(BASE_DIR / "cache" / "limites")),
        }
    )
}
# Proxies de confianza delante de la app (LeMarCloud + nginx = 2). Con eso la IP
# del usuario se toma de X-Forwarded-For sin que un cliente pueda falsificarla.
# En desarrollo (sin proxy): 0.
NINJA_NUM_PROXIES = int(os.environ.get("PROXIES_CONFIABLES", "0"))
LIMITES_API = {
    # Alto: todos los funcionarios de una entidad pueden salir por la misma IP.
    "anonimo": "100000/m" if _EN_PRUEBAS else os.environ.get("LIMITE_ANONIMO", "300/m"),
    "usuario": "100000/m" if _EN_PRUEBAS else os.environ.get("LIMITE_USUARIO", "600/m"),
    # Operaciones pesadas (leen documentos o usan la IA).
    "pesado": "100000/h" if _EN_PRUEBAS else os.environ.get("LIMITE_PESADO", "60/h"),
}

# Días que se conservan los documentos de los proponentes tras aprobar el proceso.
RETENCION_DIAS = int(os.environ.get("RETENCION_DIAS", "30"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Archivos subidos (plantillas de informe, etc.), separados por entidad. No se
# sirven públicamente: solo se entregan por la API con permisos.
MEDIA_ROOT = Path(os.environ.get("ALMACENAMIENTO_DIR", str(BASE_DIR / "almacenamiento")))
MEDIA_URL = "/no-publico/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

_CORREO_BACKEND = os.environ.get("CORREO_BACKEND", "django.core.mail.backends.console.EmailBackend")
if _CORREO_BACKEND.endswith("smtp.EmailBackend"):
    _CORREO_PUERTO = int(os.environ.get("CORREO_PUERTO", "587"))
    _CORREO_OPCIONES = {
        "host": os.environ["CORREO_SERVIDOR"],
        "port": _CORREO_PUERTO,
        "username": os.environ.get("CORREO_USUARIO", ""),
        "password": os.environ.get("CORREO_CLAVE", ""),
        # 465 = SSL directo; 587 = STARTTLS.
        "use_ssl": _CORREO_PUERTO == 465,
        "use_tls": _CORREO_PUERTO != 465 and os.environ.get("CORREO_TLS", "1") == "1",
        "timeout": 20,
    }
elif _CORREO_BACKEND.endswith("filebased.EmailBackend"):
    # Desarrollo: cada correo queda como archivo en esta carpeta.
    _CORREO_OPCIONES = {"file_path": os.environ.get("CORREO_CARPETA", str(BASE_DIR / ".scratch" / "correos"))}
else:
    _CORREO_OPCIONES = {}
MAILERS = {"default": {"BACKEND": _CORREO_BACKEND, "OPTIONS": _CORREO_OPCIONES}}

DEFAULT_FROM_EMAIL = os.environ.get("CORREO_REMITENTE", "MiEvaluador <no-responder@lemartek.com>")
# Enlaces de los correos (avisos de cuenta, recuperación de contraseña).
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
# Tiempo de validez del enlace de recuperación de contraseña (segundos).
PASSWORD_RESET_TIMEOUT = 60 * 60 * 2
# El panel de Django no pide segundo factor: en producción solo se publica
# si se habilita explícitamente (y detrás de VPN).
ADMIN_DJANGO_HABILITADO = DEBUG or os.environ.get("ADMIN_DJANGO", "0") == "1"


# Registro: advertencias en adelante para todo, e información de la verificación
# de reCAPTCHA (puntaje de cada acceso) y de la fila de evaluación.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["consola"], "level": "WARNING"},
    "loggers": {
        "cuentas.recaptcha": {"handlers": ["consola"], "level": "INFO", "propagate": False},
    },
}
