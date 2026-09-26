from .. import types
from ..tl.functions.phone import ToggleGroupCallRecordRequest
from .common import EventBuilder, EventCommon, name_inner_event


@name_inner_event
class GroupCall(EventBuilder):
    """
    Occurs on group call service messages:

    * Group call started.
    * Group call ended.
    * Group call scheduled.

    Example
        .. code-block:: python

            from telethon import events

            @client.on(events.GroupCall())
            async def handler(event):
                if event.started:
                    print('Group call started!')
                elif event.ended:
                    print('Group call ended!')
    """

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, (types.UpdateNewMessage,
                               types.UpdateNewChannelMessage)) \
                and isinstance(update.message, types.MessageService):
            action = update.message.action
            if isinstance(action, types.MessageActionGroupCall):
                return cls.Event(update.message, duration=action.duration)
            elif isinstance(action, types.MessageActionGroupCallScheduled):
                return cls.Event(update.message, scheduled=True)

    class Event(EventCommon):
        def __init__(self, update, scheduled=None, duration=None):
            super().__init__(update.peer_id, update.id)
            self._update = update
            self._input_call = update.action.call
            self._scheduled = scheduled
            self.duration = duration
            self.started = None
            self.ended = None

            # A call that was just started has a duration of 0, while an
            # ended call carries the length it ran for (None if unknown).
            if duration == 0:
                self.started = True
            elif duration is not None:
                self.ended = True

        @property
        def input_call(self):
            """The :tl:`InputGroupCall` this event refers to."""
            return self._input_call

        @property
        def scheduled(self):
            """Whether the group call has been scheduled."""
            return self._scheduled

        async def start(self, *args, **kwargs):
            """Start a group call in this chat."""
            return await self.client.create_group_call(
                self.chat_id, *args, **kwargs)

        async def discard(self):
            """Discard (end) this group call."""
            return await self.client.discard_group_call(self.input_call)

        async def toggle_record(
            self,
            start=None,
            video=None,
            video_portrait=None,
            title=None
        ):
            """Start or stop recording this group call."""
            return await self.client(ToggleGroupCallRecordRequest(
                self.input_call,
                start=start,
                video=video,
                video_portrait=video_portrait,
                title=title
            ))
