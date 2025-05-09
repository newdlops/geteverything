import requests
from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from serializer.authSerializer import AuthSerializer
from user.models import User

class UserUpdateView(APIView):
    def post(self, request):
        serializer = AuthSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        access_token = serializer.validated_data['access_token']
        refresh_token = serializer.validated_data['refresh_token']

        # 카카오 API 호출: access_token을 사용하여 사용자 정보 가져오기
        kakao_url = "https://kapi.kakao.com/v1/user/logout"
        headers = {"Authorization": f"Bearer {access_token}"}
        kakao_response = requests.get(kakao_url, headers=headers)

        if kakao_response.status_code != 200:
            return Response({"detail": "카카오 API 호출 실패"}, status=status.HTTP_400_BAD_REQUEST)

        user_info = kakao_response.json()
        kakao_id = user_info.get("id")
        if not kakao_id:
            return Response({"detail": "카카오 사용자 ID를 확인할 수 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            logout_user = User.objects.get(kakao_id=kakao_id)
            logout_user.access_token = None
            logout_user.refresh_token = None
            # 유저가 존재하면, 로그인 성공 처리(예: JWT 토큰 발급 등)
            return Response({
                "detail": "로그아웃 성공",
                "user_info": {
                    access_token: access_token,
                    refresh_token: refresh_token,
                },
                # "token": 발급한_토큰 (예: JWT)
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            # 유저가 존재하지 않는 경우, 가입이 필요함을 응답
            return Response({
                "detail": "회원가입 실패"
            }, status=status.HTTP_404_NOT_FOUND)
