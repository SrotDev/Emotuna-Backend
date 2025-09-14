from django.urls import path
from chat.api import views

urlpatterns = [
    path('', views.APIEndpointsInfoView.as_view(), name='api-info'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('dataset/', views.DatasetUploadView.as_view(), name='dataset-upload'),
    path('model/', views.ModelUploadView.as_view(), name='model-upload'),
    path('model/unzip/', views.ModelUnzipView.as_view(), name='model-unzip'),
    path('agent_status/', views.AgentStatusView.as_view(), name='agent-status'),
    path('telegram/', views.TelegramModelView.as_view(), name='telegram-model'),
    path('userbot/', views.UserbotControlView.as_view(), name='userbot-control'),
    path('messages/', views.ChatMessageListCreateView.as_view(), name='chatmessage-list-create'),
    path('messages/<int:pk>/', views.ChatMessageDetailView.as_view(), name='chatmessage-detail'),
    path('create_superuser/', views.CreateSuperuserView.as_view(), name='create-superuser'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('notifications/', views.NotificationViewSet.as_view({'get': 'list', 'post': 'create'}), name='notification-list'),
    path('notifications/<int:pk>/', views.NotificationViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='notification-detail'),
]