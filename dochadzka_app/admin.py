from pyexpat.errors import messages

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Club,
    User,
    Category,
    UserCategoryRole,
    Training,
    TrainingAttendance,
    Match,
    MatchParticipation,
    Announcement,AnnouncementRead, ExpoPushToken, Message, MessageReaction, MatchNomination, ClubPaymentSettings, 
    MemberPayment,OrderPayment, JerseyOrder, TrainingSchedule, TrainingScheduleItem,
    LinkedAccount,
)
from .models import CategoryVoteReminderSetting, TrainingVoteReminder


class UserCategoryRoleInline(admin.TabularInline):
    model = UserCategoryRole
    extra = 1  # počet prázdnych riadkov na pridanie
    autocomplete_fields = ['category']
    verbose_name = "Kategória a rola"
    verbose_name_plural = "Kategórie a roly"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        (('Doplňujúce údaje'), {'fields': ('club','email_2', 'position',
                  'birth_date', 'number','height', 'weight', 'side','preferred_role', 'iban')}),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (('Doplňujúce údaje'), {'fields': ('club','email_2', 'position',
                  'birth_date', 'number','height', 'weight', 'side', 'expo_push_token','preferred_role', 'iban')}),
    )

    list_display = ('id', 'username', 'first_name', 'position', 'email', 'club', 'email_2',
                  'birth_date', 'number','height', 'weight', 'side', 'is_staff','preferred_role', 'iban')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'club','preferred_role', 'iban')

    inlines = [UserCategoryRoleInline]

@admin.register(ExpoPushToken)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('user','token', 'created_at')


@admin.register(LinkedAccount)
class LinkedAccountAdmin(admin.ModelAdmin):
    list_display = ("owner", "linked_user", "club", "created_at")
    list_filter = ("club", "created_at")
    search_fields = (
        "owner__username",
        "owner__first_name",
        "owner__last_name",
        "linked_user__username",
        "linked_user__first_name",
        "linked_user__last_name",
    )
    autocomplete_fields = ("owner", "linked_user", "club")

@admin.register(Message)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('sender','recipient', 'text', 'timestamp', 'read')

@admin.register(MessageReaction)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('message', 'user', 'created_at', 'emoji')

@admin.register(MemberPayment)
class MemberPayment(admin.ModelAdmin):
    list_display = ('user', 'club', 'amount', 'due_date', 'variable_symbol', 'is_paid', 'created_at')

@admin.register(ClubPaymentSettings)
class ClubPaymentSettings(admin.ModelAdmin):
    list_display = ('club', 'iban', 'variable_symbol_prefix', 'payment_cycle', 'due_day')

@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'phone', 'email', 'contact_person', 'iban', 'vote_lock_days')
    search_fields = ('name', 'address', 'phone', 'email', 'contact_person', 'iban', 'vote_lock_days')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id','name', 'club')
    list_filter = ('club',)
    search_fields = ('name',)


@admin.register(UserCategoryRole)
class UserCategoryRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'category')
    list_filter = ('role', 'category__club')
    search_fields = ('user__username', 'category__name')


@admin.register(Training)
class TrainingAdmin(admin.ModelAdmin):
    list_display = ('category', 'date', 'description')
    list_filter = ('category__club', 'category')
    search_fields = ('category__name', 'description')


@admin.register(TrainingAttendance)
class TrainingAttendanceAdmin(admin.ModelAdmin):
    list_display = ('training', 'user','responded_at' )
    search_fields = ('user__username', 'training__category__name')


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('category', 'date', 'opponent', 'location', 'is_home')
    list_filter = ('category__club', 'category', 'is_home')
    search_fields = ('category__name', 'opponent', 'location', 'is_home')


@admin.register(MatchParticipation)
class MatchParticipationAdmin(admin.ModelAdmin):
    list_display = ('match', 'user', 'confirmed', 'club')
    list_filter = ('confirmed', 'match__category__club')
    search_fields = ('user__username', 'match__category__name')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'club', 'get_categories', 'date_created')
    list_filter = ('club', 'categories')
    search_fields = ('title', 'content')
    date_hierarchy = 'date_created'

    def get_categories(self, obj):
        return ", ".join([c.name for c in obj.categories.all()])
    get_categories.short_description = "Kategórie"
    
from django.contrib import admin
from .models import ClubDocument

@admin.register(ClubDocument)
class ClubDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'club', 'uploaded_at')

@admin.register(MatchNomination)
class MatchNominationAdmin(admin.ModelAdmin):
    list_display = ('match', 'user', 'is_substitute', 'rating')


from django.contrib import admin
from .models import Order, OrderItem, Order_Ludimus

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "club", "status", "created_at")
    list_filter = ("status", "club")
    search_fields = ("user__username", "items__product_name", "items__product_code")
    inlines = [OrderItemInline]


@admin.register(OrderPayment)
class orderPayment(admin.ModelAdmin):
    list_display = ('order', 'user', 'iban', 'variable_symbol', 'amount', 'is_paid', 'created_at', 'paid_at')



@admin.register(JerseyOrder)
class jerseyOrder(admin.ModelAdmin):
    list_display = ('club', 'surname', 'jersey_size', 'shorts_size', 'number', 'created_at')


@admin.register(Order_Ludimus)
class Order_Ludimus(admin.ModelAdmin):
    list_display = ("club_name", "first_name", "last_name", "email", "phone", "plan", "created_at", "processed")
    list_filter = ("plan", "processed", "created_at")
    search_fields = ("club_name", "first_name", "last_name", "email", "phone")
    ordering = ("-created_at",)


@admin.register(AnnouncementRead)
class AnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ("announcement", "user", "read_at")
    list_filter = ("announcement__club", "read_at")

@admin.register(TrainingSchedule)
class TrainingScheduleAdmin(admin.ModelAdmin):
    list_display = [field.name for field in TrainingSchedule._meta.fields]    


@admin.register(TrainingScheduleItem)
class TrainingScheduleItemAdmin(admin.ModelAdmin):
    list_display = [field.name for field in TrainingScheduleItem._meta.fields] 
       

@admin.register(CategoryVoteReminderSetting)
class CategoryVoteReminderSettingAdmin(admin.ModelAdmin):
    list_display = ("category", "club", "enabled", "reminder_hours", "updated_by", "updated_at")
    list_filter = ("enabled", "club")
    search_fields = ("category__name", "club__name")


@admin.register(TrainingVoteReminder)
class TrainingVoteReminderAdmin(admin.ModelAdmin):
    list_display = ("training", "hours_before", "scheduled_for", "sent", "sent_at")
    list_filter = ("sent", "training__club", "training__category")
    search_fields = ("training__description", "training__category__name")


from django.contrib import admin
from .models import Position, User

admin.site.register(Position)
