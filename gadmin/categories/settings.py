"""Minimal worker settings: no admin, web server or browser processes."""
import os

SECRET_KEY = 'category-worker-does-not-serve-http'
INSTALLED_APPS = ['gadmin.deals']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'UTC'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ['DATABASE_NAME'], 'HOST': os.environ['DATABASE_HOST'],
    'USER': os.environ['DATABASE_USER'], 'PASSWORD': os.environ['DATABASE_PASSWORD'],
    'PORT': os.environ.get('DATABASE_PORT', '5432'), 'CONN_MAX_AGE': 60,
    'OPTIONS': {'connect_timeout': 5, 'application_name': 'geteverything-category-worker',
                'options': '-c statement_timeout=5000 -c lock_timeout=2000'},
}}
