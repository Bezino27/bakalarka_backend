from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import Category, Club, Role, Training, UserCategoryRole


User = get_user_model()
API_PREFIX = "/api"


class ApiSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.club_a = Club.objects.create(name="Club A")
        self.club_b = Club.objects.create(name="Club B")

        self.category_a = Category.objects.create(club=self.club_a, name="U15")
        self.category_b = Category.objects.create(club=self.club_b, name="U17")

        self.player = User.objects.create_user(
            username="player",
            password="pass12345",
            club=self.club_a,
        )
        UserCategoryRole.objects.create(
            user=self.player,
            category=self.category_a,
            role=Role.PLAYER,
        )

        self.coach_a = User.objects.create_user(
            username="coach_a",
            password="pass12345",
            club=self.club_a,
        )
        UserCategoryRole.objects.create(
            user=self.coach_a,
            category=self.category_a,
            role=Role.COACH,
        )

        self.coach_b = User.objects.create_user(
            username="coach_b",
            password="pass12345",
            club=self.club_b,
        )
        UserCategoryRole.objects.create(
            user=self.coach_b,
            category=self.category_b,
            role=Role.COACH,
        )

        self.training_a = Training.objects.create(
            club=self.club_a,
            category=self.category_a,
            created_by=self.coach_a,
            date=timezone.now() + timezone.timedelta(days=1),
            description="Training A",
            location="Hall A",
        )
        self.training_b = Training.objects.create(
            club=self.club_b,
            category=self.category_b,
            created_by=self.coach_b,
            date=timezone.now() + timezone.timedelta(days=2),
            description="Training B",
            location="Hall B",
        )

    def test_anonymous_user_cannot_access_protected_endpoints(self):
        protected_urls = [
            "/me/",
            "/player-trainings/",
            "/trainings/",
            f"/trainings/{self.training_a.id}/",
            "/categories-in-club/",
            "/users-in-club/",
        ]

        for url in protected_urls:
            response = self.client.get(f"{API_PREFIX}{url}")
            self.assertIn(
                response.status_code,
                (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED),
                msg=f"{url} returned {response.status_code}",
            )

    def test_player_cannot_create_training(self):
        self.client.force_authenticate(self.player)

        response = self.client.post(
            f"{API_PREFIX}/trainings/",
            {
                "category_ids": [self.category_a.id],
                "date": (timezone.now() + timezone.timedelta(days=3)).isoformat(),
                "description": "Player-created training",
                "location": "Hall A",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_player_cannot_update_training(self):
        self.client.force_authenticate(self.player)

        response = self.client.put(
            f"{API_PREFIX}/trainings/{self.training_a.id}/",
            {
                "date": self.training_a.date.isoformat(),
                "description": "Changed by player",
                "location": "Hall A",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_update_training_from_other_category_or_club(self):
        self.client.force_authenticate(self.coach_a)

        response = self.client.put(
            f"{API_PREFIX}/trainings/{self.training_b.id}/",
            {
                "date": self.training_b.date.isoformat(),
                "description": "Changed by foreign coach",
                "location": "Hall B",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_cannot_load_other_club_categories(self):
        self.client.force_authenticate(self.coach_a)

        response = self.client.get(f"{API_PREFIX}/categories/{self.club_b.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_basic_endpoints_return_expected_status_codes(self):
        self.client.force_authenticate(self.coach_a)

        expected = {
            f"{API_PREFIX}/me/": status.HTTP_200_OK,
            f"{API_PREFIX}/categories-in-club/": status.HTTP_200_OK,
            f"{API_PREFIX}/player-trainings/": status.HTTP_200_OK,
            f"{API_PREFIX}/trainings/{self.training_a.id}/": status.HTTP_200_OK,
        }

        for url, expected_status in expected.items():
            response = self.client.get(url)
            self.assertEqual(response.status_code, expected_status, msg=url)
