# crawlers/django_setup.py
import os
import django

# 환경변수에서 넘겨받고, 없으면 기본값
DJANGO_SETTINGS_MODULE = os.getenv(
    "DJANGO_SETTINGS_MODULE",
    "gadmin.admin.settings",  # 예: 배포용 settings
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", DJANGO_SETTINGS_MODULE)

django.setup()
