"""Traffic inspection: everything sent to and received from Telegram.

Telethon ships a `loggers` dict all the way down into the transport, but
nothing populates it with anything useful and no public API reads it. This
records the request/response stream at the client boundary, where the TL
objects are still intact, rather than in the send and receive loops -
touching those risks destabilising a live connection.

Three levels of detail, because the full object graph is expensive and
usually unreadable:

    client.set_traffic_log(level='summary')   # names + sizes + timing
    client.set_traffic_log(level='full')      # full to_dict() per packet
    client.set_traffic_log(level='off')

Nothing is recorded until `enable_traffic_log` is called, and the buffer
is bounded so a long-running client cannot grow without limit.
"""
import collections
import datetime
import enum
import time
import typing

from .. import helpers, utils
from ..tl import TLObject


class Direction(enum.Enum):
    """Which way a packet travelled."""

    SENT = 'sent'
    RECEIVED = 'received'


class Detail(enum.Enum):
    """How much of each packet to keep."""

    OFF = 'off'
    SUMMARY = 'summary'
    FULL = 'full'


class Packet:
    """One request or response crossing the client boundary.

    Attributes:
        direction: `Direction.SENT` or `Direction.RECEIVED`.
        kind: the object's class name, e.g. ``GetHistoryRequest``.
        constructor: the TL constructor id, useful for cross-checking
            against `telethon_generator/data/api.tl`.
        size: encoded size in bytes, or ``None`` if not serialised.
        request: the TL object itself when retained.
        result: the resolved value, for a received packet.
        error: the exception raised by the request, if any.
        started: monotonic timestamp when the request began.
        finished: monotonic timestamp when it resolved.
    """

    __slots__ = ('direction', 'kind', 'constructor', 'size', 'request',
                 'result', 'error', 'started', 'finished', '_detail')

    def __init__(self, direction, kind, constructor, size, request,
                 detail):
        self.direction = direction
        self.kind = kind
        self.constructor = constructor
        self.size = size
        self.request = request if detail is Detail.FULL else None
        self.result = None
        self.error = None
        self.started = time.monotonic()
        self.finished = None

    @property
    def elapsed(self) -> typing.Optional[float]:
        """Seconds between send and resolution, or ``None`` if unresolved."""
        if self.finished is None:
            return None
        return self.finished - self.started

    def to_dict(self) -> dict:
        """A plain dict, with the object graph flattened if retained."""
        out = {
            'direction': self.direction.value,
            'kind': self.kind,
            'constructor': self.constructor,
            'size': self.size,
            'elapsed': self.elapsed,
        }
        if self.error is not None:
            out['error'] = '{}: {}'.format(
                type(self.error).__name__, self.error)
        if self.request is not None:
            out['request'] = self._as_dict(self.request)
        if self.result is not None:
            out['result'] = self._as_dict(self.result)
        return out

    @staticmethod
    def _as_dict(obj):
        try:
            return obj.to_dict()
        except (AttributeError, TypeError, ValueError):
            return repr(obj)

    def __repr__(self):
        return '<Packet {} {} 0x{:08x} {}B>'.format(
            self.direction.value, self.kind, self.constructor or 0,
            self.size if self.size is not None else '?')

    def __str__(self):
        when = datetime.datetime.fromtimestamp(
            time.time(), datetime.timezone.utc).strftime('%H:%M:%S')
        timing = '' if self.elapsed is None else ' {:.0f}ms'.format(
            self.elapsed * 1000)
        size = '' if self.size is None else ' {}B'.format(self.size)
        return '{} {} {}{}{}'.format(
            when, self.direction.value.ljust(8), self.kind, size, timing)


class TrafficInspectorMethods:
    """Records and reports the MTProto request/response stream."""

    #: Bound on the ring buffer, so a busy client cannot grow unbounded.
    max_packets = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._traffic_detail = Detail.OFF
        self._traffic_packets = collections.deque(maxlen=self.max_packets)
        self._traffic_counts = collections.Counter()

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------

    def set_traffic_log(self, level='summary'):
        """Choose how much traffic to record.

        Args:
            level: ``'off'``, ``'summary'`` or ``'full'``. ``'full'``
                retains the object graph, which is readable but memory
                hungry - use it to debug, not in a long-running client.
        """
        self._traffic_detail = Detail(level)
        return self

    def enable_traffic_log(self, level='summary'):
        """Start recording. Returns self so it can be chained."""
        return self.set_traffic_log(level)

    def disable_traffic_log(self):
        """Stop recording and drop everything buffered."""
        self._traffic_detail = Detail.OFF
        self._traffic_packets.clear()
        self._traffic_counts.clear()
        return self

    def clear_traffic_log(self):
        """Drop the buffer but keep recording."""
        self._traffic_packets.clear()
        self._traffic_counts.clear()
        return self

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------

    def _record(self, direction, obj, request=None):
        """Note one packet. Returns it, or ``None`` when not recording."""
        if self._traffic_detail is Detail.OFF:
            return None

        kind = type(obj).__name__
        constructor = getattr(obj, 'CONSTRUCTOR_ID', None)
        size = self._safe_size(obj)

        packet = Packet(
            direction, kind, constructor, size,
            request if request is not None else obj,
            self._traffic_detail)
        self._traffic_packets.append(packet)
        self._traffic_counts[(direction.value, kind)] += 1
        return packet

    @staticmethod
    def _safe_size(obj):
        """Encoded size, or ``None``. Never let telemetry break a send."""
        if not isinstance(obj, TLObject):
            return None
        try:
            return len(obj.__bytes__())
        except Exception:
            return None

    async def _call(self, sender, request, ordered=False,
                    flood_sleep_threshold=None):
        """Record both directions around the real request pipeline.

        Hooks ``_call`` rather than ``__call__`` deliberately:
        `UserMethods.__call__` owns the public entry point and delegates
        here, so this sits *below* entity resolution, flood-wait handling
        and retries. That means a flood wait or a retried request shows up
        in the trace as the real latency and error it was, rather than
        being hidden behind a resolved call.

        Note this is defined on a mixin placed before `TelegramBaseClient`
        in the MRO, so `super()` reaches the real implementation.
        """
        if self._traffic_detail is Detail.OFF:
            return await super()._call(
                sender, request, ordered=ordered,
                flood_sleep_threshold=flood_sleep_threshold)

        # A batch is recorded as one packet per element, which keeps the
        # sent/received pairing honest.
        if utils.is_list_like(request):
            outgoing = [self._record(Direction.SENT, r) for r in request]
        else:
            outgoing = self._record(Direction.SENT, request)

        try:
            result = await super()._call(
                sender, request, ordered=ordered,
                flood_sleep_threshold=flood_sleep_threshold)
        except BaseException as e:
            for packet in self._as_packets(outgoing):
                if packet is not None:
                    packet.error = e
                    packet.finished = time.monotonic()
            # The failure is itself what came back over the wire.
            self._record(Direction.RECEIVED, e, request=request)
            raise

        for packet in self._as_packets(outgoing):
            if packet is not None:
                packet.finished = time.monotonic()
        self._record(Direction.RECEIVED, result, request=request)
        return result

    @staticmethod
    def _as_packets(outgoing):
        """Normalise a single packet or a batch of them to a list."""
        if outgoing is None:
            return []
        if isinstance(outgoing, list):
            return outgoing
        return [outgoing]

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------

    @property
    def traffic_packets(self) -> list:
        """Recorded packets, oldest first."""
        return list(self._traffic_packets)

    def traffic_summary(self) -> collections.Counter:
        """How many of each (direction, kind) were seen."""
        return collections.Counter(self._traffic_counts)

    def traffic_report(self, limit=20) -> str:
        """A human-readable digest of the recorded traffic."""
        if not self._traffic_packets:
            return 'no traffic recorded (logging is off)'

        packets = self._traffic_packets
        sent = sum(1 for p in packets if p.direction is Direction.SENT)
        errors = [p for p in packets if p.error is not None]
        timed = [p.elapsed for p in packets if p.elapsed is not None]

        lines = [
            '{} packets ({} sent, {} received, {} errored)'.format(
                len(packets), sent, len(packets) - sent, len(errors)),
        ]
        if timed:
            lines.append(
                'latency min {:.0f}ms  median {:.0f}ms  max {:.0f}ms'.format(
                    min(timed) * 1000,
                    sorted(timed)[len(timed) // 2] * 1000,
                    max(timed) * 1000))

        counts = self.traffic_summary()
        lines.append('')
        lines.append('top traffic:')
        for (direction, kind), count in counts.most_common(limit):
            lines.append('  {:>5}  {} {}'.format(count, direction, kind))

        if errors:
            lines.append('')
            lines.append('errors:')
            for packet in errors[:limit]:
                lines.append('  {} -> {}'.format(
                    packet.kind, type(packet.error).__name__))

        lines.append('')
        lines.append('last {} packets:'.format(min(limit, len(packets))))
        for packet in list(packets)[-limit:]:
            lines.append('  {}'.format(packet))
        return '\n'.join(lines)

    def traffic_as_json(self) -> str:
        """Every recorded packet as JSON."""
        import json
        return json.dumps(
            [p.to_dict() for p in self._traffic_packets],
            indent=2, default=str)

    def traffic_to_file(self, path):
        """Write the traffic report to ``path``."""
        with open(path, 'w') as f:
            f.write(self.traffic_report())
        return path

    def __aiter__(self):
        """Iterate packets as they are recorded."""
        return self

    async def __anext__(self):
        while True:
            if not self._traffic_packets:
                await helpers.delay(0.05)
                continue
            return self._traffic_packets[-1]
