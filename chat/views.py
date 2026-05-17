from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import (
    ChatConversation,
    ChatConversationMember,
    ChatMessage,
    ChatMessageReaction,
    ChatPoll,
    ChatPollOption,
    ChatPollVote,
)
from dochadzka_app.models import Role
from .serializers import (
    ChatConversationSerializer,
    ChatConversationMemberSerializer,
    ChatMessageSerializer,
    ChatPollSerializer,
    ChatUserSerializer,
    CreatePollSerializer,
    CreateDirectConversationSerializer,
    CreateGroupConversationSerializer,
    SendChatMessageSerializer,
    ToggleReactionSerializer,
    UpdateGroupMembersSerializer,
    VotePollSerializer,
)
from .realtime import broadcast_chat_event
from .tasks import notify_new_chat_message

User = get_user_model()


def serialize_chat_message(message, request=None):
    return ChatMessageSerializer(
        message,
        context={"request": request} if request else {},
    ).data


def get_message_for_realtime(message_id):
    return (
        ChatMessage.objects
        .select_related("sender", "reply_to", "reply_to__sender")
        .prefetch_related("reactions__user", "poll__options__votes__user")
        .get(id=message_id)
    )


def broadcast_message_created(message, request=None):
    broadcast_chat_event(
        message.conversation_id,
        "message.created",
        serialize_chat_message(message, request),
    )


def broadcast_message_updated(message, request=None):
    broadcast_chat_event(
        message.conversation_id,
        "message.updated",
        serialize_chat_message(message, request),
    )


def user_is_conversation_member(user, conversation):
    return ChatConversationMember.objects.filter(
        conversation=conversation,
        user=user,
    ).exists()


def get_user_conversation_or_404(user, conversation_id):
    conversation = get_object_or_404(
        ChatConversation.objects.prefetch_related("members__user"),
        id=conversation_id,
        club=user.club,
    )

    if not user_is_conversation_member(user, conversation):
        return None

    return conversation


def user_can_create_group_conversation(user):
    if not user.club_id:
        return False

    return user.roles.filter(
        role=Role.COACH,
        category__club=user.club,
    ).exists()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chat_users_list(request):
    user = request.user

    if not user.club_id:
        return Response({"detail": "Používateľ nemá priradený klub."}, status=400)

    search = request.GET.get("search", "").strip()

    users = User.objects.filter(club=user.club).exclude(id=user.id)

    if search:
        users = users.filter(
            first_name__icontains=search
        ) | users.filter(
            last_name__icontains=search
        ) | users.filter(
            username__icontains=search
        )

    users = users.order_by("last_name", "first_name", "username").distinct()

    serializer = ChatUserSerializer(users, many=True)
    return Response(serializer.data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversations_list(request):
    conversations = (
        ChatConversation.objects
        .filter(members__user=request.user, club=request.user.club)
        .prefetch_related("members__user")
        .annotate(last_message_time=Max("messages__created_at"))
        .order_by("-last_message_time", "-updated_at")
        .distinct()
    )

    serializer = ChatConversationSerializer(
        conversations,
        many=True,
        context={"request": request},
    )
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_direct_conversation(request):
    serializer = CreateDirectConversationSerializer(
        data=request.data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)

    other_user_id = serializer.validated_data["user_id"]
    current_user = request.user

    other_user = get_object_or_404(User, id=other_user_id, club=current_user.club)

    existing = (
        ChatConversation.objects
        .filter(
            club=current_user.club,
            type=ChatConversation.DIRECT,
            members__user=current_user,
        )
        .filter(members__user=other_user)
        .distinct()
        .first()
    )

    if existing:
        data = ChatConversationSerializer(existing, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)

    with transaction.atomic():
        conversation = ChatConversation.objects.create(
            club=current_user.club,
            type=ChatConversation.DIRECT,
            created_by=current_user,
        )

        ChatConversationMember.objects.bulk_create([
            ChatConversationMember(
                conversation=conversation,
                user=current_user,
                is_admin=True,
                last_read_at=timezone.now(),
            ),
            ChatConversationMember(
                conversation=conversation,
                user=other_user,
            ),
        ])

    data = ChatConversationSerializer(conversation, context={"request": request}).data
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_group_conversation(request):
    current_user = request.user

    if not user_can_create_group_conversation(current_user):
        return Response(
            {"detail": "Skupinový chat môže vytvoriť iba tréner."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = CreateGroupConversationSerializer(
        data=request.data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)

    name = serializer.validated_data["name"]
    member_ids = serializer.validated_data["member_ids"]

    if current_user.id not in member_ids:
        member_ids.append(current_user.id)

    users = User.objects.filter(id__in=member_ids, club=current_user.club)

    with transaction.atomic():
        conversation = ChatConversation.objects.create(
            club=current_user.club,
            type=ChatConversation.GROUP,
            name=name,
            created_by=current_user,
        )

        memberships = []
        for user in users:
            memberships.append(
                ChatConversationMember(
                    conversation=conversation,
                    user=user,
                    is_admin=user.id == current_user.id,
                    last_read_at=timezone.now() if user.id == current_user.id else None,
                )
            )

        ChatConversationMember.objects.bulk_create(memberships)

    data = ChatConversationSerializer(conversation, context={"request": request}).data
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversation_detail(request, conversation_id):
    conversation = get_user_conversation_or_404(request.user, conversation_id)

    if conversation is None:
        return Response({"detail": "Nemáš prístup k tejto konverzácii."}, status=403)

    serializer = ChatConversationSerializer(conversation, context={"request": request})
    return Response(serializer.data)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def conversation_members(request, conversation_id):
    conversation = get_user_conversation_or_404(request.user, conversation_id)

    if conversation is None:
        return Response({"detail": "Nemáš prístup k tejto konverzácii."}, status=403)

    if conversation.type != ChatConversation.GROUP:
        return Response({"detail": "Členovia sa dajú spravovať iba pri skupinovom chate."}, status=400)

    current_membership = ChatConversationMember.objects.filter(
        conversation=conversation,
        user=request.user,
    ).first()

    if request.method == "GET":
        members = (
            conversation.members
            .select_related("user")
            .order_by("-is_admin", "user__last_name", "user__first_name", "user__username")
        )
        return Response(ChatConversationMemberSerializer(members, many=True).data)

    if not current_membership or not current_membership.is_admin:
        return Response({"detail": "Nemáš oprávnenie upravovať členov tejto skupiny."}, status=403)

    serializer = UpdateGroupMembersSerializer(
        data=request.data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)

    member_ids = set(serializer.validated_data["member_ids"])
    member_ids.add(request.user.id)

    users = list(User.objects.filter(id__in=member_ids, club=request.user.club))

    with transaction.atomic():
        ChatConversationMember.objects.filter(
            conversation=conversation,
        ).exclude(user_id__in=member_ids).delete()

        existing_user_ids = set(
            ChatConversationMember.objects
            .filter(conversation=conversation)
            .values_list("user_id", flat=True)
        )

        ChatConversationMember.objects.bulk_create(
            [
                ChatConversationMember(
                    conversation=conversation,
                    user=user,
                    is_admin=user.id == request.user.id,
                    last_read_at=timezone.now() if user.id == request.user.id else None,
                )
                for user in users
                if user.id not in existing_user_ids
            ]
        )

        conversation.updated_at = timezone.now()
        conversation.save(update_fields=["updated_at"])

    conversation = (
        ChatConversation.objects
        .prefetch_related("members__user")
        .get(id=conversation.id)
    )
    return Response(ChatConversationSerializer(conversation, context={"request": request}).data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def conversation_messages(request, conversation_id):
    conversation = get_user_conversation_or_404(request.user, conversation_id)

    if conversation is None:
        return Response({"detail": "Nemáš prístup k tejto konverzácii."}, status=403)

    if request.method == "GET":
        try:
            limit = int(request.GET.get("limit", 30))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Parameter limit musí byť číslo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = min(max(limit, 1), 50)
        before_message_id = request.GET.get("before_message_id")

        messages = (
            ChatMessage.objects
            .filter(conversation=conversation)
            .select_related("sender", "reply_to", "reply_to__sender")
            .prefetch_related("reactions__user", "poll__options__votes__user")
            .order_by("-created_at")
        )

        if before_message_id:
            try:
                before_message_id_int = int(before_message_id)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter before_message_id musí byť číslo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            before_message = get_object_or_404(
                ChatMessage,
                id=before_message_id_int,
                conversation=conversation,
            )
            messages = messages.filter(created_at__lt=before_message.created_at)

        page = list(messages[:limit + 1])
        has_more = len(page) > limit
        page = page[:limit]
        page.reverse()

        serializer = ChatMessageSerializer(
            page,
            many=True,
            context={"request": request},
        )

        return Response({
            "results": serializer.data,
            "limit": limit,
            "before_message_id": before_message_id,
            "has_more": has_more,
            "next_before_message_id": page[0].id if has_more and page else None,
        })

    serializer = SendChatMessageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    text = serializer.validated_data["text"]
    reply_to_id = serializer.validated_data.get("reply_to")
    client_message_id = serializer.validated_data.get("client_message_id", "")

    reply_to = None
    if reply_to_id:
        reply_to = get_object_or_404(
            ChatMessage,
            id=reply_to_id,
            conversation=conversation,
        )

    if client_message_id:
        existing_message = ChatMessage.objects.filter(
            conversation=conversation,
            sender=request.user,
            client_message_id=client_message_id,
        ).first()

        if existing_message:
            data = serialize_chat_message(existing_message, request)
            return Response(data, status=status.HTTP_200_OK)

    with transaction.atomic():
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            text=text,
            reply_to=reply_to,
            client_message_id=client_message_id,
        )

        conversation.updated_at = timezone.now()
        conversation.save(update_fields=["updated_at"])

        ChatConversationMember.objects.filter(
            conversation=conversation,
            user=request.user,
        ).update(last_read_at=timezone.now())

    notify_new_chat_message.delay(message.id)

    message = get_message_for_realtime(message.id)
    broadcast_message_created(message, request)
    data = serialize_chat_message(message, request)
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_conversation_poll(request, conversation_id):
    conversation = get_user_conversation_or_404(request.user, conversation_id)

    if conversation is None:
        return Response({"detail": "Nemáš prístup k tejto konverzácii."}, status=403)

    if conversation.type != ChatConversation.GROUP:
        return Response({"detail": "Ankety sa dajú vytvárať iba v skupinovom chate."}, status=400)

    serializer = CreatePollSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    question = serializer.validated_data["question"]
    options = serializer.validated_data["options"]
    allow_multiple = serializer.validated_data["allow_multiple"]

    with transaction.atomic():
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            text=f"Anketa: {question}",
        )
        poll = ChatPoll.objects.create(
            message=message,
            question=question,
            allow_multiple=allow_multiple,
            created_by=request.user,
        )
        ChatPollOption.objects.bulk_create([
            ChatPollOption(poll=poll, text=option, position=index)
            for index, option in enumerate(options)
        ])

        conversation.updated_at = timezone.now()
        conversation.save(update_fields=["updated_at"])

        ChatConversationMember.objects.filter(
            conversation=conversation,
            user=request.user,
        ).update(last_read_at=timezone.now())

    notify_new_chat_message.delay(message.id)

    message = (
        ChatMessage.objects
        .select_related("sender")
        .prefetch_related("reactions__user", "poll__options__votes__user")
        .get(id=message.id)
    )
    broadcast_message_created(message, request)
    return Response(serialize_chat_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_conversation_read(request, conversation_id):
    conversation = get_user_conversation_or_404(request.user, conversation_id)

    if conversation is None:
        return Response({"detail": "Nemáš prístup k tejto konverzácii."}, status=403)

    ChatConversationMember.objects.filter(
        conversation=conversation,
        user=request.user,
    ).update(last_read_at=timezone.now())

    return Response({"success": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_message_reaction(request, message_id):
    message = get_object_or_404(
        ChatMessage.objects.select_related("conversation"),
        id=message_id,
    )

    if not user_is_conversation_member(request.user, message.conversation):
        return Response({"detail": "Nemáš prístup k tejto správe."}, status=403)

    serializer = ToggleReactionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    emoji = serializer.validated_data["emoji"]

    existing = ChatMessageReaction.objects.filter(
        message=message,
        user=request.user,
        emoji=emoji,
    ).first()

    if existing:
        existing.delete()
        message = get_message_for_realtime(message.id)
        broadcast_message_updated(message, request)
        return Response({"deleted": True})

    reaction = ChatMessageReaction.objects.create(
        message=message,
        user=request.user,
        emoji=emoji,
    )
    message = get_message_for_realtime(message.id)
    broadcast_message_updated(message, request)

    return Response({
        "id": reaction.id,
        "message": message.id,
        "user": request.user.id,
        "emoji": reaction.emoji,
        "created_at": reaction.created_at,
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def vote_poll(request, poll_id):
    poll = get_object_or_404(
        ChatPoll.objects
        .select_related("message__conversation")
        .prefetch_related("options__votes__user"),
        id=poll_id,
    )
    conversation = poll.message.conversation

    if not user_is_conversation_member(request.user, conversation):
        return Response({"detail": "Nemáš prístup k tejto ankete."}, status=403)

    if poll.is_closed:
        return Response({"detail": "Anketa je už uzavretá."}, status=400)

    serializer = VotePollSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    option_ids = serializer.validated_data["option_ids"]
    valid_option_ids = set(poll.options.values_list("id", flat=True))

    if any(option_id not in valid_option_ids for option_id in option_ids):
        return Response({"detail": "Neplatná možnosť ankety."}, status=400)

    if not poll.allow_multiple and len(option_ids) > 1:
        return Response({"detail": "V tejto ankete môžeš vybrať iba jednu možnosť."}, status=400)

    with transaction.atomic():
        ChatPollVote.objects.filter(
            option__poll=poll,
            user=request.user,
        ).exclude(option_id__in=option_ids).delete()

        for option_id in option_ids:
            ChatPollVote.objects.get_or_create(
                option_id=option_id,
                user=request.user,
            )

    poll = (
        ChatPoll.objects
        .select_related("created_by", "message")
        .prefetch_related("options__votes__user")
        .get(id=poll.id)
    )
    message = get_message_for_realtime(poll.message_id)
    broadcast_message_updated(message, request)
    return Response(ChatPollSerializer(poll, context={"request": request}).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_message(request, message_id):
    message = get_object_or_404(ChatMessage, id=message_id)

    if message.sender_id != request.user.id:
        return Response({"detail": "Môžeš zmazať iba vlastnú správu."}, status=403)

    message.soft_delete()
    message = get_message_for_realtime(message.id)
    broadcast_message_updated(message, request)

    return Response({"success": True})
