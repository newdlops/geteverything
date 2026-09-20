"""Local-only tests and browser preview; no production credentials."""
from gadmin.monitoring.tests.settings import *

INSTALLED_APPS += ['gadmin.categories.tests.apps.TestDealsConfig', 'gadmin.user', 'rest_framework']
MIGRATION_MODULES = {'deals': None, 'user': None}
SILENCED_SYSTEM_CHECKS = ['fields.E120']
ROOT_URLCONF = 'gadmin.categories.tests.urls'

# The existing PostgreSQL Deal/User models use unbounded varchar fields.
# SQLite's Django 5.1 backend formats those as varchar(None); text is equivalent here.
from django.db.backends.sqlite3.base import DatabaseWrapper
DatabaseWrapper.data_types = {**DatabaseWrapper.data_types, 'CharField': 'text'}
