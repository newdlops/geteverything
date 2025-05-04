from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from user.models import User

class UserAuthentication(JWTAuthentication):
    """
    JWT 토큰의 클레임을 활용해 CustomUser 테이블에서 사용자 조회/생성.
    """
    def get_user(self, validated_token):
        """
        validated_token: SimpleJWT Token 인스턴스(페이로드 포함)
        """
        # 토큰 페이로드에 담긴 커스텀 식별자를 사용
        user_id = validated_token.get("user_id")
        if user_id is None:
            raise AuthenticationFailed("Token payload missing `user_id`", code="token_no_id")
        try:
            # 조회 또는 생성 로직

            user = User.objects.get(
                id=user_id
            )

        except User.DoesNotExist:
            raise AuthenticationFailed("No such user", code="user_not_found")
        if not user.is_active:
            raise AuthenticationFailed("User is inactive", code="user_inactive")
        return user
