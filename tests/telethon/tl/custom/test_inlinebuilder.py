"""Tests for the InlineBuilder changes ported from Telethon-Patch."""
import pytest

from telethon.tl import types
from telethon.tl.custom import InlineBuilder


class MockClient:
    def __init__(self):
        self._markup_calls = []

    def build_reply_markup(self, buttons):
        self._markup_calls.append(buttons)
        return None

    async def _parse_message_text(self, message, parse_mode):
        return message, []


def make_builder():
    return InlineBuilder(MockClient())


class TestArticle:
    @pytest.mark.asyncio
    async def test_type_defaults_to_article(self):
        result = await make_builder().article(title='T', text='body')
        assert result.type == 'article'

    @pytest.mark.asyncio
    async def test_type_can_be_overridden(self):
        """Regression: `type` was hard-coded to "article"."""
        result = await make_builder().article(
            title='T', text='body', type='photo')
        assert result.type == 'photo'

    @pytest.mark.asyncio
    async def test_include_media_is_still_supported(self):
        result = await make_builder().article(
            title='T', text='body', include_media=True)

        assert isinstance(result.send_message,
                          types.InputBotInlineMessageMediaAuto)

    @pytest.mark.asyncio
    async def test_without_include_media_uses_text(self):
        result = await make_builder().article(title='T', text='body')

        assert isinstance(result.send_message,
                          types.InputBotInlineMessageText)

    @pytest.mark.asyncio
    async def test_explicit_id_is_kept(self):
        result = await make_builder().article(
            title='T', text='body', id='my-id')
        assert result.id == 'my-id'

    @pytest.mark.asyncio
    async def test_generated_id_is_deterministic(self):
        builder = make_builder()
        first = await builder.article(title='T', text='body')
        second = await builder.article(title='T', text='body')

        assert first.id == second.id
        assert len(first.id) == 64

    @pytest.mark.asyncio
    async def test_type_changes_the_generated_id(self):
        builder = make_builder()
        article = await builder.article(title='T', text='body')
        photo = await builder.article(title='T', text='body', type='photo')

        assert article.id != photo.id
