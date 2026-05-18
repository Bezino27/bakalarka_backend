import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


logger = logging.getLogger(__name__)


def user_group_name(user_id):
    return f"user_{user_id}"


def broadcast_chat_event_to_user(user_id, event_type, payload):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        async_to_sync(channel_layer.group_send)(
            user_group_name(user_id),
            {
                "type": "chat.event",
                "event": event_type,
                "payload": payload,
            },
        )
    except Exception as exc:
        logger.warning("Chat WebSocket broadcast zlyhal user=%s: %s", user_id, exc)


def broadcast_chat_event_to_users(user_ids, event_type, payload):
    for user_id in set(user_ids):
        broadcast_chat_event_to_user(user_id, event_type, payload)
