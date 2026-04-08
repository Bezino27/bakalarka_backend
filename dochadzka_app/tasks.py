# tasks.py
from celery import shared_task
from .models import Training,JerseyOrder
from .models import User, Role
from .helpers import send_push_notification  # uprav podľa tvojej štruktúry
from .models import ExpoPushToken  # uprav podľa tvojej štruktúry
import logging
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import (
    Training,
    TrainingAttendance,
    CategoryVoteReminderSetting,
    TrainingVoteReminder,
    ExpoPushToken,
    User,
    Role,
)


logger = logging.getLogger(__name__)

@shared_task
def send_training_notifications(training_id):
    try:
        training = Training.objects.get(id=training_id)
    except Training.DoesNotExist:
        logger.warning(f"Tréning s ID {training_id} neexistuje")
        return

    players = User.objects.filter(
        roles__category=training.category,
        roles__role=Role.PLAYER
    ).distinct()

    for player in players:
        tokens = ExpoPushToken.objects.filter(user=player).values_list("token", flat=True)
        for token in tokens:
            try:
                send_push_notification(
                    token,
                    "Nový Tréning",
                    f"{training.description} - {training.date.strftime('%d.%m.%Y')} v {training.location}",
                    user_id=0,
                    user_name="tréning"
                )
                logger.info(f"Push pre {player.username} → {token}")
            except Exception as e:
                logger.warning(f"Chyba pri push pre {player.username} → {token}: {str(e)}")


@shared_task
def notify_training_deleted(training_id, training_description, category_id):
    from .models import User, Role, ExpoPushToken, Category

    try:
        category = Category.objects.get(id=category_id)
        players = User.objects.filter(
            roles__category=category,
            roles__role=Role.PLAYER
        ).distinct()

        for player in players:
            tokens = ExpoPushToken.objects.filter(user=player).values_list("token", flat=True)
            for token in tokens:
                try:
                    send_push_notification(
                        token,
                        "Zrušený tréning",
                        f"Tréning '{training_description}' bol zrušený.",
                        user_id=0,
                        user_name="tréning"
                    )
                except Exception as e:
                    logger.warning(f"Chyba pri push pre {player.username} → {token}: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Chyba pri notifikovaní o zmazaní tréningu: {str(e)}")

@shared_task
def send_match_notifications(match_id):
    from .models import Match
    match = Match.objects.get(id=match_id)

    players = User.objects.filter(
        roles__category=match.category,
        roles__role=Role.PLAYER
    ).distinct()

    for player in players:
        send_push_notification(player, f"Nový zápas: {match.opponent}", f"{match.location} ")


@shared_task
def send_training_updated_notification(training_id):
    try:
        training = Training.objects.get(id=training_id)
    except Training.DoesNotExist:
        logger.warning(f"Tréning s ID {training_id} neexistuje")
        return

    players = User.objects.filter(
        roles__category=training.category,
        roles__role=Role.PLAYER
    ).distinct()

    for player in players:
        tokens = ExpoPushToken.objects.filter(user=player).values_list("token", flat=True)
        for token in tokens:
            try:
                send_push_notification(
                    token,
                    "Zmena tréningu!",
                    f"{training.description} - {training.date.strftime('%d.%m.%Y')} v {training.location}",
                    user_id=0,
                    user_name="tréning"
                )
                logger.info(f"Notifikácia o zmene tréningu pre {player.username} → {token}")
            except Exception as e:
                logger.warning(f"Chyba pri notifikácii pre {player.username} → {token}: {str(e)}")


# dochadzka_app/tasks.py
from celery import shared_task
from .models import Match, MatchNomination, ExpoPushToken, User
from .helpers import send_push_notification
from django.utils.timezone import localtime

def get_tokens(users):
    return ExpoPushToken.objects.filter(user__in=users).values_list("token", flat=True)

from celery import shared_task
from django.utils.timezone import localtime
from .models import Match, User

@shared_task(bind=True, max_retries=3, default_retry_delay=2)
def notify_match_created(self, match_id):
    try:
        match = Match.objects.get(id=match_id)
        users = User.objects.filter(
            roles__category=match.category,
            roles__role='player',
            club=match.club
        ).distinct()
        tokens = get_tokens(users)

        date_str = localtime(match.date).strftime("%d.%m.%Y")
        for token in tokens:
            send_push_notification(
                token,
                title="Nový zápas",
                message=f"Proti {match.opponent} – {date_str} – {match.location}",
                data={"type": "match", "match_id": match.id}
            )
    except Match.DoesNotExist as e:
        print(f"❌ Zápas {match_id} zatiaľ neexistuje, retry...")
        raise self.retry(exc=e)
    except Exception as e:
        print(f"❌ notify_match_created: {e}")
@shared_task
def notify_match_updated(match_id):
    try:
        match = Match.objects.get(id=match_id)

        # 🔁 Všetci hráči s rolou 'player' v danej kategórii a klube
        users = User.objects.filter(
            roles__category=match.category,
            roles__role='player',
            club=match.club
        ).distinct()

        tokens = get_tokens(users)

        for token in tokens:
            send_push_notification(
                token,
                title="Zmena v zápase!",
                message=f"Boli zmenené údaje zápasu proti {match.opponent}, skontroluj ich!",
                data = {"type": "match", "match_id": match.id}
            )

    except Exception as e:
        print(f"❌ notify_match_updated: {e}")

@shared_task
def notify_match_deleted(opponent, category_id, club_id):
    try:
        users = User.objects.filter(
            roles__category_id=category_id,
            roles__role='player',
            club_id=club_id
        ).distinct()

        tokens = get_tokens(users)

        for token in tokens:
            send_push_notification(
                token,
                title="Zápas zrušený",
                message=f"Zápas proti {opponent} bol zrušený."
            )
    except Exception as e:
        print(f"❌ notify_match_deleted: {e}")
@shared_task
def notify_nomination_changed(match_id, user_ids):
    try:
        match = Match.objects.get(id=match_id)
        nominations = MatchNomination.objects.filter(match=match, user__id__in=user_ids).select_related('user')

        for nomination in nominations:
            token_list = get_tokens([nomination.user])
            role = "v základe" if not nomination.is_substitute else "ako náhradník"
            message = f"Bol si nominovaný na zápas proti {match.opponent} {role}."

            for token in token_list:
                send_push_notification(
                    token,
                    title="Nominácia",
                    message=message,
                    data = {"type": "match", "match_id": match.id}
                )
    except Exception as e:
        print(f"❌ notify_nomination_changed: {e}")

@shared_task
def notify_nomination_removed(match_id, user_ids):
    try:
        match = Match.objects.get(id=match_id)
        users = User.objects.filter(id__in=user_ids)
        tokens = get_tokens(users)

        for token in tokens:
            send_push_notification(
                token,
                title="Zmena v nominácii",
                message=f"Bol si odstránený z nominácie na zápas proti {match.opponent}.",
                data = {"type": "match", "match_id": match.id}
            )
    except Exception as e:
        print(f"❌ notify_nomination_removed: {e}")

@shared_task
def remind_unknown_players(training_id, user_ids):
    try:
        training = Training.objects.get(id=training_id)
        users = User.objects.filter(id__in=user_ids)

        for user in users:
            tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)
            for token in tokens:
                send_push_notification(
                    token,
                    title="Nezabudni hlasovať!",
                    message=f"Stále si nepotvrdil účasť na udalosti {training.description} ({training.date.strftime('%d.%m.%Y')})!",
                    data={"type": "training", "training_id": training.id}
                )
                logger.info(f"Pripomenutie posl. hráčovi {user.username} → {token}")

    except Exception as e:
        logger.error(f"❌ Chyba pri pripomenutí neodpovedaným: {e}")


@shared_task
def notify_match_reminder(match_id, user_ids):
    try:
        match = Match.objects.get(id=match_id)
        users = User.objects.filter(id__in=user_ids)

        for user in users:
            tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)
            for token in tokens:
                send_push_notification(
                    token=token,
                    title="Potvrď účasť na zápase",
                    message=f"Zápas proti {match.opponent} – {match.date.strftime('%d.%m.%Y')}. Nezabudni odpovedať.",
                    data={
                        "type": "match",
                        "match_id": match.id
                    }
                )
                logger.info(f"📨 Reminder na zápas poslaný hráčovi {user.username} → {token}")
    except Match.DoesNotExist:
        logger.warning(f"❌ notify_match_reminder: Match {match_id} not found")
    except Exception as e:
        logger.error(f"❌ Chyba pri pripomenutí na zápas: {e}")


@shared_task
def notify_created_member_payment(user_id, amount, due_date):
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        for token in tokens:
            send_push_notification(
                token=token,
                title="Nová platba",
                message=f"Bola ti vytvorená nová platba vo výške {amount}€ so splatnosťou do {due_date}.",
                data={"type": "payment"}
            )
            logger.info(f"Notifikácia o novej platbe → {user.username} ({token})")
    except Exception as e:
        logger.error(f"Chyba pri notifikácii novej platby: {e}")


@shared_task
def notify_payment_status(user_id, is_paid, amount=None, vs=None):
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        if is_paid:
            title = "Platba prijatá"
            message = f"Platba vo výške {amount}€ s VS {vs} bola úspešne prijatá. Ďakujeme!"
        else:
            title = "Platba chýba"
            message = "Tvoja platba zatiaľ nebola zaznamenaná. Skontroluj prosím svoje prevody."

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={"type": "payment"}
            )
            logger.info(f"Notifikácia platby ({'OK' if is_paid else 'CHÝBA'}) → {user.username} ({token})")

    except Exception as e:
        logger.error(f"Chyba pri posielaní stavu platby: {e}")

@shared_task
def notify_payment_assigned(user_id: int, amount: str, vs: str,):
    """
    Notifikácia, že používateľovi bola pridelená nová platba..
    """
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        if not tokens:
            logger.warning(f"Používateľ {user.username} nemá expo tokeny → notifikácia sa neposiela.")
            return

        title = "Nová platba"
        message = f"Bola ti vytvorená platba vo výške {amount} € (VS {vs})."

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={"type": "payment_assigned", "amount": amount, "vs": vs,},
            )
            logger.info(f"Notifikácia pridelenia platby → {user.username} ({token})")

    except Exception as e:
        logger.error(f"Chyba pri posielaní notifikácie o pridelení platby: {e}")



@shared_task
def notify_order_item_canceled(user_id: int, order_id: int, item_name: str, quantity: int, order_total: str):
    """
    Pošle používateľovi push notifikáciu, že v jeho objednávke bola zrušená položka.
    """
    try:
        user = User.objects.get(id=user_id)
        tokens = list(ExpoPushToken.objects.filter(user=user).values_list("token", flat=True))

        if not tokens:
            logger.warning(f"notify_order_item_canceled: user {user.username} nemá Expo tokeny.")
            return

        title = "Položka objednávky zrušená"
        message = (
            f"V objednávke #{order_id} bola zrušená položka {item_name} (x{quantity}). "
            f"Nový súčet objednávky: {order_total} €."
        )

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={
                    "type": "order_item_canceled",
                    "order_id": order_id,
                    "item_name": item_name,
                    "quantity": quantity,
                    "order_total": order_total,
                },
            )
            logger.info(f"Notifikácia (order_item_canceled) → {user.username} ({token})")
    except Exception as e:
        logger.error(f"Chyba notify_order_item_canceled: {e}")



@shared_task
def notify_order_paid(user_id: int, amount: str, vs: str):
    """Notifikácia, že objednávka bola zaplatená."""
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        if not tokens:
            logger.warning(f"Používateľ {user.username} nemá expo tokeny → notifikácia sa neposiela.")
            return

        title = "Platba objednávky prijatá"
        message = f"Tvoja objednávka (VS {vs}) bola uhradená. Suma: {amount} €."

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={"type": "order_paid", "vs": vs, "amount": amount},
            )
            logger.info(f"Notifikácia order_paid → {user.username} ({token})")

    except Exception as e:
        logger.error(f"Chyba notify_order_paid: {e}")


@shared_task
def notify_order_status_changed(user_id: int, status: str):
    """Notifikácia o zmene stavu objednávky."""
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        if not tokens:
            logger.warning(f"Používateľ {user.username} nemá expo tokeny → notifikácia sa neposiela.")
            return

        title = "Zmena stavu objednávky"
        message = f"Tvoja objednávka zmenila stav na: {status}."

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={"type": "order_status", "status": status},
            )
            logger.info(f"Notifikácia order_status ({status}) → {user.username} ({token})")

    except Exception as e:
        logger.error(f"Chyba notify_order_status_changed: {e}")

@shared_task
def notify_order_deleted(user_id: int, order_id: str, amount: str = None):
    """
    Pošle notifikáciu, že objednávka bola zmazaná.
    """
    try:
        user = User.objects.get(id=user_id)
        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)

        if not tokens:
            logger.warning(f"Používateľ {user.username} nemá expo tokeny → notifikácia sa neposiela.")
            return

        title = "Objednávka zrušená"
        if amount:
            message = f"Tvoja objednávka #{order_id} (suma {amount} €) bola zrušená."
        else:
            message = f"Tvoja objednávka #{order_id} bola zrušená."

        for token in tokens:
            send_push_notification(
                token=token,
                title=title,
                message=message,
                data={"type": "order_deleted", "order_id": order_id, "amount": amount or ""},
            )
            logger.info(f"Notifikácia zrušenej objednávky → {user.username} ({token})")

    except Exception as e:
        logger.error(f"Chyba pri posielaní notifikácie o zmazaní objednávky: {e}")


# tasks.py
from celery import shared_task
from django.contrib.auth import get_user_model
from .models import Announcement

from celery import shared_task

@shared_task
def send_announcement_notification(announcement_id, user_ids):
    from .models import User, Announcement

    announcement = Announcement.objects.get(id=announcement_id)
    users = User.objects.filter(id__in=user_ids)

    count = 0
    for user in users:
        for token in getattr(user, "expo_tokens", []).all():
            send_push_notification(
                token.token,
                f"Nový oznam: {announcement.title}",
                announcement.content[:100] + "..."
            )
            count += 1

    return f"Sent to {count} devices"

@shared_task
def notify_unpaid_orders(order_ids):
    """
    Odošle push notifikáciu všetkým používateľom s nezaplatenou objednávkou dresu.
    """
    User = get_user_model()
    orders = JerseyOrder.objects.filter(id__in=order_ids, is_paid=False).select_related("user")
    count = 0

    for order in orders:
        user = order.user
        title = "Pripomienka platby za dres"
        body = f"Nezabudni uhradiť objednávku dresu v sume {order.amount} €."
        # ak má user expo tokeny
        if hasattr(user, "expo_tokens"):
            for token in user.expo_tokens.all():
                send_push_notification(token.token, title, body)
                count += 1

    return f"📩 Sent {count} notifications to unpaid users."


from celery import shared_task
from django.contrib.auth import get_user_model
from .models import MemberPayment

@shared_task
def send_unpaid_payment_notifications(user_ids):
    """
    Odošle push notifikáciu členom, ktorí majú neuhradené platby.
    """
    User = get_user_model()
    users = User.objects.filter(id__in=user_ids)
    count = 0

    for user in users:
        unpaid = MemberPayment.objects.filter(user=user, is_paid=False)
        if not unpaid.exists():
            continue

        total = sum(p.amount for p in unpaid)
        title = "Pripomienka platby 💰"
        body = f"Nezabudni uhradiť svoje klubové poplatky (spolu {total:.2f} €)."
        
        if hasattr(user, "expo_tokens"):
            for token in user.expo_tokens.all():
                send_push_notification(token.token, title, body)
                count += 1

    return f"📩 Sent {count} notifications to unpaid members."



@shared_task
def send_weekly_batch_created_notification(category_id: int, count: int, week_start: str, week_end: str):
    from dochadzka_app.models import Role, ExpoPushToken
    from django.contrib.auth import get_user_model
    User = get_user_model()

    players = User.objects.filter(
        roles__category_id=category_id,
        roles__role=Role.PLAYER
    ).distinct()

    title = "Tréningy vygenerované"
    body = f"Vytvorené tréningy na nasledujúci týždeň ({week_start} – {week_end}). Počet: {count}"

    for player in players:
        tokens = ExpoPushToken.objects.filter(user=player).values_list("token", flat=True)
        for token in tokens:
            try:
                send_push_notification(
                    token,
                    title,
                    body,
                    user_id=0,
                    user_name="rozvrh"
                )
            except Exception as e:
                logger.warning(f"Chyba pri push batch pre {player.username} → {token}: {str(e)}")



# app/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta

from .models import TrainingSchedule, Training
from django.db import transaction

def _week_start(d):
    # pondelok daného týždňa
    return d - timedelta(days=d.weekday())

def _dt_for_weekday(week_monday_date, weekday, t):
    day_date = week_monday_date + timedelta(days=weekday)
    return timezone.make_aware(datetime.combine(day_date, t))

@shared_task
def process_training_schedules():
    now = timezone.localtime()

    schedules = TrainingSchedule.objects.filter(is_active=True, next_run_at__isnull=False, next_run_at__lte=now)\
                                        .prefetch_related("items")

    for s in schedules:
        if s.strategy == TrainingSchedule.STRATEGY_WEEKLY_BATCH:
            _run_weekly_batch(s, now)
        else:
            _run_days_before(s, now)

def _run_weekly_batch(schedule: TrainingSchedule, now):
    """
    Batch: v konkrétny deň/čas vytvor všetky tréningy na ďalší týždeň.
    """
    today = timezone.localdate()
    next_week_monday = _week_start(today) + timedelta(days=7)  # ďalší pondelok
    next_week_sunday = next_week_monday + timedelta(days=6)

    # orež do rozsahu schedule
    start = max(schedule.start_date, next_week_monday)
    end = min(schedule.end_date, next_week_sunday)

    if end < start:
        # mimo rozsah -> len posuň next_run_at o 7 dní
        schedule.next_run_at = schedule.next_run_at + timedelta(days=7)
        schedule.save(update_fields=["next_run_at"])
        return

    created_ids = []

    with transaction.atomic():
        for item in schedule.items.all():
            dt = _dt_for_weekday(next_week_monday, item.weekday, item.time)
            dt_date = dt.date()

            if dt_date < start or dt_date > end:
                continue

            training, was_created = Training.objects.get_or_create(
                club=schedule.club,
                category=schedule.category,
                date=dt,
                defaults={
                    "description": item.description,
                    "location": item.location,
                    "created_by": schedule.created_by,
                }
            )

            if was_created:
                rebuild_training_vote_reminders(training)
                created_ids.append(training.id)

    if created_ids:
        send_weekly_batch_created_notification.delay(
            schedule.category_id,
            len(created_ids),
            str(next_week_monday),
            str(next_week_sunday),
        )
    # ďalší batch o 7 dní v rovnaký deň/čas
    schedule.next_run_at = schedule.next_run_at + timedelta(days=7)
    schedule.save(update_fields=["next_run_at"])


def _run_days_before(schedule: TrainingSchedule, now):
    """
    Days-before: vytvor tréningy, ktoré majú byť vytvorené dnes (t.j. udalosť je o X dní).
    V praxi to znamená:
      target_date = dnes + days_before
      ak target_date je pondelok -> vytvor item s weekday=0, atď.
    """
    today = timezone.localdate()
    target_date = today + timedelta(days=schedule.days_before or 0)

    # ak target_date mimo rozsah, len posuň next_run_at na zajtra
    if target_date < schedule.start_date or target_date > schedule.end_date:
        schedule.next_run_at = (now + timedelta(days=1)).replace(hour=2, minute=10, second=0, microsecond=0)
        schedule.save(update_fields=["next_run_at"])
        return

    target_weekday = target_date.weekday()

    with transaction.atomic():
        for item in schedule.items.all():
            if item.weekday != target_weekday:
                continue

            dt = timezone.make_aware(datetime.combine(target_date, item.time))

            training, was_created = Training.objects.get_or_create(
                club=schedule.club,
                category=schedule.category,
                date=dt,
                defaults={
                    "description": item.description,
                    "location": item.location,
                    "created_by": schedule.created_by,
                }
            )

            if was_created:
                rebuild_training_vote_reminders(training)
                send_training_notifications.delay(training.id)


    # spúšťaj to denne (napr. 02:10) – aby to bolo konzistentné
    schedule.next_run_at = (now + timedelta(days=1)).replace(hour=2, minute=10, second=0, microsecond=0)
    schedule.save(update_fields=["next_run_at"])

def get_training_unknown_users(training):
    players = User.objects.filter(
        roles__category=training.category,
        roles__role=Role.PLAYER,
        club=training.club
    ).distinct()

    attendance_map = {
        a.user_id: a.status
        for a in TrainingAttendance.objects.filter(training=training)
    }

    unknown_ids = [
        player.id
        for player in players
        if attendance_map.get(player.id, "unknown") == "unknown"
    ]

    return User.objects.filter(id__in=unknown_ids)


def rebuild_training_vote_reminders(training):
    """
    Zmaže neodoslané reminders pre tréning a vytvorí ich nanovo podľa category settingu.
    """
    TrainingVoteReminder.objects.filter(training=training, sent=False).delete()

    try:
        setting = CategoryVoteReminderSetting.objects.get(
            category=training.category,
            club=training.club,
        )
    except CategoryVoteReminderSetting.DoesNotExist:
        return

    if not setting.enabled or not setting.reminder_hours:
        return

    now = timezone.now()
    reminders_to_create = []

    for hour in setting.reminder_hours:
        scheduled_for = training.date - timedelta(hours=hour)

        # nevytváraj reminder do minulosti
        if scheduled_for <= now:
            continue

        reminders_to_create.append(
            TrainingVoteReminder(
                training=training,
                setting=setting,
                hours_before=hour,
                scheduled_for=scheduled_for,
            )
        )

    if reminders_to_create:
        TrainingVoteReminder.objects.bulk_create(
            reminders_to_create,
            ignore_conflicts=True,
        )

@shared_task
def process_training_vote_reminders():
    now = timezone.now()

    reminders = (
        TrainingVoteReminder.objects
        .filter(
            sent=False,
            scheduled_for__lte=now,
            training__date__gt=now,
            setting__enabled=True,
        )
        .select_related("training", "training__category", "training__club", "setting")
        .order_by("scheduled_for")
    )

    for reminder in reminders:
        try:
            users = get_training_unknown_users(reminder.training)

            for user in users:
                tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)
                for token in tokens:
                    send_push_notification(
                        token=token,
                        title="Nezabudni hlasovať!",
                        message=(
                            f"Stále si nepotvrdil účasť na tréning "
                            f"{reminder.training.description} "
                            f"({reminder.training.date.strftime('%d.%m.%Y %H:%M')})."
                        ),
                        data={
                            "type": "training",
                            "training_id": reminder.training.id,
                        }
                    )
                    logger.info(
                        f"Auto reminder {reminder.hours_before}h "
                        f"pre {user.username} → {token}"
                    )

            reminder.sent = True
            reminder.sent_at = now
            reminder.save(update_fields=["sent", "sent_at"])

        except Exception as e:
            logger.error(f"❌ Chyba pri process_training_vote_reminders reminder={reminder.id}: {e}")