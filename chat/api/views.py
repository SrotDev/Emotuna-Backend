import os
import shutil
import zipfile

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import viewsets, generics, filters, status, serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken, BlacklistedToken

from chat.models import UserProfile, Telegram, ChatMessage, Notification, UserModelFile
from chat.api.serializers import ChatMessageSerializer, NotificationSerializer
from agent_dump.userbot_manager import TelegramUserBotManager


# Superuser creation endpoint
class CreateSuperuserView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        username = "superadmin"
        password = "helloworld123"
        email = "srot.dev@gmail.com"
        if User.objects.filter(username=username).exists():
            return Response({"status": "already exists"}, status=200)
        User.objects.create_superuser(
            username=username,
            password=password,
            email=email
        )
        return Response({"status": "created", "username": username, "email": email}, status=201)

# User Registration API
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email', '')
        first_name = request.data.get('firstname', '')
        last_name = request.data.get('lastname', '')
        if not username or not password:
            return Response({'error': 'Username and password required.'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create_user(
            username=username,
            password=password,
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        # Automatically create UserProfile for new user
        UserProfile.objects.create(user=user)

        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user.username,
            'email': user.email,
            'firstname': user.first_name,
            'lastname': user.last_name
        }, status=status.HTTP_201_CREATED)



# User Login API
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user is not None:
            serializer = TokenObtainPairSerializer(data={'username': username, 'password': password})
            if serializer.is_valid():
                data = serializer.validated_data
                data['username'] = user.username
                data['email'] = user.email
                data['firstname'] = user.first_name
                data['lastname'] = user.last_name
                return Response(data, status=status.HTTP_200_OK)
            else:
                return Response({'error': 'Token generation failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({'error': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)



# Logout endpoint: blacklist JWT and stop userbot if running
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        user = request.user
        # Blacklist all outstanding tokens for this user
        try:
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                try:
                    BlacklistedToken.objects.get_or_create(token=token)
                except Exception:
                    pass
        except Exception as e:
            print(f"Warning: Could not blacklist tokens for {user.username}: {e}")
        # Stop userbot if running
        username = user.username
        bot = RUNNING_USERBOTS.get(username)
        if bot:
            bot.stop()
            del RUNNING_USERBOTS[username]
        return Response({"status": "logged out"}, status=200)



# Profile API endpoint
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        user = request.user
        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=404)
        agent_running_status = user.username in RUNNING_USERBOTS
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'username': user.username,
            'email': user.email,
            'agent_training_status': profile.agent_training_status,
            'agent_last_modified': profile.agent_last_modified,
            'agent_running_status': agent_running_status,
        }
        return Response(data, status=200)

    def patch(self, request, format=None):
        user = request.user
        profile = UserProfile.objects.filter(user=user).first()
        if not profile:
            return Response({'error': 'UserProfile not found.'}, status=404)
        # Allow updating first_name, last_name, email
        for field in ['first_name', 'last_name', 'email']:
            if field in request.data:
                setattr(user, field, request.data[field])
        user.save()
        # Optionally allow updating agent_training_status
        if 'agent_training_status' in request.data:
            profile.agent_training_status = request.data['agent_training_status']
            profile.agent_last_modified = timezone.now()
            profile.save()
        return Response({'status': 'updated'}, status=200)

    def delete(self, request, format=None):
        user = request.user
        username = user.username
        # Stop userbot if running
        bot = RUNNING_USERBOTS.get(username)
        if bot:
            bot.stop()
            del RUNNING_USERBOTS[username]
        user.delete()
        return Response({'status': 'deleted'}, status=200)
    
    

# Utility to get per-user dump path
def get_user_dump_path(username):
    base = os.path.join('agent_dump', str(username))
    os.makedirs(base, exist_ok=True)
    return base



class DatasetUploadView(APIView):
    parser_classes = [MultiPartParser]

    def get(self, request, format=None):
        import json
        user = getattr(request, 'user', None)
        username = None
        if user and user.is_authenticated:
            username = user.username
        else:
            username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        # Export all ChatMessage fields for this user as JSON (not JSONL)
        from chat.models import ChatMessage
        messages = ChatMessage.objects.filter(user__username=username)
        data = []
        for msg in messages:
            data.append({
                'id': msg.id,
                'user': msg.user.username,
                'contact': msg.contact.name if msg.contact else None,
                'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                'message': msg.message,
                'platform': msg.platform,
                'emotion': msg.emotion,
                'sentiment': msg.sentiment,
                'is_toxic': msg.is_toxic,
                'telegram_chat_id': msg.telegram_chat_id,
                'telegram_message_id': msg.telegram_message_id,
                'is_important': msg.is_important,
                'is_nsfw': msg.is_nsfw,
                'user_approved_reply': msg.user_approved_reply,
                'reply_sent': msg.reply_sent,
                'score': msg.score,
                'ai_generated_message': msg.ai_generated_message,
                'reply_message': msg.reply_message,
            })
        return Response(data, content_type='application/json')

    def post(self, request, format=None):
        import json
        from agent_dump.pipeline_utils import embed_new_message
        user = getattr(request, 'user', None)
        username = None
        if user and user.is_authenticated:
            username = user.username
        else:
            username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)
        # Parse uploaded JSON (not JSONL) and append to ChatMessage DB
        from django.contrib.auth.models import User
        from chat.models import Contact, ChatMessage
        user_obj = User.objects.get(username=username)
        added = 0
        try:
            # file_obj.read() returns bytes, decode to str
            rows = json.loads(file_obj.read().decode('utf-8'))
            for row in rows:
                # Find or create a contact (fallback to 'Imported')
                contact, _ = Contact.objects.get_or_create(user=user_obj, name=row.get('contact') or 'Imported', defaults={'platform': row.get('platform', 'imported')})
                # Avoid duplicate: check for same message and ai_generated_message
                if not ChatMessage.objects.filter(user=user_obj, message=row.get('message'), ai_generated_message=row.get('ai_generated_message')).exists():
                    msg = ChatMessage.objects.create(
                        user=user_obj,
                        contact=contact,
                        timestamp=row.get('timestamp'),
                        message=row.get('message'),
                        platform=row.get('platform', 'imported'),
                        emotion=row.get('emotion'),
                        sentiment=row.get('sentiment'),
                        is_toxic=row.get('is_toxic', False),
                        telegram_chat_id=row.get('telegram_chat_id'),
                        telegram_message_id=row.get('telegram_message_id'),
                        is_important=row.get('is_important', False),
                        is_nsfw=row.get('is_nsfw', False),
                        user_approved_reply=row.get('user_approved_reply', False),
                        reply_sent=row.get('reply_sent', False),
                        score=row.get('score'),
                        ai_generated_message=row.get('ai_generated_message'),
                        reply_message=row.get('reply_message'),
                    )
                    added += 1
                    # Embed the new message
                    embed_new_message(msg.id)
        except Exception as e:
            return Response({'error': f'Failed to import: {str(e)}'}, status=400)
        return Response({'status': 'imported', 'added': added}, status=201)



class ModelUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, format=None):
        """Upload model zip and store in DB (overwrites previous for user)."""
        user = getattr(request, 'user', None)
        username = request.data.get('username') if not (user and user.is_authenticated) else user.username
        if not username:
            return Response({'error': 'username required'}, status=400)
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)
        from django.contrib.auth.models import User
        user_obj = User.objects.get(username=username)
        file_bytes = b''.join(chunk for chunk in file_obj.chunks())
        # Remove previous file for this user (if any)
        UserModelFile.objects.filter(user=user_obj, filename='dpo_model.zip').delete()
        UserModelFile.objects.create(user=user_obj, filename='dpo_model.zip', file=file_bytes)
        return Response({'status': 'uploaded to db'}, status=201)

    def get(self, request, format=None):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        from django.contrib.auth.models import User
        user_obj = User.objects.get(username=username)
        model_file = UserModelFile.objects.filter(user=user_obj, filename='dpo_model.zip').first()
        if not model_file:
            return Response(status=404)
        data = model_file.file
        response = Response(data, status=200, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="dpo_model.zip"'
        response['Content-Length'] = str(len(data))
        return response

    def head(self, request, format=None):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        from django.contrib.auth.models import User
        user_obj = User.objects.get(username=username)
        model_file = UserModelFile.objects.filter(user=user_obj, filename='dpo_model.zip').first()
        if not model_file:
            return Response(status=404)
        file_size = len(model_file.file)
        response = Response(status=200)
        response['Content-Length'] = str(file_size)
        response['Accept-Ranges'] = 'bytes'
        return response
    

class ModelUnzipView(APIView):
    def post(self, request, format=None):
        user = getattr(request, 'user', None)
        username = user.username if (user and user.is_authenticated) else request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        from django.contrib.auth.models import User
        user_obj = User.objects.get(username=username)
        model_file = UserModelFile.objects.filter(user=user_obj, filename='dpo_model.zip').first()
        if not model_file:
            return Response({'error': 'Model zip not found in DB.'}, status=404)
        dump_dir = get_user_dump_path(username)
        extract_dir = os.path.join(dump_dir, 'dpo_model')
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)
        # Write zip to a temp file in memory, then extract
        import io
        zip_bytes = io.BytesIO(model_file.file)
        with zipfile.ZipFile(zip_bytes, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        # Note: Extracted files in agent_dump/{username}/dpo_model/ are TEMPORARY and will be lost on redeploy.
        return Response({'status': 'unzipped'}, status=200)



# Agent status view: PATCH agent_training_status and/or agent_auto_reply
class AgentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, format=None):
        user = request.user
        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=404)

        updated = False
        resp = {}
        # Update agent_training_status if provided and valid
        if 'agent_training_status' in request.data:
            status_value = request.data['agent_training_status']
            allowed_statuses = ["idle", "pending", "training", "completed", "failed"]
            if status_value not in allowed_statuses:
                return Response({'error': 'Invalid agent_training_status value.'}, status=400)
            if profile.agent_training_status != status_value:
                profile.agent_training_status = status_value
                profile.agent_last_modified = timezone.now()
                updated = True
            resp['agent_training_status'] = profile.agent_training_status
            resp['agent_last_modified'] = profile.agent_last_modified
        # Update agent_auto_reply if provided (no timestamp update)
        if 'agent_auto_reply' in request.data:
            auto_reply = request.data['agent_auto_reply']
            if isinstance(auto_reply, str):
                auto_reply = auto_reply.lower() == 'true'
            profile.agent_auto_reply = bool(auto_reply)
            updated = True
            resp['agent_auto_reply'] = profile.agent_auto_reply
        if updated:
            profile.save()
        return Response({'status': 'updated', **resp}, status=200)


# List, filter, and create messages
class ChatMessageListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['message', 'reply_message', 'emotion', 'sentiment', 'platform', 'contact__name', 'user__username']
    ordering_fields = ['timestamp', 'score', 'is_important', 'is_toxic', 'sentiment']

    def get_queryset(self):
        queryset = super().get_queryset()
        # Optional filters via query params
        user = self.request.query_params.get('user')
        contact = self.request.query_params.get('contact')
        replied = self.request.query_params.get('replied')
        reply_sent = self.request.query_params.get('reply_sent')
        user_approved_reply = self.request.query_params.get('user_approved_reply')
        sentiment = self.request.query_params.get('sentiment')
        if user:
            queryset = queryset.filter(user__username=user)
        if contact:
            queryset = queryset.filter(contact__name=contact)
        if replied is not None:
            queryset = queryset.filter(replied=(replied.lower() == 'true'))
        if reply_sent is not None:
            queryset = queryset.filter(reply_sent=(reply_sent.lower() == 'true'))
        if user_approved_reply is not None:
            queryset = queryset.filter(user_approved_reply=(user_approved_reply.lower() == 'true'))
        if sentiment:
            queryset = queryset.filter(sentiment=sentiment)
        return queryset

# Retrieve, update, or delete a specific message
class ChatMessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer



# Telegram API Model View
class TelegramModelView(APIView):
    """
    GET: Retrieve Telegram model fields for a user (by username or authenticated user)
    POST: Create or set Telegram model fields for a user
    PATCH: Update Telegram model fields for a user
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        user = getattr(request, 'user', None)
        username = request.query_params.get('username') if not (user and user.is_authenticated) else user.username
        if not username:
            return Response({'error': 'username required'}, status=400)
        try:
            user_obj = User.objects.get(username=username)
            telegram = Telegram.objects.get(user=user_obj)
            data = {
                'username': username,
                'telegram_api_id': telegram.telegram_api_id,
                'telegram_api_hash': telegram.telegram_api_hash,
                'telegram_mobile_number': telegram.telegram_mobile_number,
                'telegram_pin_code': telegram.telegram_pin_code,
                'pin_required': telegram.pin_required,
            }
            return Response(data, status=200)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        except Telegram.DoesNotExist:
            return Response({'error': 'Telegram model not found.'}, status=404)

    def post(self, request, format=None):
        username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        try:
            user_obj = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        telegram_api_id = request.data.get('telegram_api_id')
        telegram_api_hash = request.data.get('telegram_api_hash')
        telegram_mobile_number = request.data.get('telegram_mobile_number')
        telegram_pin_code = request.data.get('telegram_pin_code')
        if not (telegram_api_id and telegram_api_hash and telegram_mobile_number):
            return Response({'error': 'telegram_api_id, telegram_api_hash, and telegram_mobile_number are required.'}, status=400)
        telegram, created = Telegram.objects.get_or_create(user=user_obj)
        telegram.telegram_api_id = telegram_api_id
        telegram.telegram_api_hash = telegram_api_hash
        telegram.telegram_mobile_number = telegram_mobile_number
        telegram.telegram_pin_code = telegram_pin_code
        telegram.save()
        return Response({'status': 'created' if created else 'updated'}, status=201 if created else 200)

    def patch(self, request, format=None):
        username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        try:
            user_obj = User.objects.get(username=username)
            telegram = Telegram.objects.get(user=user_obj)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        except Telegram.DoesNotExist:
            return Response({'error': 'Telegram model not found.'}, status=404)
        # Update only provided fields
        for field in ['telegram_api_id', 'telegram_api_hash', 'telegram_mobile_number', 'telegram_pin_code', 'pin_required']:
            if field in request.data:
                value = request.data.get(field)
                # Convert pin_required to boolean if needed
                if field == 'pin_required' and isinstance(value, str):
                    value = value.lower() == 'true'
                setattr(telegram, field, value)
        telegram.save()
        return Response({'status': 'updated'}, status=200)
    


# In-memory store for running userbots: {username: TelegramUserBotManager instance}
RUNNING_USERBOTS = {}

class UserbotControlView(APIView):
    """
    POST: Start userbot for a user (requires username, model_choice)
    DELETE: Stop userbot for a user (requires username)
    GET: Query status for a user (requires username)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        username = request.data.get('username')
        model_choice = request.data.get('model_choice', 'kimi')
        if not username:
            return Response({'error': 'username required'}, status=400)
        if username in RUNNING_USERBOTS:
            return Response({'status': 'already running'}, status=200)
        try:
            user_obj = User.objects.get(username=username)
            telegram = Telegram.objects.get(user=user_obj)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        except Telegram.DoesNotExist:
            return Response({'error': 'Telegram credentials not found.'}, status=404)
        # Start userbot
        bot = TelegramUserBotManager(
            user=user_obj,
            api_id=telegram.telegram_api_id,
            api_hash=telegram.telegram_api_hash,
            session_name=f'userbot_{username}',
            model_choice=model_choice
        )
        bot.start()
        RUNNING_USERBOTS[username] = bot
        return Response({'status': 'started'}, status=201)

    def delete(self, request, format=None):
        username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        bot = RUNNING_USERBOTS.get(username)
        if not bot:
            return Response({'status': 'not running'}, status=200)
        bot.stop()
        del RUNNING_USERBOTS[username]
        return Response({'status': 'stopped'}, status=200)

    def get(self, request, format=None):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        running = username in RUNNING_USERBOTS
        return Response({'running': running}, status=200)
    

# Notification CRUD API
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'user', 'body', 'is_read', 'timestamp']
        read_only_fields = ['id', 'timestamp', 'user']

class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by('-timestamp')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# API Endpoints Info View
class APIEndpointsInfoView(APIView):
    """
    Returns a JSON response describing each API endpoint, allowed methods, usage, sample requests, and responses.
    """
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        endpoints = [
            {
                "path": "/api/register/",
                "methods": ["POST"],
                "description": "Register a new user.",
                "sample_request": {
                    "username": "alice",
                    "password": "yourpassword",
                    "email": "alice@example.com",
                    "firstname": "Alice",
                    "lastname": "Smith"
                },
                "sample_response": {
                    "refresh": "<refresh_token>",
                    "access": "<access_token>",
                    "username": "alice",
                    "email": "alice@example.com",
                    "firstname": "Alice",
                    "lastname": "Smith"
                }
            },
            {
                "path": "/api/login/",
                "methods": ["POST"],
                "description": "Authenticate user and obtain JWT tokens.",
                "sample_request": {
                    "username": "alice",
                    "password": "yourpassword"
                },
                "sample_response": {
                    "refresh": "<refresh_token>",
                    "access": "<access_token>",
                    "username": "alice",
                    "email": "alice@example.com",
                    "firstname": "Alice",
                    "lastname": "Smith"
                }
            },
            {
                "path": "/api/logout/",
                "methods": ["POST"],
                "description": "Logout the current user, blacklist all JWT tokens, and stop the userbot if running.",
                "sample_request": {},
                "sample_response": {"status": "logged out"}
            },
            {
                "path": "/api/create-superuser/",
                "methods": ["POST"],
                "description": "Create a superuser with fixed credentials (for setup/demo only).",
                "sample_request": {},
                "sample_response": {"status": "created", "username": "superadmin", "email": "srot.dev@gmail.com"}
            },
            {
                "path": "/api/profile/",
                "methods": ["GET", "PATCH", "DELETE"],
                "description": "Get, update, or delete the authenticated user's profile. PATCH allows updating first/last name, email, and agent training status.",
                "sample_request": {
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@example.com",
                    "agent_training_status": "training"
                },
                "sample_response": {
                    "status": "updated"
                }
            },
            {
                "path": "/api/dataset/",
                "methods": ["POST", "GET"],
                "description": "Upload or download the per-user SFT dataset (JSON, not JSONL). POST accepts a JSON file, GET returns all chat messages for the user as JSON.",
                "sample_request": {
                    "file": "<file> (multipart/form-data)",
                    "username": "alice"  # if not authenticated
                },
                "sample_response": {"status": "imported", "added": 42}
            },
            {
                "path": "/api/model/",
                "methods": ["POST", "GET", "HEAD"],
                "description": "Upload, download, or check the DPO model zip file for a user. POST uploads a zip to the DB, GET downloads it, HEAD returns Content-Length.",
                "sample_request": {
                    "file": "<file> (multipart/form-data)",
                    "username": "alice"  # if not authenticated
                },
                "sample_response": {"status": "uploaded to db"}
            },
            {
                "path": "/api/model/unzip/",
                "methods": ["POST"],
                "description": "Unzip the uploaded DPO model for a user (extracts to a temp dir, not persistent).",
                "sample_request": {
                    "username": "alice"
                },
                "sample_response": {"status": "unzipped"}
            },
            {
                "path": "/api/agent-training-status/",
                "methods": ["PATCH"],
                "description": "Update the agent training status and/or agent_auto_reply for the authenticated user.",
                "sample_request": {
                    "agent_training_status": "training",  # one of [idle, pending, training, completed, failed]
                    "agent_auto_reply": true
                },
                "sample_response": {
                    "status": "updated",
                    "agent_training_status": "training",
                    "agent_last_modified": "2025-09-12T12:34:56Z",
                    "agent_auto_reply": true
                }
            },
            {
                "path": "/api/telegram/",
                "methods": ["GET", "POST", "PATCH"],
                "description": "Get, create, or update Telegram API credentials for a user.",
                "sample_request": {
                    "username": "alice",
                    "telegram_api_id": "123456",
                    "telegram_api_hash": "abcdef...",
                    "telegram_mobile_number": "+1234567890",
                    "telegram_pin_code": "12345"
                },
                "sample_response": {"status": "created"}
            },
            {
                "path": "/api/userbot/",
                "methods": ["POST", "DELETE", "GET"],
                "description": "Start, stop, or query the Telegram userbot for a user.",
                "sample_request": {
                    "username": "alice",
                    "model_choice": "kimi"  # optional, default 'kimi'
                },
                "sample_response": {"status": "started"}
            },
            {
                "path": "/api/messages/",
                "methods": ["GET", "POST"],
                "description": "List, filter, search, or create chat messages. Supports filtering by user, contact, replied, reply_sent, user_approved_reply, sentiment.",
                "sample_request": {
                    "user": "alice",  # filter by username (GET)
                    "contact": "Bob",  # filter by contact name (GET)
                    "replied": "true",  # filter by replied status (GET)
                    "sentiment": "positive"  # filter by sentiment (GET)
                },
                "sample_response": [
                    {
                        "id": 1,
                        "user": 1,
                        "contact": 2,
                        "message": "Hi!",
                        "reply_message": "Hello!",
                        "timestamp": "2025-09-12T12:34:56Z",
                        "replied": true,
                        "score": 5,
                        "is_important": false,
                        "is_toxic": false,
                        "sentiment": "positive",
                        "emotion": "happy",
                        "platform": "telegram"
                    }
                ]
            },
            {
                "path": "/api/messages/<id>/",
                "methods": ["GET", "PUT", "PATCH", "DELETE"],
                "description": "Retrieve, update, or delete a specific chat message by ID.",
                "sample_request": {
                    "message": "Updated message text"
                },
                "sample_response": {
                    "id": 1,
                    "user": 1,
                    "contact": 2,
                    "message": "Updated message text",
                    "reply_message": "Hello!",
                    "timestamp": "2025-09-12T12:34:56Z",
                    "replied": true,
                    "score": 5,
                    "is_important": false,
                    "is_toxic": false,
                    "sentiment": "positive",
                    "emotion": "happy",
                    "platform": "telegram"
                }
            },
            {
                "path": "/api/notifications/",
                "methods": ["GET", "POST"],
                "description": "List or create notifications for the authenticated user. GET returns all notifications, POST creates a new notification.",
                "sample_request": {
                    "body": "You have a new message!"
                },
                "sample_response": {
                    "id": 1,
                    "user": 1,
                    "body": "You have a new message!",
                    "is_read": false,
                    "timestamp": "2025-09-12T12:34:56Z"
                }
            },
            {
                "path": "/api/notifications/<id>/",
                "methods": ["GET", "PUT", "PATCH", "DELETE"],
                "description": "Retrieve, update, or delete a specific notification by ID.",
                "sample_request": {
                    "is_read": true
                },
                "sample_response": {
                    "id": 1,
                    "user": 1,
                    "body": "You have a new message!",
                    "is_read": true,
                    "timestamp": "2025-09-12T12:34:56Z"
                }
            }
        ]
        return JsonResponse({"api_endpoints": endpoints}, json_dumps_params={"indent": 2})
    


