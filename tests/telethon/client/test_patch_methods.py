"""Tests for the client methods ported from Telethon-Patch."""
import inspect

import pytest

from telethon import TelegramClient, utils
from telethon.client import GroupCallMethods, PyrogramMethods, TopicMethods
from telethon.client import pyrogram as pyrogram_module
from telethon.client import topics as topics_module
from telethon.tl import types


class MockClient(TelegramClient):
    """A TelegramClient that records requests instead of sending them."""
    def __init__(self):  # noinspection PyMissingConstructor
        self.sent = []

    async def __call__(self, request, ordered=False,
                       flood_sleep_threshold=None):
        self.sent.append(request)
        return request


def make_client():
    return MockClient()


def _returning(value):
    """Build a one-argument coroutine function that always returns value."""
    async def inner(*args, **kwargs):
        return value

    return inner


class TestGroupCall:
    def test_mixin_is_installed(self):
        assert issubclass(TelegramClient, GroupCallMethods)
        for name in ('create_group_call', 'join_group_call',
                     'leave_group_call', 'discard_group_call',
                     'get_group_call'):
            assert callable(getattr(TelegramClient, name))

    @pytest.mark.asyncio
    async def test_create_group_call(self):
        from telethon.tl import functions

        client = make_client()
        call = types.InputGroupCall(id=1, access_hash=2)
        await client.create_group_call(call, title='hi', random_id=5)

        request = client.sent[0]
        assert isinstance(request,
                          functions.phone.CreateGroupCallRequest)
        assert request.peer == call
        assert request.title == 'hi'
        assert request.random_id == 5

    @pytest.mark.asyncio
    async def test_join_group_call(self):
        from telethon.tl import functions

        client = make_client()
        call = types.InputGroupCall(id=1, access_hash=2)
        join_as = types.InputPeerUser(user_id=1, access_hash=2)
        await client.join_group_call(call, join_as, muted=True)

        request = client.sent[0]
        assert isinstance(request, functions.phone.JoinGroupCallRequest)
        assert request.muted is True

    @pytest.mark.asyncio
    async def test_leave_and_discard(self):
        from telethon.tl import functions

        client = make_client()
        call = types.InputGroupCall(id=1, access_hash=2)
        await client.leave_group_call(call, source=7)
        await client.discard_group_call(call)

        assert isinstance(client.sent[0],
                          functions.phone.LeaveGroupCallRequest)
        assert client.sent[0].source == 7
        assert isinstance(client.sent[1],
                          functions.phone.DiscardGroupCallRequest)

    @pytest.mark.asyncio
    async def test_get_group_call(self):
        from telethon.tl import functions

        client = make_client()
        call = types.InputGroupCall(id=1, access_hash=2)
        await client.get_group_call(call, limit=10)

        request = client.sent[0]
        assert isinstance(request, functions.phone.GetGroupCallRequest)
        assert request.limit == 10


class TestTopics:
    def test_mixin_is_installed(self):
        assert issubclass(TelegramClient, TopicMethods)
        for name in ('create_topic', 'edit_topic', 'get_topics'):
            assert callable(getattr(TelegramClient, name))

    @pytest.mark.asyncio
    async def test_create_topic(self):
        from telethon.tl import functions

        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.create_topic(peer, 'Title', icon_color=0xFF0000)

        request = client.sent[0]
        assert isinstance(request, functions.messages.CreateForumTopicRequest)
        assert request.peer == peer
        assert request.title == 'Title'
        assert request.icon_color == 0xFF0000

    @pytest.mark.asyncio
    async def test_edit_topic(self):
        from telethon.tl import functions

        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.edit_topic(peer, 3, title='New', closed=True)

        request = client.sent[0]
        assert isinstance(request, functions.messages.EditForumTopicRequest)
        assert request.topic_id == 3
        assert request.title == 'New'
        assert request.closed is True

    @pytest.mark.asyncio
    async def test_get_topics_listing(self):
        from telethon.tl import functions

        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.get_topics(peer, limit=5)

        request = client.sent[0]
        assert isinstance(request, functions.messages.GetForumTopicsRequest)
        assert request.limit == 5

    @pytest.mark.asyncio
    async def test_get_topics_by_id_wraps_int(self):
        """A bare int must be wrapped in a list, or serialisation fails."""
        from telethon.tl import functions

        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.get_topics(peer, topics=3)

        request = client.sent[0]
        assert isinstance(request, functions.messages.GetForumTopicsByIDRequest)
        assert request.topics == [3]

        await client.get_topics(peer, topics=[1, 2])
        assert client.sent[1].topics == [1, 2]


class TestReactions:
    @pytest.mark.asyncio
    async def test_send_reaction_str(self):
        from telethon.tl import functions

        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.send_reaction(peer, 10, reaction='👍')

        request = client.sent[0]
        assert isinstance(request, functions.messages.SendReactionRequest)
        assert request.msg_id == 10
        assert request.reaction == [types.ReactionEmoji('👍')]

    @pytest.mark.asyncio
    async def test_send_reaction_list_of_str(self):
        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.send_reaction(peer, 10, reaction=['👍', '🎉'])

        assert client.sent[0].reaction == [
            types.ReactionEmoji('👍'), types.ReactionEmoji('🎉')]

    @pytest.mark.asyncio
    async def test_send_reaction_none_clears(self):
        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        await client.send_reaction(peer, 10)

        assert client.sent[0].reaction == [types.ReactionEmpty()]

    @pytest.mark.asyncio
    async def test_send_reaction_passes_through_objects(self):
        client = make_client()
        peer = types.InputPeerChat(chat_id=5)
        custom = types.ReactionCustomEmoji(document_id=99)
        await client.send_reaction(peer, 10, reaction=[custom], big=True)

        assert client.sent[0].reaction == [custom]
        assert client.sent[0].big is True

    def test_is_bound_to_client(self):
        assert TelegramClient.send_reaction is topics_module.send_reaction


class TestJoinAndModeration:
    @pytest.mark.asyncio
    async def test_join_chat_by_hash(self):
        from telethon.tl import functions

        client = make_client()
        await topics_module.join_chat(client, hash='AbCdEf')

        request = client.sent[0]
        assert isinstance(request, functions.messages.ImportChatInviteRequest)
        assert request.hash == 'AbCdEf'

    @pytest.mark.asyncio
    async def test_join_chat_requires_argument(self):
        client = make_client()
        with pytest.raises(ValueError):
            await topics_module.join_chat(client)

    @pytest.mark.asyncio
    async def test_toggle_hidden_resolves_channel(self):
        from telethon.tl.functions.channels import ToggleParticipantsHiddenRequest

        client = make_client()
        channel = types.InputChannel(channel_id=1, access_hash=2)
        await topics_module.toggle_hidden(client, channel, True)

        request = client.sent[0]
        assert isinstance(request, ToggleParticipantsHiddenRequest)
        assert request.channel is channel
        assert request.enabled is True

    @pytest.mark.asyncio
    async def test_toggle_hidden_resolves_non_channel(self):
        client = make_client()
        channel = types.InputChannel(channel_id=1, access_hash=2)
        client.get_entity = _returning(
            types.Channel(id=1, access_hash=2, title='c',
                          photo=types.ChatPhotoEmpty(), date=None))
        await topics_module.toggle_hidden(client, 'mygroup', False)

        assert client.sent[0].channel == channel
        assert client.sent[0].enabled is False

    @pytest.mark.asyncio
    async def test_set_profile_photo_uploads_path(self):
        from telethon.tl.functions.photos import UploadProfilePhotoRequest

        client = make_client()
        uploaded = types.InputFile(id=1, parts=1, name='f', md5_checksum=b'0')
        client.upload_file = _returning(uploaded)
        await topics_module.set_profile_photo(client, 'photo.jpg')

        request = client.sent[0]
        assert isinstance(request, UploadProfilePhotoRequest)
        assert request.file is uploaded

    @pytest.mark.asyncio
    async def test_set_contact_photo_resolves_user(self):
        from telethon.tl.functions.photos import UploadContactProfilePhotoRequest

        client = make_client()
        user = types.User(id=1, access_hash=2)
        uploaded = types.InputFile(id=1, parts=1, name='f', md5_checksum=b'0')
        client.upload_file = _returning(uploaded)
        client.get_input_entity = _returning(
            types.InputPeerUser(user_id=1, access_hash=2))

        await topics_module.set_contact_photo(client, 1, 'photo.jpg')

        request = client.sent[0]
        assert isinstance(request, UploadContactProfilePhotoRequest)
        assert request.file is uploaded
        assert request.user_id == utils.get_input_user(user)


class TestPyrogramAliases:
    def test_mixin_is_installed(self):
        assert issubclass(TelegramClient, PyrogramMethods)
        for name in ('set_username', 'set_chat_username', 'get_users',
                     'join_chat', 'leave_chat', 'vote_poll'):
            assert callable(getattr(TelegramClient, name))

    def test_media_aliases_point_at_send_file(self):
        for name in ('send_video', 'send_voice',
                     'send_audio', 'send_sticker'):
            assert getattr(TelegramClient, name).__name__ == 'send_file'

    def test_send_document_forces_document_mode(self):
        # Not a bare alias: it must wrap send_file so images are not
        # sent as photos under a method named send_document.
        from telethon.client import pyrogram

        assert TelegramClient.send_document is pyrogram.send_document
        assert 'force_document' in inspect.getsource(
            pyrogram.send_document)

    @pytest.mark.asyncio
    async def test_set_username(self):
        from telethon.tl import functions

        client = make_client()
        await client.set_username('newuser')

        request = client.sent[0]
        assert isinstance(request, functions.account.UpdateUsernameRequest)
        assert request.username == 'newuser'

    @pytest.mark.asyncio
    async def test_set_chat_username(self):
        from telethon.tl import functions

        client = make_client()
        channel = types.InputChannel(channel_id=1, access_hash=2)
        await client.set_chat_username(channel, 'newname')

        request = client.sent[0]
        assert isinstance(request, functions.channels.UpdateUsernameRequest)
        assert request.username == 'newname'

    @pytest.mark.asyncio
    async def test_get_users_single_and_many(self):
        client = make_client()
        seen = []

        async def get_entity(entity):
            seen.append(entity)
            return types.User(id=1, access_hash=2)

        client.get_entity = get_entity

        one = await client.get_users(5)
        assert isinstance(one, types.User)
        assert seen == [5]

        many = await client.get_users([1, 2, 3])
        assert len(many) == 3
        assert seen == [5, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_join_chat_with_invite_link(self):
        from telethon.tl import functions

        client = make_client()
        await client.join_chat('https://t.me/+AbCdEf')

        assert isinstance(client.sent[0],
                          functions.messages.ImportChatInviteRequest)
        assert client.sent[0].hash == 'AbCdEf'

    @pytest.mark.asyncio
    async def test_join_chat_with_username(self):
        from telethon.tl import functions

        # A bare non-numeric string is a username, not an invite hash.
        client = make_client()
        client.get_entity = _returning(
            types.Channel(id=1234567890, access_hash=2, title='c',
                          photo=types.ChatPhotoEmpty(), date=None))
        await client.join_chat('somechannel')
        assert isinstance(client.sent[0],
                          functions.channels.JoinChannelRequest)
        assert client.sent[0].channel.channel_id == 1234567890

        # An explicit '+' prefix is still an invite link.
        client.sent.clear()
        client.get_entity = _returning(
            types.Channel(id=1234567890, access_hash=2, title='c',
                          photo=types.ChatPhotoEmpty(), date=None))
        await client.join_chat(-1001234567890)
        assert isinstance(client.sent[0],
                          functions.channels.JoinChannelRequest)
        assert client.sent[0].channel.channel_id == 1234567890

    @pytest.mark.asyncio
    async def test_leave_chat_deletes_dialog(self):
        client = make_client()
        deleted = []

        async def delete_dialog(chat_id):
            deleted.append(chat_id)
            return True

        client.delete_dialog = delete_dialog
        assert await client.leave_chat(5) is True
        assert deleted == [5]

    @pytest.mark.asyncio
    async def test_vote_poll_int_is_wrapped_in_a_list(self):
        """Regression: the upstream patch wrote ``[int]`` here."""
        client = make_client()
        clicked = []

        class FakeMessage:
            async def click(self, options):
                clicked.append(options)

        async def get_messages(chat_id, ids=None):
            return FakeMessage()

        client.get_messages = get_messages
        await client.vote_poll(5, 10, 1)

        assert clicked == [[1]]

    @pytest.mark.asyncio
    async def test_vote_poll_raises_when_missing(self):
        client = make_client()

        async def get_messages(chat_id, ids=None):
            return None

        client.get_messages = get_messages
        with pytest.raises(ValueError):
            await client.vote_poll(5, 10, 1)


class TestSendPoll:
    @pytest.mark.asyncio
    async def test_send_poll_builds_text_with_entities(self):
        from telethon.tl import functions

        client = make_client()

        async def get_input_entity(entity):
            return types.InputPeerChat(chat_id=entity)

        async def get_response_message(request, result, input_chat):
            return result

        async def parse(text, mode):
            return text, []

        client.get_input_entity = get_input_entity
        client._get_response_message = get_response_message
        client._parse_message_text = parse

        await client.send_poll(5, 'Why?', ['a', 'b'], multiple_choice=True)

        request = client.sent[0]
        assert isinstance(request, functions.messages.SendMediaRequest)
        poll = request.media.poll
        assert isinstance(poll.question, types.TextWithEntities)
        assert poll.question.text == 'Why?'
        assert [a.text.text for a in poll.answers] == ['a', 'b']
        assert all(len(a.option) == 8 for a in poll.answers)
        assert poll.multiple_choice is True
        assert poll.quiz is False
        assert request.message == ''

    @pytest.mark.asyncio
    async def test_send_poll_quiz_closes_and_sets_answers(self):
        client = make_client()

        async def get_input_entity(entity):
            return types.InputPeerChat(chat_id=entity)

        async def get_response_message(request, result, input_chat):
            return result

        async def parse(text, mode):
            return text, []

        client.get_input_entity = get_input_entity
        client._get_response_message = get_response_message
        client._parse_message_text = parse

        await client.send_poll(5, 'Q', ['a', 'b'], quiz=True,
                               correct_answers=1)

        poll = client.sent[0].media.poll
        assert poll.quiz is True
        assert poll.closed is True
        assert client.sent[0].media.correct_answers == [1]

    @pytest.mark.asyncio
    async def test_send_poll_accepts_poll_answer_objects(self):
        client = make_client()

        async def get_input_entity(entity):
            return types.InputPeerChat(chat_id=entity)

        async def get_response_message(request, result, input_chat):
            return result

        async def parse(text, mode):
            return text, []

        client.get_input_entity = get_input_entity
        client._get_response_message = get_response_message
        client._parse_message_text = parse

        answer = types.PollAnswer(
            types.TextWithEntities('given', []), b'12345678')
        await client.send_poll(5, 'Q', [answer])

        assert client.sent[0].media.poll.answers[0] is answer

    def test_is_bound_to_client(self):
        assert TelegramClient.send_poll is pyrogram_module.send_poll
