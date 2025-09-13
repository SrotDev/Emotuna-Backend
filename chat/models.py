from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE)
	agent_training_status = models.CharField(
		max_length=20,
		choices=[
			("idle", "Idle"),
			("pending", "Pending"),
			("training", "Training"),
			("completed", "Completed"),
			("failed", "Failed")
		],
		default="idle"
	)
	agent_last_modified = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.user.username


class Contact(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	name = models.CharField(max_length=100)
	relationship_type = models.CharField(max_length=50, blank=True, null=True)  # e.g., mom, boss, friend
	platform = models.CharField(max_length=50, blank=True, null=True)  # WhatsApp, Telegram, etc.
	telegram_user_id = models.BigIntegerField(blank=True, null=True)
	telegram_username = models.CharField(max_length=100, blank=True, null=True)

	def __str__(self):
		return f"{self.name} ({self.relationship_type})"



class ChatMessage(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
	timestamp = models.DateTimeField()
	message = models.TextField() 
	platform = models.CharField(max_length=50)
	emotion = models.CharField(max_length=50, blank=True, null=True)
	sentiment = models.CharField(max_length=20, blank=True, null=True)  # e.g., 'positive', 'negative', 'neutral'
	is_toxic = models.BooleanField(default=False)
	telegram_chat_id = models.BigIntegerField(blank=True, null=True)
	telegram_message_id = models.BigIntegerField(blank=True, null=True)
	is_important = models.BooleanField(default=False)
	is_nsfw = models.BooleanField(default=False)
	user_approved_reply = models.BooleanField(default=False)
	reply_sent = models.BooleanField(default=False)
	score = models.IntegerField(blank=True, null=True)
	ai_generated_message = models.TextField(blank=True, null=True)
	reply_message = models.TextField(blank=True, null=True) 

	def __str__(self):
		return f"{self.contact.name} -> {self.user.username}: {self.message[:30]}..."



# Telegram API credentials per user
class Telegram(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	telegram_api_id = models.CharField(max_length=64)
	telegram_api_hash = models.CharField(max_length=128)
	telegram_mobile_number = models.CharField(max_length=32)
	telegram_pin_code = models.CharField(max_length=6, null=True, blank=True, default=None)  # optional 2FA pin
	pin_required = models.BooleanField(default=False)

	def __str__(self):
		return f"{self.user.username} Telegram ({self.telegram_mobile_number})"
