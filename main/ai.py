"""Клиент для OpenAI-совместимых API (Ollama, LM Studio, vLLM, OpenAI, OpenRouter …).

api_url — базовый адрес, например http://localhost:11434/v1 или https://api.openai.com/v1
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

MODELS_TIMEOUT = 5
CHAT_TIMEOUT = 180
MODELS_CACHE_TTL = 300


DEFAULT_API_ID = 'default'


class AIError(Exception):
    """Ошибка обращения к API — текст безопасно показывать пользователю."""


@dataclass(frozen=True)
class DefaultApi:
    """Сервер из .env (LLM_URL / LLM_API_KEY) — ведёт себя как модель Api."""
    pk: str
    api_url: str
    api_key: str
    display_name: str
    is_default: bool = True


def default_api():
    """Сервер по умолчанию или None, если LLM_URL не задан."""
    if not settings.DEFAULT_LLM_URL:
        return None
    return DefaultApi(
        pk=DEFAULT_API_ID,
        api_url=settings.DEFAULT_LLM_URL,
        api_key=settings.DEFAULT_LLM_API_KEY,
        display_name=settings.DEFAULT_LLM_NAME,
    )


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    estimated: bool


def estimate_tokens(text):
    """Грубая оценка, если API не вернул usage (~4 символа на токен)."""
    return max(1, round(len(text) / 4)) if text else 0


def _error_detail(body):
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body.decode('utf-8', 'replace')[:200] if body else ''
    error = data.get('error') if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get('message', ''))[:200]
    return str(error or data)[:200]


def _request(api, path, payload=None, timeout=CHAT_TIMEOUT):
    url = api.api_url.rstrip('/') + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, method='POST' if data else 'GET')
    request.add_header('Accept', 'application/json')
    if data:
        request.add_header('Content-Type', 'application/json')
    if api.api_key:
        request.add_header('Authorization', f'Bearer {api.api_key}')

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        detail = _error_detail(e.read())
        raise AIError(f'API вернул ошибку {e.code}' + (f': {detail}' if detail else '')) from e
    except TimeoutError as e:
        raise AIError('API не ответил вовремя') from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, 'reason', e)
        raise AIError(f'Не удалось подключиться к API: {reason}') from e

    try:
        return json.loads(body)
    except ValueError as e:
        raise AIError('API вернул некорректный ответ (не JSON)') from e


def _models_cache_key(api):
    return f'ai-models:{api.pk}'


def list_models(api, use_cache=True):
    """Список id моделей, доступных в API."""
    key = _models_cache_key(api)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached

    data = _request(api, '/models', timeout=MODELS_TIMEOUT)
    items = data.get('data', []) if isinstance(data, dict) else []
    models = sorted({str(item['id']) for item in items if isinstance(item, dict) and item.get('id')})
    cache.set(key, models, MODELS_CACHE_TTL)
    return models


def forget_models(api):
    cache.delete(_models_cache_key(api))


def chat_completion(api, model, messages):
    """Отправляет историю диалога и возвращает ответ модели с расходом токенов."""
    data = _request(api, '/chat/completions', {
        'model': model,
        'messages': messages,
        'stream': False,
    })
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as e:
        raise AIError('Неожиданный формат ответа API') from e
    content = (content or '').strip()
    if not content:
        raise AIError('Модель вернула пустой ответ')

    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    prompt_tokens = usage.get('prompt_tokens')
    completion_tokens = usage.get('completion_tokens')
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        return ChatResult(content, prompt_tokens, completion_tokens, estimated=False)
    return ChatResult(
        content,
        prompt_tokens=sum(estimate_tokens(m.get('content', '')) for m in messages),
        completion_tokens=estimate_tokens(content),
        estimated=True,
    )
