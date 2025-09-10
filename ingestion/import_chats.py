import csv
from datetime import datetime
import os
import django
import sys
from django.contrib.auth.models import User
from chat.models import Contact, ChatMessage


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()

CSV_PATH = os.path.join(os.path.dirname(__file__), 'sample_chats.csv')



user, _ = User.objects.get_or_create(username='testuser', defaults={'password': 'testpass'})

with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        contact_name = row['contact']
        contact, _ = Contact.objects.get_or_create(user=user, name=contact_name, defaults={'relationship_type': '', 'platform': 'imported'})
        ChatMessage.objects.create(
            user=user,
            contact=contact,
            sender=user.username,
            receiver=contact_name,
            timestamp=datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S'),
            message=row['incoming_message'],
            reply_message=row['reply_message'],
            platform='imported',
        )
print('Import complete.')
