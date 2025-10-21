"""
Django settings for api_project project.

Adaptado para trabajar con Firebase + Django REST Framework
"""

from pathlib import Path
import firebase_admin
from firebase_admin import credentials


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------
# Seguridad
# -------------------------
SECRET_KEY = 'django-insecure-)%(502kzlli4p-7cvm3eenaqtn&lrqc_k52)aef764gn$zx1wr'
DEBUG = True
ALLOWED_HOSTS = []

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
    'corsheaders',
    # Terceros
    'rest_framework',

    # Tu app
    'api_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
]

ROOT_URLCONF = 'api_project.urls'

CORS_ALLOW_ALL_ORIGINS=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
 ]

CORS_ALLOW_ALL_ORIGINS = True

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

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],  # soporte para HTML si usas vistas
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
        'ENGINE': 'django.db.backends.dummy',  # no usamos ORM de Django
    }
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
STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = True 

# -------------------------
# Firebase Config
# -------------------------
cred = credentials.Certificate(
    BASE_DIR / "CredencialesFirebase" / "asistenciaconreconocimiento-firebase-adminsdk.json"
)
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)
