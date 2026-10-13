from .models import Chat

SIDEBAR_CHATS_LIMIT = 15


def sidebar(request):
    """Последние чаты пользователя для истории в сайдбаре (queryset ленивый)."""
    if not request.user.is_authenticated:
        return {'recent_chats': Chat.objects.none()}
    return {'recent_chats': Chat.objects.filter(user=request.user)[:SIDEBAR_CHATS_LIMIT]}
