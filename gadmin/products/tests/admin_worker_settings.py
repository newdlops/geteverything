"""Minimal isolated settings for product-admin form tests."""
SECRET_KEY = 'isolated-product-admin-checks'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'gadmin.categories.tests.apps.TestDealsConfig',
]
MIGRATION_MODULES = {'deals': None}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
STATIC_URL = '/static/'
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
              'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request',
                  'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages']}}]
ROOT_URLCONF = 'gadmin.products.tests.admin_urls'
SILENCED_SYSTEM_CHECKS = ['fields.E120']

from django.db.backends.sqlite3.base import DatabaseWrapper
DatabaseWrapper.data_types = {**DatabaseWrapper.data_types, 'CharField': 'text'}
