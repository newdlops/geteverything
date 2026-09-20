"""Backend checks for the worker image, which has no web authentication stack."""
SECRET_KEY = 'isolated-product-worker-checks'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'gadmin.categories.tests.apps.TestDealsConfig']
MIGRATION_MODULES = {'deals': None}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
SILENCED_SYSTEM_CHECKS = ['fields.E120']
ROOT_URLCONF = __name__
urlpatterns = []

from django.db.backends.sqlite3.base import DatabaseWrapper
DatabaseWrapper.data_types = {**DatabaseWrapper.data_types, 'CharField': 'text'}
