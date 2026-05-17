from django.urls import path

from .views import (
    chat_users_list,
    conversations_list,
    create_direct_conversation,
    create_group_conversation,
    conversation_detail,
    conversation_members,
    conversation_messages,
    create_conversation_poll,
    mark_conversation_read,
    toggle_message_reaction,
    vote_poll,
    delete_message,
)

urlpatterns = [
    path("users/", chat_users_list, name="chat-users-list"),

    path("conversations/", conversations_list, name="chat-conversations"),
    path("conversations/direct/", create_direct_conversation, name="chat-create-direct"),
    path("conversations/group/", create_group_conversation, name="chat-create-group"),
    path("conversations/<int:conversation_id>/", conversation_detail, name="chat-conversation-detail"),
    path("conversations/<int:conversation_id>/members/", conversation_members, name="chat-conversation-members"),
    path("conversations/<int:conversation_id>/messages/", conversation_messages, name="chat-conversation-messages"),
    path("conversations/<int:conversation_id>/polls/", create_conversation_poll, name="chat-create-poll"),
    path("conversations/<int:conversation_id>/read/", mark_conversation_read, name="chat-mark-read"),

    path("messages/<int:message_id>/reactions/", toggle_message_reaction, name="chat-toggle-reaction"),
    path("polls/<int:poll_id>/vote/", vote_poll, name="chat-vote-poll"),
    path("messages/<int:message_id>/", delete_message, name="chat-delete-message"),
]
