"""Friendly methods for forum topics, reactions and channel management.

Ported from https://github.com/New-dev0/Telethon-Patch (``methods.py``) and
adapted to the current layer, where the topic methods live in the ``messages``
namespace rather than ``channels``.
"""
import datetime
import typing

from .. import utils
from ..tl import functions, types

if typing.TYPE_CHECKING:
    from .. import hints
    from .telegramclient import TelegramClient


async def _get_input_channel(
    self: "TelegramClient",
    entity: "hints.EntityLike"
) -> "types.TypeInputChannel":
    """Resolve `entity` to an :tl:`InputChannel`, fetching it if needed."""
    if isinstance(entity, types.TypeInputChannel):
        return entity

    channel = utils.get_input_channel(await self.get_entity(entity))
    if not isinstance(channel, types.TypeInputChannel):
        raise TypeError(
            "Cannot cast {} to InputChannel.".format(type(entity).__name__))

    return channel


async def send_reaction(
    self: "TelegramClient",
    peer: "types.TypeInputPeer",
    msg_id: int,
    reaction=None,
    big: typing.Optional[bool] = None,
    **kwargs
) -> types.Updates:
    """
    Send a reaction to a message.

    Args:
        peer: Chat ID/username of the chat.
        msg_id: The message ID to react to.
        reaction: A single emoji string, an iterable of emoji strings, an
            iterable of :tl:`ReactionEmoji`/:tl:`ReactionCustomEmoji`, or
            `None`/empty to remove the reaction.
        big: Whether to show a big animation.
    """
    if isinstance(reaction, str):
        reaction = [types.ReactionEmoji(reaction)]
    elif reaction is None:
        reaction = [types.ReactionEmpty()]
    else:
        reaction = [
            types.ReactionEmoji(r) if isinstance(r, str) else r
            for r in reaction
        ]

    return await self(functions.messages.SendReactionRequest(
        peer=peer, msg_id=msg_id, big=big, reaction=reaction, **kwargs))


class TopicMethods:
    """Forum topic helpers, mixed into `TelegramClient`."""

    async def create_topic(
        self: "TelegramClient",
        peer: "types.TypeInputPeer",
        title: str,
        icon_color: int = None,
        icon_emoji_id: int = None,
        random_id: int = None,
        send_as: "types.TypeInputPeer" = None
    ) -> types.Updates:
        """
        Create a new forum topic.

        Args:
            peer: The forum (group or channel) to create the topic in.
            title: The title of the new topic.
            icon_color: RGB color of the topic icon.
            icon_emoji_id: Custom emoji document ID for the topic icon.
            random_id: Any random integer, or leave it `None`.
            send_as: The entity to send the topic's first message as.
        """
        return await self(functions.messages.CreateForumTopicRequest(
            peer=peer,
            title=title,
            icon_color=icon_color,
            icon_emoji_id=icon_emoji_id,
            random_id=random_id,
            send_as=send_as
        ))

    async def edit_topic(
        self: "TelegramClient",
        peer: "types.TypeInputPeer",
        topic_id: int,
        title: typing.Optional[str] = None,
        icon_emoji_id: typing.Optional[int] = None,
        closed: typing.Optional[bool] = None,
        hidden: typing.Optional[bool] = None
    ) -> types.Updates:
        """
        Edit a forum topic.

        Args:
            peer: The forum the topic belongs to.
            topic_id: The topic ID to edit.
            title: The new title, or `None` to keep it.
            icon_emoji_id: New custom emoji document ID, or `None` to keep it.
            closed: Whether to close the topic.
            hidden: Whether to hide the topic.
        """
        return await self(functions.messages.EditForumTopicRequest(
            peer=peer,
            topic_id=topic_id,
            title=title,
            icon_emoji_id=icon_emoji_id,
            closed=closed,
            hidden=hidden
        ))

    async def get_topics(
        self: "TelegramClient",
        peer: "types.TypeInputPeer",
        offset_date: typing.Optional[datetime.datetime] = None,
        offset_id: int = 0,
        offset_topic: int = 0,
        limit: int = None,
        q: typing.Optional[str] = None,
        topics: typing.Union[int, typing.Sequence[int]] = None
    ) -> typing.Union[types.messages.ForumTopics,
                      typing.Sequence[types.ForumTopic]]:
        """
        Get the forum topics of a chat.

        Args:
            peer: The forum to get the topics from.
            offset_date: Offset by date.
            offset_id: Offset by message ID.
            offset_topic: Offset by topic ID.
            limit: Maximum number of topics to retrieve.
            q: Search query.
            topics: A single topic ID or a sequence of topic IDs. When given,
                only those topics are returned instead of a full listing.
        """
        if topics is not None:
            if isinstance(topics, int):
                topics = [topics]

            return await self(functions.messages.GetForumTopicsByIDRequest(
                peer=peer, topics=list(topics)))

        return await self(functions.messages.GetForumTopicsRequest(
            peer=peer,
            offset_date=offset_date,
            offset_id=offset_id,
            offset_topic=offset_topic,
            limit=limit,
            q=q
        ))


async def join_chat(
    self: "TelegramClient",
    entity: "typing.Optional[hints.EntityLike]" = None,
    hash: str = ""
) -> types.Updates:
    """
    Join a chat by username, ID or invite link.

    Args:
        entity: Username, ID or input channel of the chat to join.
        hash: The invite link hash, if joining via an invite link.
    """
    if entity:
        return await self(functions.channels.JoinChannelRequest(
            await _get_input_channel(self, entity)))

    if hash:
        return await self(functions.messages.ImportChatInviteRequest(hash))

    raise ValueError("Either entity or hash is required.")


async def toggle_hidden(
    self: "TelegramClient",
    channel: "hints.EntityLike",
    enabled: bool = False
) -> types.Updates:
    """Toggle the "hidden members" setting of a supergroup."""
    return await self(functions.channels.ToggleParticipantsHiddenRequest(
        await _get_input_channel(self, channel), enabled))


async def set_profile_photo(
    self: "TelegramClient",
    file: "typing.Union[str, types.TypeInputFile]",
    **kwargs
) -> types.photos.Photo:
    """Upload a new profile photo for yourself."""
    if isinstance(file, str):
        file = await self.upload_file(file)

    return await self(functions.photos.UploadProfilePhotoRequest(
        file=file, **kwargs))


async def set_contact_photo(
    self: "TelegramClient",
    user: "typing.Optional[hints.EntityLike]",
    file: "typing.Union[str, types.TypeInputFile]" = None,
    **kwargs
) -> types.Updates:
    """
    Upload a new profile photo for another user you can edit.

    `user` may be an ID, username or :tl:`InputUser`; anything that is not
    already an :tl:`InputUser` is resolved first.
    """
    if isinstance(file, str):
        file = await self.upload_file(file)

    if not isinstance(user, types.TypeInputUser):
        if user is None:
            raise ValueError("user is required.")
        user = utils.get_input_user(await self.get_input_entity(user))

    return await self(functions.photos.UploadContactProfilePhotoRequest(
        user, file=file, **kwargs))
