from rest_framework.permissions import BasePermission


class IsSuperUserOnly(BasePermission):
    """
    Povoliť prístup iba prihlásenému superuserovi.
    Toto je tvoj hlavný systémový admin, nie klubový admin.
    """

    message = "Prístup má iba systémový administrátor."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )