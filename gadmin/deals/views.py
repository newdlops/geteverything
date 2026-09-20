
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly, SAFE_METHODS
from rest_framework.pagination import CursorPagination

from gadmin.deals.models import Deal
from gadmin.deals.serializer import DealSerializer
from gadmin.user.user_authentication import UserAuthentication


class DealPagination(CursorPagination):
    page_size = 30
    ordering = "-write_at"
    cursor_query_param = "cursor"

class DealViewSet(viewsets.ModelViewSet):
    queryset = Deal.objects.select_related('classification','measurements','product_assignment').all()
    serializer_class = DealSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = DealPagination

    def get_queryset(self):
        from django.db.models import Q
        from rest_framework.exceptions import ValidationError
        from gadmin.categories.taxonomy import LABELS
        query = super().get_queryset()
        category = self.request.query_params.get('standard_category')
        if category:
            if category not in LABELS:
                raise ValidationError({'standard_category': '알 수 없는 표준 카테고리입니다.'})
            query = query.filter(classification__status='ready').filter(
                Q(classification__category=category) | Q(classification__category__startswith=category + '.'))
        return query

    def get_authenticators(self):
        # SAFE_METHODS(GET/HEAD/OPTIONS)에서는 인증 스킵
        if self.request.method in SAFE_METHODS:
            return []
        return super().get_authenticators()
