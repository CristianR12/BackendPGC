"""
Django settings for api_project project.
Adaptado para trabajar con Firebase + Django REST Framework
"""

from pathlib import Path
import json
import firebase_admin
import os
from django.core.exceptions import ImproperlyConfigured
from firebase_admin import credentials
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------
# Seguridad
# -------------------------
DEBUG = os.getenv('DJANGO_DEBUG', 'False') == 'True'

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'solo-para-desarrollo-local-no-usar-en-produccion'
    else:
        raise ImproperlyConfigured('Falta la variable de entorno DJANGO_SECRET_KEY.')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
# Render define esta variable con el dominio público del servicio (xxx.onrender.com)
_render_host = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

# -------------------------
# Registro de docentes
# -------------------------
# Administradores (correos separados por coma): aprueban solicitudes y autorizan docentes. Siempre
# deben tener el correo verificado. Se define solo aquí, nunca desde la base de datos ni el navegador.
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv('ADMIN_EMAILS', '').split(',') if e.strip()}
# Dominios que pueden registrarse (los administradores quedan exentos)
REGISTRO_DOMINIOS = [d.strip().lower().lstrip('@') for d in os.getenv('REGISTRO_DOMINIOS', 'ucundinamarca.edu.co').split(',') if d.strip()]

# -------------------------
# Apps instaladas
# -------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Terceros (corsheaders DEBE estar antes de tu app)
    'corsheaders',
    'rest_framework',

    # Tu app
    'api_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # ← DEBE estar AQUÍ (segundo)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'api_project.urls'

# -------------------------
# CONFIGURACIÓN DE CORS (CRÍTICO)
# -------------------------

# En desarrollo permitir todos, en producción usar lista específica
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]

# Permitir credenciales (cookies, auth headers)
CORS_ALLOW_CREDENTIALS = True

# Headers permitidos
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Métodos HTTP permitidos
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# -------------------------
# Templates
# -------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'api_project.wsgi.application'

# -------------------------
# Base de datos (Firebase → no SQL)
# -------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.dummy',
    }
}

# -------------------------
# REST Framework Configuration
# -------------------------
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
}

# -------------------------
# Passwords
# -------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# -------------------------
# Internacionalización
# -------------------------
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# -------------------------
# Archivos estáticos
# -------------------------
STATIC_URL = '/static/'
STATIC_ROOT = os.getenv('STATIC_ROOT', BASE_DIR / 'staticfiles')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# -------------------------
# Producción detrás del proxy de Render (HTTPS lo termina Render)
# -------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'

# -------------------------
# Firebase Config
# -------------------------
# Dos formas de entregar las credenciales (la primera tiene prioridad):
#   FIREBASE_CREDENTIALS_JSON  -> contenido completo del JSON (ideal en Render, sin archivos)
#   FIREBASE_CREDENTIALS_PATH  -> ruta al archivo JSON (desarrollo local)
firebase_cred_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
if firebase_cred_json:
    cred = credentials.Certificate(json.loads(firebase_cred_json))
else:
    firebase_cred_path = os.getenv(
        'FIREBASE_CREDENTIALS_PATH',
        'CredencialesFirebase/asistenciaconreconocimiento-firebase-adminsdk.json'
    )
    cred_file = BASE_DIR / firebase_cred_path
    if not cred_file.exists():
        raise ImproperlyConfigured(
            f'No se encontraron las credenciales de Firebase en {cred_file}. '
            'Define FIREBASE_CREDENTIALS_JSON o FIREBASE_CREDENTIALS_PATH.'
        )
    cred = credentials.Certificate(cred_file)
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)