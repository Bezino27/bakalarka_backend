from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    ChatConversation,
    ChatConversationMember,
    ChatMessage,
    ChatMessageReaction,
    ChatPoll,
    ChatPollOption,
    ChatPollVote,
)

User = get_user_model()


class ChatUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "number"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username


class ChatMessageReactionSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessageReaction
        fields = ["id", "user", "user_name", "emoji", "created_at"]

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username


class ChatPollOptionSerializer(serializers.ModelSerializer):
    votes_count = serializers.SerializerMethodField()
    voted_by_current_user = serializers.SerializerMethodField()
    voters = serializers.SerializerMethodField()

    class Meta:
        model = ChatPollOption
        fields = [
            "id",
            "text",
            "position",
            "votes_count",
            "voted_by_current_user",
            "voters",
        ]

    def get_votes_count(self, obj):
        return obj.votes.count()

    def get_voted_by_current_user(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return False

        return obj.votes.filter(user=request.user).exists()

    def get_voters(self, obj):
        votes = obj.votes.select_related("user").order_by(
            "user__last_name",
            "user__first_name",
            "user__username",
        )
        return [
            {
                "id": vote.user_id,
                "name": vote.user.get_full_name() or vote.user.username,
                "username": vote.user.username,
            }
            for vote in votes
        ]


class ChatPollSerializer(serializers.ModelSerializer):
    options = ChatPollOptionSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    is_closed = serializers.BooleanField(read_only=True)
    total_votes = serializers.SerializerMethodField()
    user_option_ids = serializers.SerializerMethodField()

    class Meta:
        model = ChatPoll
        fields = [
            "id",
            "message",
            "question",
            "allow_multiple",
            "created_by",
            "created_by_name",
            "created_at",
            "closed_at",
            "is_closed",
            "total_votes",
            "user_option_ids",
            "options",
        ]
        read_only_fields = ["id", "message", "created_by", "created_at", "closed_at"]

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username

    def get_total_votes(self, obj):
        return ChatPollVote.objects.filter(option__poll=obj).count()

    def get_user_option_ids(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return []

        return list(
            ChatPollVote.objects
            .filter(option__poll=obj, user=request.user)
            .values_list("option_id", flat=True)
        )


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_detail = ChatUserSerializer(source="sender", read_only=True)
    reactions = ChatMessageReactionSerializer(many=True, read_only=True)
    reply_to_message = serializers.SerializerMethodField()
    is_own = serializers.SerializerMethodField()
    poll = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "conversation",
            "sender",
            "sender_detail",
            "text",
            "reply_to",
            "reply_to_message",
            "client_message_id",
            "created_at",
            "edited_at",
            "deleted_at",
            "is_deleted",
            "is_own",
            "reactions",
            "poll",
        ]
        read_only_fields = [
            "id",
            "sender",
            "created_at",
            "edited_at",
            "deleted_at",
            "is_deleted",
            "is_own",
            "reactions",
            "poll",
        ]

    def get_is_own(self, obj):
        request = self.context.get("request")
        return bool(request and request.user and obj.sender_id == request.user.id)

    def get_reply_to_message(self, obj):
        if not obj.reply_to:
            return None

        return {
            "id": obj.reply_to.id,
            "text": obj.reply_to.text,
            "sender_name": obj.reply_to.sender.get_full_name() or obj.reply_to.sender.username,
            "deleted_at": obj.reply_to.deleted_at,
        }

    def get_poll(self, obj):
        poll = getattr(obj, "poll", None)
        if not poll:
            return None

        return ChatPollSerializer(poll, context=self.context).data


class ChatConversationMemberSerializer(serializers.ModelSerializer):
    user_detail = ChatUserSerializer(source="user", read_only=True)

    class Meta:
        model = ChatConversationMember
        fields = [
            "id",
            "user",
            "user_detail",
            "is_admin",
            "is_muted",
            "is_archived",
            "last_read_at",
            "joined_at",
        ]


class ChatConversationSerializer(serializers.ModelSerializer):
    members = ChatConversationMemberSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    class Meta:
        model = ChatConversation
        fields = [
            "id",
            "club",
            "type",
            "name",
            "title",
            "created_by",
            "created_at",
            "updated_at",
            "members",
            "last_message",
            "unread_count",
        ]
        read_only_fields = ["id", "club", "created_by", "created_at", "updated_at"]

    def get_title(self, obj):
        request = self.context.get("request")

        if obj.type == ChatConversation.GROUP:
            return obj.name or "Skupina"

        if not request:
            return "Chat"

        other_member = (
            obj.members
            .exclude(user=request.user)
            .select_related("user")
            .first()
        )

        if not other_member:
            return "Chat"

        user = other_member.user
        return user.get_full_name() or user.username

    def get_last_message(self, obj):
        msg = obj.messages.order_by("-created_at").select_related("sender").first()
        if not msg:
            return None

        return {
            "id": msg.id,
            "text": "" if msg.deleted_at else msg.text,
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.get_full_name() or msg.sender.username,
            "created_at": msg.created_at,
            "deleted_at": msg.deleted_at,
        }

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request:
            return 0

        membership = obj.members.filter(user=request.user).first()
        if not membership:
            return 0

        qs = obj.messages.exclude(sender=request.user)

        if membership.last_read_at:
            qs = qs.filter(created_at__gt=membership.last_read_at)

        return qs.count()


class CreateDirectConversationSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()

    def validate_user_id(self, value):
        request = self.context["request"]

        if value == request.user.id:
            raise serializers.ValidationError("Nemôžeš vytvoriť chat sám so sebou.")

        try:
            user = User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Používateľ neexistuje.")

        if user.club_id != request.user.club_id:
            raise serializers.ValidationError("Používateľ nie je v tvojom klube.")

        return value


class CreateGroupConversationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )

    def validate_member_ids(self, value):
        request = self.context["request"]

        unique_ids = list(set(value))
        users_count = User.objects.filter(
            id__in=unique_ids,
            club=request.user.club,
        ).count()

        if users_count != len(unique_ids):
            raise serializers.ValidationError("Niektorí používatelia neexistujú alebo nie sú v tvojom klube.")

        return unique_ids


class UpdateGroupMembersSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )

    def validate_member_ids(self, value):
        request = self.context["request"]

        unique_ids = list(set(value))
        users_count = User.objects.filter(
            id__in=unique_ids,
            club=request.user.club,
        ).count()

        if users_count != len(unique_ids):
            raise serializers.ValidationError("Niektorí používatelia neexistujú alebo nie sú v tvojom klube.")

        other_member_ids = [user_id for user_id in unique_ids if user_id != request.user.id]
        if not other_member_ids:
            raise serializers.ValidationError("Skupina musí mať aspoň jedného ďalšieho člena.")

        return unique_ids


class SendChatMessageSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=False, trim_whitespace=True)
    reply_to = serializers.IntegerField(required=False, allow_null=True)
    client_message_id = serializers.CharField(required=False, allow_blank=True, max_length=120)

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Správa nemôže byť prázdna.")

        if len(value) > 5000:
            raise serializers.ValidationError("Správa je príliš dlhá.")

        return value.strip()


class ToggleReactionSerializer(serializers.Serializer):
    emoji = serializers.CharField(max_length=20)

    def validate_emoji(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Emoji je povinné.")
        return value


class CreatePollSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=240, trim_whitespace=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=120, trim_whitespace=True),
        allow_empty=False,
    )
    allow_multiple = serializers.BooleanField(required=False, default=False)

    def validate_question(self, value):
        if not value.strip():
            raise serializers.ValidationError("Otázka ankety je povinná.")
        return value.strip()

    def validate_options(self, value):
        options = [option.strip() for option in value if option.strip()]

        if len(options) < 2:
            raise serializers.ValidationError("Anketa musí mať aspoň dve možnosti.")

        if len(options) > 6:
            raise serializers.ValidationError("Anketa môže mať najviac šesť možností.")

        lowered = [option.lower() for option in options]
        if len(lowered) != len(set(lowered)):
            raise serializers.ValidationError("Možnosti ankety sa nemôžu opakovať.")

        return options


class VotePollSerializer(serializers.Serializer):
    option_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=True,
    )

    def validate_option_ids(self, value):
        return list(dict.fromkeys(value))
