from rest_framework import serializers
from chat.models import ChatMessage, Notification

class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = '__all__'


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'user', 'body', 'is_read', 'timestamp']
        read_only_fields = ['id', 'timestamp', 'user']