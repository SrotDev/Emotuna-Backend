from django.contrib import admin
from .models import UserProfile, Contact, ChatMessage, Telegram


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'agent_training_status', 'agent_last_modified')
	search_fields = ('user__username',)
	list_filter = ('agent_training_status',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ('name', 'telegram_user_id', 'telegram_username', 'user')
	search_fields = ('name', 'telegram_username', 'user__username')
	list_filter = ('user',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
	list_display = ('user', 'contact', 'message', 'reply_message', 'timestamp', 'reply_sent', 'user_approved_reply', 'score', 'is_important', 'is_toxic', 'sentiment', 'emotion', 'platform')
	search_fields = ('message', 'reply_message', 'user__username', 'contact__name', 'sentiment', 'emotion', 'platform')
	list_filter = ('user', 'contact', 'reply_sent', 'user_approved_reply', 'is_important', 'is_toxic', 'sentiment', 'platform')


@admin.register(Telegram)
class TelegramAdmin(admin.ModelAdmin):
	list_display = ('user', 'telegram_api_id', 'telegram_mobile_number', 'pin_required')
	search_fields = ('user__username', 'telegram_mobile_number')
	list_filter = ('pin_required',)
