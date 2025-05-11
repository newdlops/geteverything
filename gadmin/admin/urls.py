"""
URL configuration for admin project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from user.views.kakao_login_api_view import KakaoLoginAPIView
from user.views.kakao_signup_api_view import KakaoSignupAPIView
from user.views.logout_view import LogoutView
from user.views.user_update_view import UserUpdateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/kakaologin/', KakaoLoginAPIView.as_view(), name='kakao-login'),
    path('api/kakaosignup/', KakaoSignupAPIView.as_view(), name='kakao-signup'),
    path('api/logout/', LogoutView.as_view(), name='logout'),
    path('api/user/update', UserUpdateView.as_view(), name='user-update'),
    path('api/', include('forum.urls')),
    path('summernote/', include('django_summernote.urls')),
]
