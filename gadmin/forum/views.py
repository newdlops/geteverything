from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly, SAFE_METHODS
from rest_framework.response import Response

from user.user_authentication import UserAuthentication
from forum.models.post import Post, Comment
from serializer.post_serializer import PostSerializer
from serializer.comment_serializer import CommentSerializer

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.order_by('-created_at')
    serializer_class = PostSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_authenticators(self):
        # SAFE_METHODS(GET/HEAD/OPTIONS)에서는 인증 스킵
        if self.request.method in SAFE_METHODS:
            return []
        return super().get_authenticators()

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(author=user, created_id=user.id, updated_id=user.id)



class CommentViewSet(viewsets.ModelViewSet):
    """
    /posts/{post_pk}/comments/                  → list, create
    /posts/{post_pk}/comments/{comment_pk}/     → retrieve, update, destroy
    """
    serializer_class      = CommentSerializer
    authentication_classes = [UserAuthentication]
    permission_classes    = [IsAuthenticatedOrReadOnly]

    def get_authenticators(self):
        # SAFE_METHODS(GET/HEAD/OPTIONS)에서는 인증 스킵
        if self.request.method in SAFE_METHODS:
            return []
        return super().get_authenticators()

    def get_queryset(self):
        # URL에서 전달된 post_pk 혹은 parent comment_pk 기준으로 필터링
        post_pk    = self.kwargs.get('post_pk')
        comment_pk = self.kwargs.get('comment_pk')
        qs = Comment.objects.filter(post_id=post_pk)
        if comment_pk is not None:
            # 대댓글 조회 시 parent 필터 추가
            qs = qs.filter(parent_id=comment_pk)
        return qs.order_by('created_at')

    def perform_create(self, serializer):
        # 생성 시 author와 post, parent 자동 설정
        post_pk    = self.kwargs.get('post_pk')
        comment_pk = self.kwargs.get('comment_pk')
        user = self.request.user
        serializer.save(
            author=self.request.user,
            post_id=post_pk,
            parent_id=comment_pk,
            created_id=user.id,
            updated_id=user.id
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
