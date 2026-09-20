"""Isolated monitoring tests; never connect to an application database."""
import os

SECRET_KEY = 'isolated-storage-test-settings-only'
DEBUG = True
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
INSTALLED_APPS = [
    'gadmin.monitoring.apps.MonitoringConfig',
    'gadmin.monitoring.apps.MonitoringAdminConfig',
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.environ.get('STORAGE_PREVIEW_DB', ':memory:')}}
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
              'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request',
                  'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages']}}]
ROOT_URLCONF = 'gadmin.monitoring.tests.urls'
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_TZ = True
STATIC_URL = '/static/'
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
STORAGE_METRICS_DIR = os.environ.get('STORAGE_METRICS_DIR', '/nonexistent/storage-test')
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
