from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from dochadzka_app.models import Category, Club, Role, UserCategoryRole

from .models import (
    ChatConversation,
    ChatConversationMember,
    ChatMessage,
    ChatMessageReaction,
    ChatPoll,
    ChatPollVote,
)


User = get_user_model()


class ChatApiTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Ludimus")
        self.other_club = Club.objects.create(name="Iny klub")
        self.category = Category.objects.create(name="U10", club=self.club)

        self.user = User.objects.create_user(
            username="adam",
            password="test",
            first_name="Adam",
            last_name="Novak",
            club=self.club,
        )
        self.friend = User.objects.create_user(
            username="samuel",
            password="test",
            first_name="Samuel",
            last_name="Novak",
            club=self.club,
        )
        self.group_member = User.objects.create_user(
            username="tomas",
            password="test",
            first_name="Tomas",
            last_name="Kovac",
            club=self.club,
        )
        self.outsider = User.objects.create_user(
            username="outsider",
            password="test",
            first_name="Out",
            last_name="Sider",
            club=self.club,
        )
        self.other_club_user = User.objects.create_user(
            username="mimo",
            password="test",
            first_name="Mimo",
            last_name="Klub",
            club=self.other_club,
        )
        UserCategoryRole.objects.create(
            user=self.user,
            category=self.category,
            role=Role.COACH,
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_direct(self):
        return self.client.post(
            "/api/chat/conversations/direct/",
            {"user_id": self.friend.id},
            format="json",
        )

    def test_direct_conversation_between_same_club_users_is_created(self):
        response = self.create_direct()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["type"], ChatConversation.DIRECT)
        self.assertEqual(ChatConversation.objects.count(), 1)
        self.assertEqual(
            ChatConversationMember.objects.filter(conversation_id=response.data["id"]).count(),
            2,
        )

    def test_repeated_direct_conversation_does_not_create_duplicate(self):
        first_response = self.create_direct()
        second_response = self.create_direct()

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.data["id"], second_response.data["id"])
        self.assertEqual(ChatConversation.objects.filter(type=ChatConversation.DIRECT).count(), 1)

    def test_direct_conversation_with_user_from_other_club_is_rejected(self):
        response = self.client.post(
            "/api/chat/conversations/direct/",
            {"user_id": self.other_club_user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatConversation.objects.count(), 0)

    def test_group_conversation_is_created(self):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["type"], ChatConversation.GROUP)
        self.assertEqual(response.data["name"], "Rodicia U10")
        self.assertEqual(
            ChatConversationMember.objects.filter(conversation_id=response.data["id"]).count(),
            3,
        )

    def test_group_conversation_requires_coach_role(self):
        self.client.force_authenticate(self.friend)
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.user.id, self.group_member.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "Skupinový chat môže vytvoriť iba tréner.")
        self.assertEqual(ChatConversation.objects.filter(type=ChatConversation.GROUP).count(), 0)

    def test_group_members_can_be_listed_by_member(self):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )
        conversation_id = response.data["id"]

        self.client.force_authenticate(self.friend)
        members_response = self.client.get(f"/api/chat/conversations/{conversation_id}/members/")

        self.assertEqual(members_response.status_code, 200)
        self.assertEqual(len(members_response.data), 3)

    def test_group_admin_can_update_members(self):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )
        conversation_id = response.data["id"]

        update_response = self.client.patch(
            f"/api/chat/conversations/{conversation_id}/members/",
            {"member_ids": [self.friend.id, self.outsider.id]},
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        member_ids = set(
            ChatConversationMember.objects
            .filter(conversation_id=conversation_id)
            .values_list("user_id", flat=True)
        )
        self.assertEqual(member_ids, {self.user.id, self.friend.id, self.outsider.id})

    def test_non_admin_group_member_cannot_update_members(self):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )
        conversation_id = response.data["id"]

        self.client.force_authenticate(self.friend)
        update_response = self.client.patch(
            f"/api/chat/conversations/{conversation_id}/members/",
            {"member_ids": [self.group_member.id]},
            format="json",
        )

        self.assertEqual(update_response.status_code, 403)

    @patch("chat.views.notify_new_chat_message.delay")
    def test_group_member_can_create_poll_and_vote(self, notify_delay):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )
        conversation_id = response.data["id"]

        self.client.force_authenticate(self.friend)
        poll_response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/polls/",
            {
                "question": "Kto môže v piatok?",
                "options": ["Môžem", "Nemôžem"],
                "allow_multiple": False,
            },
            format="json",
        )

        self.assertEqual(poll_response.status_code, 201)
        notify_delay.assert_called_once()
        self.assertEqual(poll_response.data["poll"]["question"], "Kto môže v piatok?")
        self.assertEqual(len(poll_response.data["poll"]["options"]), 2)
        self.assertEqual(ChatPoll.objects.count(), 1)

        option_id = poll_response.data["poll"]["options"][0]["id"]
        vote_response = self.client.post(
            f"/api/chat/polls/{poll_response.data['poll']['id']}/vote/",
            {"option_ids": [option_id]},
            format="json",
        )

        self.assertEqual(vote_response.status_code, 200)
        self.assertEqual(vote_response.data["user_option_ids"], [option_id])
        self.assertEqual(vote_response.data["options"][0]["votes_count"], 1)
        self.assertEqual(ChatPollVote.objects.count(), 1)

    def test_direct_conversation_cannot_create_poll(self):
        conversation_id = self.create_direct().data["id"]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/polls/",
            {
                "question": "Toto má zlyhať?",
                "options": ["Áno", "Nie"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Ankety sa dajú vytvárať iba v skupinovom chate.")

    @patch("chat.views.notify_new_chat_message.delay")
    def test_poll_vote_rejects_outsider(self, notify_delay):
        response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Rodicia U10", "member_ids": [self.friend.id]},
            format="json",
        )
        conversation_id = response.data["id"]
        poll_response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/polls/",
            {
                "question": "Kto príde?",
                "options": ["Áno", "Nie"],
            },
            format="json",
        )
        poll_id = poll_response.data["poll"]["id"]
        option_id = poll_response.data["poll"]["options"][0]["id"]

        self.client.force_authenticate(self.outsider)
        vote_response = self.client.post(
            f"/api/chat/polls/{poll_id}/vote/",
            {"option_ids": [option_id]},
            format="json",
        )

        self.assertEqual(vote_response.status_code, 403)

    @patch("chat.views.notify_new_chat_message.delay")
    def test_group_members_can_see_messages_and_outsider_cannot_access(self, notify_delay):
        group_response = self.client.post(
            "/api/chat/conversations/group/",
            {"name": "Tim", "member_ids": [self.friend.id, self.group_member.id]},
            format="json",
        )
        conversation_id = group_response.data["id"]

        message_response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Ahojte"},
            format="json",
        )
        self.assertEqual(message_response.status_code, 201)
        notify_delay.assert_called_once()

        self.client.force_authenticate(self.friend)
        member_response = self.client.get(f"/api/chat/conversations/{conversation_id}/messages/")
        self.assertEqual(member_response.status_code, 200)
        self.assertEqual(len(member_response.data["results"]), 1)
        self.assertEqual(member_response.data["results"][0]["text"], "Ahojte")

        self.client.force_authenticate(self.outsider)
        outsider_response = self.client.get(f"/api/chat/conversations/{conversation_id}/messages/")
        self.assertEqual(outsider_response.status_code, 403)

    @patch("chat.views.notify_new_chat_message.delay")
    def test_send_message_and_client_message_id_prevents_duplicate(self, notify_delay):
        conversation_id = self.create_direct().data["id"]

        first_response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Cau", "client_message_id": "mobile-1"},
            format="json",
        )
        second_response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Cau este raz", "client_message_id": "mobile-1"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.data["id"], second_response.data["id"])
        self.assertEqual(ChatMessage.objects.filter(conversation_id=conversation_id).count(), 1)
        notify_delay.assert_called_once()

    @patch("chat.views.notify_new_chat_message.delay")
    def test_messages_support_cursor_pagination(self, notify_delay):
        conversation_id = self.create_direct().data["id"]

        for index in range(5):
            self.client.post(
                f"/api/chat/conversations/{conversation_id}/messages/",
                {"text": f"Sprava {index}"},
                format="json",
            )

        response = self.client.get(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"limit": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limit"], 2)
        self.assertTrue(response.data["has_more"])
        self.assertEqual([item["text"] for item in response.data["results"]], ["Sprava 3", "Sprava 4"])

        next_response = self.client.get(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {
                "limit": 2,
                "before_message_id": response.data["next_before_message_id"],
            },
        )

        self.assertEqual(next_response.status_code, 200)
        self.assertEqual([item["text"] for item in next_response.data["results"]], ["Sprava 1", "Sprava 2"])

    def test_messages_reject_invalid_cursor_params(self):
        conversation_id = self.create_direct().data["id"]

        limit_response = self.client.get(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"limit": "vela"},
        )
        cursor_response = self.client.get(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"before_message_id": "nula"},
        )

        self.assertEqual(limit_response.status_code, 400)
        self.assertEqual(limit_response.data["detail"], "Parameter limit musí byť číslo.")

        self.assertEqual(cursor_response.status_code, 400)
        self.assertEqual(cursor_response.data["detail"], "Parameter before_message_id musí byť číslo.")

    @patch("chat.views.notify_new_chat_message.delay")
    def test_mark_conversation_read_sets_last_read_at(self, notify_delay):
        conversation_id = self.create_direct().data["id"]

        self.client.force_authenticate(self.friend)
        self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Neprecitana"},
            format="json",
        )

        self.client.force_authenticate(self.user)
        before = timezone.now()
        response = self.client.post(f"/api/chat/conversations/{conversation_id}/read/")

        self.assertEqual(response.status_code, 200)
        membership = ChatConversationMember.objects.get(
            conversation_id=conversation_id,
            user=self.user,
        )
        self.assertIsNotNone(membership.last_read_at)
        self.assertGreaterEqual(membership.last_read_at, before)

    @patch("chat.views.notify_new_chat_message.delay")
    def test_reactions_toggle_on_and_off(self, notify_delay):
        conversation_id = self.create_direct().data["id"]
        message_id = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Super"},
            format="json",
        ).data["id"]

        create_response = self.client.post(
            f"/api/chat/messages/{message_id}/reactions/",
            {"emoji": "👍"},
            format="json",
        )
        delete_response = self.client.post(
            f"/api/chat/messages/{message_id}/reactions/",
            {"emoji": "👍"},
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.data["deleted"], True)
        self.assertEqual(ChatMessageReaction.objects.count(), 0)

    @patch("chat.views.notify_new_chat_message.delay")
    def test_delete_message_is_soft_delete(self, notify_delay):
        conversation_id = self.create_direct().data["id"]
        message_id = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/",
            {"text": "Zmaz ma"},
            format="json",
        ).data["id"]

        response = self.client.delete(f"/api/chat/messages/{message_id}/")
        self.assertEqual(response.status_code, 200)

        message = ChatMessage.objects.get(id=message_id)
        self.assertEqual(message.text, "")
        self.assertIsNotNone(message.deleted_at)
        self.assertTrue(message.is_deleted)
