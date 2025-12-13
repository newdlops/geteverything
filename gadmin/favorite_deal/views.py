from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from gadmin.user.user_authentication import UserAuthentication


# Create your views here.
class FavoriteViewSet(viewsets.ModelViewSet):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]
