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

    Takes tags in order and ignores quality values. Each tag is fully
    processed before the next one: the full tag is tried first, then the
    base subtag (``en-US`` -> ``en``), so an earlier regional tag keeps
    priority over a different full tag that appears later. Falls back to
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
        base = tag.split('-')[0]
        if base in _translations:
            return base
    return DEFAULT_LOCALE


def get_locale() -> str:
    """Return the locale for the current context.

    Inside a request this is parsed from the Accept-Language header;
    otherwise the thread locale set by :func:`set_locale` is used after
    validating it against the available translations.
    """
    if has_request_context():
        return _parse_accept_language(request.headers.get('Accept-Language', ''))
    locale = getattr(_thread_local, 'locale', DEFAULT_LOCALE)
    return locale if locale in _translations else DEFAULT_LOCALE


def t(key: str, **kwargs) -> str:
    """Translate a dotted key in the current locale.

    Falls back to the default locale when the key is missing there, and
    returns the key itself when it is unknown in every locale. ``kwargs``
    are substituted into ``{placeholder}`` slots of the message.
    """
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
    """Return the LLM instruction line for the current locale, in English when unknown."""
    locale = get_locale()
    lang_config = _languages.get(locale, _languages.get(DEFAULT_LOCALE, {}))
    return lang_config.get('llmInstruction',
                           _languages.get(DEFAULT_LOCALE, {}).get('llmInstruction', ''))
