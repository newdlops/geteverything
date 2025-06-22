
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.pagination import CursorPagination

from deals.models import Deal
from deals.serializer import DealSerializer
from user.user_authentication import UserAuthentication


class DealPagination(CursorPagination):
    page_size = 30
    ordering = "-create_at"
    cursor_query_param = "cursor"

class DealViewSet(viewsets.ModelViewSet):
    queryset = Deal.objects.all()
    serializer_class = DealSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = DealPagination
