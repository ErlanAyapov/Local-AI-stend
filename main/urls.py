from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = 'main'

urlpatterns = [
    path('', views.index, name='index'),

    path('chat/', views.chat, name='chat'),
    path('chat/<int:pk>/', views.chat_detail, name='chat_detail'),
    path('chat/send/', views.chat_send, name='chat_send_new'),
    path('chat/<int:pk>/send/', views.chat_send, name='chat_send'),
    path('chat/<int:pk>/delete/', views.chat_delete, name='chat_delete'),
    path('chat/models/', views.chat_models, name='chat_models'),
    path('chat/history/', views.chat_history, name='chat_history'),

    path('search/', views.search, name='search'),
    path('tasks/', views.tasks, name='tasks'),
    path('calendar/', views.calendar, name='calendar'),

    path('profile/', views.profile, name='profile'),
    path('profile/apis/', views.api_create, name='api_create'),
    path('profile/apis/<int:pk>/delete/', views.api_delete, name='api_delete'),
    path('profile/apis/<int:pk>/check/', views.api_check, name='api_check'),

    path('login/', views.SignInView.as_view(), name='login'),
    path('register/', views.register, name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
