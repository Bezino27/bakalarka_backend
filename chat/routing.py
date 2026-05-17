from django.urls import path

from .consumers import ChatConversationConsumer


websocket_urlpatterns = [
    path("ws/chat/conversations/<int:conversation_id>/", ChatConversationConsumer.as_asgi()),
]
