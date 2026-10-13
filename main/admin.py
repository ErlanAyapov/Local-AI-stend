from django.contrib import admin

from .models import Api, Chat, Message, Profile, Setting, TokenUsage


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'created_at')
    search_fields = ('user__username', 'user__email', 'phone')


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'language', 'notifications_enabled')
    list_filter = ('theme', 'language', 'notifications_enabled')
    search_fields = ('user__username',)


@admin.register(Api)
class ApiAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'api_url', 'user')
    search_fields = ('name', 'api_url', 'user__username')
    exclude = ('api_key',)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ('role', 'sender', 'content', 'used_model', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'selected_model', 'updated_at')
    list_filter = ('updated_at',)
    search_fields = ('title', 'user__username')
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'role', 'sender', 'used_model', 'created_at')
    list_filter = ('role',)
    search_fields = ('content', 'chat__title')


@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'model', 'api_name', 'prompt_tokens', 'completion_tokens', 'total', 'estimated')
    list_filter = ('estimated', 'model', 'api_name', 'created_at')
    search_fields = ('user__username', 'model', 'api_name')
    date_hierarchy = 'created_at'
    list_select_related = ('user',)
    readonly_fields = [f.name for f in TokenUsage._meta.fields]

    @admin.display(description='Всего')
    def total(self, obj):
        return obj.total_tokens

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        # Итоги по текущей выборке (с учётом фильтров) — над таблицей
        response = super().changelist_view(request, extra_context)
        try:
            queryset = response.context_data['cl'].queryset
        except (AttributeError, KeyError):
            return response
        totals = TokenUsage.summary(queryset)
        response.context_data['title'] = (
            f"Расход токенов — вход: {totals['prompt']:,} · выход: {totals['completion']:,} · "
            f"всего: {totals['total']:,} · запросов: {totals['requests']:,}"
        ).replace(',', ' ')
        return response
