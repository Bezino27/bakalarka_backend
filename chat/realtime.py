import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


logger = logging.getLogger(__name__)


def conversation_group_name(conversation_id):
    return f"chat_conversation_{conversation_id}"


def broadcast_chat_event(conversation_id, event_type, payload):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        async_to_sync(channel_layer.group_send)(
            conversation_group_name(conversation_id),
            {
                "type": "chat.event",
                "event": event_type,
                "payload": payload,
            },
        )
    except Exception as exc:
        logger.warning("Chat WebSocket broadcast zlyhal conversation=%s: %s", conversation_id, exc)
