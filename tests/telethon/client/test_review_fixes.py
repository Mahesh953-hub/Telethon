"""Regression tests for the review findings on PR #1.

Each of these failed silently at runtime rather than raising, which is why
they are pinned here: `random_id=None` serialised as a garbage integer, and
`message_link` produced a `/c/` URL for one-to-one dialogs.
"""
import pytest

from telethon.tl import types
from telethon.tl.custom import Message


class TestRandomIdIsAlwaysGenerated:
    """`random_id` is required; `None` serialised instead of raising."""

    @pytest.mark.asyncio
    async def test_create_group_call_generates_random_id(self):
        from telethon.client.groupcall import GroupCallMethods

        captured = {}

        class Client(GroupCallMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                captured['request'] = request
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.create_group_call(types.InputPeerChat(1), title='t')

        random_id = captured['request'].random_id
        assert random_id is not None
        # Must be a real integer, not the garbage `None` produced.
        assert isinstance(random_id, int)
        assert abs(random_id) > 1

    @pytest.mark.asyncio
    async def test_create_group_call_honours_explicit_random_id(self):
        from telethon.client.groupcall import GroupCallMethods

        captured = {}

        class Client(GroupCallMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                captured['request'] = request
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.create_group_call(
            types.InputPeerChat(1), title='t', random_id=12345)

        assert captured['request'].random_id == 12345

    @pytest.mark.asyncio
    async def test_generated_random_id_differs_between_calls(self):
        from telethon.client.groupcall import GroupCallMethods

        seen = []

        class Client(GroupCallMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                seen.append(request.random_id)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.create_group_call(types.InputPeerChat(1), title='a')
        await client.create_group_call(types.InputPeerChat(1), title='b')

        assert seen[0] != seen[1], 'random_id must be unique per call'

    @pytest.mark.asyncio
    async def test_create_topic_generates_random_id(self):
        from telethon.client.topics import TopicMethods

        captured = {}

        class Client(TopicMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                captured['request'] = request
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.create_topic(types.InputPeerChat(1), title='topic')

        random_id = captured['request'].random_id
        assert isinstance(random_id, int)
        assert abs(random_id) > 1

    def test_none_random_id_would_have_been_garbage(self):
        """Documents *why* the guard exists.

        Passing ``None`` straight through does not raise - it serialises
        as a non-zero garbage integer, so the failure only appears
        server-side as an opaque error.
        """
        from telethon.tl.functions import phone

        with_none = phone.CreateGroupCallRequest(
            peer=types.InputPeerChat(1), random_id=None, title='t')
        assert len(with_none.__bytes__()) > 0, 'None still serialises'
        # Proving it is not simply zero:
        assert with_none.__bytes__() != phone.CreateGroupCallRequest(
            peer=types.InputPeerChat(1), random_id=0, title='t'
        ).__bytes__()


class TestMessageLink:
    """`/c/` links address channels, never one-to-one user dialogs."""

    def test_user_peer_has_no_link(self):
        message = Message(
            id=42, peer_id=types.PeerUser(user_id=555), date=None,
            message='hi')
        assert message.message_link is None

    def test_private_channel_uses_c_form(self):
        message = Message(
            id=42, peer_id=types.PeerChannel(channel_id=1001234567890),
            date=None, message='hi')
        link = message.message_link
        assert link is not None
        # The -100 prefix must be stripped exactly once.
        assert link == 'https://t.me/c/1001234567890/42'
        assert '-100' not in link

    def test_private_chat_uses_c_form(self):
        message = Message(
            id=42, peer_id=types.PeerChat(chat_id=10), date=None,
            message='hi')
        assert message.message_link == 'https://t.me/c/10/42'

    def test_public_chat_uses_username(self):
        # Only a Channel carries a username, and `chat` is populated by
        # ChatGetter._load_chat rather than being a constructor argument.
        chat = types.Channel(
            id=10, title='pub', photo=types.ChatPhotoEmpty(),
            participants_count=2, date=None,
            username='mychannel', access_hash=3)
        message = Message(
            id=42, peer_id=types.PeerChannel(channel_id=10), date=None,
            message='hi')
        message._chat = chat
        assert message.message_link == 'https://t.me/mychannel/42'


class TestPythonFloor:
    """The project declares `requires-python = ">=3.5"`."""

    def test_rawrequests_avoids_str_removeprefix(self):
        import ast
        import inspect

        from telethon.client import rawrequests

        source = inspect.getsource(rawrequests)
        # Check the code, not the comments: the file documents *why* it
        # avoids these, so a plain substring search matches the prose.
        tree = ast.parse(inspect.cleandoc(source))
        called = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in ('removeprefix', 'removesuffix')
        }
        assert not called, (
            'str.{} is 3.9+ but requires-python is >=3.5'.format(
                sorted(called)[0]))

    def test_namespace_extraction_still_works(self):
        from telethon.client.rawrequests import _QUALIFIED_REQUESTS, _namespace_of

        for request in list(_QUALIFIED_REQUESTS.values())[:20]:
            namespace = _namespace_of(request)
            assert namespace
            assert not namespace.startswith('telethon.tl.functions.')


class TestJoinChatRouting:
    """A bare username must not be sent as an invite hash."""

    @pytest.mark.asyncio
    async def test_username_routes_to_entity_not_hash(self):
        from telethon.client.pyrogram import PyrogramMethods
        from telethon.tl.functions import channels, messages

        sent = []

        class Client(PyrogramMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

            async def get_entity(self, peer):
                return types.Channel(
                    id=10, title='pub', photo=types.ChatPhotoEmpty(),
                    participants_count=2, date=None, access_hash=1)

        client = Client()
        await client.join_chat('somechannel')

        assert sent, 'a request should have been sent'
        # An ImportChatInviteRequest here would be the bug.
        assert not isinstance(sent[0], messages.ImportChatInviteRequest)
        assert isinstance(sent[0], channels.JoinChannelRequest)

    @pytest.mark.asyncio
    async def test_plus_prefix_routes_to_invite_hash(self):
        from telethon.client.pyrogram import PyrogramMethods
        from telethon.tl.functions import messages

        sent = []

        class Client(PyrogramMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.join_chat('+AbCdEf')

        assert isinstance(sent[0], messages.ImportChatInviteRequest)
        assert sent[0].hash == 'AbCdEf'

    @pytest.mark.asyncio
    async def test_tme_link_routes_to_invite_hash(self):
        from telethon.client.pyrogram import PyrogramMethods
        from telethon.tl.functions import messages

        sent = []

        class Client(PyrogramMethods):
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await client.join_chat('https://t.me/+JoinChat')

        assert isinstance(sent[0], messages.ImportChatInviteRequest)
        assert sent[0].hash == 'JoinChat'


class TestEmptyReactionClears:
    """`reaction=[]` must become `[ReactionEmpty()]`, not an empty vector."""

    @pytest.mark.asyncio
    async def test_empty_iterable_sends_reaction_empty(self):
        from telethon.client.topics import send_reaction
        from telethon.tl.functions import messages

        sent = []

        class Client:
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await send_reaction(client, 1, 1, reaction=[])

        request = sent[0]
        assert isinstance(request, messages.SendReactionRequest)
        assert len(request.reaction) == 1
        assert isinstance(request.reaction[0], types.ReactionEmpty)

    @pytest.mark.asyncio
    async def test_none_sends_reaction_empty(self):
        from telethon.client.topics import send_reaction

        sent = []

        class Client:
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await send_reaction(client, 1, 1, reaction=None)

        assert isinstance(sent[0].reaction[0], types.ReactionEmpty)

    @pytest.mark.asyncio
    async def test_explicit_reactions_are_preserved(self):
        from telethon.client.topics import send_reaction

        sent = []

        class Client:
            async def __call__(self, request, ordered=False, **kwargs):
                sent.append(request)
                return types.Updates(
                    updates=[], users=[], chats=[], date=None, seq=0)

        client = Client()
        await send_reaction(client, 1, 1, reaction=['\U0001F44D'])

        reactions = sent[0].reaction
        assert len(reactions) == 1
        assert isinstance(reactions[0], types.ReactionEmoji)


class TestButtonMention:
    """`get_input_user` invents access_hash=0; that must be rejected."""

    def test_accepts_valid_input_user(self):
        from telethon import Button

        button = Button.mention(
            'hi', types.InputUser(user_id=5, access_hash=7))
        assert button is not None

    def test_rejects_zero_access_hash(self):
        from telethon import Button

        with pytest.raises(ValueError, match='access hash'):
            Button.mention('hi', types.InputUser(user_id=5, access_hash=0))

    def test_rejects_plain_string(self):
        from telethon import Button

        with pytest.raises(ValueError):
            Button.mention('hi', 'someusername')


class TestSendDocumentAlias:
    """`send_document` must force document mode, not alias send_file."""

    def test_send_document_forces_force_document(self):
        import inspect

        from telethon import TelegramClient
        from telethon.client import pyrogram

        assert TelegramClient.send_document is pyrogram.send_document
        source = inspect.getsource(pyrogram.send_document)
        assert 'force_document' in source
