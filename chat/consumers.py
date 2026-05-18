from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import ChatConversationMember
from .realtime import user_group_name


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        self.group_name = user_group_name(self.user.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})
            return

        event_type = content.get("type")
        if event_type not in {"typing.start", "typing.stop"}:
            return

        conversation_id = content.get("conversation_id")
        if not conversation_id:
            return

        recipients = await self.get_typing_recipients(conversation_id)
        if not recipients:
            return

        payload = {
            "type": "typing",
            "conversation_id": str(conversation_id),
            "user_id": self.user.id,
            "user_name": self.user.get_full_name() or self.user.username,
            "is_typing": event_type == "typing.start",
        }

        for recipient_id in recipients:
            await self.channel_layer.group_send(
                user_group_name(recipient_id),
                {
                    "type": "chat.event",
                    "event": "typing",
                    "payload": payload,
                },
            )

    async def chat_event(self, event):
        await self.send_json({
            "type": event["event"],
            "payload": event["payload"],
        })

    @database_sync_to_async
    def get_typing_recipients(self, conversation_id):
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return []

        is_member = ChatConversationMember.objects.filter(
            conversation_id=conversation_id,
            user=self.user,
        ).exists()

        if not is_member:
            return []

        return list(
            ChatConversationMember.objects
            .filter(conversation_id=conversation_id)
            .exclude(user=self.user)
            .values_list("user_id", flat=True)
        )
