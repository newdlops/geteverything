from datetime import datetime
from django.db import models


class User(models.Model):
    PROVIDER_CHOICES = [
        ('google', 'Google'),
        ('kakao', 'Kakao'),
        ('naver', 'Naver'),
    ]
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    social_id = models.CharField(max_length=255, unique=True)  # 소셜 플랫폼에서 제공하는 고유 식별자
    access_token = models.CharField(max_length=255, blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)  # 프로필 사진, 닉네임 등 추가 정보 저장
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        db_table='user'
