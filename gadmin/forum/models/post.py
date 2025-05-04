from django.db.models import Manager

from user.models import User
from django.db import models

# front의 post 구조
# const [postsData, setPostsData] = useState({
#     announce: {
#         id: 'announce',
#         title: '📢 관리자 공지',
#         date: '2025-04-27',
#         author: '관리자',
#         views: 340,
#         content: '새로운 기능 업데이트가 적용되었습니다. 카테고리 추가 및 댓글 좋아요 기능이 추가되었으니 확인해 보세요!',
#         comments: [
#             { author: '홍길동', time: '2025-04-27 10:15', text: '정말 유용한 업데이트네요! 감사합니다 😊' },
#             { author: '이영희', time: '2025-04-27 09:42', text: '카테고리 기능 너무 기다렸어요!' }
#         ]
#     },
#     '1': {
#         id: '1', title: '핫딜 정보 공유합니다!', date: '2025-04-26', author: '사용자A', views: 120,
#         content: '오늘 아침에 확인한 핫딜 링크와 할인 쿠폰 정보를 공유합니다. 놓치지 마세요!', comments: []
#     },
#     '2': {
#         id: '2', title: '가격 변동 알림 설정 방법', date: '2025-04-24', author: '사용자B', views: 200,
#         content: '키워드 알림을 설정해서 할인 정보를 받을 수 있는 방법을 단계별로 정리했습니다.', comments: []
#     }
# });

class Post(models.Model):
    POST_TYPE_CHOICES = (
        ('NOTICE', '공지'),
        ('NORMAL', '일반'),
    )

    post_type = models.CharField(max_length=32, choices=POST_TYPE_CHOICES,
                                 default='NORMAL')
    title = models.CharField(max_length=256)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_id = models.BigIntegerField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_id = models.BigIntegerField()
    is_hidden = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)

    objects = Manager()

    class Meta:
        db_table = 'post'
        ordering = ['-created_at']


class Comment(models.Model):
    post = models.ForeignKey(Post, related_name='comments',
                             on_delete=models.CASCADE)
    parent = models.ForeignKey('Comment', related_name='replies', on_delete=models.DO_NOTHING, null=True, blank=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_id = models.BigIntegerField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_id = models.BigIntegerField()

    objects = Manager()

    class Meta:
        db_table = 'comment'
        ordering = ['-created_at']
