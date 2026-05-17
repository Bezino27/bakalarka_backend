import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from dochadzka_app.models import ExpoPushToken
from dochadzka_app.helpers import send_push_notification

from .models import ChatMessage, ChatConversationMember, ChatConversation

logger = logging.getLogger(__name__)
User = get_user_model()


def get_chat_unread_count(user):
    total = 0
    memberships = (
        ChatConversationMember.objects
        .filter(user=user, conversation__club=user.club)
        .select_related("conversation")
    )

    for membership in memberships:
        messages = ChatMessage.objects.filter(
            conversation=membership.conversation,
            deleted_at__isnull=True,
        ).exclude(sender=user)

        if membership.last_read_at:
            messages = messages.filter(created_at__gt=membership.last_read_at)

        total += messages.count()

    return total


@shared_task
def notify_new_chat_message(message_id: int):
    try:
        message = (
            ChatMessage.objects
            .select_related("conversation", "sender")
            .get(id=message_id)
        )
    except ChatMessage.DoesNotExist:
        logger.warning("ChatMessage %s neexistuje", message_id)
        return

    conversation = message.conversation
    sender = message.sender

    recipient_members = (
        ChatConversationMember.objects
        .filter(conversation=conversation, is_muted=False)
        .exclude(user=sender)
        .select_related("user")
    )

    sender_name = sender.get_full_name() or sender.username

    if conversation.type == ChatConversation.GROUP:
        title = conversation.name or "Nová skupinová správa"
        body = f"{sender_name}: {message.text[:120]}"
    else:
        title = f"Nová správa od {sender_name}"
        body = message.text[:120]

    for member in recipient_members:
        tokens = ExpoPushToken.objects.filter(user=member.user).values_list("token", flat=True)
        unread_count = get_chat_unread_count(member.user)

        for token in tokens:
            try:
                send_push_notification(
                    token=token,
                    title=title,
                    message=body,
                    data={
                        "type": "chat_message",
                        "conversation_id": conversation.id,
                        "message_id": message.id,
                        "sender_id": sender.id,
                    },
                    badge=unread_count,
                )
                logger.info("Chat push odoslaný user=%s token=%s", member.user_id, token)
            except Exception as e:
                logger.warning("Chyba pri chat push user=%s token=%s: %s", member.user_id, token, e)
