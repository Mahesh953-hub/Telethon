from . import (
    AccountMethods,
    AuthMethods,
    BotMethods,
    ButtonMethods,
    ChatMethods,
    DialogMethods,
    DownloadMethods,
    GroupCallMethods,
    MessageMethods,
    MessageParseMethods,
    PyrogramMethods,
    RawRequestMethods,
    TelegramBaseClient,
    TopicMethods,
    TrafficInspectorMethods,
    UpdateMethods,
    UploadMethods,
    UserMethods,
)
from . import pyrogram as _pyrogram
from . import topics as _topics


class TelegramClient(
    # `TrafficInspectorMethods` wraps `_call`, so it must come before
    # `UserMethods` (which defines it) in the cooperative MRO chain.
    TrafficInspectorMethods,
    AccountMethods, AuthMethods, DownloadMethods, DialogMethods, ChatMethods,
    BotMethods, MessageMethods, UploadMethods, ButtonMethods, UpdateMethods,
    MessageParseMethods, UserMethods, GroupCallMethods, TopicMethods,
    PyrogramMethods, RawRequestMethods,
    TelegramBaseClient
):
    # Pyrogram-flavoured aliases for existing Telethon methods.
    read = MessageMethods.send_read_acknowledge
    send_poll = _pyrogram.send_poll
    send_document = _pyrogram.send_document
    send_video = UploadMethods.send_file
    send_voice = UploadMethods.send_file
    send_audio = UploadMethods.send_file
    send_sticker = UploadMethods.send_file
    pin_chat_message = MessageMethods.pin_message
    unpin_chat_message = MessageMethods.unpin_message
    get_chat = UserMethods.get_entity
    resolve_peer = UserMethods.get_input_entity
    run = UpdateMethods.run_until_disconnected

    # Standalone friendly methods.
    send_reaction = _topics.send_reaction
    set_profile_photo = _topics.set_profile_photo
    set_contact_photo = _topics.set_contact_photo
    toggle_hidden = _topics.toggle_hidden
