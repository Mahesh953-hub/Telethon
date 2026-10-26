"""Compatibility request for the fork's layer-232 RichMessage send extension.

Telegram layer 233 removed ``rich_message`` from ``messages.sendMessage``.
Ordinary sends use the generated layer-233 request; this subclass is only used
when the caller explicitly supplies a RichMessage payload.
"""

import struct

from ..functions.messages import SendMessageRequest


class SendMessageWithRichRequest(SendMessageRequest):
    """Send using the layer-232 method signature with a RichMessage payload."""

    CONSTRUCTOR_ID = 0xfef48f62
    __slots__ = ('rich_message',)

    def __init__(self, *args, rich_message, **kwargs):
        if rich_message is None:
            raise ValueError('rich_message must be provided')
        super().__init__(*args, **kwargs)
        self.rich_message = rich_message

    def to_dict(self):
        result = super().to_dict()
        result['_'] = 'SendMessageWithRichRequest'
        value = self.rich_message
        result['rich_message'] = value.to_dict() if hasattr(value, 'to_dict') else value
        return result

    def _bytes(self):
        # All fields before rich_message have the same order and encoding in
        # layers 232 and 233. Reuse the generated serializer for those fields,
        # restore the old constructor ID, set flags.23, and append the payload.
        data = super()._bytes()
        flags = struct.unpack('<I', data[4:8])[0] | (1 << 23)
        return (
            struct.pack('<I', self.CONSTRUCTOR_ID)
            + struct.pack('<I', flags)
            + data[8:]
            + self.rich_message._bytes()
        )
