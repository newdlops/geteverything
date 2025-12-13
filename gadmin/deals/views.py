
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
    queryset = Deal.objects.all()
    serializer_class = DealSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = DealPagination

    def get_authenticators(self):
        # SAFE_METHODS(GET/HEAD/OPTIONS)에서는 인증 스킵
        if self.request.method in SAFE_METHODS:
            return []
        return super().get_authenticators()
