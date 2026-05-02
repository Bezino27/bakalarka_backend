from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import IsSuperUserOnly
from .models import (
    Club,
    Category,
    UserCategoryRole,
    Training,
    TrainingAttendance,
    Match,
    MatchParticipation,
    MemberPayment,
    Order,
)

User = get_user_model()


# =============================================================================
# HELPERS
# =============================================================================

def decimal_to_str(value):
    if value is None:
        return "0.00"

    if isinstance(value, Decimal):
        return str(value)

    return str(value)


def user_full_name(user):
    if not user:
        return ""

    return f"{user.first_name} {user.last_name}".strip() or user.username


def serialize_club(club):
    users_count = User.objects.filter(club=club).count()
    categories_count = Category.objects.filter(club=club).count()
    trainings_count = Training.objects.filter(club=club).count()
    matches_count = Match.objects.filter(club=club).count()

    return {
        "id": club.id,
        "name": club.name,
        "description": club.description,
        "address": club.address,
        "phone": club.phone,
        "email": club.email,
        "contact_person": club.contact_person,
        "iban": club.iban,
        "vote_lock_days": club.vote_lock_days,
        "training_lock_hours": club.training_lock_hours,
        "users_count": users_count,
        "categories_count": categories_count,
        "trainings_count": trainings_count,
        "matches_count": matches_count,
    }


def serialize_user(user):
    roles = UserCategoryRole.objects.filter(user=user).select_related("category")

    return {
        "id": user.id,
        "username": user.username,
        "name": user_full_name(user),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "email_2": getattr(user, "email_2", ""),
        "birth_date": user.birth_date,
        "number": getattr(user, "number", ""),
        "preferred_role": getattr(user, "preferred_role", None),
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "date_joined": user.date_joined,
        "club": {
            "id": user.club.id,
            "name": user.club.name,
        } if getattr(user, "club", None) else None,
        "roles": [
            {
                "role": role.role,
                "category_id": role.category.id if role.category else None,
                "category_name": role.category.name if role.category else None,
            }
            for role in roles
        ],
    }


def serialize_member_payment(payment):
    return {
        "id": payment.id,
        "amount": decimal_to_str(payment.amount),
        "cycle": payment.cycle,
        "period_start": payment.period_start,
        "period_end": payment.period_end,
        "due_date": payment.due_date,
        "is_paid": payment.is_paid,
        "description": payment.description,
        "variable_symbol": payment.variable_symbol,
        "club": {
            "id": payment.club.id,
            "name": payment.club.name,
        } if payment.club else None,
        "user": {
            "id": payment.user.id,
            "name": user_full_name(payment.user),
            "username": payment.user.username,
            "email": payment.user.email,
        } if payment.user else None,
    }


def serialize_order(order):
    return {
        "id": order.id,
        "created_at": order.created_at,
        "status": order.status,
        "total_amount": decimal_to_str(order.total_amount),
        "is_paid": getattr(order, "is_paid", False),
        "note": getattr(order, "note", ""),
        "club": {
            "id": order.club.id,
            "name": order.club.name,
        } if getattr(order, "club", None) else None,
        "user": {
            "id": order.user.id,
            "name": user_full_name(order.user),
            "username": order.user.username,
            "email": order.user.email,
        } if getattr(order, "user", None) else None,
    }


def serialize_training_usage(training):
    players_count = (
        UserCategoryRole.objects
        .filter(category=training.category, role="player")
        .values("user_id")
        .distinct()
        .count()
    )

    present_count = TrainingAttendance.objects.filter(
        training=training,
        status="present",
    ).count()

    absent_count = TrainingAttendance.objects.filter(
        training=training,
        status="absent",
    ).count()

    unknown_count = max(players_count - present_count - absent_count, 0)

    attendance_percent = 0
    if players_count > 0:
        attendance_percent = round((present_count / players_count) * 100, 1)

    return {
        "id": training.id,
        "description": training.description,
        "date": training.date,
        "location": training.location,
        "category": {
            "id": training.category.id,
            "name": training.category.name,
        } if training.category else None,
        "club": {
            "id": training.club.id,
            "name": training.club.name,
        } if training.club else None,
        "players_count": players_count,
        "present_count": present_count,
        "absent_count": absent_count,
        "unknown_count": unknown_count,
        "attendance_percent": attendance_percent,
        "created_by": user_full_name(training.created_by) if training.created_by else None,
    }


def serialize_match_usage(match):
    players_count = (
        UserCategoryRole.objects
        .filter(category=match.category, role="player")
        .values("user_id")
        .distinct()
        .count()
    )

    participation_count = MatchParticipation.objects.filter(match=match).count()

    confirmed_count = MatchParticipation.objects.filter(
        match=match,
        confirmed=True,
    ).count()

    declined_count = MatchParticipation.objects.filter(
        match=match,
        confirmed=False,
    ).count()

    return {
        "id": match.id,
        "date": match.date,
        "location": match.location,
        "opponent": match.opponent,
        "description": match.description,
        "is_home": getattr(match, "is_home", None),
        "category": {
            "id": match.category.id,
            "name": match.category.name,
        } if match.category else None,
        "club": {
            "id": match.club.id,
            "name": match.club.name,
        } if match.club else None,
        "players_count": players_count,
        "participation_count": participation_count,
        "confirmed_count": confirmed_count,
        "declined_count": declined_count,
    }


# =============================================================================
# OVERVIEW
# =============================================================================

@api_view(["GET"])
@permission_classes([IsSuperUserOnly])
def system_admin_overview(request):
    now = timezone.now()

    total_clubs = Club.objects.count()
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    inactive_users = User.objects.filter(is_active=False).count()

    total_categories = Category.objects.count()

    total_trainings = Training.objects.count()
    upcoming_trainings = Training.objects.filter(date__gte=now).count()
    past_trainings = Training.objects.filter(date__lt=now).count()
    trainings_last_30_days = Training.objects.filter(date__gte=now - timedelta(days=30)).count()

    total_matches = Match.objects.count()
    upcoming_matches = Match.objects.filter(date__gte=now).count()
    past_matches = Match.objects.filter(date__lt=now).count()
    matches_last_30_days = Match.objects.filter(date__gte=now - timedelta(days=30)).count()

    total_member_payments = MemberPayment.objects.count()
    paid_member_payments = MemberPayment.objects.filter(is_paid=True).count()
    unpaid_member_payments = MemberPayment.objects.filter(is_paid=False).count()

    total_member_payment_amount = MemberPayment.objects.aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    paid_member_payment_amount = MemberPayment.objects.filter(
        is_paid=True
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    unpaid_member_payment_amount = MemberPayment.objects.filter(
        is_paid=False
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    total_orders = Order.objects.count()
    paid_orders = Order.objects.filter(is_paid=True).count()
    unpaid_orders = Order.objects.filter(is_paid=False).count()

    latest_users = (
        User.objects
        .select_related("club")
        .order_by("-date_joined")[:8]
    )

    latest_payments = (
        MemberPayment.objects
        .select_related("user", "club")
        .order_by("-id")[:8]
    )

    latest_orders = (
        Order.objects
        .select_related("user", "club")
        .order_by("-created_at")[:8]
    )

    clubs = Club.objects.all().order_by("name")[:10]

    return Response({
        "summary": {
            "total_clubs": total_clubs,

            "total_users": total_users,
            "active_users": active_users,
            "inactive_users": inactive_users,

            "total_categories": total_categories,

            "total_trainings": total_trainings,
            "upcoming_trainings": upcoming_trainings,
            "past_trainings": past_trainings,
            "trainings_last_30_days": trainings_last_30_days,

            "total_matches": total_matches,
            "upcoming_matches": upcoming_matches,
            "past_matches": past_matches,
            "matches_last_30_days": matches_last_30_days,

            "total_member_payments": total_member_payments,
            "paid_member_payments": paid_member_payments,
            "unpaid_member_payments": unpaid_member_payments,
            "total_member_payment_amount": decimal_to_str(total_member_payment_amount),
            "paid_member_payment_amount": decimal_to_str(paid_member_payment_amount),
            "unpaid_member_payment_amount": decimal_to_str(unpaid_member_payment_amount),

            "total_orders": total_orders,
            "paid_orders": paid_orders,
            "unpaid_orders": unpaid_orders,
        },
        "latest_users": [serialize_user(user) for user in latest_users],
        "latest_payments": [serialize_member_payment(payment) for payment in latest_payments],
        "latest_orders": [serialize_order(order) for order in latest_orders],
        "clubs": [serialize_club(club) for club in clubs],
    })


# =============================================================================
# CLUBS
# =============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsSuperUserOnly])
def system_admin_clubs(request):
    if request.method == "GET":
        search = request.GET.get("search", "").strip()

        qs = Club.objects.all().order_by("name")

        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(contact_person__icontains=search)
            )

        return Response([serialize_club(club) for club in qs])

    name = (request.data.get("name") or "").strip()

    if not name:
        return Response(
            {"detail": "Názov klubu je povinný."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    club = Club.objects.create(
        name=name,
        description=request.data.get("description", ""),
        address=request.data.get("address", ""),
        phone=request.data.get("phone", ""),
        email=request.data.get("email", ""),
        contact_person=request.data.get("contact_person", ""),
        iban=request.data.get("iban", ""),
        vote_lock_days=request.data.get("vote_lock_days", 2) or 2,
        training_lock_hours=request.data.get("training_lock_hours", 2) or 2,
    )

    return Response(serialize_club(club), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperUserOnly])
def system_admin_club_detail(request, club_id):
    club = get_object_or_404(Club, id=club_id)

    if request.method == "GET":
        return Response(serialize_club(club))

    if request.method == "PATCH":
        allowed_fields = [
            "name",
            "description",
            "address",
            "phone",
            "email",
            "contact_person",
            "iban",
            "vote_lock_days",
            "training_lock_hours",
        ]

        for field in allowed_fields:
            if field in request.data:
                setattr(club, field, request.data.get(field))

        club.save()
        return Response(serialize_club(club))

    club.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# USERS
# =============================================================================

@api_view(["GET"])
@permission_classes([IsSuperUserOnly])
def system_admin_users(request):
    search = request.GET.get("search", "").strip()
    user_id = request.GET.get("id", "").strip()
    club_id = request.GET.get("club_id", "").strip()
    role = request.GET.get("role", "").strip()
    active = request.GET.get("active", "").strip()
    registered_from = request.GET.get("registered_from", "").strip()
    registered_to = request.GET.get("registered_to", "").strip()
    ordering = request.GET.get("ordering", "-date_joined").strip()
    limit = request.GET.get("limit", "300").strip()

    qs = User.objects.select_related("club").order_by("-date_joined")

    if user_id:
        try:
            qs = qs.filter(id=int(user_id))
        except ValueError:
            return Response(
                {"detail": "ID používateľa musí byť číslo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )

    if club_id:
        try:
            qs = qs.filter(club_id=int(club_id))
        except ValueError:
            return Response(
                {"detail": "club_id musí byť číslo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if role:
        qs = qs.filter(roles__role=role).distinct()

    if active == "true":
        qs = qs.filter(is_active=True)
    elif active == "false":
        qs = qs.filter(is_active=False)

    if registered_from:
        qs = qs.filter(date_joined__date__gte=registered_from)

    if registered_to:
        qs = qs.filter(date_joined__date__lte=registered_to)

    allowed_ordering = {
        "id",
        "-id",
        "username",
        "-username",
        "first_name",
        "-first_name",
        "last_name",
        "-last_name",
        "date_joined",
        "-date_joined",
        "club__name",
        "-club__name",
    }

    if ordering not in allowed_ordering:
        ordering = "-date_joined"

    qs = qs.order_by(ordering)

    try:
        limit_int = int(limit)
    except ValueError:
        limit_int = 300

    limit_int = min(max(limit_int, 1), 1000)

    return Response({
        "count": qs.count(),
        "results": [serialize_user(user) for user in qs[:limit_int]],
    })


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsSuperUserOnly])
def system_admin_user_detail(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == "GET":
        return Response(serialize_user(user))

    if request.method == "PATCH":
        allowed_fields = [
            "first_name",
            "last_name",
            "email",
            "email_2",
            "birth_date",
            "number",
            "preferred_role",
            "is_active",
            "is_staff",
        ]

        for field in allowed_fields:
            if field in request.data:
                setattr(user, field, request.data.get(field))

        if "club_id" in request.data:
            club_id = request.data.get("club_id")

            if club_id:
                user.club = get_object_or_404(Club, id=club_id)
            else:
                user.club = None

        # is_superuser zámerne nemeníme cez API.
        # Je to bezpečnejšie, aby si si náhodou nevyrobil problém.
        user.save()

        return Response(serialize_user(user))

    if user.id == request.user.id:
        return Response(
            {"detail": "Nemôžeš vymazať sám seba."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# MEMBER PAYMENTS
# =============================================================================

@api_view(["GET"])
@permission_classes([IsSuperUserOnly])
def system_admin_member_payments(request):
    search = request.GET.get("search", "").strip()
    club_id = request.GET.get("club_id", "").strip()
    is_paid = request.GET.get("is_paid", "").strip()

    qs = (
        MemberPayment.objects
        .select_related("user", "club")
        .order_by("-period_start", "-due_date", "user__last_name")
    )

    if search:
        qs = qs.filter(
            Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(variable_symbol__icontains=search)
            | Q(description__icontains=search)
        )

    if club_id:
        qs = qs.filter(club_id=club_id)

    if is_paid == "true":
        qs = qs.filter(is_paid=True)
    elif is_paid == "false":
        qs = qs.filter(is_paid=False)

    return Response([serialize_member_payment(payment) for payment in qs[:500]])


@api_view(["PATCH"])
@permission_classes([IsSuperUserOnly])
def system_admin_member_payment_detail(request, payment_id):
    payment = get_object_or_404(MemberPayment, id=payment_id)

    allowed_fields = [
        "amount",
        "cycle",
        "period_start",
        "period_end",
        "due_date",
        "is_paid",
        "description",
        "variable_symbol",
    ]

    for field in allowed_fields:
        if field in request.data:
            setattr(payment, field, request.data.get(field))

    payment.save()
    return Response(serialize_member_payment(payment))


# =============================================================================
# ORDERS
# =============================================================================

@api_view(["GET"])
@permission_classes([IsSuperUserOnly])
def system_admin_orders(request):
    search = request.GET.get("search", "").strip()
    club_id = request.GET.get("club_id", "").strip()
    status_param = request.GET.get("status", "").strip()
    is_paid = request.GET.get("is_paid", "").strip()

    qs = (
        Order.objects
        .select_related("user", "club")
        .order_by("-created_at")
    )

    if search:
        qs = qs.filter(
            Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(status__icontains=search)
        )

    if club_id:
        qs = qs.filter(club_id=club_id)

    if status_param:
        qs = qs.filter(status=status_param)

    if is_paid == "true":
        qs = qs.filter(is_paid=True)
    elif is_paid == "false":
        qs = qs.filter(is_paid=False)

    return Response([serialize_order(order) for order in qs[:500]])


@api_view(["PATCH"])
@permission_classes([IsSuperUserOnly])
def system_admin_order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    allowed_fields = [
        "status",
        "total_amount",
        "is_paid",
        "note",
    ]

    for field in allowed_fields:
        if field in request.data and hasattr(order, field):
            setattr(order, field, request.data.get(field))

    order.save()
    return Response(serialize_order(order))


# =============================================================================
# CLUB USAGE / MONITORING
# =============================================================================

@api_view(["GET"])
@permission_classes([IsSuperUserOnly])
def system_admin_club_usage(request):
    search = request.GET.get("search", "").strip()
    club_id = request.GET.get("club_id", "").strip()

    now = timezone.now()
    last_30_days = now - timedelta(days=30)
    last_90_days = now - timedelta(days=90)

    clubs_qs = Club.objects.all().order_by("name")

    if search:
        clubs_qs = clubs_qs.filter(
            Q(name__icontains=search)
            | Q(email__icontains=search)
            | Q(contact_person__icontains=search)
        )

    if club_id:
        try:
            clubs_qs = clubs_qs.filter(id=int(club_id))
        except ValueError:
            return Response(
                {"detail": "club_id musí byť číslo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    result = []

    for club in clubs_qs:
        users_qs = User.objects.filter(club=club)
        active_users_qs = users_qs.filter(is_active=True)

        categories_qs = Category.objects.filter(club=club)

        roles_qs = UserCategoryRole.objects.filter(user__club=club)

        players_count = roles_qs.filter(role="player").values("user_id").distinct().count()
        coaches_count = roles_qs.filter(role="coach").values("user_id").distinct().count()
        admins_count = roles_qs.filter(role="admin").values("user_id").distinct().count()
        parents_count = roles_qs.filter(role="parent").values("user_id").distinct().count()

        trainings_qs = (
            Training.objects
            .filter(club=club)
            .select_related("category", "club", "created_by")
            .order_by("-date")
        )

        matches_qs = (
            Match.objects
            .filter(club=club)
            .select_related("category", "club")
            .order_by("-date")
        )

        member_payments_qs = MemberPayment.objects.filter(club=club)

        total_trainings = trainings_qs.count()
        trainings_last_30_days = trainings_qs.filter(date__gte=last_30_days).count()
        trainings_last_90_days = trainings_qs.filter(date__gte=last_90_days).count()

        total_matches = matches_qs.count()
        matches_last_30_days = matches_qs.filter(date__gte=last_30_days).count()
        matches_last_90_days = matches_qs.filter(date__gte=last_90_days).count()

        total_member_payments = member_payments_qs.count()
        unpaid_member_payments = member_payments_qs.filter(is_paid=False).count()
        paid_member_payments = member_payments_qs.filter(is_paid=True).count()

        unpaid_amount = member_payments_qs.filter(is_paid=False).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        paid_amount = member_payments_qs.filter(is_paid=True).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        last_training = trainings_qs.first()
        last_match = matches_qs.first()
        last_user = users_qs.order_by("-date_joined").first()

        recent_trainings = [
            serialize_training_usage(training)
            for training in trainings_qs[:15]
        ]

        recent_matches = [
            serialize_match_usage(match)
            for match in matches_qs[:5]
        ]

        status_value = "ok"
        status_label = "Aktívny klub"

        if users_qs.count() == 0:
            status_value = "empty"
            status_label = "Bez používateľov"
        elif total_trainings == 0 and total_matches == 0:
            status_value = "warning"
            status_label = "Zatiaľ bez tréningov a zápasov"
        elif trainings_last_30_days == 0 and matches_last_30_days == 0:
            status_value = "inactive"
            status_label = "Bez aktivity za posledných 30 dní"
        elif unpaid_member_payments >= 10:
            status_value = "warning"
            status_label = "Veľa neuhradených platieb"

        result.append({
            "club": {
                "id": club.id,
                "name": club.name,
                "email": club.email,
                "phone": club.phone,
                "contact_person": club.contact_person,
                "iban": club.iban,
            },
            "status": {
                "value": status_value,
                "label": status_label,
            },
            "summary": {
                "users_count": users_qs.count(),
                "active_users_count": active_users_qs.count(),
                "categories_count": categories_qs.count(),

                "players_count": players_count,
                "coaches_count": coaches_count,
                "admins_count": admins_count,
                "parents_count": parents_count,

                "total_trainings": total_trainings,
                "trainings_last_30_days": trainings_last_30_days,
                "trainings_last_90_days": trainings_last_90_days,

                "total_matches": total_matches,
                "matches_last_30_days": matches_last_30_days,
                "matches_last_90_days": matches_last_90_days,

                "total_member_payments": total_member_payments,
                "paid_member_payments": paid_member_payments,
                "unpaid_member_payments": unpaid_member_payments,
                "paid_amount": decimal_to_str(paid_amount),
                "unpaid_amount": decimal_to_str(unpaid_amount),
            },
            "last_activity": {
                "last_training_date": last_training.date if last_training else None,
                "last_match_date": last_match.date if last_match else None,
                "last_user_joined": last_user.date_joined if last_user else None,
            },
            "recent_trainings": recent_trainings,
            "recent_matches": recent_matches,
        })

    return Response(result)