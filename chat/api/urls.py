from django.urls import path, include
from chat.api import views

urlpatterns = [
    path('', views.APIEndpointsInfoView.as_view(), name='api-info'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('dataset/', views.DatasetUploadView.as_view(), name='dataset-upload'),
    path('model/', views.ModelUploadView.as_view(), name='model-upload'),
    path('model/unzip/', views.ModelUnzipView.as_view(), name='model-unzip'),
    path('agent-training-status/', views.AgentTrainingStatusView.as_view(), name='agent-training-status'),
    path('telegram/', views.TelegramModelView.as_view(), name='telegram-model'),
    path('userbot/', views.UserbotControlView.as_view(), name='userbot-control'),
    path('messages/', views.ChatMessageListCreateView.as_view(), name='chatmessage-list-create'),
    path('messages/<int:pk>/', views.ChatMessageDetailView.as_view(), name='chatmessage-detail'),
    path('create-superuser/', views.CreateSuperuserView.as_view(), name='create-superuser'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
]