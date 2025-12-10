import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from serializer.kakao_token_serializer import KakaoTokenSerializer
from gadmin.user.models import User

class KakaoLoginAPIView(APIView):
    def post(self, request):
        serializer = KakaoTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        access_token = serializer.validated_data['access_token']
        refresh_token = serializer.validated_data['refresh_token']

        # 카카오 API 호출: access_token을 사용하여 사용자 정보 가져오기
        kakao_url = "https://kapi.kakao.com/v2/user/me"
        headers = {"Authorization": f"Bearer {access_token}"}
        kakao_response = requests.get(kakao_url, headers=headers)

        if kakao_response.status_code != 200:
            return Response({"detail": "카카오 API 호출 실패"}, status=status.HTTP_400_BAD_REQUEST)

        user_info = kakao_response.json()
        kakao_id = user_info.get("id")
        if not kakao_id:
            return Response({"detail": "카카오 사용자 ID를 확인할 수 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        # DB에서 해당 카카오 ID를 가진 유저가 존재하는지 확인
        try:
            user = User.objects.get(kakao_id=kakao_id)
            user.access_token = access_token # 카카오 토큰
            user.refresh_token = refresh_token # 카카오 토큰
            user.save()
            # 유저가 존재하면, 로그인 성공 처리(예: JWT 토큰 발급 등)
            refresh = RefreshToken.for_user(user)
            service_access_token = str(refresh.access_token)
            service_refresh_token = str(refresh)

            return Response({
                "detail": "로그인 성공",
                "id": user.id,
                "user_id": user.user_id,
                "email": user.email,
                "access_token": service_access_token,
                "refresh_token": service_refresh_token,
                # "token": 발급한_토큰 (예: JWT)
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            # 유저가 존재하지 않는 경우, 가입이 필요함을 응답
            return Response({
                "detail": "가입된 유저가 아닙니다. 회원가입을 진행해 주세요.",
                "kakao_id": kakao_id
            }, status=status.HTTP_404_NOT_FOUND)
