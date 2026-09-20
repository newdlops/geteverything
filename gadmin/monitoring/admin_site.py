from django.contrib.admin import AdminSite
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .storage import storage_context
from .logs import log_context


class MonitoringAdminSite(AdminSite):
    def get_urls(self):
        return [
            path('storage/', self.admin_view(require_GET(self.storage)), name='storage'),
            path('storage/data/', self.admin_view(require_GET(self.storage_data)), name='storage_data'),
            path('logs/', self.admin_view(require_GET(self.logs)), name='logs'),
            path('logs/data/', self.admin_view(require_GET(self.logs_data)), name='logs_data'),
        ] + super().get_urls()

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        if app_label is None and self.has_permission(request):
            url = reverse('admin:storage', current_app=self.name)
            apps.append({
                'name': '서버 운영', 'app_label': 'monitoring', 'app_url': url,
                'has_module_perms': True,
                'models': [{'name': '저장 공간', 'object_name': 'Storage',
                            'perms': {'view': True}, 'admin_url': url,
                            'add_url': None, 'view_only': True}],
            })
            if request.user.is_superuser:
                apps[-1]['models'].append({
                    'name': '크롤러 로그', 'object_name': 'Logs', 'perms': {'view': True},
                    'admin_url': reverse('admin:logs', current_app=self.name),
                    'add_url': None, 'view_only': True,
                })
        return apps

    def storage(self, request):
        request.current_app = self.name
        context = {**self.each_context(request), **storage_context(), 'title': '저장 공간'}
        return TemplateResponse(request, 'monitoring/storage.html', context)

    def storage_data(self, request):
        context = storage_context()
        return JsonResponse({
            'html': render_to_string('monitoring/storage_panels.html', context, request=request),
            'refreshed_at': timezone.localtime(context['checked_at']).strftime('%Y-%m-%d %H:%M:%S'),
        })

    def logs(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        request.current_app = self.name
        return TemplateResponse(request, 'monitoring/logs.html', {
            **self.each_context(request), **log_context(request.GET), 'title': '크롤러 로그',
        })

    def logs_data(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        context = log_context(request.GET)
        return JsonResponse({
            'html': '' if request.GET.get('cursor') else render_to_string('monitoring/log_results.html', context, request=request),
            'page_html': render_to_string('monitoring/log_page.html', context, request=request) if request.GET.get('cursor') else '',
            'next_cursor': context['next_cursor'], 'count': len(context['lines']),
            'displayed_count': context['displayed_count'], 'message': context['message'],
            'error_field': next(iter(context['form_errors']), ''),
            'refreshed_at': timezone.localtime(context['checked_at']).strftime('%Y-%m-%d %H:%M:%S'),
        }, status=context['http_status'])
