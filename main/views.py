from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django_htmx.http import HttpResponseClientRedirect, HttpResponseLocation, trigger_client_event

from . import ai
from .forms import (
    ApiForm, LoginForm, ProfileForm, RegisterForm, SendMessageForm, SettingForm, UserForm,
)
from .models import Api, Chat, Message, Profile, Setting, TokenUsage


# ---------- Вспомогательное ----------

def render_page(request, template_name, context=None):
    """Полная страница для обычного запроса, только контент (partial) — для htmx."""
    if request.htmx and not request.htmx.history_restore_request:
        title = render_to_string(f'{template_name}#title', context, request).strip()
        content = render_to_string(f'{template_name}#content', context, request)
        return HttpResponse(f'<title>{title}</title>{content}')
    return render(request, template_name, context)


def login_required_htmx(view):
    """login_required, который для htmx-запросов делает полную переадресацию на страницу входа."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view(request, *args, **kwargs)
        login_url = f'{resolve_url(settings.LOGIN_URL)}?next={quote(request.get_full_path())}'
        if request.htmx:
            return HttpResponseClientRedirect(login_url)
        return redirect(login_url)
    return wrapper


def safe_next(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return ''


def api_section_response(request, api_form=None, event=None):
    response = render(request, 'main/profile.html#api_section', {
        'apis': Api.objects.filter(user=request.user),
        'api_form': api_form or ApiForm(prefix='api'),
    })
    if event:
        trigger_client_event(response, event)
    return response


# ---------- Страницы ----------

@login_required_htmx
def index(request):
    return render_page(request, 'main/index.html')


@login_required_htmx
def chat(request):
    return render_page(request, 'main/chat.html', {'chat': None, 'chat_messages': []})


@login_required_htmx
def chat_detail(request, pk):
    chat_obj = get_object_or_404(Chat, pk=pk, user=request.user)
    selected = ''
    if chat_obj.selected_model:
        api_id = chat_obj.selected_api_id or ai.DEFAULT_API_ID
        selected = f'{api_id}:{chat_obj.selected_model}'
    return render_page(request, 'main/chat.html', {
        'chat': chat_obj,
        'chat_messages': chat_obj.messages.select_related('token_usage'),
        'selected': selected,
    })


@login_required_htmx
def search(request):
    query = request.GET.get('q', '').strip()
    results = []
    if query:
        results = (
            Chat.objects.filter(user=request.user)
            .filter(Q(title__icontains=query) | Q(messages__content__icontains=query))
            .distinct()[:30]
        )
        for chat_obj in results:
            match = chat_obj.messages.filter(content__icontains=query).first()
            chat_obj.snippet = _snippet(match.content, query) if match else ''

    context = {'query': query, 'results': results}
    if request.htmx and request.htmx.target == 'search-results':
        return render(request, 'main/search.html#results', context)
    return render_page(request, 'main/search.html', context)


def _snippet(text, query, radius=60):
    text = ' '.join(text.split())
    pos = text.lower().find(query.lower())
    if pos == -1:
        return text[:radius * 2]
    start = max(0, pos - radius)
    end = min(len(text), pos + len(query) + radius)
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


@login_required_htmx
def tasks(request):
    return render_page(request, 'main/tasks.html')


@login_required_htmx
def calendar(request):
    return render_page(request, 'main/calendar.html')


# ---------- Чат: действия ----------

@require_POST
def chat_send(request, pk=None):
    """Сохраняет сообщение пользователя, запрашивает ответ модели и возвращает JSON."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Сессия истекла — войдите снова.'}, status=401)

    chat_obj = get_object_or_404(Chat, pk=pk, user=request.user) if pk else None
    form = SendMessageForm(request.POST, user=request.user)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        return JsonResponse({'ok': False, 'error': error}, status=400)

    text = form.cleaned_data['message']
    api = form.cleaned_data['api']
    model = form.cleaned_data['model']
    # Сервер по умолчанию не хранится в БД — в связях пишем None
    db_api = api if isinstance(api, Api) else None

    with transaction.atomic():
        created = chat_obj is None
        if created:
            chat_obj = Chat.objects.create(user=request.user, title=Chat.title_from_text(text))
        Message.objects.create(
            chat=chat_obj, role=Message.Role.USER, sender=request.user,
            content=text, used_api=db_api, used_model=model,
        )
        chat_obj.selected_api = db_api
        chat_obj.selected_model = model
        chat_obj.save(update_fields=['selected_api', 'selected_model', 'updated_at'])

    payload = {
        'ok': True,
        'created': created,
        'chat_id': chat_obj.pk,
        'chat_url': chat_obj.get_absolute_url(),
        'send_url': reverse('main:chat_send', args=[chat_obj.pk]),
        'delete_url': reverse('main:chat_delete', args=[chat_obj.pk]),
        'title': chat_obj.title,
        'model': model,
    }

    try:
        result = ai.chat_completion(api, model, chat_obj.history())
    except ai.AIError as e:
        # Сообщение пользователя сохранено, ответа нет — показываем ошибку в чате
        return JsonResponse({**payload, 'ok': False, 'error': str(e)}, status=502)

    with transaction.atomic():
        reply = Message.objects.create(
            chat=chat_obj, role=Message.Role.ASSISTANT, content=result.content,
            used_api=db_api, used_model=model,
        )
        TokenUsage.objects.create(
            user=request.user, chat=chat_obj, message=reply, api=db_api,
            api_name=api.display_name, model=model,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            estimated=result.estimated,
        )
        chat_obj.save(update_fields=['updated_at'])

    return JsonResponse({
        **payload,
        'reply': result.content,
        'usage': {
            'prompt_tokens': result.prompt_tokens,
            'completion_tokens': result.completion_tokens,
            'estimated': result.estimated,
        },
    })


@login_required_htmx
@require_POST
def chat_delete(request, pk):
    chat_obj = get_object_or_404(Chat, pk=pk, user=request.user)
    chat_obj.delete()
    if request.htmx:
        response = HttpResponseLocation(
            reverse('main:chat'), target='#page-content', swap='innerHTML swap:400ms settle:20ms',
        )
        return trigger_client_event(response, 'chatsChanged')
    return redirect('main:chat')


@login_required_htmx
@require_GET
def chat_models(request):
    """Список моделей всех API пользователя — подгружается в выпадающее меню чата."""
    groups = []
    apis = list(Api.objects.filter(user=request.user))
    default = ai.default_api()
    if default:
        apis.insert(0, default)
    for api in apis:
        try:
            groups.append({'api': api, 'models': ai.list_models(api), 'error': ''})
        except ai.AIError as e:
            groups.append({'api': api, 'models': [], 'error': str(e)})
    return render(request, 'main/chat.html#model_options', {'groups': groups})


@require_GET
def chat_history(request):
    """Список чатов в сайдбаре (обновляется после создания/удаления чата)."""
    return render(request, 'base.html#history')


# ---------- Профиль и API ----------

def profile(request):
    """Форма профиля и настроек — открывается в модальном окне через htmx."""
    if not request.htmx:
        return redirect('main:index')

    if not request.user.is_authenticated:
        return render(request, 'main/profile.html', {'next': request.htmx.current_url_abs_path or '/'})

    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    setting_obj, _ = Setting.objects.get_or_create(user=request.user)
    saved = False

    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user, prefix='user')
        profile_form = ProfileForm(request.POST, request.FILES, instance=profile_obj, prefix='profile')
        setting_form = SettingForm(request.POST, instance=setting_obj, prefix='setting')
        if user_form.is_valid() and profile_form.is_valid() and setting_form.is_valid():
            user_form.save()
            profile_form.save()
            setting_form.save()
            saved = True
            # Свежие формы, чтобы файловое поле не держало загруженный файл
            user_form = UserForm(instance=request.user, prefix='user')
            profile_form = ProfileForm(instance=profile_obj, prefix='profile')
            setting_form = SettingForm(instance=setting_obj, prefix='setting')
    else:
        user_form = UserForm(instance=request.user, prefix='user')
        profile_form = ProfileForm(instance=profile_obj, prefix='profile')
        setting_form = SettingForm(instance=setting_obj, prefix='setting')

    active_tab = request.POST.get('active_tab') or request.GET.get('tab') or 'profile'
    if active_tab not in ('profile', 'settings', 'api', 'usage'):
        active_tab = 'profile'

    return render(request, 'main/profile.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'setting_form': setting_form,
        'profile': profile_obj,
        'saved': saved,
        'active_tab': active_tab,
        'apis': Api.objects.filter(user=request.user),
        'api_form': ApiForm(prefix='api'),
        'default_api': ai.default_api(),
        'usage': usage_stats(request.user),
    })


def usage_stats(user):
    """Сводка расхода токенов пользователя для вкладки «Расход»."""
    records = TokenUsage.objects.filter(user=user)
    now = timezone.localtime()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_model = (
        records.values('model', 'api_name')
        .annotate(prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens'), requests=Count('pk'))
        .order_by('-completion', '-prompt')[:10]
    )
    return {
        'all': TokenUsage.summary(records),
        'month': TokenUsage.summary(records.filter(created_at__gte=month_start)),
        'today': TokenUsage.summary(records.filter(created_at__gte=day_start)),
        'by_model': [{**row, 'total': row['prompt'] + row['completion']} for row in by_model],
        'has_estimated': records.filter(estimated=True).exists(),
    }


@login_required_htmx
@require_POST
def api_create(request):
    form = ApiForm(request.POST, prefix='api')
    if not form.is_valid():
        return api_section_response(request, api_form=form)
    api = form.save(commit=False)
    api.user = request.user
    api.setting, _ = Setting.objects.get_or_create(user=request.user)
    api.save()
    return api_section_response(request, event='apisChanged')


@login_required_htmx
@require_POST
def api_delete(request, pk):
    api = get_object_or_404(Api, pk=pk, user=request.user)
    ai.forget_models(api)
    api.delete()
    return api_section_response(request, event='apisChanged')


@login_required_htmx
@require_POST
def api_check(request, pk):
    api = get_object_or_404(Api, pk=pk, user=request.user)
    try:
        models = ai.list_models(api, use_cache=False)
    except ai.AIError as e:
        return HttpResponse(format_html('<span class="api-status is-error">{}</span>', e))
    return HttpResponse(format_html('<span class="api-status is-ok">Подключено · моделей: {}</span>', len(models)))


# ---------- Вход и регистрация ----------

class SignInView(LoginView):
    template_name = 'main/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


def register(request):
    next_url = safe_next(request)

    if request.user.is_authenticated:
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    else:
        form = RegisterForm()

    return render(request, 'main/register.html', {'form': form, 'next': next_url})
