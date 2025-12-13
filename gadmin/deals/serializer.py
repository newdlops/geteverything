from rest_framework import serializers
from gadmin.deals.models import Deal

class DealSerializer(serializers.ModelSerializer):


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
