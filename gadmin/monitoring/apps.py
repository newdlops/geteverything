from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class MonitoringConfig(AppConfig):
    name = 'gadmin.monitoring'
    verbose_name = '서버 운영'


class MonitoringAdminConfig(AdminConfig):
    default_site = 'gadmin.monitoring.admin_site.MonitoringAdminSite'
