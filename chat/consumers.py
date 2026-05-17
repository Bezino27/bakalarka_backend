from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import ChatConversationMember
from .realtime import conversation_group_name


class ChatConversationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group_name = conversation_group_name(self.conversation_id)
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        is_member = await self.user_is_member()
        if not is_member:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def chat_event(self, event):
        await self.send_json({
            "type": event["event"],
            "payload": event["payload"],
        })

    @database_sync_to_async
    def user_is_member(self):
        return ChatConversationMember.objects.filter(
            conversation_id=self.conversation_id,
            conversation__club=self.user.club,
            user=self.user,
        ).exists()
