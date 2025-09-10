from django.contrib import admin
from .models import UserProfile, Contact, ChatMessage, ReplyTemplate, PersonalitySetting

admin.site.register(UserProfile)
admin.site.register(Contact)
admin.site.register(ChatMessage)
admin.site.register(ReplyTemplate)
admin.site.register(PersonalitySetting)
