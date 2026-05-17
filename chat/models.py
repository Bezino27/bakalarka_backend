from django.conf import settings
from django.db import models
from django.utils import timezone


class ChatConversation(models.Model):
    DIRECT = "direct"
    GROUP = "group"

    TYPE_CHOICES = [
        (DIRECT, "Súkromný chat"),
        (GROUP, "Skupinový chat"),
    ]

    club = models.ForeignKey(
        "dochadzka_app.Club",
        on_delete=models.CASCADE,
        related_name="chat_conversations",
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    name = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chat_conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        if self.type == self.GROUP and self.name:
            return self.name
        return f"Konverzácia #{self.id}"


class ChatConversationMember(models.Model):
    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_memberships",
    )
    is_admin = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("conversation", "user")
        indexes = [
            models.Index(fields=["conversation", "user"]),
            models.Index(fields=["user", "is_archived"]),
        ]

    def __str__(self):
        return f"{self.user} v {self.conversation}"


class ChatMessage(models.Model):
    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages_sent",
    )
    text = models.TextField()
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )
    client_message_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="ID z frontendu kvôli ochrane pred duplicitným odoslaním.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.sender}: {self.text[:40]}"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.text = ""
        self.save(update_fields=["deleted_at", "text"])


class ChatMessageReaction(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_reactions",
    )
    emoji = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user", "emoji")
        indexes = [
            models.Index(fields=["message", "user"]),
        ]

    def __str__(self):
        return f"{self.user} {self.emoji} -> {self.message_id}"


class ChatPoll(models.Model):
    message = models.OneToOneField(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="poll",
    )
    question = models.CharField(max_length=240)
    allow_multiple = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_polls_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.question

    @property
    def is_closed(self):
        return self.closed_at is not None


class ChatPollOption(models.Model):
    poll = models.ForeignKey(
        ChatPoll,
        on_delete=models.CASCADE,
        related_name="options",
    )
    text = models.CharField(max_length=120)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text


class ChatPollVote(models.Model):
    option = models.ForeignKey(
        ChatPollOption,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_poll_votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("option", "user")
        indexes = [
            models.Index(fields=["option", "user"]),
        ]

    def __str__(self):
        return f"{self.user} -> {self.option}"
