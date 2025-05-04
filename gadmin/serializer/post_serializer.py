from rest_framework import serializers
from forum.models.post import Post, Comment


class PostSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ['id', 'post_type', 'author', 'title', 'user_name', 'content', 'view_count', 'created_at']
        read_only_fields = ['id', 'post_type', 'author', 'user_name', 'created_at', ]

    def get_user_name(self, obj: Comment):
        return obj.author.user_id

