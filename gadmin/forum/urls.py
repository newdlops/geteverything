# from rest_framework.routers import DefaultRouter
# from .views import PostViewSet
#
# router = DefaultRouter()
# router.register(r'posts', PostViewSet, basename='post')
#
# urlpatterns = router.urls

# forum/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, CommentViewSet

# 1) 기본 Post 라우터 설정
router = DefaultRouter()
router.register(r'posts', PostViewSet, basename='post')

# 2) CommentViewSet의 액션을 뽑아 놓기
#    - list: GET   /posts/{post_pk}/            → post_pk 게시물의 댓글 목록
#    - create: POST /posts/{post_pk}/           → post_pk 게시물에 새 댓글
#    - list: GET   /posts/{post_pk}/{comment_pk}/ → comment_pk 댓글의 대댓글 목록
#    - create: POST /posts/{post_pk}/{comment_pk}/→ comment_pk 댓글에 새 대댓글
comment_list = CommentViewSet.as_view({
    'get':    'list',
    'post':   'create',
})

urlpatterns = [
    # Post CRUD 엔드포인트: /posts/ , /posts/{pk}/
    path('', include(router.urls)),

    # 댓글: 해당 post_pk 게시물에 댓글 조회/등록
    path(
        'posts/<int:post_pk>/comments/',
        comment_list,
        name='post-comment-list'
    ),

    # 대댓글: 해당 post_pk 게시물의 comment_pk 댓글에 대한 대댓글 조회/등록
    path(
        'posts/<int:post_pk>/comments/<int:comment_pk>/',
        comment_list,
        name='post-comment-reply-list'
    ),
]
