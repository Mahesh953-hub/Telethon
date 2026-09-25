"""Tests for the Button and Message extensions ported from Telethon-Patch."""
import pytest

from telethon import Button, utils
from telethon.tl import types
from telethon.tl.custom import Message


class TestButtonMention:
    def test_mention_builds_a_user_profile_inline_button(self):
        user = types.InputUser(user_id=7, access_hash=8)
        button = Button.mention('Open Profile', user)

        assert isinstance(button, types.KeyboardInlineButton)
        assert button.text == 'Open Profile'
        assert isinstance(button.type,
                          types.InputInlineButtonTypeUserProfile)
        assert button.type.user_id is user

    def test_mention_accepts_a_user_object(self):
        user = types.User(id=7, access_hash=8)
        button = Button.mention('Profile', user)

        assert button.type.user_id == types.InputUser(user_id=7,
                                                      access_hash=8)

    def test_mention_is_recognised_as_inline(self):
        user = types.InputUser(user_id=7, access_hash=8)
        assert Button._is_inline(Button.mention('Profile', user))

    def test_mention_accepts_a_style(self):
        user = types.InputUser(user_id=7, access_hash=8)
        button = Button.mention('Profile', user, style='primary')
        assert button.style.bg_primary is True

    def test_mention_rejects_unusable_input(self):
        with pytest.raises(ValueError):
            Button.mention('Profile', 'just-a-username')


class TestButtonWeb:
    def test_web_builds_a_keyboard_button(self):
        button = Button.web('Open', 'https://example.com')

        assert button.resize is None
        markup = markup_of(button)
        assert isinstance(markup.button, types.KeyboardButton)
        assert markup.button.text == 'Open'
        assert isinstance(markup.button.type, types.ButtonTypeSimpleWebView)
        assert markup.button.type.url == 'https://example.com'

    def test_web_forwards_markup_options(self):
        button = Button.web('Open', 'https://example.com', resize=True,
                            single_use=True, selective=True, persistent=True,
                            placeholder='type here')

        assert button.resize is True
        assert button.single_use is True
        assert button.selective is True
        assert button.persistent is True
        assert button.placeholder == 'type here'

    def test_web_is_not_inline(self):
        # A reply-keyboard button, unlike `web_view`.
        assert not Button._is_inline(
            markup_of(Button.web('Open', 'https://e.com')).button)

    def test_web_view_is_an_inline_button(self):
        button = Button.web_view('Open', 'https://example.com')

        assert isinstance(button, types.KeyboardInlineButton)
        assert isinstance(button.type, types.InlineButtonTypeWebView)
        assert button.type.url == 'https://example.com'
        assert Button._is_inline(button)


def markup_of(button):
    """`Button` is itself the markup wrapper, so hand it straight back."""
    return button


class MockClient:
    def __init__(self):
        self.calls = []

    async def send_message(self, entity, message='', **kwargs):
        self.calls.append(('send_message', entity, message, kwargs))
        return 'sent'

    async def send_reaction(self, peer, msg_id, *args, **kwargs):
        self.calls.append(('send_reaction', peer, msg_id, args, kwargs))
        return 'reacted'


def make_message(client, peer=None, msg_id=42):
    if peer is None:
        peer = types.PeerChat(chat_id=10)
    message = Message(id=msg_id, peer_id=peer, date=None, message='hi')
    message._client = client
    message._entities = {}
    return message


class TestMessageComment:
    @pytest.mark.asyncio
    async def test_comment_sets_comment_to(self):
        client = MockClient()
        message = make_message(client)
        message._input_chat = types.InputPeerChat(chat_id=10)

        assert await message.comment('nice') == 'sent'

        name, entity, text, kwargs = client.calls[0]
        assert name == 'send_message'
        assert text == 'nice'
        assert kwargs['comment_to'] == 42

    @pytest.mark.asyncio
    async def test_comment_without_client_does_nothing(self):
        message = make_message(None)
        message._client = None
        assert await message.comment('nice') is None


class TestMessageReact:
    @pytest.mark.asyncio
    async def test_react_delegates_to_send_reaction(self):
        client = MockClient()
        message = make_message(client)
        message._input_chat = types.InputPeerChat(chat_id=10)

        assert await message.react('👍') == 'reacted'

        name, peer, msg_id, args, kwargs = client.calls[0]
        assert name == 'send_reaction'
        assert msg_id == 42
        assert args == ('👍',)

    @pytest.mark.asyncio
    async def test_react_without_client_does_nothing(self):
        message = make_message(None)
        message._client = None
        assert await message.react('👍') is None


class TestMessageLink:
    def test_public_chat_uses_username(self):
        message = make_message(None)
        message._chat = types.Channel(id=1, access_hash=2, title='c',
                                      username='mychannel',
                                      photo=types.ChatPhotoEmpty(), date=None)

        assert message.message_link == 'https://t.me/mychannel/42'

    def test_private_channel_strips_the_minus_100_prefix(self):
        """Regression: the old code never stripped `-100`."""
        message = make_message(None, peer=types.PeerChannel(1234567890))
        message._chat = types.Channel(id=1234567890, access_hash=2, title='c',
                                      photo=types.ChatPhotoEmpty(), date=None)

        assert message.message_link == 'https://t.me/c/1234567890/42'

    def test_basic_chat_is_unchanged(self):
        message = make_message(None, peer=types.PeerChat(10))
        message._chat = types.Chat(id=10, title='c',
                                   photo=types.ChatPhotoEmpty(),
                                   participants_count=2, date=None,
                                   version=1)

        assert message.message_link == 'https://t.me/c/10/42'

    def test_marked_chat_id_from_chat_id_alone(self):
        message = make_message(None, peer=types.PeerChannel(1234567890))
        message._chat = None

        assert message.message_link == 'https://t.me/c/1234567890/42'

    def test_private_chat(self):
        message = make_message(None, peer=types.PeerUser(555))
        message._chat = types.User(id=555, access_hash=1)

        assert message.message_link == 'https://t.me/c/555/42'

    def test_uses_resolve_id_not_string_replacement(self):
        # The old `"-100".replace()` approach mangled ordinary chat IDs.
        resolved, _ = utils.resolve_id(-1001234567890)
        message = make_message(None, peer=types.PeerChannel(1234567890))
        message._chat = None

        assert message.message_link == 'https://t.me/c/{}/42'.format(resolved)
