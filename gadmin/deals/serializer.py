from rest_framework import serializers
from gadmin.deals.models import Deal

class DealSerializer(serializers.ModelSerializer):
    standard_category = serializers.SerializerMethodField()
    classification_status = serializers.SerializerMethodField()
    measurements = serializers.SerializerMethodField()
    measurement_status = serializers.SerializerMethodField()
    product_id = serializers.SerializerMethodField()
    product_status = serializers.SerializerMethodField()

    def get_product_id(self,obj):
        result=getattr(obj,'product_assignment',None)
        return str(result.product_id) if result and result.status=='ready' and result.product_id else None

    def get_product_status(self,obj):
        result=getattr(obj,'product_assignment',None)
        return result.status if result else 'pending'

    def get_standard_category(self, obj):
        from gadmin.categories.taxonomy import describe
        result = getattr(obj, 'classification', None)
        return describe(result.category) if result and result.status == 'ready' else None

    def get_classification_status(self, obj):
        result = getattr(obj, 'classification', None)
        return result.status if result else 'pending'

    def get_measurements(self, obj):
        from gadmin.metrics.fx import convert, cached_latest
        result = getattr(obj, 'measurements', None)
        if not result or result.status in ('pending','error'):
            return None
        code = (result.result.get('price') or {}).get('currency')
        return convert(result.result,cached_latest() if code and code!='KRW' else None)

    def get_measurement_status(self, obj):
        result = getattr(obj, 'measurements', None)
        return result.status if result else 'pending'

    class Meta:
        model = Deal
        fields = ['article_id',
                  'community_name',
                  'origin_url',
                  'shop_url_1',
                  'shop_url_2',
                  'shop_name',
                  'thumbnail',
                  'subject',
                  'category',
                  'standard_category',
                  'classification_status',
                  'measurements',
                  'measurement_status',
                  'product_id',
                  'product_status',
                  'price',
                  'currency',
                  'delivery_price',
                  'recommend_count',
                  'dislike_count',
                  'view_count',
                  'create_at',
                  'write_at',
                  'update_at',
                  'crawled_at',
                  'is_end',]
        read_only_fields = ['article_id',
                            'community_name',
                            'origin_url',
                            'shop_url_1',
                            'shop_url_2',
                            'shop_name',
                            'thumbnail',
                            'subject',
                            'category',
                            'price',
                            'currency',
                            'delivery_price',
                            'recommend_count',
                            'dislike_count',
                            'view_count',
                            'create_at',
                            'write_at',
                            'update_at',
                            'crawled_at',
                            'is_end',]
