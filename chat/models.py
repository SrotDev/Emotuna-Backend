
from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE)
	# Add more preferences as needed

	def __str__(self):
		return self.user.username

class Contact(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	name = models.CharField(max_length=100)
	relationship_type = models.CharField(max_length=50, blank=True, null=True)  # e.g., mom, boss, friend
	platform = models.CharField(max_length=50, blank=True, null=True)  # WhatsApp, Telegram, etc.

	def __str__(self):
		return f"{self.name} ({self.relationship_type})"

class ChatMessage(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
	sender = models.CharField(max_length=100)
	receiver = models.CharField(max_length=100)
	timestamp = models.DateTimeField()
	message = models.TextField()  # incoming message
	reply_message = models.TextField(blank=True, null=True)  # user's reply
	platform = models.CharField(max_length=50)
	emotion = models.CharField(max_length=50, blank=True, null=True)
	is_toxic = models.BooleanField(default=False)
	is_important = models.BooleanField(default=False)
	# Classification for reply message
	reply_emotion = models.CharField(max_length=50, blank=True, null=True)
	reply_is_toxic = models.BooleanField(default=False)
	reply_is_important = models.BooleanField(default=False)
	reply = models.TextField(blank=True, null=True)  # legacy, can be removed later

	def __str__(self):
		return f"{self.sender} -> {self.receiver}: {self.message[:30]}..."

class ReplyTemplate(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	name = models.CharField(max_length=100)
	template = models.TextField()

	def __str__(self):
		return self.name

class PersonalitySetting(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	tone = models.CharField(max_length=50, default="default")  # e.g., friendly, sarcastic
	emoji_usage = models.BooleanField(default=True)
	reply_length = models.CharField(max_length=20, default="normal")  # short, normal, long

	def __str__(self):
		return f"{self.user.username} - {self.tone}"
