
# serializers.py
from rest_framework import serializers

class AuthSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
