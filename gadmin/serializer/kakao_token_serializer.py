
# serializers.py
from rest_framework import serializers

class KakaoTokenSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
