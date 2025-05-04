from rest_framework import serializers
from forum.models.post import Comment

class CommentSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()

    class Meta:
        model  = Comment
        fields = ['id', 'post', 'parent', 'author', 'content', 'created_at', 'replies']
        read_only_fields = ['author', 'created_at', 'replies', 'post', 'parent']

    def get_replies(self, obj):
        # 대댓글이 있을 경우 재귀적으로 포함
        serializer = CommentSerializer(obj.replies.all(), many=True, context=self.context)
        return serializer.data

