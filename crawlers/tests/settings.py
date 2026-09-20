"""Isolated settings for crawler tests; never use the production database."""

SECRET_KEY = "crawler-tests-only"
INSTALLED_APPS = ["gadmin.deals"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# The production PostgreSQL schema allows article_id without max_length.
# These tests mock ORM writes and do not create that schema in SQLite.
SILENCED_SYSTEM_CHECKS = ["fields.E120"]
