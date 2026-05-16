from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

class Club(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    vote_lock_days = models.PositiveIntegerField(default=2)
    training_lock_hours = models.IntegerField(default=2)  
    address = models.CharField(max_length=255, blank=True, null=True)
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)

    phone = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    iban = models.CharField(max_length=34, blank=True, null=True)

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    PLAYER = 'player', 'Hráč'
    COACH = 'coach', 'Tréner'
    PARENT = 'parent', 'Rodič'
    ADMIN = 'admin', 'Admin'

class User(AbstractUser):
    # Môžeš sem pridať ďalšie polia, ak chceš (napr. telefón, avatar...)
    club = models.ForeignKey(Club,on_delete=models.CASCADE, null=True, blank=True, related_name='users')
    # Poznámka: tu je každý user priradený k jednému klubu
    # Dodatočné polia:
    birth_date = models.DateField(null=True, blank=True)
    number = models.CharField(max_length=10, blank=True)  # číslo na drese
    height = models.CharField(max_length=10, blank=True)  # výška napr. "180 cm"
    weight = models.CharField(max_length=10, blank=True)  # váha napr. "75 kg"
    side = models.CharField(max_length=10, blank=True)    # napr. "ľavá", "pravá"
    email_2 = models.EmailField(null=True, blank=True)    # druhý email
    position = models.ForeignKey('Position', on_delete=models.SET_NULL, null=True, blank=True)
    preferred_role = models.CharField(max_length=20, null=True, blank=True, choices=Role.choices)
    iban = models.CharField(max_length=34, blank=True, null=True, help_text="IBAN používateľa")

    def __str__(self):
        return self.username


class LinkedAccount(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="linked_accounts",
    )
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="linked_to_accounts",
    )
    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="linked_accounts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("owner", "linked_user")
        ordering = ["linked_user__last_name", "linked_user__first_name", "linked_user__username"]

    def __str__(self):
        return f"{self.owner} -> {self.linked_user}"


class ExpoPushToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="expo_tokens")
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} – {self.token[:15]}..."

class Category(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.club.name})"






class Training(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='trainings')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='trainings')
    date = models.DateTimeField()
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["club", "category", "date"], name="uniq_training_club_category_date")
        ]


    def __str__(self):
        return f"Tréning {self.category.name} - {self.date.strftime('%Y-%m-%d %H:%M')}"





class Match(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='matches')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='matches')
    date = models.DateTimeField()
    opponent = models.CharField(max_length=100)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    video_link = models.URLField(blank=True, null=True)
    is_home = models.BooleanField(default=False)

    def __str__(self):
        home_away = "Doma" if self.is_home else "Vonku"
        return f"{home_away}: {self.category.name} vs {self.opponent} - {self.date.strftime('%Y-%m-%d %H:%M')}"


class UserCategoryRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='roles')  # oprava
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='user_roles')
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        unique_together = ('user', 'category', 'role')

    def __str__(self):
        return f"{self.user.username} - {self.role} - {self.category.name}"


class AttendanceStatus(models.TextChoices):
    PRESENT = 'present', 'Príde'
    ABSENT = 'absent', 'Nepríde'
    UNANSWERED = 'unanswered', 'Nezodpovedané'

class TrainingAttendance(models.Model):
    training = models.ForeignKey(Training, on_delete=models.CASCADE, related_name='attendances')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='training_attendances')
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.UNANSWERED)
    reason = models.CharField(max_length=255, blank=True, null=True)  
    responded_at = models.DateTimeField(null=True, blank=True)  

    class Meta:
        unique_together = ('training', 'user')

    def __str__(self):
        return f"{self.user.username} - {self.get_status_display()} - {self.training}"

class MatchParticipation(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='participations')
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='participations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='match_participations')  # oprava
    confirmed = models.BooleanField(default=False)
    responded_at = models.DateTimeField(null=True, blank=True)  
    reason = models.CharField(max_length=255, blank=True, null=True)  # 🆕 pridané pole

    class Meta:
        unique_together = ('match', 'user')

    def __str__(self):
        return f"{self.user.username} - {'potvrdený' if self.confirmed else 'nepotvrdený'} - {self.match}"

class Announcement(models.Model):
    club = models.ForeignKey(
        Club, on_delete=models.CASCADE, related_name='announcements'
    )
    categories = models.ManyToManyField(
        Category, blank=True, related_name='announcements'
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="announcements_created"
    )

    def __str__(self):
        if self.categories.exists():
            return f"Oznámenie pre {', '.join([c.name for c in self.categories.all()])} - {self.title}"
        return f"Oznámenie pre {self.club.name} - {self.title}"
    
    
from django.conf import settings  # ← dôležité
from django.db import models

class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_messages', on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='received_messages', on_delete=models.CASCADE)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        return f"From {self.sender} to {self.recipient}: {self.text[:20]}"





class MessageReaction(models.Model):
    message = models.ForeignKey("Message", on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=10)  # napr. "👍", "❤️"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')  # 1 reakcia na 1 správu od jedného usera


from django.db import models

class Position(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

# models.py
from django.db import models

class ClubDocument(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} – {self.club.name}"

class MatchNomination(models.Model):
    match = models.ForeignKey(Match, related_name="nominations", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_substitute = models.BooleanField(default=False)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)  # neskôr
    goals = models.PositiveSmallIntegerField(default=0)
    plus_minus = models.SmallIntegerField(default=0)
    confirmed = models.BooleanField(null=True, blank=True)  # None = nereagoval, True/False = odpovedal
    class Meta:
        unique_together = ('match', 'user')

from django.db import models
from django.contrib.auth import get_user_model

class PaymentCycle(models.TextChoices):
    MONTHLY = 'monthly', 'Mesačný'
    QUARTERLY = 'quarterly', 'Štvrťročný'
    HALF_YEAR = 'half_year', 'Polročný'
    SEASONAL = 'seasonal', 'Celosezónny'

class ClubPaymentSettings(models.Model):
    club = models.OneToOneField(Club, on_delete=models.CASCADE)
    iban = models.CharField(max_length=34)
    variable_symbol_prefix = models.CharField(max_length=10, blank=True)
    payment_cycle = models.CharField(max_length=20, choices=PaymentCycle.choices)
    due_day = models.PositiveSmallIntegerField(default=10)  # deň v mesiaci

class MemberPayment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    club = models.ForeignKey(Club, on_delete=models.CASCADE)

    amount = models.DecimalField(max_digits=8, decimal_places=2)

    cycle = models.CharField(
        max_length=20,
        choices=PaymentCycle.choices,
        default=PaymentCycle.MONTHLY,
    )

    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    due_date = models.DateField()

    variable_symbol = models.CharField(max_length=20)
    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.user} – {self.amount} € – VS: {self.variable_symbol}"


from django.db import models
from django.conf import settings

class NordigenConnection(models.Model):
    club = models.OneToOneField(Club, on_delete=models.CASCADE)
    requisition_id = models.CharField(max_length=128)
    account_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Nordigen pripojenie pre klub {self.club.name}"


from django.db import models
from django.conf import settings

class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "Nová", "Nová"
        PROCESSING = "Spracováva sa", "Spracováva sa"
        ORDERED = "Objednaná", "Objednaná"
        DONE = "Doručená", "Doručená"
        CANCELED = "Zrušená", "Zrušená"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)  # ← NOVÉ
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # ✅ PRIDAJ TOTO

    

    def __str__(self):
        return f"Order #{self.pk} by {self.user} ({self.created_at:%Y-%m-%d})"


class OrderItem(models.Model):
    class ProductType(models.TextChoices):
        STICK = "stick", "Hokejka"
        BLADE = "blade", "Čepeľ"
        APPAREL = "apparel", "Oblečenie"
        OTHER = "other", "Iné"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product_type = models.CharField(max_length=20, choices=ProductType.choices)
    product_name = models.CharField(max_length=120, blank=True)          # "Názov produktu"
    product_code = models.CharField(max_length=120, blank=True)          # "Kód produktu"
    side = models.CharField(max_length=30, blank=True)                   # "Strana" (ľavá/pravá)
    height = models.CharField(max_length=30, blank=True)                 # "Výška" (napr. 100 cm)
    size = models.CharField(max_length=30, blank=True)                   # "Veľkosť" (oblečenie)
    quantity = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=255, blank=True)                  # drobná poznámka k položke
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # ← NOVÉ (€/ks)
    is_canceled = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.get_product_type_display()} – {self.product_name or self.product_code or 'item'}"
    
class JerseyOrder(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jersey_orders")  # 🔥
    surname = models.CharField(max_length=50)
    jersey_size = models.CharField(max_length=5, choices=[(s, s) for s in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]])
    shorts_size = models.CharField(max_length=5, choices=[(s, s) for s in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]])
    number = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)  
    created_at = models.DateTimeField(auto_now_add=True)

    # models.py
from django.db import models
from django.conf import settings

class OrderPayment(models.Model):
    order = models.OneToOneField(Order, null=True, blank=True, on_delete=models.CASCADE, related_name="payment")
    jersey_order = models.OneToOneField(JerseyOrder, null=True, blank=True, on_delete=models.CASCADE, related_name="payment")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="order_payments")
    iban = models.CharField(max_length=34)             # IBAN pre objednávky (môže byť iný než pre členské platby)
    variable_symbol = models.CharField(max_length=20)  # VS špecifický pre túto objednávku
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # suma, ktorú má užívateľ zaplatiť
    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        if self.order:
            return f"Platba za objednávku #{self.order.id} - {self.amount}€"
        elif self.jersey_order:
            return f"Platba za dresovú objednávku #{self.jersey_order.id} - {self.amount}€"
        return f"Platba bez objednávky - {self.amount}€"

from django.db import models

class Order_Ludimus(models.Model):
    PLAN_CHOICES = [
        ("start", "Štart – 0 € (1. mesiac zdarma)"),
        ("yearly", "Ročne – 25 €/mes (platba ročne)"),
        ("monthly", "Flexi – 30 €/mes (platba mesačne)"),
    ]

    club_name = models.CharField("Názov klubu", max_length=150)
    first_name = models.CharField("Meno", max_length=100)
    last_name = models.CharField("Priezvisko", max_length=100)
    email = models.EmailField("Email")
    phone = models.CharField("Telefón", max_length=30)
    plan = models.CharField("Balík", max_length=20, choices=PLAN_CHOICES)
    created_at = models.DateTimeField("Vytvorené", auto_now_add=True)
    processed = models.BooleanField("Spracované", default=False)

    def __str__(self):
        return f"{self.club_name} – {self.get_plan_display()}"



# models.py

class AnnouncementRead(models.Model):
    announcement = models.ForeignKey(Announcement, related_name="reads", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("announcement", "user")



class Formation(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

class FormationLine(models.Model):
    formation = models.ForeignKey(Formation, on_delete=models.CASCADE, related_name="lines")
    number = models.PositiveIntegerField()  # napr. 1, 2, 3. päťka

class FormationPlayer(models.Model):
    line = models.ForeignKey(FormationLine, on_delete=models.CASCADE, related_name="players")
    player = models.ForeignKey(User, on_delete=models.CASCADE)
    position = models.CharField(max_length=3, choices=[("LW", "LW"), ("C", "C"), ("RW", "RW"), ("LD", "LD"), ("RD", "RD"), ("N", "N")])


# app/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, datetime, time, date

class TrainingSchedule(models.Model):
    STRATEGY_WEEKLY_BATCH = "weekly_batch"
    STRATEGY_DAYS_BEFORE = "days_before"

    STRATEGY_CHOICES = [
        (STRATEGY_WEEKLY_BATCH, "Vytvoriť všetky tréningy na ďalší týždeň v konkrétny deň/čas"),
        (STRATEGY_DAYS_BEFORE, "Vytvárať tréning X dní pred udalosťou"),
    ]

    WEEKDAYS = [
        (0, "Pondelok"),
        (1, "Utorok"),
        (2, "Streda"),
        (3, "Štvrtok"),
        (4, "Piatok"),
        (5, "Sobota"),
        (6, "Nedeľa"),
    ]

    club = models.ForeignKey("Club", on_delete=models.CASCADE, related_name="training_schedules")
    category = models.ForeignKey("Category", on_delete=models.CASCADE, related_name="training_schedules")

    # platnosť rozvrhu
    start_date = models.DateField()
    end_date = models.DateField()

    strategy = models.CharField(max_length=32, choices=STRATEGY_CHOICES)

    # --- STRATEGY_WEEKLY_BATCH ---
    batch_weekday = models.IntegerField(choices=WEEKDAYS, null=True, blank=True)  # napr. Sobota
    batch_time = models.TimeField(null=True, blank=True)  # napr. 15:00

    # --- STRATEGY_DAYS_BEFORE ---
    days_before = models.PositiveIntegerField(null=True, blank=True)  # napr. 3

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    # interné polia plánovania
    next_run_at = models.DateTimeField(null=True, blank=True)  # kedy má schedule najbližšie generovať
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Schedule {self.category} {self.start_date}–{self.end_date} ({self.strategy})"

    def clean(self):
        # voliteľné: môžeš doplniť validácie aj tu, ale my ich spravíme v serializeroch
        pass


class TrainingScheduleItem(models.Model):
    WEEKDAYS = TrainingSchedule.WEEKDAYS

    schedule = models.ForeignKey(TrainingSchedule, on_delete=models.CASCADE, related_name="items")
    weekday = models.IntegerField(choices=WEEKDAYS)  # Po=0 .. Ne=6
    time = models.TimeField()                       # 16:30
    location = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.schedule.category}: {self.weekday} {self.time}"



from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone

class CategoryVoteReminderSetting(models.Model):
    club = models.ForeignKey(
        "Club",
        on_delete=models.CASCADE,
        related_name="vote_reminder_settings",
    )
    category = models.OneToOneField(
        "Category",
        on_delete=models.CASCADE,
        related_name="vote_reminder_setting",
    )

    enabled = models.BooleanField(default=False)
    reminder_hours = models.JSONField(default=list, blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_vote_reminder_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__name"]

    def clean(self):
        if self.category.club_id != self.club_id:
            raise ValidationError("Kategória nepatrí do zvoleného klubu.")

        if not isinstance(self.reminder_hours, list):
            raise ValidationError("reminder_hours musí byť zoznam.")

        cleaned = []
        for h in self.reminder_hours:
            try:
                hour = int(h)
            except (TypeError, ValueError):
                raise ValidationError("Každá hodnota v reminder_hours musí byť číslo.")

            if hour < 1 or hour > 168:
                raise ValidationError("Každý interval musí byť v rozsahu 1 až 168 hodín.")
            cleaned.append(hour)

        cleaned = sorted(set(cleaned), reverse=True)

        if len(cleaned) > 3:
            raise ValidationError("Maximálne 3 pripomienky na kategóriu.")

        self.reminder_hours = cleaned

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.club.name} / {self.category.name} / reminders"


class TrainingVoteReminder(models.Model):
    training = models.ForeignKey(
        "Training",
        on_delete=models.CASCADE,
        related_name="vote_reminders",
    )
    setting = models.ForeignKey(
        "CategoryVoteReminderSetting",
        on_delete=models.CASCADE,
        related_name="training_reminders",
    )

    hours_before = models.PositiveIntegerField()
    scheduled_for = models.DateTimeField(db_index=True)

    sent = models.BooleanField(default=False, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("training", "hours_before")
        ordering = ["scheduled_for"]

    def clean(self):
        if self.training.category_id != self.setting.category_id:
            raise ValidationError("Reminder setting nepatrí k rovnakej kategórii ako tréning.")

        if self.hours_before < 1 or self.hours_before > 168:
            raise ValidationError("hours_before musí byť v rozsahu 1 až 168.")

        scheduled = self.training.date - timedelta(hours=self.hours_before)
        if scheduled >= self.training.date:
            raise ValidationError("scheduled_for musí byť pred dátumom tréningu.")

        self.scheduled_for = scheduled

    def save(self, *args, **kwargs):
        self.scheduled_for = self.training.date - timedelta(hours=self.hours_before)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.training} / {self.hours_before}h"
