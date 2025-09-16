from django.contrib import admin
from .models import UserProfile, Contact, ChatMessage, Telegram, Notification, UserModelFile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'agent_training_status', 'agent_last_modified', 'is_onboarded', 'agent_auto_reply')
	search_fields = ('user__username', 'agent_auto_reply')
	list_filter = ('agent_training_status', 'is_onboarded', 'agent_auto_reply')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'telegram_user_id', 'telegram_username', 'user')
	search_fields = ('name', 'telegram_username', 'user__username')
	list_filter = ('user',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
	list_display = ('user', 'contact', 'message', 'ai_generated_message', 'reply_message', 'timestamp', 'reply_sent', 'user_approved_reply', 'score', 'is_important', 'is_toxic', 'sentiment', 'emotion', 'platform')
	search_fields = ('message', 'reply_message', 'user__username', 'contact__name', 'sentiment', 'emotion', 'platform')
	list_filter = ('user', 'contact', 'reply_sent', 'user_approved_reply', 'is_important', 'is_toxic', 'sentiment', 'platform')


@admin.register(Telegram)
class TelegramAdmin(admin.ModelAdmin):
	list_display = ('user', 'telegram_api_id', 'telegram_mobile_number', 'pin_required')
	search_fields = ('user__username', 'telegram_mobile_number')
	list_filter = ('pin_required',)


# Register Notification model
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('user', 'body', 'is_read', 'timestamp')
	search_fields = ('user__username', 'body')
	list_filter = ('user', 'is_read', 'timestamp')


# Register UserModelFile model
@admin.register(UserModelFile)
class UserModelFileAdmin(admin.ModelAdmin):
	list_display = ('user', 'filename', 'uploaded_at')
	search_fields = ('user__username', 'filename')
	list_filter = ('user', 'uploaded_at')
