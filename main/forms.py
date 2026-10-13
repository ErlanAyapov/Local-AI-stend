from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from . import ai
from .models import Api, Profile, Setting

AVATAR_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
AVATAR_MAX_SIZE = 5 * 1024 * 1024

THEME_CHOICES = [
    ('dark', 'Тёмная'),
    ('light', 'Светлая'),
]

LANGUAGE_CHOICES = [
    ('ru', 'Русский'),
    ('en', 'English'),
]


class HudFormMixin:
    """Проставляет виджетам CSS-классы в стиле интерфейса."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'hud-switch-input'
            elif isinstance(widget, forms.FileInput):
                css = 'visually-hidden'
            elif isinstance(widget, forms.Select):
                css = 'hud-input hud-select'
            else:
                css = 'hud-input'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()


class UserForm(HudFormMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name', 'email')
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email'}),
        }


class ProfileForm(HudFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('avatar', 'phone', 'bio')
        widgets = {
            'avatar': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/gif,image/webp'}),
            'phone': forms.TextInput(attrs={'autocomplete': 'tel', 'inputmode': 'tel'}),
            'bio': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        # Проверяем только новый загруженный файл
        if avatar and hasattr(avatar, 'content_type'):
            if Path(avatar.name).suffix.lower() not in AVATAR_EXTENSIONS:
                raise forms.ValidationError('Допустимы только изображения JPG, PNG, GIF или WEBP.')
            if not avatar.content_type.startswith('image/') or avatar.content_type == 'image/svg+xml':
                raise forms.ValidationError('Файл не похож на изображение.')
            if avatar.size > AVATAR_MAX_SIZE:
                raise forms.ValidationError('Размер файла не должен превышать 5 МБ.')
        return avatar


class SettingForm(HudFormMixin, forms.ModelForm):
    theme = forms.ChoiceField(label='Тема', choices=THEME_CHOICES)
    language = forms.ChoiceField(label='Язык', choices=LANGUAGE_CHOICES)

    class Meta:
        model = Setting
        fields = ('theme', 'language', 'notifications_enabled')


class LoginForm(HudFormMixin, AuthenticationForm):
    pass


class RegisterForm(HudFormMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True


class ApiForm(HudFormMixin, forms.ModelForm):
    class Meta:
        model = Api
        fields = ('name', 'api_url', 'api_key')
        labels = {'api_url': 'Базовый URL'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ollama'}),
            'api_url': forms.URLInput(attrs={'placeholder': 'http://localhost:11434/v1'}),
            'api_key': forms.PasswordInput(attrs={'placeholder': 'Не обязательно для локальных моделей', 'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Поля привязаны к отдельной форме, т.к. в модалке они лежат внутри формы профиля
        for field in self.fields.values():
            field.widget.attrs['form'] = 'api-add-form'


class SendMessageForm(forms.Form):
    MAX_LENGTH = 10000

    message = forms.CharField(max_length=MAX_LENGTH, strip=True)
    api = forms.CharField(max_length=20, error_messages={'required': 'Выберите модель.'})
    model = forms.CharField(max_length=255, error_messages={'required': 'Выберите модель.'})

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_api(self):
        """Возвращает Api пользователя или сервер по умолчанию из .env."""
        value = self.cleaned_data['api']
        if value == ai.DEFAULT_API_ID:
            default = ai.default_api()
            if default:
                return default
        elif value.isdigit():
            api = Api.objects.filter(user=self.user, pk=int(value)).first()
            if api:
                return api
        raise forms.ValidationError('Выбранный API не найден.')
