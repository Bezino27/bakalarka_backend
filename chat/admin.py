from django.contrib import admin
from .models import (
    ChatConversation,
    ChatConversationMember,
    ChatMessage,
    ChatMessageReaction,
    ChatPoll,
    ChatPollOption,
    ChatPollVote,
)


class ChatConversationMemberInline(admin.TabularInline):
    model = ChatConversationMember
    extra = 0


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("sender", "text", "created_at", "deleted_at")
    readonly_fields = ("created_at",)


class ChatPollOptionInline(admin.TabularInline):
    model = ChatPollOption
    extra = 0
    fields = ("text", "position")


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "club", "type", "name", "created_by", "updated_at")
    list_filter = ("type", "club", "created_at")
    search_fields = ("name", "created_by__username", "created_by__first_name", "created_by__last_name")
    inlines = [ChatConversationMemberInline]


@admin.register(ChatConversationMember)
class ChatConversationMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "user", "is_admin", "is_muted", "is_archived", "last_read_at")
    list_filter = ("is_admin", "is_muted", "is_archived")
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "short_text", "created_at", "deleted_at")
    list_filter = ("created_at", "deleted_at")
    search_fields = ("text", "sender__username", "sender__first_name", "sender__last_name")

    def short_text(self, obj):
        return obj.text[:60]


@admin.register(ChatMessageReaction)
class ChatMessageReactionAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "user", "emoji", "created_at")
    list_filter = ("emoji", "created_at")
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(ChatPoll)
class ChatPollAdmin(admin.ModelAdmin):
    list_display = ("id", "question", "message", "created_by", "allow_multiple", "created_at", "closed_at")
    list_filter = ("allow_multiple", "created_at", "closed_at")
    search_fields = ("question", "created_by__username", "created_by__first_name", "created_by__last_name")
    inlines = [ChatPollOptionInline]


@admin.register(ChatPollVote)
class ChatPollVoteAdmin(admin.ModelAdmin):
    list_display = ("id", "option", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "option__text")
