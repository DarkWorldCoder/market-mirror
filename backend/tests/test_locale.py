"""Accept-Language parsing and locale fallback tests (no server needed)."""
import pytest
from flask import Flask

from app.utils.locale import get_locale, get_language_instruction, set_locale, t


@pytest.fixture()
def app():
    return Flask(__name__)


def test_browser_header_resolves_base_subtag(app):
    with app.test_request_context(headers={'Accept-Language': 'en-US,en;q=0.9'}):
        assert get_locale() == 'en'


def test_zh_full_tag_wins_over_later_en(app):
    with app.test_request_context(headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}):
        assert get_locale() == 'zh'


def test_regional_tag_beats_later_full_tag(app):
    # A regional tag earlier in the header keeps priority over a different
    # supported full tag that appears later: en-GB falls back to en before zh.
    with app.test_request_context(headers={'Accept-Language': 'en-GB,zh'}):
        assert get_locale() == 'en'


def test_missing_header_defaults_to_en(app):
    with app.test_request_context():
        assert get_locale() == 'en'


def test_unavailable_tags_fall_back_to_en(app):
    with app.test_request_context(headers={'Accept-Language': 'fr,de;q=0.5'}):
        assert get_locale() == 'en'


def test_t_translates_in_resolved_locale(app):
    with app.test_request_context(headers={'Accept-Language': 'zh-CN'}):
        assert t('common.confirm') != 'Confirm'
    with app.test_request_context(headers={'Accept-Language': 'en-US,en;q=0.9'}):
        assert t('common.confirm') == 'Confirm'


def test_t_missing_key_returns_key_itself(app):
    with app.test_request_context():
        assert t('does.not.exist') == 'does.not.exist'


def test_language_instruction_follows_resolved_locale(app):
    with app.test_request_context(headers={'Accept-Language': 'zh-CN'}):
        instruction = get_language_instruction()
        assert instruction == '请使用中文回答。'
    with app.test_request_context(headers={'Accept-Language': 'en-US,en;q=0.9'}):
        assert get_language_instruction() == 'Please respond in English.'


def test_thread_locale_outside_request_is_validated():
    set_locale('es')  # languages.json advertises es but no es.json exists
    try:
        assert get_locale() == 'en'
        assert t('common.confirm') == 'Confirm'
    finally:
        set_locale('en')
