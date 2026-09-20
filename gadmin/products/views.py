from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from gadmin.deals.models import Product
from .history import history
from .catalog import canonical


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model=Product
        fields=['id','name','brand','model','attributes','category','verified','created_at']


class ProductPagination(CursorPagination):
    page_size=30
    ordering='-created_at'


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset=Product.objects.all()
    serializer_class=ProductSerializer
    authentication_classes=[]
    permission_classes=[AllowAny]
    pagination_class=ProductPagination

    def get_queryset(self):
        query=super().get_queryset()
        if self.action=='list':query=query.filter(is_active=True)
        term=(self.request.query_params.get('q') or '').strip()[:120]
        if term:query=query.filter(name__icontains=term)
        return query

    def get_object(self):
        return canonical(super().get_object())

    @action(detail=True,methods=['get'])
    def history(self,request,pk=None):
        product=self.get_object()
        try:result=history(product,request.query_params)
        except ValueError as exc:raise ValidationError({'filters':str(exc)})
        return Response(result)
