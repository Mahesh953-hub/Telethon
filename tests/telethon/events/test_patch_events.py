"""Tests for the events ported from Telethon-Patch."""
import pytest

from telethon import events
from telethon.tl import types


def make_client():
    class MockClient:
        def __init__(self):
            self.sent = []
            self._self_id = 1

        async def __call__(self, request, ordered=False,
                           flood_sleep_threshold=None):
            self.sent.append(request)
            return types.Updates(
                updates=[types.UpdateDeleteMessages(
                    messages=[1], pts=1, pts_count=1)],
                users=[], chats=[], date=None, seq=0
            )

        async def get_input_entity(self, peer):
            return types.InputPeerUser(user_id=peer, access_hash=2)

        async def get_entity(self, peer):
            return types.User(id=peer, access_hash=2)

        async def create_group_call(self, peer, *args, **kwargs):
            return ('created', peer)

        async def discard_group_call(self, call):
            return ('discarded', call)

    client = MockClient()
    # `_set_client`/`input_chat` read this cache, keyed by the *unmarked*
    # peer id, to resolve the event's chat without an API call.
    client._mb_entity_cache = {10: types.Chat(
        id=10, title='c', photo=types.ChatPhotoEmpty(),
        participants_count=2, date=None, version=1)}
    return client


def set_client(event, client):
    event._client = client
    event._entities = {}
    event._set_client(client)
    # `Chat` has no `_as_input_peer`, so `input_chat` stays unresolved and
    # `get_input_chat` would hit the network. Seed it directly instead.
    event._input_chat = types.InputPeerChat(chat_id=10)
    return event


def make_join_request():
    update = types.UpdateBotChatInviteRequester(
        peer=types.PeerChat(chat_id=10),
        date=None,
        user_id=55,
        about='let me in',
        invite=types.ChatInviteExported(
            link='https://t.me/+abc', admin_id=1, date=None
        ),
        qts=1
    )
    return events.JoinRequest.Event(update)


class TestJoinRequest:
    def test_is_registered(self):
        assert events.JoinRequest is not None
        assert hasattr(events, 'JoinRequest')

    def test_build_matches_only_invite_requesters(self):
        builder = events.JoinRequest()
        assert builder.build(types.UpdateNewMessage(
            message=types.Message(id=1, peer_id=types.PeerChat(1),
                                  message='', date=None),
            pts=1, pts_count=1)) is None
        assert builder.build(None) is None

    def test_properties(self):
        event = make_join_request()
        assert event.user_id == 55
        assert event.about == 'let me in'
        assert event.user_about == 'let me in'
        assert event.link == 'https://t.me/+abc'
        assert event.invite is not None

    @pytest.mark.asyncio
    async def test_approve_sends_hide_request(self):
        from telethon.tl.functions.messages import HideChatJoinRequestRequest

        client = make_client()
        event = set_client(make_join_request(), client)
        result = await event.approve()

        request = client.sent[0]
        assert isinstance(request, HideChatJoinRequestRequest)
        assert request.approved is True
        # A single update is unwrapped for convenience.
        assert isinstance(result, types.UpdateDeleteMessages)

    @pytest.mark.asyncio
    async def test_reject_sends_hide_request(self):
        from telethon.tl.functions.messages import HideChatJoinRequestRequest

        client = make_client()
        event = set_client(make_join_request(), client)
        await event.reject()

        request = client.sent[0]
        assert isinstance(request, HideChatJoinRequestRequest)
        assert request.approved is False

    @pytest.mark.asyncio
    async def test_get_user(self):
        client = make_client()
        event = set_client(make_join_request(), client)
        user = await event.get_user()

        assert isinstance(user, types.User)
        assert user.id == 55


def make_group_call_update(action, cls=types.MessageService):
    message = cls(
        id=7,
        peer_id=types.PeerChat(chat_id=10),
        date=None,
        action=action
    )
    return types.UpdateNewMessage(message=message, pts=1, pts_count=1)


class TestGroupCall:
    def test_is_registered(self):
        assert hasattr(events, 'GroupCall')

    def test_build_ignores_non_service_messages(self):
        builder = events.GroupCall()
        assert builder.build(types.UpdateNewMessage(
            message=types.Message(id=1, peer_id=types.PeerChat(1),
                                  message='hi', date=None),
            pts=1, pts_count=1)) is None

    def test_started_when_duration_is_zero(self):
        call = types.InputGroupCall(id=1, access_hash=2)
        update = make_group_call_update(
            types.MessageActionGroupCall(call, duration=0))
        event = events.GroupCall.build(update)
        assert event is not None

        assert event.started is True
        assert event.ended is None
        assert event.input_call is call
        assert event._message_id == 7
        assert event.duration == 0

    def test_ended_when_duration_is_set(self):
        call = types.InputGroupCall(id=1, access_hash=2)
        update = make_group_call_update(
            types.MessageActionGroupCall(call, duration=120))
        event = events.GroupCall.build(update)
        assert event is not None

        assert event.ended is True
        assert event.started is None
        assert event.duration == 120

    def test_scheduled(self):
        call = types.InputGroupCall(id=1, access_hash=2)
        update = make_group_call_update(
            types.MessageActionGroupCallScheduled(call, schedule_date=None))
        event = events.GroupCall.build(update)
        assert event is not None

        assert event.scheduled is True
        assert event.started is None
        assert event.ended is None

    def test_channel_message_variant(self):
        call = types.InputGroupCall(id=1, access_hash=2)
        message = types.MessageService(
            id=7, peer_id=types.PeerChannel(10), date=None,
            action=types.MessageActionGroupCall(call, duration=0))
        event = events.GroupCall.build(
            types.UpdateNewChannelMessage(message=message, pts=1, pts_count=1))
        assert event is not None

        assert event.started is True

    @pytest.mark.asyncio
    async def test_start_and_discard_delegate_to_client(self):
        call = types.InputGroupCall(id=1, access_hash=2)
        update = make_group_call_update(
            types.MessageActionGroupCall(call, duration=0))
        client = make_client()
        event = set_client(events.GroupCall.build(update), client)
        assert event is not None

        assert await event.start() == ('created', -10)
        assert await event.discard() == ('discarded', call)

    @pytest.mark.asyncio
    async def test_toggle_record(self):
        from telethon.tl.functions.phone import ToggleGroupCallRecordRequest

        call = types.InputGroupCall(id=1, access_hash=2)
        update = make_group_call_update(
            types.MessageActionGroupCall(call, duration=0))
        client = make_client()
        event = set_client(events.GroupCall.build(update), client)
        assert event is not None

        await event.toggle_record(start=True, title='rec')

        request = client.sent[0]
        assert isinstance(request, ToggleGroupCallRecordRequest)
        assert request.start is True
        assert request.title == 'rec'
