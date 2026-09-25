"""Friendly methods for group (voice) calls.

Ported from https://github.com/New-dev0/Telethon-Patch (``methods.py``) and
adapted to the current layer.
"""
import datetime
import typing

from ..tl import functions, types

if typing.TYPE_CHECKING:
    from .telegramclient import TelegramClient


class GroupCallMethods:
    """Group call helpers, mixed into `TelegramClient`."""

    async def create_group_call(
        self: "TelegramClient",
        peer: "types.TypeInputPeer",
        rtmp_stream: typing.Optional[bool] = None,
        random_id: int = None,
        title: typing.Optional[str] = None,
        schedule_date: typing.Optional[datetime.datetime] = None
    ) -> types.Updates:
        """
        Create or schedule a group call.

        You will need to have the voice chat admin privilege to start a call.

        Args:
            peer: Chat ID/username of the chat.
            rtmp_stream: Whether to start an RTMP stream.
            random_id: Any random integer, or leave it `None`.
            title: Title to keep for the voice chat.
            schedule_date: `datetime` object to schedule the call for.
        """
        return await self(functions.phone.CreateGroupCallRequest(
            peer=peer,
            rtmp_stream=rtmp_stream,
            title=title,
            random_id=random_id,
            schedule_date=schedule_date
        ))

    async def join_group_call(
        self: "TelegramClient",
        call: "types.TypeInputGroupCall",
        join_as: "types.TypeInputPeer",
        params: "typing.Optional[types.TypeDataJSON]" = None,
        muted: typing.Optional[bool] = None,
        video_stopped: typing.Optional[bool] = None,
        invite_hash: typing.Optional[str] = None
    ) -> types.Updates:
        """
        Join a group call.

        Args:
            call: The group call to join.
            join_as: The entity to join as.
            params: The group call connection parameters (``DataJSON``).
            muted: Whether to join muted.
            video_stopped: Whether to join with the video stopped.
            invite_hash: The invite hash, if joining via an invite link.
        """
        return await self(functions.phone.JoinGroupCallRequest(
            call=call,
            join_as=join_as,
            params=params,
            muted=muted,
            video_stopped=video_stopped,
            invite_hash=invite_hash
        ))

    async def leave_group_call(
        self: "TelegramClient",
        call: "types.TypeInputGroupCall",
        source: int
    ) -> types.Updates:
        """
        Leave a group call.

        Args:
            call: The group call to leave.
            source: The source ID to leave from.
        """
        return await self(functions.phone.LeaveGroupCallRequest(
            call=call, source=source))

    async def discard_group_call(
        self: "TelegramClient",
        call: "types.TypeInputGroupCall"
    ) -> types.Updates:
        """
        Discard (end) a group call for everyone.

        You will need to have the voice chat admin privilege to do this.

        Args:
            call: The group call to discard.
        """
        return await self(functions.phone.DiscardGroupCallRequest(call=call))

    async def get_group_call(
        self: "TelegramClient",
        call: "types.TypeInputGroupCall",
        limit: int
    ) -> types.phone.GroupCall:
        """
        Get a group call and its participants.

        Args:
            call: The group call to fetch.
            limit: Maximum number of participants to retrieve.
        """
        return await self(functions.phone.GetGroupCallRequest(
            call=call, limit=limit))
