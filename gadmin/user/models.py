from django.db import models
import uuid


class User(models.Model):
    PROVIDER_CHOICES = [
        ('google', 'Google'),
        ('kakao', 'Kakao'),
        ('naver', 'Naver'),
    ]
    provider = models.CharField(max_length=64, choices=PROVIDER_CHOICES)
    social_id = models.CharField(max_length=255, null=True, blank=True)  # 소셜 플랫폼에서 제공하는 고유 식별자
    access_token = models.CharField(max_length=255, blank=True, null=True)
    access_token_expire_date = models.DateTimeField(auto_now=True)
    refresh_token = models.CharField(max_length=255, blank=True, null=True)
    refresh_token_expire_date = models.DateTimeField(auto_now=True)
    extra_data = models.JSONField(blank=True, null=True)  # 프로필 사진, 닉네임 등 추가 정보 저장
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    kakao_id = models.CharField(max_length=255, unique=True, null=True, blank=True)  # 소셜 플랫폼에서 제공하는 고유 식별자
    user_id = models.CharField(max_length=255, unique=True, null=False, default=uuid.uuid4) # 유저 아이디
    email = models.CharField(max_length=255, null=True, blank=True) # 유저 이메일
    is_active = models.BooleanField(default=True) # 유저 활성화 여부
    is_authenticated = models.BooleanField(default=True)

    objects = models.Manager()

    class Meta:
        db_table='user'
