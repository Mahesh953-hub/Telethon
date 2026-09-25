"""Call raw TL requests by name, without importing their classes.

Ported from https://github.com/New-dev0/Telethon-Patch (``methods.py``).

Any ``*Request`` class known to the current layer can be invoked as an
attribute of the client, with or without the ``Request`` suffix::

    await client.SendReactionRequest(peer, msg_id, reaction='👍')
    await client.SendReaction(peer, msg_id, reaction='👍')

The MTProto schema has no globally unique class names: 21 of them exist in
more than one namespace (for example both ``messages.SendReactionRequest``
and ``stories.SendReactionRequest``). Resolving an ambiguous bare name
would silently send the wrong request, so those names are rejected and the
caller is told to qualify it with its namespace::

    await client.messages.SendReactionRequest(peer, msg_id)
"""
import typing
from collections import defaultdict

from ..tl import TLRequest
from ..tl.alltlobjects import tlobjects

if typing.TYPE_CHECKING:
    from .telegramclient import TelegramClient

_SUFFIX = 'Request'
_PREFIX = 'telethon.tl.functions.'


def _namespace_of(request: type) -> str:
    return request.__module__.removeprefix(_PREFIX)


def _build_request_maps() -> typing.Tuple[
        typing.Dict[str, type], typing.Dict[str, type]]:
    """Build the unambiguous-name map and the fully qualified map.

    The first holds every name that maps to exactly one request (both the
    ``FooRequest`` and the ``Foo`` spelling, when they are free). The second
    holds every request under its ``namespace.ClassName`` key.
    """
    by_name = defaultdict(set)
    qualified = {}

    for obj in tlobjects.values():
        if not (isinstance(obj, type) and issubclass(obj, TLRequest)):
            continue

        name = obj.__name__
        if not name.endswith(_SUFFIX):
            continue

        by_name[name].add(obj)
        by_name[name[:-len(_SUFFIX)]].add(obj)
        qualified['{}.{}'.format(_namespace_of(obj), name)] = obj

    resolved = {
        name: next(iter(classes))
        for name, classes in by_name.items()
        if len(classes) == 1
    }
    return resolved, qualified


_REQUESTS, _QUALIFIED_REQUESTS = _build_request_maps()
_NAMESPACES = frozenset(
    key.split('.', 1)[0] for key in _QUALIFIED_REQUESTS
)


def _find_ambiguous(name: str) -> typing.List[type]:
    """Return every request whose class name is exactly `name`."""
    return [
        request
        for request in _QUALIFIED_REQUESTS.values()
        if request.__name__ == name
    ]


class _Namespace:
    """A request namespace, reachable as ``client.messages`` and so on."""

    def __init__(self, client: "TelegramClient", namespace: str):
        self._client = client
        self._namespace = namespace

    def __getattr__(self, item: str):
        request = _QUALIFIED_REQUESTS.get(
            '{}.{}'.format(self._namespace, item))
        if request is None:
            # Allow the same "with or without Request suffix" convenience
            # that the client itself offers.
            request = _QUALIFIED_REQUESTS.get(
                '{}.{}Request'.format(self._namespace, item))

        if request is None:
            raise AttributeError(
                "the {} namespace has no request '{}'".format(
                    self._namespace, item))

        return self._client._make_caller(request, item)

    def __repr__(self):
        return '<Telethon requests namespace {!r}>'.format(self._namespace)


class RawRequestMethods:
    """Dynamic ``client.SomeRequest(...)`` access, mixed into `TelegramClient`."""

    def __getattr__(self: "TelegramClient", item: str):
        # `__getattr__` only fires when normal lookup fails, so real client
        # methods and attributes always win. Anything else must resolve to a
        # known request, otherwise we raise so `hasattr` keeps working.
        request = _REQUESTS.get(item)
        if request is not None:
            return self._make_caller(request, item)

        clashes = _find_ambiguous(item)
        if clashes:
            options = ', '.join(sorted(
                _namespace_of(clash) for clash in clashes))
            raise AttributeError(
                "'{}' is ambiguous between {}; qualify it, e.g. "
                "client.messages.{}".format(item, options, item))

        if item in _NAMESPACES:
            return _Namespace(self, item)

        raise AttributeError(
            "'{}' object has no attribute '{}'".format(
                type(self).__name__, item))

    def _make_caller(self, request: type, name: str):
        async def caller(*args, **kwargs):
            return await self(request(*args, **kwargs))

        caller.__name__ = request.__name__
        caller.__qualname__ = '{}.{}'.format(type(self).__name__, name)
        caller.__doc__ = 'Calls ``{}(*args, **kwargs)``.'.format(
            request.__name__)

        return caller
