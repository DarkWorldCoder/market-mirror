import json
import os
import threading
from flask import request, has_request_context

_thread_local = threading.local()

DEFAULT_LOCALE = 'en'

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

# Load language registry
with open(os.path.join(_locales_dir, 'languages.json'), 'r', encoding='utf-8') as f:
    _languages = json.load(f)

# Load translation files
_translations = {}
for filename in os.listdir(_locales_dir):
    if filename.endswith('.json') and filename != 'languages.json':
        locale_name = filename[:-5]
        with open(os.path.join(_locales_dir, filename), 'r', encoding='utf-8') as f:
            _translations[locale_name] = json.load(f)


def set_locale(locale: str):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = locale


def _parse_accept_language(header: str) -> str:
    """Resolve an Accept-Language header to an available locale.

    Takes tags in order and ignores quality values. Matches the full tag
    first, then the base subtag (``en-US`` -> ``en``). Falls back to
    DEFAULT_LOCALE when no tag matches or no header was sent.
    """
    tags = []
    for part in header.split(','):
        tag = part.split(';')[0].strip().lower()
        if tag:
            tags.append(tag)
    for tag in tags:
        if tag in _translations:
            return tag
    for tag in tags:
        base = tag.split('-')[0]
        if base in _translations:
            return base
    return DEFAULT_LOCALE


def get_locale() -> str:
    if has_request_context():
        return _parse_accept_language(request.headers.get('Accept-Language', ''))
    locale = getattr(_thread_local, 'locale', DEFAULT_LOCALE)
    return locale if locale in _translations else DEFAULT_LOCALE


def t(key: str, **kwargs) -> str:
    locale = get_locale()
    messages = _translations.get(locale, _translations.get(DEFAULT_LOCALE, {}))

    value = messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        value = _translations.get(DEFAULT_LOCALE, {})
        for part in key.split('.'):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break

    if value is None:
        return key

    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_instruction() -> str:
    locale = get_locale()
    lang_config = _languages.get(locale, _languages.get(DEFAULT_LOCALE, {}))
    return lang_config.get('llmInstruction',
                           _languages.get(DEFAULT_LOCALE, {}).get('llmInstruction', ''))
