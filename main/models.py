from django.conf import settings
from django.db import models
from django.urls import reverse


class AbstractProfile(models.Model):
    """Абстрактная модель профиля, связанная с пользователем через OneToOne."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='%(class)s',
        verbose_name='Пользователь',
    )
    avatar = models.FileField('Аватар', upload_to='avatars/', blank=True, null=True)
    bio = models.TextField('О себе', blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return str(self.user)


class Profile(AbstractProfile):
    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

class Setting(models.Model):
    """Модель настроек приложения."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='settings',
        verbose_name='Пользователь',
    )
    theme = models.CharField('Тема', max_length=50, default='light')
    notifications_enabled = models.BooleanField('Уведомления включены', default=True)
    language = models.CharField('Язык', max_length=10, default='en')

    class Meta:
        verbose_name = 'Настройка'
        verbose_name_plural = 'Настройки'

    def __str__(self):
        return f"Настройки пользователя {self.user.username}"

class Api(models.Model):
    """Модель настроек API."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='api_settings',
        verbose_name='Пользователь',
    )
    api_url = models.URLField('URL API', max_length=200)
    api_key = models.CharField('API ключ', max_length=255, blank=True)
    setting = models.ForeignKey(
        Setting,
        on_delete=models.CASCADE,
        related_name='api_settings',
        verbose_name='Настройка',
    )
    name = models.CharField('Название', max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = 'Настройка API'
        verbose_name_plural = 'Настройки API'
        ordering = ['pk']

    @property
    def display_name(self):
        return self.name or self.api_url

    @property
    def masked_key(self):
        if not self.api_key:
            return ''
        return '•' * 6 + self.api_key[-4:]

    def __str__(self):
        return f"API настройки для {self.user.username} - {self.name or 'Без названия'}"


class Chat(models.Model):
    """Модель чата."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chats',
        verbose_name='Пользователь',
    )
    title = models.CharField('Название', max_length=255)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)
    selected_api = models.ForeignKey(
        Api,
        on_delete=models.SET_NULL,
        related_name='chats',
        verbose_name='Выбранный API',
        null=True,
        blank=True,
    )
    selected_model = models.CharField('Выбранная модель', max_length=255, blank=True, null=True)

    TITLE_LENGTH = 60

    class Meta:
        verbose_name = 'Чат'
        verbose_name_plural = 'Чаты'
        ordering = ['-updated_at']

    def get_absolute_url(self):
        return reverse('main:chat_detail', args=[self.pk])

    @classmethod
    def title_from_text(cls, text):
        text = ' '.join(text.split())
        if len(text) <= cls.TITLE_LENGTH:
            return text
        return text[:cls.TITLE_LENGTH - 1].rstrip() + '…'

    def history(self, limit=30):
        """Последние сообщения в формате, который понимает OpenAI-совместимый API."""
        recent = list(self.messages.order_by('-created_at', '-pk')[:limit])
        return [{'role': m.role, 'content': m.content} for m in reversed(recent)]

    def __str__(self):
        return f"Чат {self.title} для {self.user.username}"


class Message(models.Model):
    """Модель сообщения в чате."""

    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Чат',
    )
    class Role(models.TextChoices):
        USER = 'user', 'Пользователь'
        ASSISTANT = 'assistant', 'Ассистент'

    role = models.CharField('Роль', max_length=20, choices=Role.choices, default=Role.USER)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='Отправитель',
        null=True,
        blank=True,
    )
    content = models.TextField('Содержимое')
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    used_api = models.ForeignKey(
        Api,
        on_delete=models.SET_NULL,
        related_name='messages',
        verbose_name='Используемый API',
        null=True,
        blank=True,
    )
    used_model = models.CharField('Используемая модель', max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['created_at', 'pk']

    @property
    def is_user(self):
        return self.role == self.Role.USER

    def __str__(self):
        author = self.sender.username if self.sender else (self.used_model or 'AI')
        return f"Сообщение от {author} в чате {self.chat.title}"

class TokenUsage(models.Model):
    """Расход токенов: одна запись на каждый запрос к модели.

    Записи не удаляются вместе с чатом — это журнал учёта.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='token_usage',
        verbose_name='Пользователь',
    )
    chat = models.ForeignKey(
        Chat,
        on_delete=models.SET_NULL,
        related_name='token_usage',
        verbose_name='Чат',
        null=True,
        blank=True,
    )
    message = models.OneToOneField(
        Message,
        on_delete=models.SET_NULL,
        related_name='token_usage',
        verbose_name='Ответ модели',
        null=True,
        blank=True,
    )
    api = models.ForeignKey(
        Api,
        on_delete=models.SET_NULL,
        related_name='token_usage',
        verbose_name='API',
        null=True,
        blank=True,
    )
    api_name = models.CharField('Название API', max_length=255, blank=True)
    model = models.CharField('Модель', max_length=255)
    prompt_tokens = models.PositiveIntegerField('Входные токены', default=0)
    completion_tokens = models.PositiveIntegerField('Выходные токены', default=0)
    estimated = models.BooleanField('Оценка', default=False, help_text='API не вернул usage — посчитано приблизительно')
    created_at = models.DateTimeField('Создано', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Расход токенов'
        verbose_name_plural = 'Расход токенов'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'created_at'])]

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    @classmethod
    def summary(cls, queryset):
        """Суммы входных/выходных токенов и число запросов по queryset."""
        data = queryset.aggregate(
            prompt=models.Sum('prompt_tokens', default=0),
            completion=models.Sum('completion_tokens', default=0),
            requests=models.Count('pk'),
        )
        data['total'] = data['prompt'] + data['completion']
        return data

    def __str__(self):
        return f'{self.user} · {self.model} · {self.prompt_tokens}↑ {self.completion_tokens}↓'
