from .. import types
from ..tl.functions.messages import HideChatJoinRequestRequest
from .common import EventBuilder, EventCommon, name_inner_event


@name_inner_event
class JoinRequest(EventBuilder):
    """
    Occurs when a new chat join request is sent. **Bots only.**

    Example
        .. code-block:: python

            from telethon import events

            @client.on(events.JoinRequest())
            async def handler(event):
                await event.approve()
    """

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, types.UpdateBotChatInviteRequester):
            return cls.Event(update)

    class Event(EventCommon):
        def __init__(self, update):
            super().__init__(chat_peer=update.peer)
            self._user_id = update.user_id
            self._invite = update.invite
            self._about = update.about

        @property
        def user_id(self) -> int:
            """The ID of the user who sent the join request."""
            return self._user_id

        @property
        def invite(self):
            """The :tl:`ExportedChatInvite` this request belongs to."""
            return self._invite

        @property
        def link(self) -> str:
            """The invite link of the chat."""
            return self._invite.link

        @property
        def about(self) -> str:
            """The bio the user filled in with the join request."""
            return self._about

        # Kept for backwards compatibility with the original patch.
        user_about = about

        async def _hide(self, approved: bool):
            user = await self.client.get_input_entity(self._user_id)
            result = await self.client(HideChatJoinRequestRequest(
                peer=await self.get_input_chat(),
                user_id=user,
                approved=approved
            ))

            # Telegram usually returns a single update; unwrap it for
            # convenience, but keep the full result when there are several.
            if isinstance(result, types.Updates) and len(result.updates) == 1:
                return result.updates[0]

            return result

        async def approve(self):
            """Approve the join request of the user."""
            return await self._hide(True)

        async def reject(self):
            """Reject the join request of the user."""
            return await self._hide(False)

        async def get_user(self):
            """Get the :tl:`User` who sent the join request."""
            return await self.client.get_entity(self._user_id)
