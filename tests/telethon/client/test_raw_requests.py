"""Tests for the raw request dispatch ported from Telethon-Patch."""
import pytest

from telethon import TelegramClient
from telethon.client.rawrequests import _QUALIFIED_REQUESTS, _REQUESTS, _find_ambiguous
from telethon.tl import TLRequest, types
from telethon.tl.alltlobjects import tlobjects

PREFIX = 'telethon.tl.functions.'


class MockClient(TelegramClient):
    def __init__(self):  # noinspection PyMissingConstructor
        self.sent = []

    async def __call__(self, request, ordered=False,
                       flood_sleep_threshold=None):
        self.sent.append(request)
        return request


def lookup(obj, name):
    """Resolve `name` on `obj`; the tests assert this raises."""
    return getattr(obj, name)


def layer_requests():
    return {
        obj for obj in tlobjects.values()
        if (isinstance(obj, type) and issubclass(obj, TLRequest)
            and obj.__name__.endswith('Request'))
    }


class TestRequestMaps:
    def test_unambiguous_map_only_holds_requests(self):
        assert _REQUESTS
        for name, request in _REQUESTS.items():
            assert issubclass(request, TLRequest), name

    def test_qualified_map_covers_every_request_once(self):
        assert len(_QUALIFIED_REQUESTS) == len(layer_requests())

    def test_qualified_keys_are_namespaced(self):
        for key, request in _QUALIFIED_REQUESTS.items():
            assert key == '{}.{}'.format(
                request.__module__.removeprefix(PREFIX), request.__name__)

    def test_unambiguous_names_resolve_to_one_request(self):
        for name, request in _REQUESTS.items():
            # The key is either the class name or that name minus the suffix.
            assert name in (request.__name__,
                            request.__name__[:-len('Request')]), name
            if name == request.__name__:
                # A full class name maps here only if it is unique; the
                # short form can still be free (e.g. `HideChatJoinRequest`,
                # the short form of `HideChatJoinRequestRequest`).
                assert _find_ambiguous(name) == [request], name

    def test_both_spellings_present_when_free(self):
        # `HideChatJoinRequestRequest` is unambiguous, so its short form
        # `HideChatJoinRequest` is free too.
        assert _REQUESTS['HideChatJoinRequestRequest'] is not None
        assert _REQUESTS['HideChatJoinRequest'] is \
            _REQUESTS['HideChatJoinRequestRequest']

    def test_types_do_not_leak_in(self):
        for name in ('Message', 'PeerChat', 'InputChannel', 'Updates'):
            assert name not in _REQUESTS

    def test_ambiguous_names_are_excluded(self):
        # SendReactionRequest exists in both messages. and stories.
        assert len(_find_ambiguous('SendReactionRequest')) > 1
        assert 'SendReactionRequest' not in _REQUESTS


class TestDispatch:
    def test_known_request_resolves_with_and_without_suffix(self):
        client = MockClient()
        assert callable(client.CreateGroupCallRequest)
        assert callable(client.CreateGroupCall)

    @pytest.mark.asyncio
    async def test_calling_builds_and_sends_the_request(self):
        from telethon.tl.functions.phone import CreateGroupCallRequest

        client = MockClient()
        result = await client.CreateGroupCallRequest(
            types.InputPeerChat(chat_id=1), title='x')

        assert isinstance(result, CreateGroupCallRequest)
        assert client.sent[0] is result
        assert result.title == 'x'

    @pytest.mark.asyncio
    async def test_short_name_calls_the_same_request(self):
        client = MockClient()
        await client.CreateGroupCall(types.InputPeerChat(chat_id=1), title='x')

        assert type(client.sent[0]).__name__ == 'CreateGroupCallRequest'

    @pytest.mark.asyncio
    async def test_positional_and_keyword_args_are_forwarded(self):
        client = MockClient()
        await client.HideChatJoinRequestRequest(
            types.InputPeerChat(chat_id=1),
            types.InputUser(user_id=2, access_hash=3),
            True)

        request = client.sent[0]
        assert request.approved is True
        assert request.user_id.user_id == 2

    @pytest.mark.asyncio
    async def test_qualified_name_picks_the_right_namespace(self):
        """Regression: the flat map sent stories. for messages. here."""
        from telethon.tl.functions.messages import SendReactionRequest as MessagesReaction
        from telethon.tl.functions.stories import SendReactionRequest as StoriesReaction

        client = MockClient()
        result = await client.messages.SendReactionRequest(
            types.InputPeerChat(chat_id=1), 5)

        assert isinstance(result, MessagesReaction)
        assert not isinstance(result, StoriesReaction)

    @pytest.mark.asyncio
    async def test_both_namespaces_are_reachable(self):
        from telethon.tl.functions.messages import SendReactionRequest as MessagesReaction
        from telethon.tl.functions.stories import SendReactionRequest as StoriesReaction

        client = MockClient()
        stories = await client.stories.SendReactionRequest(
            types.InputPeerUser(user_id=1, access_hash=2),
            story_id=1,
            reaction=[types.ReactionEmpty()])

        assert isinstance(stories, StoriesReaction)
        assert not isinstance(stories, MessagesReaction)

    def test_ambiguous_name_raises_with_a_helpful_message(self):
        # A bare attribute is what user code writes, but route it through
        # `lookup` so the intent (the lookup must raise) is explicit.
        client = MockClient()
        with pytest.raises(AttributeError) as exc:
            lookup(client, 'SendReactionRequest')

        message = str(exc.value)
        assert 'ambiguous' in message
        assert 'messages' in message
        assert 'stories' in message

    def test_unknown_attribute_raises_attribute_error(self):
        client = MockClient()
        with pytest.raises(AttributeError) as exc:
            lookup(client, 'ThisIsNotAThing')

        assert 'ThisIsNotAThing' in str(exc.value)
        assert 'MockClient' in str(exc.value)

    def test_unknown_qualified_name_raises(self):
        client = MockClient()
        with pytest.raises(AttributeError):
            lookup(client.messages, 'NopeRequest')

    def test_unknown_namespace_raises(self):
        client = MockClient()
        with pytest.raises(AttributeError):
            lookup(client, 'nosuchns')

    def test_namespace_repr(self):
        assert 'messages' in repr(MockClient().messages)

    def test_namespace_allows_short_names(self):
        assert callable(MockClient().phone.CreateGroupCall)

    def test_hasattr_is_false_for_unknown_names(self):
        client = MockClient()
        assert not hasattr(client, 'ThisIsNotAThing')
        assert not hasattr(client, 'SendReactionRequest')
        assert hasattr(client, 'CreateGroupCallRequest')

    def test_real_methods_are_not_shadowed(self):
        client = MockClient()
        assert client.send_message.__name__ == 'send_message'
        assert client.get_entity.__name__ == 'get_entity'
        assert client.send_reaction.__name__ == 'send_reaction'

    def test_callable_metadata(self):
        client = MockClient()
        func = client.CreateGroupCallRequest
        assert func.__name__ == 'CreateGroupCallRequest'
        assert func.__qualname__ == 'MockClient.CreateGroupCallRequest'
        assert 'CreateGroupCallRequest' in func.__doc__

    def test_friendlier_methods_still_win_over_requests(self):
        """`read`, `get_chat` etc. must not be shadowed by request names."""
        client = MockClient()
        assert client.get_chat.__name__ == 'get_entity'
        assert client.read.__name__ == 'send_read_acknowledge'
