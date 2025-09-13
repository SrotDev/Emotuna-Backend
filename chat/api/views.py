from rest_framework import generics, filters
from chat.api.serializers import ChatMessageSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework.parsers import MultiPartParser
from django.http import FileResponse
from chat.models import UserProfile, Telegram, ChatMessage
from django.utils import timezone
import os
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from rest_framework.permissions import AllowAny
from agent_dump.userbot_manager import TelegramUserBotManager
import shutil

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
                "path": "/api/dataset/",
                "methods": ["POST", "GET"],
                "description": "Upload or download the per-user SFT dataset (JSONL).",
                "sample_request": {
                    "file": "<file> (multipart/form-data)",
                    "username": "alice"  # if not authenticated
                },
                "sample_response": "204 No Content (on upload success) or file download (on GET)"
            },
            {
                "path": "/api/model/",
                "methods": ["POST", "GET", "HEAD"],
                "description": "Upload, download, or check the DPO model zip file for a user.",
                "sample_request": {
                    "file": "<file> (multipart/form-data)",
                    "username": "alice"  # if not authenticated
                },
                "sample_response": "204 No Content (on upload success), file download (on GET), or Content-Length header (on HEAD)"
            },
            {
                "path": "/api/model/unzip/",
                "methods": ["POST"],
                "description": "Unzip the uploaded DPO model for a user.",
                "sample_request": {
                    "username": "alice"
                },
                "sample_response": {
                    "status": "unzipped"
                }
            },
            {
                "path": "/api/agent-training-status/",
                "methods": ["POST"],
                "description": "Update the agent training status for the authenticated user.",
                "sample_request": {
                    "status": "training"  # one of [idle, pending, training, completed, failed]
                },
                "sample_response": {
                    "status": "updated",
                    "agent_training_status": "training",
                    "agent_last_modified": "2025-09-12T12:34:56Z"
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
                "sample_response": {
                    "status": "created"  # or "updated"
                }
            },
            {
                "path": "/api/userbot/",
                "methods": ["POST", "DELETE", "GET"],
                "description": "Start, stop, or query the Telegram userbot for a user.",
                "sample_request": {
                    "username": "alice",
                    "model_choice": "kimi"  # optional, default 'kimi'
                },
                "sample_response": {
                    "status": "started"  # or "stopped", "already running", "not running"
                }
            },
            {
                "path": "/api/messages/",
                "methods": ["GET", "POST"],
                "description": "List, filter, search, or create chat messages.",
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
                        "replied": True,
                        "score": 5,
                        "is_important": False,
                        "is_toxic": False,
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
                    "replied": True,
                    "score": 5,
                    "is_important": False,
                    "is_toxic": False,
                    "sentiment": "positive",
                    "emotion": "happy",
                    "platform": "telegram"
                }
            }
        ]
        return JsonResponse({"api_endpoints": endpoints}, json_dumps_params={"indent": 2})
    


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

        # Create agent_dump/{username} and copy template files/folders
        base_dir = os.path.join('agent_dump', username)
        template_dir = os.path.join('agent_dump', 'emotuna_user')
        os.makedirs(base_dir, exist_ok=True)
        if os.path.exists(template_dir):
            for item in os.listdir(template_dir):
                s = os.path.join(template_dir, item)
                d = os.path.join(base_dir, item)
                if os.path.isdir(s):
                    if not os.path.exists(d):
                        shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

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



# Utility to get per-user dump path
def get_user_dump_path(username):
    base = os.path.join('agent_dump', str(username))
    os.makedirs(base, exist_ok=True)
    return base



class DatasetUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, format=None):
        user = getattr(request, 'user', None)
        username = None
        if user and user.is_authenticated:
            username = user.username
        else:
            username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        dump_dir = get_user_dump_path(username)
        dataset_path = os.path.join(dump_dir, 'sft_dataset.jsonl')
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)
        with open(dataset_path, 'wb+') as f:
            for chunk in file_obj.chunks():
                f.write(chunk)
        return Response(status=204)

    def get(self, request, format=None):
        user = getattr(request, 'user', None)
        username = None
        if user and user.is_authenticated:
            username = user.username
        else:
            username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        dump_dir = get_user_dump_path(username)
        dataset_path = os.path.join(dump_dir, 'sft_dataset.jsonl')
        if os.path.exists(dataset_path):
            return FileResponse(open(dataset_path, 'rb'), as_attachment=True)
        return Response(status=404)



class ModelUnzipView(APIView):
    def post(self, request, format=None):
        import zipfile, shutil
        user = getattr(request, 'user', None)
        username = None
        if user and user.is_authenticated:
            username = user.username
        else:
            username = request.data.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)
        dump_dir = get_user_dump_path(username)
        model_path = os.path.join(dump_dir, 'dpo_model.zip')
        extract_dir = os.path.join(dump_dir, 'dpo_model')
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)
        if not os.path.exists(model_path):
            return Response({'error': 'Model zip not found.'}, status=404)
        with zipfile.ZipFile(model_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        # Delete the zip file after extraction
        try:
            os.remove(model_path)
        except Exception as e:
            print(f"Warning: Could not delete zip file {model_path}: {e}")
        return Response({'status': 'unzipped'}, status=200)



class ModelUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, format=None):
        """Upload model in chunks"""
        user = getattr(request, 'user', None)
        username = request.data.get('username') if not (user and user.is_authenticated) else user.username
        if not username:
            return Response({'error': 'username required'}, status=400)
        dump_dir = get_user_dump_path(username)
        model_path = os.path.join(dump_dir, 'dpo_model.zip')
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)

        # Append chunk
        with open(model_path, 'ab') as f:
            for chunk in file_obj.chunks():
                f.write(chunk)
        return Response({'status': 'Chunk uploaded successfully'}, status=204)

    def head(self, request, format=None):
        """Return Content-Length for HEAD requests"""
        user = getattr(request, 'user', None)
        username = request.query_params.get('username') if not (user and user.is_authenticated) else user.username
        if not username:
            return Response({'error': 'username required'}, status=400)
        dump_dir = get_user_dump_path(username)
        model_path = os.path.join(dump_dir, 'dpo_model.zip')
        if not os.path.exists(model_path):
            return Response(status=404)
        file_size = os.path.getsize(model_path)
        response = Response(status=200)
        response['Content-Length'] = str(file_size)
        response['Accept-Ranges'] = 'bytes'
        return response

    def get(self, request, format=None):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username required'}, status=400)

        dump_dir = get_user_dump_path(username)
        model_path = os.path.join(dump_dir, 'dpo_model.zip')
        if not os.path.exists(model_path):
            return Response(status=404)

        # Serve the full file
        with open(model_path, 'rb') as f:
            data = f.read()
        response = Response(data, status=200, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="dpo_model.zip"'
        response['Content-Length'] = str(os.path.getsize(model_path))
        return response


class AgentTrainingStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        user = request.user
        status_value = request.data.get('status')
        allowed_statuses = ["idle", "pending", "training", "completed", "failed"]
        if status_value not in allowed_statuses:
            return Response({'error': 'Invalid status value.'}, status=400)
        try:
            profile = UserProfile.objects.get(user=user)
            profile.agent_training_status = status_value
            profile.agent_last_modified = timezone.now()
            profile.save()
            return Response({'status': 'updated', 'agent_training_status': status_value, 'agent_last_modified': profile.agent_last_modified}, status=200)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=404)


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