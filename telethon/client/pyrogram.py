"""Pyrogram-flavoured convenience methods.

Ported from https://github.com/New-dev0/Telethon-Patch (``pyrogram.py``) and
adapted to the current layer, where polls take ``TextWithEntities``.
"""
import datetime
import typing
from secrets import token_bytes

from .. import hints
from ..tl import functions, types
from ..tl.custom import Message

if typing.TYPE_CHECKING:
    from .telegramclient import TelegramClient


class PyrogramMethods:
    """Pyrogram-style aliases, mixed into `TelegramClient`."""

    async def set_username(
        self: "TelegramClient",
        username: str
    ) -> types.User:
        """Change your own username."""
        return await self(functions.account.UpdateUsernameRequest(username))

    async def set_chat_username(
        self: "TelegramClient",
        chat_id: "hints.EntityLike",
        username: str
    ):
        """Change the username of a group or channel you own."""
        from .topics import _get_input_channel

        return await self(functions.channels.UpdateUsernameRequest(
            await _get_input_channel(self, chat_id), username))

    async def get_users(
        self: "TelegramClient",
        users: "typing.Union[hints.EntityLike, typing.Sequence[hints.EntityLike]]"
    ) -> typing.Union[types.User, typing.List[types.User]]:
        """Get one user, or a list of users, by ID/username/mention."""
        if isinstance(users, (list, tuple, set, frozenset)):
            return [await self.get_entity(user) for user in users]

        return await self.get_entity(users)

    async def join_chat(
        self: "TelegramClient",
        chat_id: "typing.Union[hints.EntityLike, str]" = None
    ) -> types.Updates:
        """
        Join a chat.

        ``chat_id`` may be a username, an ID, an invite link, or the hash of
        an invite link.
        """
        from .topics import join_chat

        if chat_id is None:
            raise ValueError("chat_id is required.")

        if isinstance(chat_id, str):
            if 't.me/' in chat_id:
                # A t.me link is only ever an invite link here, and its
                # hash may or may not carry the leading '+'.
                return await join_chat(self, hash=chat_id.rsplit('/', 1)[-1]
                                       .lstrip('+'))

            if chat_id.startswith('+'):
                return await join_chat(self, hash=chat_id[1:])

            # Otherwise this is a username, not an invite hash. A bare
            # non-numeric string is ambiguous, so treat it as a username
            # and let entity resolution decide; guessing "hash" here made
            # `join_chat('somechannel')` send an ImportChatInviteRequest
            # instead of joining the channel.

        return await join_chat(self, entity=chat_id)

    async def leave_chat(
        self: "TelegramClient",
        chat_id: "hints.EntityLike"
    ):
        """Leave a chat and delete its dialog."""
        return await self.delete_dialog(chat_id)

    async def vote_poll(
        self: "TelegramClient",
        chat_id: "hints.EntityLike",
        message_id: int,
        options: typing.Union[int, typing.Sequence[int]]
    ) -> typing.Optional[typing.Any]:
        """
        Vote in a poll.

        Args:
            chat_id: The chat the poll is in.
            message_id: The ID of the poll message.
            options: The index (or indices, for multiple choice) to vote for.
        """
        if isinstance(options, int):
            options = [options]

        message = await self.get_messages(chat_id, ids=message_id)
        if message:
            return await message.click(list(options))

        raise ValueError("The poll message does not exist.")


async def send_poll(
    self: "TelegramClient",
    chat_id: "hints.EntityLike",
    question: str,
    options: "typing.Sequence[typing.Union[str, types.TypePollAnswer]]",
    is_anonymous: bool = True,
    multiple_choice: bool = False,
    quiz: bool = False,
    closed: bool = False,
    correct_answers: typing.Optional[typing.Sequence[int]] = None,
    solution: str = "",
    close_date: typing.Optional[datetime.datetime] = None,
    schedule: typing.Optional[datetime.datetime] = None
) -> typing.Optional["Message"]:
    """
    Send a poll.

    Args:
        chat_id: The chat to send the poll to.
        question: The poll question.
        options: The poll answers, as strings or :tl:`PollAnswer` objects.
        is_anonymous: Whether voters are hidden.
        multiple_choice: Whether more than one answer can be picked.
        quiz: Whether this is a quiz (implies ``closed=True``).
        closed: Whether the poll is immediately closed.
        correct_answers: Indices of the correct answers, for quizzes.
        solution: The quiz explanation.
        close_date: `datetime` at which the poll closes.
        schedule: `datetime` at which to schedule the poll.
    """
    if quiz:
        closed = True

    if correct_answers is not None and not isinstance(
            correct_answers, (list, tuple)):
        correct_answers = [correct_answers]

    if isinstance(question, types.TypeTextWithEntities):
        question_text = question
    else:
        text, entities = await self._parse_message_text(question, None)
        question_text = types.TextWithEntities(text, entities or [])

    answers = []
    for option in options:
        if isinstance(option, types.PollAnswer):
            answers.append(option)
            continue

        text, entities = await self._parse_message_text(option, None)
        answers.append(types.PollAnswer(
            types.TextWithEntities(text, entities or []),
            token_bytes(8)
        ))

    solution, solution_entities = await self._parse_message_text(
        solution, None)

    updates = await self(functions.messages.SendMediaRequest(
        peer=chat_id,
        media=types.InputMediaPoll(
            poll=types.Poll(
                id=0,
                question=question_text,
                answers=answers,
                hash=0,
                closed=closed,
                public_voters=not is_anonymous,
                multiple_choice=multiple_choice,
                quiz=quiz,
                close_date=close_date
            ),
            correct_answers=(
                list(correct_answers) if correct_answers else None),
            solution=solution,
            solution_entities=solution_entities
        ),
        message='',
        schedule_date=schedule
    ))

    return await self._get_response_message(
        None, updates, await self.get_input_entity(chat_id))


async def send_document(
    self: "TelegramClient",
    chat_id: "hints.EntityLike",
    document: "hints.FileLike",
    **kwargs
) -> "types.Message":
    """Send a file as a document rather than a photo or video.

    `send_file` picks the media type from the file, so an image passed to
    it is sent as a photo. A bare alias cannot change that, so this is a
    real wrapper that forces ``force_document=True``.
    """
    from .uploads import UploadMethods

    kwargs.setdefault('force_document', True)
    return await UploadMethods.send_file(self, chat_id, document, **kwargs)
