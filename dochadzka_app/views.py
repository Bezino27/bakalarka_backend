# odstránil som import z allauth.conftest
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import (ClubSerializer, CategorySerializer,
                          UserMeUpdateSerializer, CategorySerializer2, UserCategoryRoleSerializer,
                          MatchParticipationCreateSerializer)
from django.utils.timezone import localtime
from rest_framework import status
from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, permission_classes
from .models import UserCategoryRole, Category, User, Club, TrainingAttendance
from django.db.models import IntegerField, Value, Case, When
from django.db.models.functions import Cast
User = get_user_model()


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def me_view(request):
    user = request.user

    if request.method == 'PUT':
        print("PRIJATÉ ÚDAJE:", request.data)
        serializer = UserMeUpdateSerializer(user, data=request.data, partial=True)  # ⬅️ dôležité
        if serializer.is_valid():
            serializer.save()
            print("ULOŽENÉ ÚDAJE:", serializer.validated_data)
            return Response({'detail': 'Údaje boli aktualizované'})
        print("CHYBY SERIALIZERA:", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Pôvodné GET zostáva
    roles_qs = UserCategoryRole.objects.filter(user=user)
    roles = UserCategoryRoleSerializer(
        roles_qs.exclude(category__isnull=True), many=True
    ).data
    assigned_categories = list(set(
        role.category.name for role in roles_qs if role.category
    ))
    club_serialized = ClubSerializer(user.club).data if user.club else None

    data = {
        'id': user.id,
        'username': user.username,
        'name': f"{user.first_name} {user.last_name}",
        'email': user.email,
        'email_2': user.email_2,
        'birth_date': user.birth_date,
        'number': user.number,
        'roles': roles,
        'assigned_categories': assigned_categories,
        'club': club_serialized,
        'height': user.height,
        'weight': user.weight,
        'side': user.side,
        'position': user.position.name if user.position else None,
        'preferred_role': user.preferred_role,
    }

    return Response(data)


from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def login_view(request):
    if request.method == "POST":
        data = json.loads(request.body)
        username_or_email = data.get("username")
        password = data.get("password")

        # ak obsahuje @ -> je to email
        if "@" in username_or_email:
            try:
                user_obj = User.objects.get(email=username_or_email)
                username = user_obj.username
            except User.DoesNotExist:
                return JsonResponse({"message": "Login failed"}, status=401)
        else:
            username = username_or_email

        user = authenticate(username=username, password=password)

        if user is not None:
            login(request, user)
            return JsonResponse({
                "message": "Login successful",
                "username": user.username
            })
        else:
            return JsonResponse({"message": "Login failed"}, status=401)

    return JsonResponse({"message": "Method not allowed"}, status=405)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_categories(request, club_id):
    # Skontrolujeme, či klub s daným id existuje
    try:
        club = Club.objects.get(id=club_id)
    except Club.DoesNotExist:
        return Response({"detail": "Club not found."}, status=404)

    # Filtrovanie kategórií podľa club_id
    categories = Category.objects.filter(club=club)
    serializer = CategorySerializer(categories, many=True)
    return Response(serializer.data)



from .models import User  # už asi máš, ale pre istotu
from .models import UserCategoryRole, Role
import logging
logger = logging.getLogger(__name__)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.contrib.auth import get_user_model
from .models import Role, ExpoPushToken
from .serializers import TrainingCreateSerializer
from .helpers import send_push_notification  # tvoje posielanie
import logging
from dochadzka_app.tasks import send_training_notifications
logger = logging.getLogger(__name__)
User = get_user_model()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_training_view(request):
    category_ids = request.data.get("category_ids")

    if not category_ids or not isinstance(category_ids, list):
        return Response({"error": "Musíš zadať aspoň jednu kategóriu."}, status=400)

    created_trainings = []

    for cat_id in category_ids:
        data = {
            "description": request.data.get("description"),
            "location": request.data.get("location"),
            "date": request.data.get("date"),
            "category": cat_id
        }

        serializer = TrainingCreateSerializer(data=data)
        if serializer.is_valid():
            training = serializer.save(
                created_by=request.user,
                club=request.user.club
            )

            logger.info(f"✅ Tréning vytvorený: {training.description}")
            logger.info(f"➡️ Kategória: {training.category.name}")
            # vytvor automatické reminders podľa nastavenia kategórie
            rebuild_training_vote_reminders(training)
            
            # Všetci hráči danej kategórie
            players = User.objects.filter(
                roles__category=training.category,
                roles__role=Role.PLAYER
            ).distinct()

            logger.info(f"➡️ Posielam notifikácie hráčom ({players.count()})")

            send_training_notifications.delay(training.id)
            created_trainings.append(training.id)
        else:
            logger.warning(f"❌ Nevalidné dáta pre kategóriu {cat_id}: {serializer.errors}")

    if not created_trainings:
        return Response({"error": "Žiadny tréning nebol vytvorený."}, status=400)

    return Response({"success": True, "created_ids": created_trainings}, status=201)

# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from dochadzka_app.models import Training, Category
from dochadzka_app.serializers import TrainingSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_trainings_view(request):
    user = request.user
    club = user.club

    # Získaj kategórie, kde je hráč
    categories = Category.objects.filter(club=club, user_roles__user=user).distinct()

    # Aktuálny čas
    from django.utils import timezone
    now = timezone.now()

    # Tréningy, ktoré ešte len budú
    trainings = (
        Training.objects.filter(
            category__in=categories,
            club=club,
            date__gte=now,  # ⬅️ pridali sme filter na budúce tréningy
        )
        .select_related('category')
        .prefetch_related('attendances')
        .order_by('date')
    )

    serializer = TrainingSerializer(trainings, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_training_attendance(request):
    training_id = request.data.get('training_id')
    user_id = request.data.get('user_id')  # možnosť, ak tréner mení iným hráčom
    status_value = request.data.get('status')
    reason = request.data.get('reason', None)  # 💥 nový parameter

    if status_value not in ['present', 'absent', 'unknown']:
        return Response({"error": "Neplatný status"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        training = Training.objects.get(id=training_id)
    except Training.DoesNotExist:
        return Response({"error": "Tréning nenájdený"}, status=status.HTTP_404_NOT_FOUND)

    # Ak je tréner, môže meniť aj iným hráčom
    user_to_update = request.user
    if user_id and int(user_id) != request.user.id:
        is_coach = request.user.roles.filter(role='coach', category=training.category).exists()
        if not is_coach:
            return Response({"error": "Nemáš oprávnenie meniť účasť iným hráčom"}, status=status.HTTP_403_FORBIDDEN)
        try:
            user_to_update = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Používateľ nenájdený"}, status=status.HTTP_404_NOT_FOUND)

    # Získaj alebo vytvor záznam
    attendance, created = TrainingAttendance.objects.get_or_create(
        user=user_to_update,
        training=training,
        defaults={
            'status': status_value,
            'reason': reason if status_value == 'absent' else None,  # 💥 uložíme dôvod iba pri absencii
            'responded_at': timezone.now(),  # 🕓 zaznamenáme čas, keď hráč zahlasoval prvýkrát

        },
    )

    if not created:
        attendance.status = status_value
        attendance.reason = reason if status_value == 'absent' else None  # 💥 aktualizujeme dôvod
        attendance.responded_at = timezone.now()  # 🕓 aktualizujeme čas pri každej zmene hlasovania
        attendance.save()

    return Response({
        "message": "Účasť bola úspešne zaznamenaná",
        "status": status_value,
        "reason": attendance.reason,  # 💥 pridaj aj spätnú hodnotu
        "responded_at": attendance.responded_at,  # 💥 vrátime čas hlasovania

    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_categories_view(request):
    user = request.user
    categories = Category.objects.filter(players__user=user).distinct()
    serializer = CategorySerializer2(categories, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def training_detail_view(request, training_id):
    try:
        training = Training.objects.select_related('category', 'created_by').get(id=training_id)
    except Training.DoesNotExist:
        return Response({"error": "Tréning neexistuje"}, status=status.HTTP_404_NOT_FOUND)

    attendances = TrainingAttendance.objects.filter(training=training).select_related('user')

    # Zistí, či je aktuálny používateľ tréner tejto kategórie
    is_coach = request.user.roles.filter(role='coach', category=training.category).exists()

    # Získaj všetkých hráčov z kategórie
    all_players = (
        User.objects.filter(roles__category=training.category, roles__role='player')
        .distinct()
        .select_related('position')
        .annotate(
            number_int=Case(
                When(number__regex=r'^\d+$', then=Cast('number', IntegerField())),
                default=Value(9999),
                output_field=IntegerField(),
            )
        )
        .order_by('number_int', 'last_name', 'first_name')
    )

    present, absent, unknown = [], [], []

    for player in all_players:
        att = next((a for a in attendances if a.user_id == player.id), None)
        full_name = f"{player.first_name} {player.last_name}".strip() or player.username

        player_data = {
            "id": player.id,
            "name": full_name,
            "number": player.number,
            "birth_date": player.birth_date,
            "position": player.position.name if player.position else None,
        }

        if att and att.responded_at:
            local_dt = localtime(att.responded_at)
            player_data["responded_at"] = local_dt.isoformat() 

        if att:
            if att.status == 'present':
                present.append(player_data)
            elif att.status == 'absent':
                if is_coach and att.reason:
                    player_data["reason"] = att.reason
                absent.append(player_data)
            else:
                unknown.append(player_data)
        else:
            unknown.append(player_data)

    return Response({
        "id": training.id,
        "description": training.description,
        "date": training.date.isoformat(),
        "location": training.location,
        "created_by": training.created_by.username if training.created_by else "Neznámy",
        "category_id": training.category.id,
        "category_name": training.category.name,
        "players": {
            "present": present,
            "absent": absent,
            "unknown": unknown,
        },
    })


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from .models import ExpoPushToken

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_expo_push_token(request):
    token = request.data.get("token")
    logger.info(f"🔔 Prišiel request na uloženie tokenu od {request.user.username}")
    logger.info(f"📦 Token z requestu: {token}")

    if not token:
        logger.info("❌ Token neprišiel")
        return Response({"error": "Token je povinný"}, status=400)

    # Ak token už existuje pre iného používateľa, zmaž ho
    ExpoPushToken.objects.filter(token=token).exclude(user=request.user).delete()

    # Ak token ešte neexistuje pre tohto usera, vytvor
    ExpoPushToken.objects.get_or_create(user=request.user, token=token)

    logger.info(f"✅ Token {token} uložený pre používateľa {request.user.username}")
    return Response({"success": True})


from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['POST'])
def test_push(request):
    token = request.data.get("token")  # teraz už bude fungovať
    if not token:
        return Response({"error": "Token is required"}, status=400)

    from .helpers import send_push_notification
    send_push_notification(token, "Test Notifikácia", "Toto je test.")

    return Response({"success": True})


from dochadzka_app.tasks import notify_training_deleted

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_training_view(request, training_id):
    training = get_object_or_404(Training, id=training_id)

    # Over, či používateľ je tréner v tejto kategórii
    is_coach = request.user.roles.filter(category=training.category, role=Role.COACH).exists()
    if not is_coach:
        return Response({"error": "Nemáš oprávnenie na zmazanie tohto tréningu."}, status=403)

    logger.info(f"🗑️ Mazanie tréningu {training.id} – {training.description}")

    # Spusti Celery task na notifikáciu hráčov
    notify_training_deleted.delay(training.id, training.description, training.category.id)

    training.delete()
    logger.info(f"✅ Tréning {training.id} úspešne zmazaný.")
    return Response({"success": True}, status=204)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def training_attendance_view(request, training_id):
    try:
        training = Training.objects.get(id=training_id)
    except Training.DoesNotExist:
        return Response({"error": "Tréning neexistuje"}, status=404)

    players = User.objects.filter(
        roles__category=training.category,
        roles__role='player'
    ).distinct()

    # načítaj všetky dochádzky pre tento tréning
    attendances = TrainingAttendance.objects.filter(training=training)
    attendance_map = {a.user_id: a.status for a in attendances}

    data = [
        {
            "id": player.id,
            "name": f"{player.first_name} {player.last_name}".strip() or player.username,
            "number": player.number,
            "birth_date": player.birth_date,
            "status": attendance_map.get(player.id, "unknown")  # ← pridaj status
            
        }
        for player in players
    ]

    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import User, Training, TrainingAttendance, Category

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_players_attendance_view(request):
    user = request.user

    coach_categories = Category.objects.filter(user_roles__user=user, user_roles__role='coach').distinct()

    # Všetci hráči v týchto kategóriách
    players = User.objects.filter(
        roles__category__in=coach_categories,
        roles__role='player'
    ).distinct()

    # Odstráň používateľov, ktorí sú zároveň trénermi v tej istej kategórii
    filtered_players = []
    for player in players:
        player_roles = player.roles.filter(category__in=coach_categories)
        has_only_player_role = all(role.role == 'player' for role in player_roles)
        if has_only_player_role:
            filtered_players.append(player)

    response_data = []

    for player in filtered_players:
        player_categories = coach_categories.filter(user_roles__user=player).distinct()
        trainings_by_category = {}

        for cat in player_categories:
            trainings = Training.objects.filter(category=cat).order_by('-date')
            total = trainings.count()
            attendances = TrainingAttendance.objects.filter(user=player, training__in=trainings)
            present = attendances.filter(status='present').count()
            absent = attendances.filter(status='absent').count()
            unknown = total - (present + absent)

            percent = round((present / total) * 100) if total > 0 else 0

            trainings_serialized = []
            for t in trainings:
                att = attendances.filter(training=t).first()
                trainings_serialized.append({
                    'id': t.id,
                    'description': t.description,
                    'date': t.date.isoformat(),
                    'location': t.location,
                    'category': cat.id,
                    'category_name': cat.name,
                    'status': att.status if att else 'unknown',
                })

            trainings_by_category[cat.name] = {
                'total': total,
                'present': present,
                'absent': absent,
                'unknown': unknown,
                'percentage': percent,
                'trainings': trainings_serialized,
            }

        response_data.append({
            'player_id': player.id,
            'name': f"{player.first_name} {player.last_name}".strip() or player.username,
            'number': player.number,
            'birth_date': player.birth_date,
            'categories': trainings_by_category,
        })

    return Response(response_data)

# VYMAZAT PO UPDATE COACH TRENINGY
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_trainings_view(request):
    user = request.user
    club = user.club

    # Získaj kategórie, kde má používateľ rolu coach
    coach_categories = Category.objects.filter(club=club, user_roles__user=user, user_roles__role='coach').distinct()

    # Získaj tréningy len pre tieto kategórie
    trainings = Training.objects.filter(
        category__in=coach_categories,
        club=club
    ).select_related('category').prefetch_related('attendances').order_by('date')

    serializer = TrainingSerializer(trainings, many=True, context={'request': request})
    return Response(serializer.data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    user = request.user
    data = request.data
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    if not user.check_password(old_password):
        return Response({'detail': 'Zlé pôvodné heslo.'}, status=status.HTTP_400_BAD_REQUEST)

    if not new_password or len(new_password) < 6:
        return Response({'detail': 'Nové heslo musí mať aspoň 6 znakov.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()
    return Response({'detail': 'Heslo úspešne zmenené.'})



# BACKEND - views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()



@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    data = request.data
    username = data.get('username')
    password = data.get('password')
    password2 = data.get('password2')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    birth_date = data.get('birth_date')
    club_id = data.get('club_id')
    email = data.get('email')
    email_2 = data.get('email_2')

    # 🔹 1. Kontrola povinných polí
    if not all([username, password, password2, first_name, last_name, birth_date, club_id]):
        return Response({'detail': 'Vyplň všetky povinné polia.'}, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 2. Overenie hesla
    if password != password2:
        return Response({'detail': 'Heslá sa nezhodujú.'}, status=status.HTTP_400_BAD_REQUEST)

    if len(password) < 8 or not any(ch.isdigit() for ch in password):
        return Response({'detail': 'Heslo musí mať aspoň 8 znakov a obsahovať číslicu.'}, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 3. Overenie používateľského mena
    if User.objects.filter(username=username).exists():
        return Response({'detail': 'Používateľské meno už existuje.'}, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 4. Overenie klubu
    try:
        club = Club.objects.get(id=club_id)
    except Club.DoesNotExist:
        return Response({'detail': 'Zvolený klub neexistuje.'}, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 5. Overenie emailu (ak je zadaný)
    if email and User.objects.filter(email=email).exists():
        return Response({'detail': 'Tento email už je zaregistrovaný.'}, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 6. Vytvorenie používateľa
    user = User.objects.create_user(
        username=username,
        password=password,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        email=email,
        email_2=email_2,
        club=club
    )

    return Response({'detail': 'Registrácia prebehla úspešne.'}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_clubs(request):
    clubs = Club.objects.all()
    data = [{"id": club.id, "name": club.name} for club in clubs]
    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import Message, MessageReaction
from .serializers import MessageSerializer, MessageReactionSerializer


from .models import ExpoPushToken  #
import logging
logger = logging.getLogger(__name__)  # pre logovanie chýb

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def chat_messages_view(request, user_id):
    current_user = request.user

    if request.method == 'GET':
        # Parametre pre pagináciu
        offset = int(request.GET.get("offset", 0))
        limit = int(request.GET.get("limit", 20))

        # Označíme prijaté správy ako prečítané
        Message.objects.filter(sender_id=user_id, recipient=current_user, read=False).update(read=True)

        # Vyber všetky správy medzi užívateľmi
        messages = Message.objects.filter(
            Q(sender=current_user, recipient_id=user_id) |
            Q(sender_id=user_id, recipient=current_user)
        ).order_by('-timestamp')  # najnovšie ako prvé

        # Aplikuj slice
        paginated = messages[offset:offset+limit]

        # Otoč späť do prirodzeného poradia (od najstaršej po najnovšiu)
        serializer = MessageSerializer(paginated[::-1], many=True, context={"request": request})
        return Response(serializer.data)


    elif request.method == 'POST':
        data = request.data.copy()
        data['sender'] = current_user.id
        serializer = MessageSerializer(data=data, context={"request": request})
        if serializer.is_valid():
            message = serializer.save()
            # Posielanie notifikácií
            tokens = ExpoPushToken.objects.filter(user=message.recipient).values_list("token", flat=True)
            full_name = f"{current_user.first_name} {current_user.last_name}".strip()
            preview = message.text[:80] + ("..." if len(message.text) > 80 else "")
            for token in tokens:
                try:
                    response = send_push_notification(
                        token,
                        title=f"Nová správa od {full_name}",
                        message=preview,
                        user_id=current_user.id,  # ← ten kto posiela správu
                        user_name=full_name  # ← celé meno
                    )
                    logger.info(f"📤 {message.recipient.username} → {token} → {response.status_code} - {response.text}")
                except Exception as e:
                    logger.warning(f"❌ Chyba pri push {message.recipient.username} → {token}: {str(e)}")
            # Vždy vráť validný JSON
            return Response(MessageSerializer(message, context={"request": request}).data, status=201)
        # Ak je invalid
        return Response(serializer.errors, status=400)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model

User = get_user_model()

from django.db.models import Q


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chat_users_list(request):
    user = request.user
    club = user.club
    roles = UserCategoryRole.objects.filter(user=user).values_list("role", flat=True)
    is_coach_or_admin = any(r.lower() in ['coach', 'admin'] for r in roles)

    users = User.objects.filter(club=club).exclude(id=user.id)

    filtered_users = []
    for u in users:
        u_roles = UserCategoryRole.objects.filter(user=u).values_list("role", flat=True)
        u_is_coach_or_admin = any(r.lower() in ['coach', 'admin'] for r in u_roles)

        # Ak si tréner alebo admin, zobraz všetkých
        # Inak zobraz len trénerov a adminov
        if is_coach_or_admin or u_is_coach_or_admin:
            messages_between = Message.objects.filter(
                Q(sender=user, recipient=u) | Q(sender=u, recipient=user)
            )

            last_msg = messages_between.order_by("-timestamp").first()
            last_timestamp = last_msg.timestamp.isoformat() if last_msg else None
            has_unread = messages_between.filter(sender=u, recipient=user, read=False).exists()

            filtered_users.append({
                "id": u.id,
                "username": u.username,
                "full_name": f"{u.first_name} {u.last_name}".strip(),
                "last_message_timestamp": last_timestamp,
                "has_unread": has_unread,
                "number": u.number,
            })

    sorted_users = sorted(
        filtered_users,
        key=lambda x: x["last_message_timestamp"] or "",
        reverse=True
    )

    return Response(sorted_users)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_reaction(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    emoji = request.data.get('emoji')
    user = request.user

    if not emoji:
        return Response({"error": "Emoji is required."}, status=status.HTTP_400_BAD_REQUEST)

    # Skontroluj, či už existuje reakcia
    existing_reaction = MessageReaction.objects.filter(message=message, user=user).first()

    if existing_reaction:
        if existing_reaction.emoji == emoji:
            # rovnaká emoji → vymaž (toggle off)
            existing_reaction.delete()
            return Response({"deleted": True})
        else:
            # iná emoji → aktualizuj
            existing_reaction.emoji = emoji
            existing_reaction.save()
            return Response(MessageReactionSerializer(existing_reaction).data)
    else:
        # nová reakcia
        reaction = MessageReaction.objects.create(message=message, user=user, emoji=emoji)
        return Response(MessageReactionSerializer(reaction).data, status=status.HTTP_201_CREATED)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import User


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def users_in_club(request):
    club = request.user.club
    if not club:
        return Response([], status=400)

    users = User.objects.filter(club=club).order_by('-date_joined')
    data = []
    for u in users:
        roles = UserCategoryRole.objects.filter(user=u).values('role', 'category__id', 'category__name')
        data.append({
            "id": u.id,
            "username": u.username,
            "name": u.get_full_name(),
            "email": u.email,
            "date_joined": u.date_joined,
            "birth_date": u.birth_date,
            "roles": list(roles),
            'position': u.position.name if u.position else None,
        })
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def assign_role(request):
    try:
        user_id = int(request.data.get("user_id"))
        category_id = int(request.data.get("category_id"))
        role = str(request.data.get("role")).strip()
    except (TypeError, ValueError):
        return Response({"error": "Neplatné dáta – user_id a category_id musia byť čísla."}, status=400)

    if not user_id or not category_id or not role:
        return Response({"error": "Missing fields"}, status=400)

    obj, created = UserCategoryRole.objects.get_or_create(
        user_id=user_id,
        category_id=category_id,
        role=role
    )

    if created:
        User = get_user_model()
        user = User.objects.get(id=user_id)
        category = Category.objects.get(id=category_id)

        tokens = ExpoPushToken.objects.filter(user=user).values_list("token", flat=True)
        for token in tokens:
            try:
                send_push_notification(
                    token,
                    title="Nová rola priradená",
                    message=f"Bola ti priradená rola '{role}' v kategórii '{category.name}'."
                )
            except Exception as e:
                print(f"❌ Chyba pri notifikácii {user.username}: {e}")

    return Response({"success": True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remove_role(request):
    user_id = request.data.get("user_id")
    category_id = request.data.get("category_id")
    role = request.data.get("role")

    try:
        obj = UserCategoryRole.objects.get(user_id=user_id, category_id=category_id, role=role)
        obj.delete()
        return Response({"success": True})
    except UserCategoryRole.DoesNotExist:
        return Response({"error": "Not found"}, status=404)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def categories_in_club(request):
    club = request.user.club
    if not club:
        return Response({"error": "Používateľ nemá priradený klub."}, status=400)

    categories = Category.objects.filter(club=club).order_by("name")
    data = [{"id": c.id, "name": c.name} for c in categories]
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_players_view(request):
    user = request.user
    coach_roles = UserCategoryRole.objects.filter(user=user, role='coach')
    category_ids = coach_roles.values_list('category_id', flat=True)

    users = User.objects.filter(
        roles__category_id__in=category_ids,
        roles__role='player'
    ).distinct().order_by('last_name')

    result = []
    for u in users:
        user_roles = UserCategoryRole.objects.filter(user=u, role='player', category_id__in=category_ids)
        result.append({
            'id': u.id,
            'name': u.get_full_name(),
            'birth_date': u.birth_date,
            'categories': list(user_roles.values('category__id', 'category__name')),
        })

    return Response(result)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def all_players_with_roles(request):
    user = request.user
    coach_roles = UserCategoryRole.objects.filter(user=user, role='coach')
    category_ids = coach_roles.values_list('category_id', flat=True)

    users = User.objects.exclude(id=user.id).order_by('-date_joined')

    result = []
    for u in users:
        player_roles = UserCategoryRole.objects.filter(user=u, role='player')
        result.append({
            'id': u.id,
            'name': u.get_full_name(),
            'birth_date': u.birth_date,
            'categories': list(player_roles.values('category__id', 'category__name')),
        })
    return Response(result)

#VYMAZAT PO UPDATE, TRENINGY SCREEN V HRACOVI
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_trainings_history_view(request):
    user = request.user
    club = user.club

    # Tréningy z aktuálnych kategórií, kde má rolu player
    current_categories = Category.objects.filter(user_roles__user=user, user_roles__role='player')
    trainings_from_roles = Training.objects.filter(
        club=club,
        category__in=current_categories
    )

    # Tréningy, kde má user zaznamenanú dochádzku (aj ak už nemá rolu)
    trainings_from_attendance = Training.objects.filter(
        club=club,
        attendances__user=user
    )

    # Spojíme obe množiny
    all_trainings = (trainings_from_roles | trainings_from_attendance).select_related(
        'category'
    ).prefetch_related(
        'attendances'
    ).order_by('date').distinct()

    serializer = TrainingSerializer(all_trainings, many=True, context={'request': request})
    return Response(serializer.data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import Position
from .serializers import PositionSerializer

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def positions_list(request):
    positions = Position.objects.all()
    serializer = PositionSerializer(positions, many=True)
    return Response(serializer.data)


from .serializers import MatchParticipationCreateSerializer

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import Match, MatchParticipation


from itertools import chain
from operator import attrgetter

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_matches_view(request):
    user = request.user
    try:
        categories = user.roles.filter(role='player').values_list('category_id', flat=True)

        matches = Match.objects.filter(category_id__in=categories)
        participations = MatchParticipation.objects.filter(user=user).select_related('match')
        participated_matches = Match.objects.filter(id__in=participations.values_list('match_id', flat=True))

        combined = list(chain(matches, participated_matches))

        # Odstránenie duplicít podľa ID
        unique_matches_dict = {match.id: match for match in combined}
        unique_matches = list(unique_matches_dict.values())

        # Zoradenie podľa dátumu zostupne
        sorted_matches = sorted(unique_matches, key=attrgetter('date'), reverse=True)

        serializer = MatchSerializer(sorted_matches, many=True, context={'request': request})

        # ⬅️ pridáme info o locknutí
        club = user.club  # ak má user priamo FK na club
        vote_lock_days = getattr(club, "vote_lock_days", 0)

        return Response({
            "matches": serializer.data,
            "vote_lock_days": vote_lock_days
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


from itertools import chain
from operator import attrgetter
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from .models import Match, MatchParticipation
from .serializers import MatchSerializer

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_matches_view(request):
    """
    Vracia zápasy trénera podľa jeho kategórií + účasti.
    Podporuje query parameter ?filter=upcoming|past|all
    (predvolený = upcoming)
    """
    user = request.user
    try:
        categories = user.roles.filter(role='coach').values_list('category_id', flat=True)
        matches = Match.objects.filter(category_id__in=categories)
        participations = MatchParticipation.objects.filter(user=user).select_related('match')
        participated_matches = Match.objects.filter(id__in=participations.values_list('match_id', flat=True))

        # Spojenie a odstránenie duplicít
        combined = list(chain(matches, participated_matches))
        unique_matches_dict = {match.id: match for match in combined}
        unique_matches = list(unique_matches_dict.values())

        # 🔹 Filtrovanie podľa času
        now = timezone.now()
        filter_param = request.GET.get('filter', 'upcoming')

        if filter_param == 'upcoming':
            unique_matches = [m for m in unique_matches if m.date >= now]
        elif filter_param == 'past':
            unique_matches = [m for m in unique_matches if m.date < now]
        # ak "all" → nenecháme žiadny filter

        # 🔹 Zoradenie
        sorted_matches = sorted(unique_matches, key=attrgetter('date'), reverse=True)

        serializer = MatchSerializer(sorted_matches, many=True, context={'request': request})
        return Response(serializer.data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_match_participation(request):
    serializer = MatchParticipationCreateSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response({'status': 'saved'})
    return Response(serializer.errors, status=400)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from .serializers import MatchSerializer,MatchDetailSerializer
from .tasks import notify_match_created, notify_match_deleted,notify_nomination_changed,notify_match_updated
from django.db import transaction


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_match_view(request):
    user = request.user
    club = user.club
    category_ids = request.data.get("category_ids", [])

    if not category_ids:
        return Response({"error": "Pole 'category_ids' je povinné."}, status=400)

    created_matches = []

    try:
        with transaction.atomic():
            for category_id in category_ids:
                match_data = {
                    "date": request.data.get("date"),
                    "location": request.data.get("location"),
                    "opponent": request.data.get("opponent"),
                    "description": request.data.get("description"),
                    "category": category_id,
                    "is_home": request.data.get("is_home", False),
                }

                serializer = MatchSerializer(data=match_data, context={"request": request})
                serializer.is_valid(raise_exception=True)

                match = serializer.save(club=club)  # ✅ ulož
                created_matches.append(MatchSerializer(match, context={"request": request}).data)  # ✅ bezpečne získaš data

                notify_match_created.delay(match.id)

        return Response(created_matches, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)

from django.contrib.auth import get_user_model

User = get_user_model()
from django.contrib.auth import get_user_model

User = get_user_model()


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import UserCategoryRole, Category, Role
from django.contrib.auth import get_user_model

User = get_user_model()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def jersey_numbers_view(request):
    user_club = request.user.club
    categories = Category.objects.filter(club=user_club)

    result = []

    for category in categories:
        player_user_ids = UserCategoryRole.objects.filter(
            category=category,
            role=Role.PLAYER
        ).values_list("user_id", flat=True)

        used_numbers = (
            User.objects
            .filter(id__in=player_user_ids)
            .exclude(number__isnull=True)
            .exclude(number="")
            .values_list("number", flat=True)
        )

        valid_numbers = []
        for n in used_numbers:
            try:
                num = int(n)
                if 1 <= num <= 99:
                    valid_numbers.append(num)
            except ValueError:
                continue

        result.append({
            "category": category.name,
            "used_numbers": sorted(valid_numbers)
        })

    # Ak sa zada query param all=true, vrátime všetky čísla z klubu
    if request.query_params.get("all") == "true":
        used_numbers = (
            User.objects
            .filter(club=user_club)
            .exclude(number__isnull=True)
            .exclude(number="")
            .values_list("number", flat=True)
        )

        valid_numbers = []
        for n in used_numbers:
            try:
                num = int(n)
                if 1 <= num <= 99:
                    valid_numbers.append(num)
            except ValueError:
                continue

        return Response({"all": sorted(valid_numbers)})

    return Response(result)

# views_documents.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import ClubDocument

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def club_documents_view(request):
    documents = ClubDocument.objects.filter(club=request.user.club).order_by('-uploaded_at')
    return Response([
        {
            "id": doc.id,
            "title": doc.title,
            "file": request.build_absolute_uri(doc.file.url),
            "uploaded_at": doc.uploaded_at.strftime("%d.%m.%Y"),
        }
        for doc in documents
    ])


from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.decorators import api_view, parser_classes
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from .models import ClubDocument

User = get_user_model()


from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

@api_view(['POST'])
@parser_classes([MultiPartParser])
@permission_classes([IsAuthenticated])   # ← použijeme DRF permission
def upload_document(request):
    user = request.user   # ← Django už vyrieši token podľa hlavičky

    file = request.FILES.get('file')
    title = request.POST.get('title')

    if file and title:
        ClubDocument.objects.create(
            club=user.club,
            title=title,
            file=file
        )
        return Response({"detail": "Upload successful"})

    return Response({"detail": "Missing file or title"}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def match_detail_view(request, match_id):
    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({"error": "Match not found"}, status=404)

    nominations_exist = MatchNomination.objects.filter(match=match).exists()
    serializer = MatchDetailSerializer(match, context={"nominations_exist": nominations_exist})
    return Response(serializer.data)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from .serializers import MatchParticipantSerializer
from datetime import datetime


# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Match, MatchNomination
from .serializers import MatchNominationSerializer, MatchNominationUpdateSerializer
from django.contrib.auth import get_user_model

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from .models import Match, MatchNomination
from .serializers import MatchNominationSerializer
from .tasks import notify_nomination_changed, notify_nomination_removed
from django.db import transaction

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def match_nominations_view(request, match_id):
    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({"error": "Zápas neexistuje"}, status=404)

    User = get_user_model()

    if request.method == "GET":
        nominations = MatchNomination.objects.filter(match=match)

        all_players = User.objects.filter(
            roles__category=match.category,
            roles__role='player',
            club=match.club
        ).distinct()

        nominated_user_ids = nominations.values_list("user_id", flat=True)
        nominated_serialized = MatchNominationSerializer(nominations, many=True).data

        non_nominated_players = all_players.exclude(id__in=nominated_user_ids)
        non_nominated_data = [
            {
                "user_id": p.id,
                "name": p.get_full_name() or p.username,
                "number": p.number,
                "birth_date": p.birth_date.strftime("%d.%m.%Y") if p.birth_date else None,
            }
            for p in non_nominated_players
        ]

        return Response({
            "match_id": match.id,
            "location": match.location,
            "date": match.date,
            "nominations": nominated_serialized + non_nominated_data
        })

    elif request.method == "POST":
        data = request.data.get("nominations", [])
        if not isinstance(data, list):
            return Response({"error": "Očakáva sa zoznam nominácií."}, status=400)

        # Staré nominácie pred zmazaním
        old_user_ids = list(MatchNomination.objects.filter(match=match).values_list("user_id", flat=True))

        MatchNomination.objects.filter(match=match).delete()

        new_nominations = []
        starter_ids = []
        sub_ids = []

        for item in data:
            user_id = item["user"]
            is_sub = item.get("is_substitute", False)
            new_nominations.append(MatchNomination(
                match=match,
                user_id=user_id,
                is_substitute=is_sub,
                rating=item.get("rating"),
                goals=item.get("goals", 0),
                plus_minus=item.get("plus_minus", 0),
            ))

            if is_sub:
                sub_ids.append(user_id)
            else:
                starter_ids.append(user_id)

        with transaction.atomic():
            MatchNomination.objects.bulk_create(new_nominations)

        new_user_ids = [item["user"] for item in data]
        removed_ids = list(set(old_user_ids) - set(new_user_ids))

        notify_nomination_changed.delay(match.id, starter_ids + sub_ids)
        if removed_ids:
            notify_nomination_removed.delay(match.id, removed_ids)

        return Response({"success": "Nominácia bola uložená"})
from django.utils import timezone
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def player_nominated_matches_view(request):
    user = request.user

    nominations = MatchNomination.objects.filter(
        user=user,
        match__date__gt=timezone.now(),
        match__club=user.club  # ← ak máš multi-klub systém
    ).select_related("match").distinct()

    results = []
    for nomination in nominations:
        match = nomination.match
        results.append({
            "id": match.id,
            "date": match.date,
            "location": match.location,
            "opponent": match.opponent,
            "category": match.category.id,
            "category_name": match.category.name,
            "description": match.description,
            "is_substitute": nomination.is_substitute,
            "confirmed": nomination.confirmed,
        })

    return Response(results)

# views.py

from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])  # ⬅⬅⬅ DÔLEŽITÉ
def match_participation_view(request):
    print("RAW DATA:", request.body)
    print("PARSED DATA:", request.data)

    user = request.user
    match_id = request.data.get("match_id")
    confirmed = request.data.get("confirmed")

    if match_id is None or confirmed is None:
        return Response({"error": "Chýbajú údaje"}, status=400)

    if isinstance(confirmed, str):
        confirmed = confirmed.lower() == 'true'

    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({"error": "Zápas neexistuje"}, status=404)

    nomination, _ = MatchNomination.objects.get_or_create(match=match, user=user)
    nomination.confirmed = confirmed
    nomination.save()

    return Response({"success": "Účasť bola uložená"})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def match_stats_view(request, match_id):
    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({"error": "Zápas neexistuje"}, status=404)

    if request.method == "GET":
        nominations = MatchNomination.objects.filter(match=match).select_related('user')
        serializer = MatchNominationUpdateSerializer(nominations, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        nominations_data = request.data.get("nominations", [])

        for entry in nominations_data:
            user_id = entry.get("user")
            if not user_id:
                continue  # bezpečnostná kontrola

            try:
                nomination = MatchNomination.objects.get(match=match, user_id=user_id)
                nomination.rating = entry.get("rating")
                nomination.plus_minus = entry.get("plus_minus")
                nomination.goals = entry.get("goals", 0)  # ak používaš
                nomination.save()
            except MatchNomination.DoesNotExist:
                continue  # neukladaj nič novému hráčovi

        return Response({"success": "Štatistiky boli uložené"})


# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from .models import Match

def user_is_admin_or_match_coach(user, category_id: int) -> bool:
    return user.roles.filter(
        Q(role='admin') | Q(role='coach', category_id=category_id)
    ).exists()

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def match_delete_view(request, match_id: int):
    match = get_object_or_404(Match, id=match_id)

    if not user_is_admin_or_match_coach(request.user, match.category_id):
        return Response({"detail": "Nemáš oprávnenie zmazať tento zápas."}, status=403)

    try:
        # pošli všetko, čo budeš potrebovať, lebo zápas sa zmaže
        notify_match_deleted.delay(match.opponent, match.category_id, match.club_id)
        match.delete()
    except ProtectedError:
        return Response(
            {"detail": "Zápas má naviazané dáta (napr. štatistiky/účasti) a nie je možné ho zmazať."},
            status=409
        )

    return Response(status=204)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Training
from .serializers import TrainingUpdateSerializer
from dochadzka_app.tasks import send_training_updated_notification


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def training_update_view(request, training_id):
    try:
        training = Training.objects.get(id=training_id)
    except Training.DoesNotExist:
        return Response({'error': 'Tréning neexistuje'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = TrainingUpdateSerializer(training)
        return Response(serializer.data)

    if request.method == 'PUT':
        serializer = TrainingUpdateSerializer(training, data=request.data)
        if serializer.is_valid():
            updated_training = serializer.save()

            # prepočíta automatické reminders podľa aktuálneho nastavenia kategórie
            rebuild_training_vote_reminders(updated_training)

            # notifikácia o zmene tréningu
            send_training_updated_notification.delay(updated_training.id)

            return Response(TrainingUpdateSerializer(updated_training).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from .models import User, Category, UserCategoryRole

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def assign_players_to_category(request):
    category_id = request.data.get("category_id")
    player_ids = request.data.get("player_ids", [])

    if not category_id:
        return Response({"error": "category_id je povinný"}, status=400)

    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        return Response({"error": "Kategória neexistuje"}, status=404)

    # Získaj všetky existujúce role pre túto kategóriu
    existing_roles = UserCategoryRole.objects.filter(
        category=category,
        role="player"
    )

    existing_user_ids = set(existing_roles.values_list("user_id", flat=True))
    new_user_ids = set(player_ids)

    # Pridaj nových hráčov
    to_add = new_user_ids - existing_user_ids
    for user_id in to_add:
        UserCategoryRole.objects.create(
            user_id=user_id,
            category=category,
            role="player"
        )

    # Odstráň hráčov, ktorí už nemajú byť v kategórii
    to_remove = existing_user_ids - new_user_ids
    UserCategoryRole.objects.filter(
        category=category,
        role="player",
        user_id__in=to_remove
    ).delete()

    return Response({"success": True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_preferred_role(request):
    role = request.data.get("preferred_role")
    if role not in ['player', 'coach', 'admin']:
        return Response({"error": "Invalid role"}, status=400)

    request.user.preferred_role = role
    request.user.save()
    return Response({"success": True})


@api_view(['GET'])
@permission_classes([AllowAny])
def club_detail(request, club_id):
    try:
        club = Club.objects.get(id=club_id)
    except Club.DoesNotExist:
        return Response({"error": "Club not found"}, status=404)

    data = {
        "id": club.id,
        "name": club.name,
        "description": club.description,
        "address": club.address,
        "phone": club.phone,
        "email": club.email,
        "contact_person": club.contact_person,
        "iban": club.iban,
    }
    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count, Q
from .models import User
from .models import TrainingAttendance, Training

from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count, Q
from .models import Training, TrainingAttendance
from .models import User


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def coach_attendance_summary(request):
    user = request.user
    trainings = Training.objects.none()  # len pre typový check (Pylance)

    # 🔹 1. Získaj všetky kategórie, kde má tréner rolu 'coach'
    coach_roles = user.roles.filter(role="coach")
    category_ids = list(coach_roles.values_list("category__id", flat=True).distinct())

    if not category_ids:
        return Response([])

    # 🔹 2. Filtrovanie parametrov
    month = request.GET.get("month")
    season = request.GET.get("season")
    category_param = request.GET.get("category")

    # 🔹 3. Načítaj hráčov podľa filtra
    player_filter = Q(roles__category__id__in=category_ids, roles__role="player")
    if category_param:
        player_filter &= Q(roles__category__name=category_param)

    players = (
        User.objects.filter(player_filter)
        .distinct()
        .select_related("position")
    )

    # 🔹 4. Filtrovanie tréningov
    training_filter = Q(category_id__in=category_ids)

    if category_param:
        training_filter &= Q(category__name=category_param)

    if month:
        try:
            training_filter &= Q(date__month=int(month))
        except ValueError:
            pass

    if season:
        try:
            start_year, end_year = map(int, season.split("/"))
            training_filter &= Q(date__year__in=[start_year, end_year])
        except ValueError:
            pass

    # ✅ Reálne načítanie tréningov
    trainings = (
        Training.objects.filter(training_filter)
        .select_related("category")
        .only("id", "category_id", "category__name", "date")
    )

    # Ak nie sú žiadne tréningy, vráť prázdnu odpoveď
    if not trainings.exists():
        return Response([])

    # ✅ Počet tréningov v každej kategórii
    category_training_counts = {
        item["category_id"]: item["total_count"]
        for item in trainings.values("category_id").annotate(total_count=Count("id"))
    }

    # 🔹 5. Vyber všetky attendance záznamy v tomto rozsahu
    attendance_qs = TrainingAttendance.objects.filter(
        training__in=trainings, user__in=players
    ).values("user_id", "training__category_id", "status")

    # 🔹 6. Počítaj počet "present" účastí pre každého hráča podľa kategórie
    attendance_map = {}
    for att in attendance_qs:
        if att["status"] != "present":
            continue
        key = (att["user_id"], att["training__category_id"])
        attendance_map[key] = attendance_map.get(key, 0) + 1

    # 🔹 7. Zloženie výsledku
    result = []
    for player in players:
        player_data = {
            "player_id": player.id,
            "name": f"{player.first_name} {player.last_name}",
            "birth_date": player.birth_date,
            "position": player.position.name if player.position else None,
            "number": player.number,
            "categories": [],
            "overall_attendance": 0.0,
        }

        player_roles = player.roles.filter(role="player", category_id__in=category_ids)
        total_percent_sum = 0.0
        total_categories = 0

        for role in player_roles:
            cat_id = role.category_id
            if not cat_id or cat_id not in category_training_counts:
                continue

            total_trainings = category_training_counts.get(cat_id, 0)
            present_count = attendance_map.get((player.id, cat_id), 0)

            if total_trainings == 0:
                continue

            percent = round((present_count / total_trainings) * 100, 1)
            player_data["categories"].append(
                {
                    "category_id": cat_id,
                    "category_name": role.category.name if role.category else None,
                    "attendance_percentage": percent,
                    "last_training_date": trainings.filter(category_id=cat_id)
                    .order_by("-date")
                    .values_list("date", flat=True)
                    .first(),
                }
            )

            total_percent_sum += percent
            total_categories += 1

        # 🔸 Ak hráč nemá žiadne kategórie po filtrovaní, preskoč
        if not player_data["categories"]:
            continue

        if total_categories > 0:
            player_data["overall_attendance"] = round(
                total_percent_sum / total_categories, 1
            )

        result.append(player_data)

    # 🔹 8. Usporiadaj hráčov podľa čísla (ak majú)
    result.sort(
        key=lambda p: (
            -p.get("overall_attendance", 0),  # zostupne podľa dochádzky
            int(p.get("number") or 0)         # sekundárne podľa čísla
        )
    )
    return Response(result)


from datetime import date, datetime

from datetime import date
from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import User
from .models import Training, TrainingAttendance


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_attendance_detail(request, player_id):
    user = request.user
    coach_roles = user.roles.filter(role='coach')
    coach_category_ids = set(coach_roles.values_list('category__id', flat=True))

    try:
        player = User.objects.get(id=player_id)
    except User.DoesNotExist:
        return Response({'error': 'Player not found'}, status=404)

    # kategórie hráča
    player_categories = player.roles.filter(role='player')
    player_category_ids = set(player_categories.values_list('category__id', flat=True))

    # overenie oprávnenia
    if not coach_category_ids.intersection(player_category_ids):
        return Response({'error': 'Unauthorized'}, status=403)

    # 🔥 query params pre filter
    month = request.GET.get('month')   # napr. "0-11"
    season = request.GET.get('season') # napr. "2024/2025"

    season_start, season_end = None, None
    if season:
        try:
            start_year = int(season.split('/')[0])
            season_start = date(start_year, 6, 1)           # 1. jún
            season_end = date(start_year + 1, 5, 31)        # 31. máj
        except Exception:
            pass

    response_data = {
        "player_id": player.id,
        "name": f"{player.first_name} {player.last_name}",
        "number": player.number,
        "birth_date": player.birth_date,
        "email": player.email,
        "email_2": player.email_2,
        "height": player.height,
        "weight": player.weight,
        "side": player.side,
        "position": player.position.name if player.position else None,
        "categories": [],
        "trainings": [],
        "absence_reasons": []
    }

    # Všetky tréningy, ktoré tréner môže vidieť
    all_trainings = Training.objects.filter(category_id__in=coach_category_ids)

    if season_start and season_end:
        all_trainings = all_trainings.filter(date__range=(season_start, season_end))
    if month is not None and month.isdigit():
        all_trainings = all_trainings.filter(date__month=int(month) + 1)

    # 🔹 Agregácia dôvodov neúčasti
    absence_stats = (
        TrainingAttendance.objects.filter(
            user=player,
            training__in=all_trainings,
            status="absent"
        )
        .values("reason")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    response_data["reason"] = [
        {"reason": item["reason"] or "Nezadané", "count": item["count"]}
        for item in absence_stats
    ]

    # pre každú kategóriu hráča, kde tréner má prístup
    for role in player_categories:
        category = role.category
        if category.id not in coach_category_ids:
            continue

        trainings = Training.objects.filter(category=category)

        # aplikuj filter sezóna
        if season_start and season_end:
            trainings = trainings.filter(date__range=(season_start, season_end))

        # aplikuj filter mesiac
        if month is not None and month.isdigit():
            trainings = trainings.filter(date__month=int(month) + 1)

        trainings = trainings.order_by('-date')

        total = trainings.count()
        present = TrainingAttendance.objects.filter(user=player, training__in=trainings, status='present').count()
        absent = TrainingAttendance.objects.filter(user=player, training__in=trainings, status='absent').count()
        unknown = total - present - absent

        if total == 0:
            continue

        percent = round((present / total) * 100, 1)

        response_data['categories'].append({
            'category_id': category.id,
            'category_name': category.name,
            'present': present,
            'absent': absent,
            'unknown': unknown,
            'total': total,
            'percentage': percent
        })

        # detail tréningov
        for tr in trainings:
            try:
                attendance = TrainingAttendance.objects.get(user=player, training=tr)
                status = attendance.status
            except TrainingAttendance.DoesNotExist:
                status = "unknown"

            response_data['trainings'].append({
                "id": tr.id,
                "date": tr.date.strftime("%Y-%m-%d"),
                "time": tr.date.strftime("%H:%M"),
                "location": tr.location,
                "category": category.name,
                "status": status,
                "players_present": TrainingAttendance.objects.filter(training=tr, status="present").count(),
                "players_total": TrainingAttendance.objects.filter(training=tr).count(),
            })

    return Response(response_data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import ClubPaymentSettings, MemberPayment
from .serializers import ClubPaymentSettingsSerializer, MemberPaymentSerializer

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def club_payment_settings_list(request):
    if request.method == 'GET':
        settings = ClubPaymentSettings.objects.all()
        serializer = ClubPaymentSettingsSerializer(settings, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ClubPaymentSettingsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import ClubPaymentSettings
from .serializers import ClubPaymentSettingsSerializer


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])  # ← zmenené z IsAdminUser
def club_payment_settings_detail(request, pk):
    setting = get_object_or_404(ClubPaymentSettings, pk=pk)

    if request.method == 'GET':
        serializer = ClubPaymentSettingsSerializer(setting)
        return Response(serializer.data)

    # PUT/DELETE len pre admina
    if not request.user.is_staff:
        return Response({"detail": "Len admin môže upravovať nastavenia."}, status=403)

    if request.method == 'PUT':
        serializer = ClubPaymentSettingsSerializer(setting, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        setting.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def member_payments(request):
    user = request.user
    show_all = request.query_params.get('all') == 'true'

    # Iba ak má rolu admin a chce všetko
    is_admin = user.roles.filter(role="admin").exists()  # uprav podľa svojho modelu

    if show_all and is_admin:
        payments = MemberPayment.objects.all()
    else:
        payments = MemberPayment.objects.filter(user=user)

    serializer = MemberPaymentSerializer(payments, many=True)
    return Response(serializer.data)

from dochadzka_app.tasks import notify_created_member_payment, notify_payment_status

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_member_payments(request):
    club = request.user.club
    try:
        settings = ClubPaymentSettings.objects.get(club=club)
    except ClubPaymentSettings.DoesNotExist:
        return Response({"error": "Klub nemá nastavené platobné údaje."}, status=400)

    amount = request.data.get("amount")
    due_date = request.data.get("due_date")
    category_id = request.data.get("category_id")
    user_id = request.data.get("user_id")
    description = request.data.get("description", "")  # <- pridaj túto riadku

    if not amount or not due_date:
        return Response({"error": "Zadaj amount a due_date."}, status=400)

    # výber používateľov
    if user_id:
        users = User.objects.filter(id=user_id, club=club)
    elif category_id:
        user_ids = UserCategoryRole.objects.filter(
            category_id=category_id,
            role='player'
        ).values_list('user_id', flat=True)
        users = User.objects.filter(id__in=user_ids, club=club)
    else:
        users = User.objects.filter(club=club)

    created = []
    for user in users:
        variable_symbol = f"{settings.variable_symbol_prefix}{user.id:04d}"
        payment = MemberPayment.objects.create(
            user=user,
            club=club,
            amount=amount,
            due_date=due_date,
            variable_symbol=variable_symbol,
            is_paid=False,
            description=description  # <- a túto
        )
        notify_created_member_payment.delay(user.id, amount, due_date)
        created.append(payment.id)

    return Response({"created_payments": created}, status=201)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_member_payment(request, pk):
    payment = get_object_or_404(MemberPayment, pk=pk)
    serializer = MemberPaymentSerializer(payment, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT'])
@permission_classes([IsAdminUser])
def admin_member_payments(request):
    if request.method == 'GET':
        payments = MemberPayment.objects.select_related('user').filter(club=request.user.club)
        data = [
            {
                "id": p.id,
                "amount": str(p.amount),
                "due_date": p.due_date,
                "is_paid": p.is_paid,
                "description": p.description,
                "variable_symbol": p.variable_symbol,
                "user": {
                    "id": p.user.id,
                    "name": f"{p.user.first_name} {p.user.last_name}".strip() or p.user.username,
                    "username": p.user.username,
                },
            }
            for p in payments
        ]
        return Response(data)

    elif request.method == 'PUT':
        # 🔥 Ak príde zoznam
        if isinstance(request.data, list):
            updated = []
            for item in request.data:
                payment_id = item.get("id")
                is_paid = item.get("is_paid")

                if payment_id is None or is_paid is None:
                    continue

                try:
                    payment = MemberPayment.objects.get(id=payment_id, club=request.user.club)
                    payment.is_paid = is_paid
                    payment.save()
                    notify_payment_status.delay(
                        user_id=payment.user.id,
                        is_paid=is_paid,
                        amount=str(payment.amount),
                        vs=payment.variable_symbol
                    )
                    updated.append(payment_id)
                except MemberPayment.DoesNotExist:
                    continue

            return Response({"success": True, "updated": updated})

        # 🔥 Ak príde iba jeden objekt
        else:
            payment_id = request.data.get("id")
            is_paid = request.data.get("is_paid")

            if payment_id is None or is_paid is None:
                return Response({"error": "Chýbajú údaje."}, status=400)

            try:
                payment = MemberPayment.objects.get(id=payment_id, club=request.user.club)
                payment.is_paid = is_paid
                payment.save()
                notify_payment_status.delay(
                    user_id=payment.user.id,
                    is_paid=is_paid,
                    amount=str(payment.amount),
                    vs=payment.variable_symbol
                )
                return Response({"success": True, "updated": [payment_id]})
            except MemberPayment.DoesNotExist:
                return Response({"error": "Platba neexistuje."}, status=404)


from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.parsers import MultiPartParser
import csv, io


import os
import json
import pdfplumber
from openai import OpenAI
from django.core.files.storage import default_storage
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .models import MemberPayment

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_pdf_statement_chatgpt(request):
    file = request.FILES.get("file")
    if not file:
        return Response({"error": "Súbor nebol priložený"}, status=400)

    # Uložíme PDF
    file_path = default_storage.save(f"bank_statements/{file.name}", file)
    full_path = default_storage.path(file_path)

    # Načítame text z PDF
    text = ""
    try:
        with pdfplumber.open(full_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        return Response({"error": f"Chyba pri čítaní PDF: {str(e)}"}, status=500)

    if not text.strip():
        return Response({"error": "Výpis z PDF je prázdny alebo nečitateľný."}, status=400)

    # Inicializujeme klienta OpenAI
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    except Exception as e:
        return Response({"error": f"Chyba pri inicializácii OpenAI klienta: {str(e)}"}, status=500)

    # Pripravíme prompt
    prompt = f"""
Toto je výpis z banky. Nájdi všetky prichádzajúce transakcie, ktoré obsahujú:
- variabilný symbol (VS)
- sumu v eurách
- dátum

Vráť to ako **platný JSON zoznam** s kľúčmi: vs, amount, date. Nepridávaj žiaden komentár ani text mimo JSON.

[
  {{
    "vs": "123456",
    "amount": 25.50,
    "date": "2025-08-01"
  }},
  ...
]

Tu je výpis:
{text}
"""

    # Zavoláme AI
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Si expert na bankové transakcie."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=1000
        )

        extracted_data = response.choices[0].message.content.strip()

        # Odstráň markdown kódový blok ak je tam
        if extracted_data.startswith("```") and extracted_data.endswith("```"):
            extracted_data = "\n".join(extracted_data.split("\n")[1:-1]).strip()

        if not extracted_data:
            return Response({
                "error": "AI nevrátilo žiadny obsah.",
                "raw_response": str(response)
            }, status=500)

        try:
            data = json.loads(extracted_data)
        except json.JSONDecodeError as e:
            return Response({
                "error": f"Neplatný JSON z AI: {str(e)}",
                "raw_response": extracted_data
            }, status=500)

        # Spracujeme dáta
        matches = []
        for row in data:
            vs = str(row.get("vs", "")).strip()
            amount = float(str(row.get("amount", "0")).replace(",", "."))
            matched = MemberPayment.objects.filter(
                variable_symbol=vs,
                amount=amount,
                is_paid=False
            ).first()
            if matched:
                matched.is_paid = True
                matched.save()
                notify_payment_status.delay(user_id=matched.user.id, is_paid=True)
                matches.append({"id": matched.id, "vs": vs, "amount": amount})

        return Response({"message": f"Spracovaných: {len(matches)}", "matched": matches})

    except Exception as e:
        return Response({"error": f"Chyba pri spracovaní AI odpovede: {str(e)}"}, status=500)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q
from .models import Match
from .serializers import MatchSerializer
from .tasks import notify_match_updated


@api_view(['GET', 'PUT', 'PATCH'])  # podporuje načítanie aj úpravu
@permission_classes([IsAuthenticated])
def update_match_view(request, match_id):
    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({'error': 'Zápas neexistuje'}, status=404)

    if request.method == 'GET':
        serializer = MatchSerializer(match, context={"request": request})
        return Response(serializer.data)

    # PATCH / PUT – úprava zápasu
    is_authorized = request.user.roles.filter(
        Q(role='coach', category=match.category) | Q(role='admin')
    ).exists()

    if not is_authorized:
        return Response({"error": "Nemáš oprávnenie upraviť tento zápas."}, status=403)

    serializer = MatchSerializer(
        match,
        data=request.data,
        partial=True,
        context={"request": request}
    )

    if serializer.is_valid():
        serializer.save()
        notify_match_updated.delay(match.id)

        # serializuj znova po uložení (kvôli napr. .data a context)
        updated = MatchSerializer(match, context={"request": request})
        return Response(updated.data)

    return Response(serializer.errors, status=400)


from .tasks import remind_unknown_players,notify_match_reminder

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def remind_attendance_view(request):
    training_id = request.data.get("training_id")
    user_ids = request.data.get("user_ids", [])

    if not training_id or not isinstance(user_ids, list):
        return Response({"error": "Neplatné dáta"}, status=400)

    # Spusti Celery task
    remind_unknown_players.delay(training_id, user_ids)

    return Response({"status": "ok", "message": "Pripomienky sa odosielajú."})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remind_match_attendance_view(request):
    match_id = request.data.get("match_id")
    user_ids = request.data.get("user_ids", [])

    if not match_id or not isinstance(user_ids, list):
        return Response({"detail": "Neplatné dáta."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return Response({"detail": "Zápas neexistuje."}, status=status.HTTP_404_NOT_FOUND)

    if not user_is_admin_or_match_coach(request.user, match.category_id):
        return Response({"detail": "Nemáš oprávnenie."}, status=status.HTTP_403_FORBIDDEN)

    notify_match_reminder.delay(match_id, user_ids)
    return Response({"detail": "Notifikácie budú odoslané."})


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from .models import MemberPayment

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_member_payments_summary(request):
    if not hasattr(request.user, "club") or not request.user.club:
        return Response({"error": "Používateľ nemá priradený klub."}, status=400)

    club = request.user.club
    users = User.objects.filter(club=club)

    data = []
    for user in users:
        payments = MemberPayment.objects.filter(user=user)
        all_paid = all(p.is_paid for p in payments)

        data.append({
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "email": user.email or "",
            "email_2": getattr(user, "email_2", None) or getattr(user, "user", None) and getattr(user, "email_2", ""),
            "birth_date": getattr(user, "birth_date", None) or getattr(user, "user", None) and getattr(user, "birth_date", None),
            "number": getattr(user, "number", None) or getattr(user, "user", None) and getattr(user, "number", ""),
            "all_payments_paid": all_paid,
        })

    return Response(data)



# views.py
from collections import defaultdict
from django.db.models import Exists, OuterRef
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import User, MemberPayment, UserCategoryRole  # prispôsobiť ceste importov

from collections import defaultdict
from django.db.models import Exists, OuterRef
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import User, MemberPayment, UserCategoryRole


# views.py
from collections import defaultdict
from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import User, MemberPayment, UserCategoryRole


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def new_members_without_payments(request):
    """
    GET /api/new-members-without-payments/?role=player&scope=club|any

    - scope=any (default): vráti členov, ktorí NIKDY nemali žiadnu platbu (v akomkoľvek klube)
    - scope=club: vráti členov, ktorí NIKDY nemali žiadnu platbu v aktuálnom klube

    Výstup má rovnaký tvar ako users_in_club.
    """
    club = getattr(request.user, 'club', None)
    if not club:
        return Response([], status=400)

    scope = request.query_params.get('scope', 'any')  # 'any' | 'club'

    qs = (
        User.objects
        .filter(club=club)
        .select_related('position')
        .order_by('-date_joined')
    )

    # spočítaj platby podľa zvoleného scope
    if scope == 'club':
        qs = qs.annotate(
            payments_count=Count(
                'memberpayment',
                filter=Q(memberpayment__club_id=club.id),
                distinct=True,
            )
        )
    else:  # 'any' (default)
        qs = qs.annotate(
            payments_count=Count('memberpayment', distinct=True)
        )

    # nechceme nikoho, kto už má aspoň jednu platbu
    qs = qs.filter(payments_count=0)

    # voliteľný filter podľa roly (napr. ?role=player)
    role = request.query_params.get('role')
    if role:
        qs = qs.filter(usercategoryrole__role=role).distinct()

    users = list(qs)

    # načítaj roly hromadne (bez N+1)
    role_rows = (
        UserCategoryRole.objects
        .filter(user__in=users)
        .select_related('category')
        .values('user_id', 'role', 'category__id', 'category__name')
    )
    roles_map = defaultdict(list)
    for r in role_rows:
        roles_map[r['user_id']].append({
            'role': r['role'],
            'category__id': r['category__id'],
            'category__name': r['category__name'],
        })

    data = []
    for u in users:
        data.append({
            "id": u.id,
            "username": u.username,
            "name": u.get_full_name(),
            "email": u.email,
            "date_joined": u.date_joined,
            "birth_date": getattr(u, 'birth_date', None),
            "roles": roles_map.get(u.id, []),
            "position": u.position.name if getattr(u, 'position', None) else None,
        })

    return Response(data)


from rest_framework import permissions, status, generics
from rest_framework.response import Response
from .models import Order
from .serializers import OrderSerializer, OrderSerializer2

class OrderCreateView(generics.CreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        # ak máš kontext klubu na userovi, môžeš predvyplniť; tu očakávame club z requestu
        serializer.save(user=user)

class MyOrdersListView(generics.ListAPIView):
    serializer_class = OrderSerializer2
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by("-created_at")

from .models import Order
from .serializers import ClubOrderReadSerializer

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404

from rest_framework import status as http_status

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as http_status
from rest_framework.response import Response

from .models import Order
from .serializers import ClubOrderReadSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])  # v produkcii nahraď vlastnou IsClubAdmin
def club_orders_view(request, club_id: int):
    """
    GET /api/club-orders/<club_id>/?status=Nová
    GET /api/club-orders/<club_id>/?status__in=Nová,Spracováva sa,Objednaná
    """
    # ✅ kontrola, či má user prístup do tohto klubu
    if not request.user.is_superuser:
        if getattr(request.user, "club_id", None) != club_id:
            return Response({"detail": "Forbidden"}, status=http_status.HTTP_403_FORBIDDEN)

    qs = (
        Order.objects.filter(club_id=club_id)
        .select_related("user", "club")
        .prefetch_related("items")
        .order_by("-created_at")
    )

    # 1) ak je zadaný konkrétny status
    status_param = request.query_params.get("status")
    if status_param:
        qs = qs.filter(status=status_param)

    # 2) ak je zadané viac statusov
    status_in_param = request.query_params.get("status__in")
    if status_in_param:
        statuses = [s.strip() for s in status_in_param.split(",") if s.strip()]
        if statuses:
            qs = qs.filter(status__in=statuses)

    ser = ClubOrderReadSerializer(qs, many=True)
    return Response(ser.data, status=http_status.HTTP_200_OK)


# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from .models import Order,OrderItem
from .serializers import OrderUpdateSerializer
from .tasks import notify_order_paid, notify_order_status_changed


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from .models import OrderItem, OrderPayment
from .serializers import OrderItemSerializer, OrderUpdateSerializer, OrderPaymentSerializer, JerseyOrderSerializer


# dochadzka_app/views.py
from .tasks import notify_order_item_canceled  # pridaj import

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_order_item_view(request, item_id: int):
    item = get_object_or_404(OrderItem, pk=item_id)

    if item.order.user != request.user and not request.user.is_superuser:
        return Response({"detail": "Forbidden"}, status=http_status.HTTP_403_FORBIDDEN)

    if item.is_canceled:
        return Response({"detail": "Položka už bola zrušená"}, status=http_status.HTTP_400_BAD_REQUEST)

    item.is_canceled = True
    item.save()

    # 🔔 Push notifikácia pre vlastníka objednávky
    try:
        # bezpečný názov položky
        item_name = item.product_name or item.product_code or item.product_type or "Položka"
        notify_order_item_canceled.delay(
            user_id=item.order.user_id,
            order_id=item.order_id,
            item_name=str(item_name),
            quantity=int(item.quantity or 1),
            order_total=str(item.order.total_amount),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"notify_order_item_canceled spawn error: {e}")

    try:
        serialized_item = OrderItemSerializer(item)
        print("==> Serializer OK:", serialized_item.data)
    except Exception as e:
        import traceback
        print("==> Serializer ERROR:", str(e))
        traceback.print_exc()
        return Response({"detail": f"Serializer error: {str(e)}"}, status=500)

    return Response({
        "detail": "Položka bola zrušená",
        "item": serialized_item.data,
        "order_total": str(item.order.total_amount),
    }, status=http_status.HTTP_200_OK)




from django.db.models import Q

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def orders_payments(request):
    user = request.user
    show_all = request.query_params.get('all') == 'true'
    is_admin = user.roles.filter(role="admin").exists()

    if show_all and is_admin:
        payments = OrderPayment.objects.all()
    else:
        payments = OrderPayment.objects.filter(
            Q(order__user=user) | Q(jersey_order__user=user)   # 🔥 len jeho vlastné objednávky dresov
        )

    serializer = OrderPaymentSerializer(payments, many=True)
    return Response(serializer.data)
import io
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
import qrcode
from pay_by_square import generate  # funkcia z balíka
from .models import MemberPayment, OrderPayment

def payment_qr(request, payment_type, pk):
    if payment_type == "member":
        payment = get_object_or_404(MemberPayment, pk=pk)
        iban = payment.club.iban
        vs = payment.variable_symbol
        amount = float(payment.amount)
        message = payment.description or "Členský príspevok"
        date = payment.due_date

    elif payment_type == "order":
        payment = get_object_or_404(OrderPayment, pk=pk)
        iban = payment.iban
        vs = payment.variable_symbol
        amount = float(payment.amount)

        if payment.order:
            message = f"Objednávka #{payment.order.id}"
        elif payment.jersey_order:
            message = f"Dresová objednávka #{payment.jersey_order.id}"
        else:
            message = "Objednávka"

        date = None

    else:
        return HttpResponse("Neplatný typ platby", status=400)

    code_string = generate(
        amount=amount,
        iban=iban,
        variable_symbol=vs,
        note=message,
        date=date,
        currency="EUR",
    )

    qr_img = qrcode.make(code_string)
    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    buffer.seek(0)
    return HttpResponse(buffer, content_type="image/png")


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderPayment
from .tasks import notify_payment_assigned


from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_payment(request, order_id):
    """
    Vygeneruje alebo zaktualizuje platbu pre objednávku.
    IBAN, ktorý sa uloží, bude IBAN používateľa, ktorý túto platbu generuje (request.user).
    """
    order = get_object_or_404(Order, id=order_id)
    recipient = order.user  # vlastník objednávky

    generator = request.user  # kto platbu generuje
    if not getattr(generator, "iban", None):
        return Response({"error": "Generátor platby (request.user) nemá nastavený IBAN v profile"}, status=400)

    # ak chceš zároveň overiť, že len admin / konkrétny role môžu vytvárať platby:
    # if not (generator.is_staff or generator.has_role("admin")):
    #     return Response({"error": "Nemáš oprávnenie generovať platby"}, status=403)

    with transaction.atomic():
        payment, created = OrderPayment.objects.get_or_create(
            order=order,
            defaults={
                # user tu ponechám recipientom (vlastník objednávky),
                "user": recipient,
                # IBAN uložíme generatorov IBAN (ten, kto platbu generuje)
                "iban": generator.iban,
                "variable_symbol": str(order.id),
                "amount": order.total_amount,
                # prípadne ulož info, kto generoval, ak máš také pole:
                # "generated_by": generator,
            },
        )

        # ak už existuje, vždy aktualizujeme IBAN na IBAN generátora
        if not created:
            payment.iban = generator.iban
            payment.amount = order.total_amount
            payment.variable_symbol = str(order.id)
            # ak máš field generated_by, aktualizuj ho tiež:
            # payment.generated_by = generator
            payment.save()

    # notifikácia príjemcovi (vlastníkovi objednávky)
    try:
        notify_payment_assigned.delay(
            user_id=recipient.id,
            amount=str(payment.amount),
            vs=payment.variable_symbol,
            # môžete pridať informáciu kto platbu vytvoril:
            # generated_by_username=generator.username
        )
        logger.info(
            f"Notifikácia: platba {payment.amount}€ (VS {payment.variable_symbol}) "
            f"pre {recipient.username} odoslaná (vytvoril: {generator.username})"
        )
    except Exception as e:
        logger.error(f"Chyba pri spúšťaní notifikácie: {e}")

    return Response({
        "vs": payment.variable_symbol,
        "iban": payment.iban,
        "amount": str(payment.amount),
        "is_paid": payment.is_paid,
        # pridaj info o tom, kto platbu vytvoril
        "generated_by": generator.username,
    })

@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def orders_bulk_update(request):
    from django.utils.timezone import now
    data = request.data
    if not isinstance(data, list):
        return Response({"detail": "Očakáva sa zoznam objednávok"}, status=400)

    updated = []
    for entry in data:
        order = get_object_or_404(Order, pk=entry.get("id"))

        # uložíme pôvodné hodnoty pred update
        old_is_paid = getattr(order, "is_paid", False)
        old_status = getattr(order, "status", None)

        serializer = OrderUpdateSerializer(order, data=entry, partial=True)

        if serializer.is_valid():
            order = serializer.save()

            # 🔄 synchronizácia s OrderPayment
            if "is_paid" in entry:
                if hasattr(order, "payment"):
                    order.payment.is_paid = order.is_paid
                    order.payment.paid_at = now() if order.is_paid else None
                    order.payment.save()

   
                # 🔔 notifikácia IBA ak sa zmenilo na True
                if not old_is_paid and order.is_paid:
                    from .tasks import notify_order_paid
                    notify_order_paid.delay(order.user.id, str(order.total_amount), str(order.id))

            # 🔔 notifikácia IBA ak sa status zmenil
            if "status" in entry and old_status != order.status:
                from .tasks import notify_order_status_changed
                notify_order_status_changed.delay(order.user.id, order.status)

            updated.append(serializer.data)
        else:
            return Response(serializer.errors, status=400)

    return Response(updated, status=200)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Order, JerseyOrder

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def order_delete_view(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)

    # 🔒 Kontrola – môže zmazať iba vlastník alebo admin
    if request.user != order.user and not request.user.roles.filter(role="admin").exists():
        return Response({"detail": "Nemáš oprávnenie vymazať túto objednávku."}, status=403)

    target_user = order.user
    total_amount = str(order.total_amount)
    order.delete()

    # 🔔 Notifikácia po vymazaní
    try:
        from .tasks import notify_order_deleted
        notify_order_deleted.delay(target_user.id, str(order_id), total_amount)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Chyba pri spúšťaní notify_order_deleted: {e}")

    return Response({"detail": f"Objednávka {order_id} bola vymazaná."}, status=204)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def check_number(request, club_id, number: int):
    players = User.objects.filter(club_id=club_id, number=number)
    if players.exists():
        return Response({
            "taken": True,
            "players": [
                {"name": p.get_full_name(), "birth_year": p.birth_date.year if p.birth_date else ""}
                for p in players
            ]
        })
    return Response({"taken": False, "players": []})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_jersey_order(request):
    data = request.data.copy()
    data["user"] = request.user.id   # 🔥 priradíme prihláseného usera
    serializer = JerseyOrderSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def jersey_orders_list(request, club_id: int):
    user = request.user
    user_club_id = getattr(user, "club_id", None) or getattr(getattr(user, "profile", None), "club_id", None)

    # ak používateľ nemá klub, alebo sa pokúša načítať iný klub → odmietni
    if not user_club_id:
        return Response({"detail": "Používateľ nemá priradený klub."}, status=403)
    if user_club_id != club_id and not user.is_superuser:
        return Response({"detail": "Nemáš oprávnenie zobraziť objednávky iného klubu."}, status=403)

    qs = JerseyOrder.objects.filter(club_id=user_club_id).order_by("-created_at")
    serializer = JerseyOrderSerializer(qs, many=True)
    return Response(serializer.data)



# views.py
from .models import JerseyOrder
from .serializers import JerseyOrderSerializer

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def jersey_order_delete_view(request, order_id: int):
    order = get_object_or_404(JerseyOrder, pk=order_id)

    if not request.user.roles.filter(role="admin").exists():
        return Response({"detail": "Nemáš oprávnenie zmazať túto objednávku."}, status=403)

    order.delete()
    return Response({"detail": f"Objednávka dresu {order_id} bola vymazaná."}, status=204)


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def jersey_orders_bulk_update(request):
    """
    Aktualizuje viac objednávok dresov naraz.
    Očakáva list objektov: [{id, amount, is_paid}, ...]
    """
    from django.utils.timezone import now
    data = request.data
    if not isinstance(data, list):
        return Response({"detail": "Očakáva sa zoznam objednávok"}, status=400)

    updated = []
    for entry in data:
        order = get_object_or_404(JerseyOrder, pk=entry.get("id"))

        old_is_paid = order.is_paid

        serializer = JerseyOrderSerializer(order, data=entry, partial=True)
        if serializer.is_valid():
            order = serializer.save()

            # 🔄 synchronizácia s OrderPayment
            if "is_paid" in entry:
                if hasattr(order, "payment"):
                    order.payment.is_paid = order.is_paid
                    order.payment.paid_at = now() if order.is_paid else None
                    order.payment.save()
                else:
                    from .models import OrderPayment
                    payment, _ = OrderPayment.objects.get_or_create(
                        jersey_order=order,
                        defaults={
                            "user": request.user,
                            "iban": request.user.iban if hasattr(request.user, "iban") else "",
                            "variable_symbol": f"J{order.id}",
                            "amount": order.amount,
                            "is_paid": order.is_paid,
                            "paid_at": now() if order.is_paid else None,
                        },
                    )

                # 🔔 notifikácia iba ak sa zmenilo na True
                if not old_is_paid and order.is_paid:
                    from .tasks import notify_order_paid
                    notify_order_paid.delay(order.id, str(order.amount), f"J{order.id}")

            updated.append(order)
        else:
            return Response(serializer.errors, status=400)

    return Response(JerseyOrderSerializer(updated, many=True).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_jersey_payment(request, order_id):
    order = get_object_or_404(JerseyOrder, id=order_id)

    if not getattr(request.user, "iban", None):
        return Response({"error": "Nemáš nastavený IBAN v profile"}, status=400)

    from .models import OrderPayment
    payment, created = OrderPayment.objects.get_or_create(
        jersey_order=order,
        defaults={
            "user": request.user,
            "iban": request.user.iban,
            "variable_symbol": f"{order.id}",
            "amount": order.amount,
            "is_paid": order.is_paid,
        },
    )

    if not created:
        payment.iban = request.user.iban
        payment.amount = order.amount
        payment.save()

    return Response({
        "vs": payment.variable_symbol,
        "iban": payment.iban,
        "amount": str(payment.amount),
        "is_paid": payment.is_paid,
    })


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.core.mail import send_mail
from django.conf import settings
from .models import Order
from .serializers import OrderLudimusSerializer

@api_view(["POST"])
@permission_classes([AllowAny])
def create_order(request):
    serializer = OrderLudimusSerializer(data=request.data)
    if serializer.is_valid():
        order = serializer.save()

        # pošli mail adminovi
        subject = f"Nová objednávka balíka ({order.get_plan_display()})"
        message = (
            f"Názov klubu: {order.club_name}\n"
            f"Admin: {order.first_name} {order.last_name}\n"
            f"Email: {order.email}\n"
            f"Telefón: {order.phone}\n"
            f"Balík: {order.get_plan_display()}\n"
            f"Dátum: {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_user_from_club(request, user_id: int):
    """
    Vymaže používateľa z klubu (iba admin).
    """
    try:
        user_to_delete = get_object_or_404(User, pk=user_id)

        # kontrola – musí byť v rovnakom klube
        if not request.user.roles.filter(role="admin").exists():
            return Response({"detail": "Nemáš oprávnenie vymazať používateľov."}, status=status.HTTP_403_FORBIDDEN)

        if user_to_delete.club_id != request.user.club_id:
            return Response({"detail": "Používateľ nepatrí do tvojho klubu."}, status=status.HTTP_403_FORBIDDEN)

        user_to_delete.delete()
        return Response({"detail": f"Používateľ {user_to_delete.username} bol vymazaný."}, status=status.HTTP_204_NO_CONTENT)

    except Exception as e:
        return Response({"detail": f"Chyba pri mazaní: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from dochadzka_app.models import Category, Training

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def categories_admin(request):
    """
    GET → vráti zoznam kategórií klubu
    POST → vytvorí novú kategóriu v klube
    """
    user = request.user
    club = user.club

    if request.method == "GET":
        categories = Category.objects.filter(club=club).values("id", "name", "description")
        return Response(categories)

    if request.method == "POST":
        name = request.data.get("name")
        description = request.data.get("description", "")
        if not name:
            return Response({"detail": "Meno kategórie je povinné."}, status=400)

        category = Category.objects.create(club=club, name=name, description=description)
        return Response({"id": category.id, "name": category.name, "description": category.description}, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_category(request, category_id: int):
    """
    Vymaže kategóriu a všetky tréningy v nej
    """
    user = request.user
    category = get_object_or_404(Category, pk=category_id, club=user.club)

    # pri zmazaní sa cascaduju aj tréningy
    category.delete()

    return Response({"detail": "Kategória a jej tréningy boli vymazané."}, status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_vote_lock_days(request):
    user = request.user
    if not user.roles.filter(role="admin").exists():
        return Response({"detail": "Nemáš oprávnenie."}, status=403)

    days = request.data.get("vote_lock_days")
    try:
        days = int(days)
        if days < 0 or days > 30:
            return Response({"detail": "Neplatný rozsah (0–30 dní)"}, status=400)
    except:
        return Response({"detail": "Neplatná hodnota"}, status=400)

    club = user.club
    club.vote_lock_days = days
    club.save()
    return Response({"vote_lock_days": club.vote_lock_days})



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_training_lock_hours(request):
    user = request.user
    if not user.roles.filter(role="admin").exists():
        return Response({"error": "Unauthorized"}, status=403)

    try:
        hours = int(request.data.get("training_lock_hours"))
    except (TypeError, ValueError):
        return Response({"error": "Neplatná hodnota"}, status=400)

    club = user.club
    club.training_lock_hours = hours
    club.save()

    return Response({"training_lock_hours": club.training_lock_hours})



# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q

from .models import Announcement, AnnouncementRead
from .serializers import AnnouncementSerializer, AnnouncementReadSerializer

from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .tasks import send_announcement_notification

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def announcements_list(request):
    """
    Vráti všetky oznamy pre klub používateľa + podľa jeho kategórie (ak má).
    Optimalizované: počty sa rátajú na úrovni DB.
    """
    user = request.user
    if not user.club:
        return Response({"detail": "Používateľ nemá klub"}, status=400)

    # základný queryset
    qs = (
        Announcement.objects.filter(club=user.club)
        .annotate(read_count=Count("reads", distinct=True))
        .select_related("club", "created_by")
        .prefetch_related("categories")  # 🔑 pridaj prefetch na M2M
        .order_by("-date_created")
    )

    if hasattr(user, "roles"):
        user_category_ids = list(user.roles.values_list("category_id", flat=True))
        if user_category_ids:
            qs = qs.filter(
                Q(categories__in=user_category_ids) | Q(categories=None)
            ).distinct()
    # počet userov v klube vyrátame raz
    total_count = user.club.users.count()

    serializer = AnnouncementSerializer(
        qs, many=True, context={"request": request, "total_count": total_count}
    )
    return Response(serializer.data)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_announcement(request):
    """
    Vytvorí nový oznam – admin alebo tréner.
    """
    user = request.user
    if not user.club_id:
        return Response({"detail": "Používateľ nemá priradený klub"}, status=400)

    
    serializer = AnnouncementSerializer(data=request.data, context={"request": request})
    if serializer.is_valid():
        announcement = serializer.save(
            created_by=user,
            club=user.club   # 🔑 nastavíme explicitne klub
        )
         # 🔑 určíme používateľov ktorým to patrí
        if request.data.get("target") == "club":
            target_users = user.club.users.all()
        else:
            category_ids = request.data.get("categories", [])
            target_users = user.club.users.filter(roles__category_id__in=category_ids).distinct()

        user_ids = list(target_users.values_list("id", flat=True))

        send_announcement_notification.delay(announcement.id, user_ids)


        return Response(
            AnnouncementSerializer(announcement, context={"request": request}).data,
            status=status.HTTP_201_CREATED
        )
    else:
        print("❌ Serializer errors:", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_announcement_read(request, pk):
    """
    Označí oznam ako prečítaný (uloží alebo updatuje read_at).
    """
    user = request.user
    try:
        announcement = Announcement.objects.get(pk=pk, club=user.club)
    except Announcement.DoesNotExist:
        return Response({"detail": "Oznam neexistuje"}, status=404)

    read, created = AnnouncementRead.objects.update_or_create(
        user=user, announcement=announcement,
        defaults={"read_at": timezone.now()}
    )
    return Response(AnnouncementReadSerializer(read).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def announcement_readers(request, pk):
    """
    Zoznam používateľov klubu + info kto kedy prečítal.
    Optimalizované cez prefetch.
    """
    ann = get_object_or_404(
        Announcement.objects.prefetch_related("reads__user"),
        pk=pk, club=request.user.club
    )

    # všetci užívatelia v klube
    users = ann.club.users.all().select_related("club")

    # indexujeme reads podľa user.id aby to bolo O(1)
    read_map = {r.user_id: r.read_at for r in ann.reads.all()}

    data = [
        {
            "id": u.id,
            "full_name": f"{u.first_name} {u.last_name}".strip() or u.username,
            "read_at": read_map.get(u.id),
        }
        for u in users
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def announcements_admin_list(request):
    """
    Admin endpoint – všetky oznamy pre klub s počtom prečítaných a celkovým počtom cieľových používateľov.
    """
    user = request.user
    if not user.club:
        return Response({"detail": "Používateľ nemá klub"}, status=400)

    qs = (
        Announcement.objects.filter(club=user.club)
        .annotate(read_count=Count("reads", distinct=True))
        .select_related("club", "created_by")
        .prefetch_related("categories")
        .order_by("-date_created")
    )

    data = []
    for ann in qs:
        # 🔑 používateľov rátame podľa cieľa
        if ann.categories.exists():
            total_count = (
                request.user.club.users.filter(roles__category__in=ann.categories.all())
                .distinct()
                .count()
            )
        else:
            total_count = request.user.club.users.count()

        data.append(
            AnnouncementSerializer(
                ann, context={"request": request, "total_count": total_count}
            ).data
        )

    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def announcement_admin_readers(request, pk):
    """
    Admin endpoint – zoznam používateľov, ktorí mohli oznam vidieť,
    a info kto kedy prečítal.
    """
    ann = get_object_or_404(
        Announcement.objects.prefetch_related("reads__user", "categories"),
        pk=pk, club=request.user.club
    )

    # ak oznam patrí konkrétnym kategóriám → obmedzíme
    if ann.categories.exists():
        users = ann.club.users.filter(roles__category__in=ann.categories.all()).distinct()
    else:
        users = ann.club.users.all()

    read_map = {r.user_id: r.read_at for r in ann.reads.all()}

    data = [
        {
            "id": u.id,
            "full_name": f"{u.first_name} {u.last_name}".strip() or u.username,
            "read_at": read_map.get(u.id),
        }
        for u in users
    ]
    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django_rest_passwordreset.models import ResetPasswordToken

@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password_confirm_custom(request):
    token = request.data.get("token")
    password = request.data.get("password")

    if not token or not password:
        return Response({"detail": "Chýba token alebo heslo"}, status=400)

    try:
        reset_token = ResetPasswordToken.objects.get(key=token)
    except ResetPasswordToken.DoesNotExist:
        return Response({"detail": "Neplatný alebo expirovaný token"}, status=400)

    # Zmeň heslo používateľovi
    user = reset_token.user
    user.set_password(password)
    user.save()

    # Token odstránime, aby sa nedal znova použiť
    reset_token.delete()

    return Response({"detail": "✅ Heslo bolo úspešne zmenené"})


@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_request(request):
    email = request.data.get("email")
    if not email:
        return Response({"detail": "Chýba email"}, status=400)

    users = User.objects.filter(email=email)
    if not users.exists():
        return Response({"detail": "Používateľ s týmto emailom neexistuje"}, status=404)

    # 🔧 tu opravujeme – ak existuje presne 1 používateľ, hneď pošli reset link
    if users.count() == 1:
        user = users.first()
        # Zmaž staré tokeny
        ResetPasswordToken.objects.filter(user=user).delete()
        # Vytvor nový token
        token = ResetPasswordToken.objects.create(user=user)
        # Vytvor odkaz
        reset_url = f"https://app.ludimus.sk/reset-password?token={token.key}"
        # Pošli e-mail
        user.email_user("🔑 Reset hesla Ludimus", f"Klikni na tento odkaz: {reset_url}")
        return Response({"detail": "Na email bol odoslaný odkaz na reset hesla"})

    else:
        # Viac účtov – treba vybrať konkrétneho používateľa
        accounts = [
            {"id": u.id, "username": u.username, "full_name": f"{u.first_name} {u.last_name}"}
            for u in users
        ]
        return Response({"multiple": True, "accounts": accounts})


@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_generate_for_user(request):
    user_id = request.data.get("user_id")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({"detail": "Používateľ neexistuje"}, status=404)

    # Zmaž staré tokeny
    ResetPasswordToken.objects.filter(user=user).delete()
    # Vytvor nový token
    token = ResetPasswordToken.objects.create(user=user)
    # Pošli e-mail
    reset_url = f"https://ludimus.sk/reset-password?token={token.key}"
    user.email_user("🔑 Reset hesla Ludimus", f"Klikni na tento odkaz: {reset_url}")

    return Response({"detail": "Reset link bol odoslaný", "token": token.key})


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_coach_categories(request):
    """
    Vráti zoznam kategórií, kde má prihlásený používateľ rolu 'coach'.
    """
    user = request.user
    if not user.club:
        return Response({"detail": "Používateľ nemá priradený klub"}, status=400)

    # predpokladáš, že user.roles je M2M s modelom Role, ktorý má polia role a category
    categories = (
        user.roles.filter(role="coach")
        .select_related("category")
        .values("category__id", "category__name")
    )

    data = [
        {"id": c["category__id"], "name": c["category__name"]}
        for c in categories if c["category__id"] is not None
    ]

    return Response(data)


# views/announcements_admin.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Announcement

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def announcement_delete_view(request, pk: int):
    """
    Zmaže oznam podľa ID (iba admin klubu).
    """
    announcement = get_object_or_404(Announcement, pk=pk)

    # kontrola oprávnenia – napríklad len admin klubu môže zmazať
    if not request.user.roles.filter(role="admin").exists():
        return Response({"detail": "Nemáš oprávnenie zmazať tento oznam."}, status=403)

    announcement.delete()
    return Response({"detail": f"Oznam {pk} bol zmazaný."}, status=204)



from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Formation, FormationLine, FormationPlayer, Category
from .serializers import FormationSerializer, FormationLineSerializer, FormationPlayerSerializer


# ✅ 1. Všetky formácie pre kategóriu
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def formations_by_category(request, category_id):
    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        return Response({"detail": "Kategória neexistuje"}, status=404)

    if request.method == "GET":
        formations = Formation.objects.filter(category=category)
        serializer = FormationSerializer(formations, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        serializer = FormationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(category=category)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


# ✅ 2. Detail formácie (GET, PUT, DELETE)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def formation_detail(request, formation_id):
    try:
        formation = Formation.objects.get(id=formation_id)
    except Formation.DoesNotExist:
        return Response({"detail": "Formácia neexistuje"}, status=404)

    if request.method == "GET":
        serializer = FormationSerializer(formation)
        return Response(serializer.data)

    if request.method == "PUT":
        serializer = FormationSerializer(formation, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    if request.method == "DELETE":
        formation.delete()
        return Response({"detail": "Formácia zmazaná"}, status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_line_to_formation(request, formation_id):
    try:
        formation = Formation.objects.get(id=formation_id)
    except Formation.DoesNotExist:
        return Response({"detail": "Formácia neexistuje"}, status=404)

    # automaticky určíme číslo päťky
    existing_count = formation.lines.count()
    new_number = existing_count + 1

    serializer = FormationLineSerializer(data={"number": new_number})
    if serializer.is_valid():
        serializer.save(formation=formation)
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)

# ✅ 4. Pridanie alebo úprava hráča v päťke
@api_view(["POST", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def formation_player_manage(request, line_id):
    try:
        line = FormationLine.objects.get(id=line_id)
    except FormationLine.DoesNotExist:
        return Response({"detail": "Päťka neexistuje"}, status=404)

    if request.method == "POST":
        serializer = FormationPlayerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(line=line)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    if request.method == "PUT":
        try:
            player_id = request.data.get("id")
            player = FormationPlayer.objects.get(id=player_id, line=line)
        except FormationPlayer.DoesNotExist:
            return Response({"detail": "Hráč v tejto päťke neexistuje"}, status=404)

        serializer = FormationPlayerSerializer(player, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    if request.method == "DELETE":
        player_id = request.data.get("id")
        FormationPlayer.objects.filter(id=player_id, line=line).delete()
        return Response({"detail": "Hráč odstránený"}, status=204)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User



from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from .models import Category, UserCategoryRole

User = get_user_model()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def players_in_category(request, category_id):
    """
    Vráti všetkých hráčov (role='player') v danej kategórii.
    """
    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        return Response({"detail": "Kategória neexistuje"}, status=status.HTTP_404_NOT_FOUND)

    # nájdi používateľov s rolou 'player' v danej kategórii
    roles = UserCategoryRole.objects.filter(category=category, role="player").select_related("user", "user__position")

    players = []
    for r in roles:
        u = r.user
        players.append({
            "id": u.id,
            "name": f"{u.first_name} {u.last_name}".strip() or u.username,
            "number": u.number,
            "position": u.position.name if u.position else None,
            "birth_date": u.birth_date,
        })

    return Response(players, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def formation_with_attendance(request, category_id, training_id):
    """
    Vráti formácie + info o hráčoch s farbou podľa dochádzky.
    """
    from .serializers import FormationSerializer
    from .models import TrainingAttendance, Formation

    try:
        formations = Formation.objects.filter(category_id=category_id)
    except Formation.DoesNotExist:
        return Response({"detail": "Kategória neexistuje"}, status=404)

    # načítaj všetky attendance pre daný tréning
    attendances = TrainingAttendance.objects.filter(training_id=training_id)
    attendance_map = {a.user_id: a.status for a in attendances}

    serializer = FormationSerializer(formations, many=True)
    data = serializer.data

    # doplň status hráčov
    for formation in data:
        for line in formation["lines"]:
            for player in line["players"]:
                user_id = player["player"]
                status = attendance_map.get(user_id, "unanswered")
                player["attendance_status"] = status

    return Response(data)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_account_view(request):
    user = request.user

    try:
        username = user.username

        # 🔹 bezpečné mazanie (každý blok má vlastný try)
        try:
            from models import TrainingAttendance
            TrainingAttendance.objects.filter(user=user).delete()
        except Exception as e:
            print("⚠️ TrainingAttendance skip:", e)

        try:
            from models import MatchParticipation, MatchNomination
            MatchParticipation.objects.filter(user=user).delete()
            MatchNomination.objects.filter(user=user).delete()
        except Exception as e:
            print("⚠️ Match models skip:", e)

        try:
            from models import MemberPayment
            MemberPayment.objects.filter(user=user).delete()
        except Exception as e:
            print("⚠️ Payments skip:", e)

        try:
            from models import Message
            Message.objects.filter(sender=user).delete()
            Message.objects.filter(receiver=user).delete()
        except Exception as e:
            print("⚠️ Chat skip:", e)

        # 🔹 vymaž profil, ak existuje
        if hasattr(user, "userprofile"):
            user.delete()

        # 🔹 vymaž roly, ak ich má
        if hasattr(user, "roles"):
            user.roles.all().delete()

        # 🔹 nakoniec samotný používateľ
        user.delete()

        print(f"✅ Účet {username} bol odstránený.")
        return Response(
            {"detail": f"Účet používateľa {username} bol úspešne odstránený."},
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        print(f"❌ Chyba pri mazaní účtu: {type(e).__name__}: {e}")
        return Response(
            {"error": f"Nepodarilo sa vymazať účet: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

from .serializers import UserMeSerializer, AdminEditUserSerializer
@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def admin_edit_member(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({"detail": "Používateľ neexistuje"}, status=404)

    if request.method == "GET":
        serializer = UserMeSerializer(user)
        return Response(serializer.data)

    if request.method == "PUT":
        serializer = AdminEditUserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"detail": "✅ Údaje boli uložené"})
        else:
            return Response(serializer.errors, status=400)



# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q
from .models import Match
from .serializers import MatchSerializer
from itertools import chain
from operator import attrgetter
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Match, MatchParticipation
from .serializers import MatchSerializer

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_matches_filtered_view(request):
    """
    Endpoint, ktorý vracia zápasy hráča podľa filtra:
    ?filter=NEODOHRANÉ | ODOHRANÉ | VŠETKY
    """
    user = request.user
    try:
        filter_type = request.GET.get('filter', 'NEODOHRANÉ').upper()
        now = timezone.now()

        # 1️⃣ Získaj kategórie, kde má používateľ rolu hráča
        categories = user.roles.filter(role='player').values_list('category_id', flat=True)

        # 2️⃣ Zápasy v týchto kategóriách
        matches = Match.objects.filter(category_id__in=categories)

        # 3️⃣ Zápasy, kde má používateľ záznam účasti
        participations = MatchParticipation.objects.filter(user=user).select_related('match')
        participated_matches = Match.objects.filter(id__in=participations.values_list('match_id', flat=True))

        # 4️⃣ Spojenie a odstránenie duplicít
        combined = list(chain(matches, participated_matches))
        unique_matches_dict = {match.id: match for match in combined}
        unique_matches = list(unique_matches_dict.values())

        # 5️⃣ Filtrovanie podľa dátumu
        if filter_type == "NEODOHRANÉ":
            filtered_matches = [m for m in unique_matches if m.date >= now]
        elif filter_type == "ODOHRANÉ":
            filtered_matches = [m for m in unique_matches if m.date < now]
        else:
            filtered_matches = unique_matches

        # 6️⃣ Zoradenie podľa dátumu (najbližšie hore)
        sorted_matches = sorted(filtered_matches, key=attrgetter('date'))

        # 7️⃣ Serializácia
        serializer = MatchSerializer(sorted_matches, many=True, context={'request': request})

        # 8️⃣ Lock days
        club = getattr(user, 'club', None)
        vote_lock_days = getattr(club, 'vote_lock_days', 0) if club else 0

        return Response({
            "matches": serializer.data,
            "vote_lock_days": vote_lock_days
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
    




from datetime import datetime
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Training, Category
from .serializers import TrainingSerializer

from datetime import datetime
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def player_trainings_history_view_optimalization(request):
    """
    Vracia históriu tréningov hráča s možnosťou filtrovať podľa sezóny a mesiaca
    ?season=2024/2025&month=9
    """
    user = request.user
    club = user.club

    season_param = request.GET.get("season")
    month_param = request.GET.get("month")

    current_categories = Category.objects.filter(
        user_roles__user=user,
        user_roles__role="player"
    )

    trainings_from_roles = Training.objects.filter(
        club=club,
        category__in=current_categories
    )

    trainings_from_attendance = Training.objects.filter(
        club=club,
        attendances__user=user
    )

    trainings = (
        trainings_from_roles | trainings_from_attendance
    ).select_related(
        "category"
    ).prefetch_related(
        "attendances"
    ).distinct()

    if season_param:
        try:
            start_year, end_year = season_param.split("/")
            start = timezone.make_aware(datetime(int(start_year), 6, 1))
            end = timezone.make_aware(datetime(int(end_year), 5, 31, 23, 59, 59))
            trainings = trainings.filter(date__range=(start, end))
        except ValueError:
            pass

    if month_param is not None:
        try:
            month = int(month_param)
            if month >= 0:
                trainings = trainings.filter(date__month=month + 1)
        except ValueError:
            pass

    trainings = trainings.order_by("date")

    # len docasny test
    print("VOLANY player_trainings_history_view_optimalization")

    serializer = TrainingSerializer(trainings, many=True, context={"request": request})
    return Response(serializer.data)

    
from datetime import datetime
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils.timezone import make_aware

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_trainings_view_optimalization(request):
    """
    Vracia tréningy trénera podľa jeho kategórií.
    ?season=2024/2025  (voliteľné)
    ?month=0-11        (voliteľné)
    """
    user = request.user
    club = user.club
    now = timezone.now()
    month_param = request.GET.get("month")
    season_param = request.GET.get("season")

    coach_categories = Category.objects.filter(
        club=club,
        user_roles__user=user,
        user_roles__role="coach"
    ).distinct()

    trainings = Training.objects.filter(category__in=coach_categories, club=club)

    # 🔹 Filter podľa sezóny
    if season_param:
        try:
            start_year, end_year = season_param.split("/")
            start = make_aware(datetime(int(start_year), 6, 1, 0, 0))
            end = make_aware(datetime(int(end_year), 5, 31, 23, 59))
            trainings = trainings.filter(date__range=(start, end))
        except Exception as e:
            print("⚠️ Season filter error:", e)

    # 🔹 Filter podľa mesiaca
    if month_param is not None:
        try:
            month = int(month_param)
            if 0 <= month <= 11:
                trainings = trainings.filter(date__month=month + 1)
        except ValueError:
            pass

    # 🔹 Ak nie sú filtre → len budúce tréningy
    if not month_param and not season_param:
        trainings = trainings.filter(date__gte=now)

    trainings = trainings.select_related("category").prefetch_related("attendances").order_by("date")

    serializer = TrainingSerializer(trainings, many=True, context={"request": request})
    return Response(serializer.data)



from .tasks import notify_unpaid_orders

@api_view(['POST'])
@permission_classes([IsAdminUser])
def remind_unpaid_orders_view(request):
    """
    Spustí task, ktorý odošle pripomienky všetkým používateľom s nezaplatenými objednávkami.
    """
    order_ids = request.data.get('order_ids', [])
    if not isinstance(order_ids, list):
        return Response({"detail": "Neplatný formát – očakáva sa list order_ids."}, status=400)

    unpaid_orders = JerseyOrder.objects.filter(id__in=order_ids, is_paid=False)
    if not unpaid_orders.exists():
        return Response({"detail": "Žiadne nezaplatené objednávky."}, status=200)

    # Spusti celery task
    notify_unpaid_orders.delay(list(unpaid_orders.values_list('id', flat=True)))

    return Response({
        "detail": f"📩 Pripomienky boli odoslané pre {unpaid_orders.count()} objednávok."
    }, status=200)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def remind_unpaid_payments(request):
    """
    Spustí Celery task na odoslanie pripomienok členom s neuhradenými platbami.
    """
    payment_ids = request.data.get('payment_ids', [])
    if not isinstance(payment_ids, list):
        return Response({"detail": "Neplatný formát dát."}, status=400)

    from .models import MemberPayment  # podľa tvojho modelu
    unpaid = MemberPayment.objects.filter(id__in=payment_ids, is_paid=False).select_related("user")

    if not unpaid.exists():
        return Response({"detail": "Žiadne neuhradené platby."}, status=200)

    user_ids = list(unpaid.values_list("user_id", flat=True).distinct())

    from .tasks import send_unpaid_payment_notifications
    send_unpaid_payment_notifications.delay(user_ids)

    return Response({"detail": f"Pripomienky boli odoslané {len(user_ids)} používateľom."})



from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import datetime, timedelta
from django.db import transaction

from .models import TrainingSchedule, TrainingScheduleItem, Training
from .serializers import TrainingScheduleSerializer
from .tasks import process_training_schedules


def _next_weekday_time(now, weekday: int, t):
    """
    Najbližší datetime na zadaný weekday (0=Po) a čas t.
    """
    target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    days_ahead = (weekday - now.weekday()) % 7
    target = target + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return target


def _next_daily_0210(now):
    target = now.replace(hour=2, minute=10, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _set_next_run_at(schedule: TrainingSchedule):
    now = timezone.localtime()

    if schedule.strategy == TrainingSchedule.STRATEGY_WEEKLY_BATCH:
        # musí mať batch_weekday & batch_time
        schedule.next_run_at = _next_weekday_time(now, schedule.batch_weekday, schedule.batch_time)
    else:
        schedule.next_run_at = _next_daily_0210(now)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def training_schedules_list_create(request):
    user = request.user
    try:
        club = user.club
    except Exception:
        return Response({"detail": "Používateľ nemá priradený klub."}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "GET":
        qs = TrainingSchedule.objects.filter(club=club).prefetch_related("items").order_by("-id")
        return Response(TrainingScheduleSerializer(qs, many=True).data)

    # POST
    data = request.data.copy()
    serializer = TrainingScheduleSerializer(data=data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    schedule = serializer.save(club=club, created_by=user)

    # nastav next_run_at
    _set_next_run_at(schedule)
    schedule.save(update_fields=["next_run_at"])

    # vráť fresh data aj s next_run_at
    schedule = TrainingSchedule.objects.prefetch_related("items").get(id=schedule.id)
    return Response(TrainingScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def training_schedule_detail(request, schedule_id: int):
    user = request.user
    try:
        club = user.club
    except Exception:
        return Response({"detail": "Používateľ nemá priradený klub."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        schedule = TrainingSchedule.objects.prefetch_related("items").get(id=schedule_id, club=club)
    except TrainingSchedule.DoesNotExist:
        return Response({"detail": "Rozvrh neexistuje."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(TrainingScheduleSerializer(schedule).data)

    if request.method == "DELETE":
        schedule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PUT (update + items)
    data = request.data.copy()
    serializer = TrainingScheduleSerializer(schedule, data=data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    schedule = serializer.save()

    _set_next_run_at(schedule)
    schedule.save(update_fields=["next_run_at"])

    schedule = TrainingSchedule.objects.prefetch_related("items").get(id=schedule.id)
    return Response(TrainingScheduleSerializer(schedule).data)


def _week_start(d):
    return d - timedelta(days=d.weekday())

def _dt_for_weekday(week_monday_date, weekday, t):
    day_date = week_monday_date + timedelta(days=weekday)
    return timezone.make_aware(datetime.combine(day_date, t))

def _run_weekly_batch_now(schedule: TrainingSchedule):
    today = timezone.localdate()
    next_week_monday = _week_start(today) + timedelta(days=7)
    next_week_sunday = next_week_monday + timedelta(days=6)

    start = max(schedule.start_date, next_week_monday)
    end = min(schedule.end_date, next_week_sunday)
    if end < start:
        return 0

    created = 0
    with transaction.atomic():
        # generuj v rámci týždňa, kde je start
        week_monday = _week_start(start)

        for item in schedule.items.all():
            dt = _dt_for_weekday(week_monday, item.weekday, item.time)
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
                created += 1

    # posuň next_run_at o 7 dní
    if schedule.next_run_at:
        schedule.next_run_at = schedule.next_run_at + timedelta(days=7)
        schedule.save(update_fields=["next_run_at"])

    return created



def _run_days_before_now(schedule: TrainingSchedule):
    now = timezone.localtime()
    today = timezone.localdate()
    target_date = today + timedelta(days=schedule.days_before or 0)

    if target_date < schedule.start_date or target_date > schedule.end_date:
        schedule.next_run_at = (now + timedelta(days=1)).replace(hour=2, minute=10, second=0, microsecond=0)
        schedule.save(update_fields=["next_run_at"])
        return 0

    target_weekday = target_date.weekday()
    created = 0

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
                created += 1

    schedule.next_run_at = (now + timedelta(days=1)).replace(hour=2, minute=10, second=0, microsecond=0)
    schedule.save(update_fields=["next_run_at"])
    return created


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def training_schedule_run_now(request, schedule_id: int):
    user = request.user
    try:
        club = user.club
    except Exception:
        return Response({"detail": "Používateľ nemá priradený klub."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        schedule = TrainingSchedule.objects.prefetch_related("items").get(id=schedule_id, club=club)
    except TrainingSchedule.DoesNotExist:
        return Response({"detail": "Rozvrh neexistuje."}, status=status.HTTP_404_NOT_FOUND)

    if not schedule.is_active:
        return Response({"detail": "Rozvrh je neaktívny."}, status=status.HTTP_400_BAD_REQUEST)

    if schedule.strategy == TrainingSchedule.STRATEGY_WEEKLY_BATCH:
        created = _run_weekly_batch_now(schedule)
    else:
        created = _run_days_before_now(schedule)

    return Response({"created": created})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def training_schedules_process_now(request):
    # spustí synchronne rovnakú logiku ako celery task
    process_training_schedules()
    return Response({"detail": "OK"})



from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import EmailOrUsernameTokenObtainPairSerializer


class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer


from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from django.core.mail import send_mail
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
import traceback


@api_view(["POST"])
@permission_classes([AllowAny])
def contact_form_view(request):
    try:
        name = (request.data.get("name") or "").strip()
        club = (request.data.get("club") or "").strip()
        email = (request.data.get("email") or "").strip()
        phone = (request.data.get("phone") or "").strip()
        message = (request.data.get("message") or "").strip()
        website = (request.data.get("website") or "").strip()  # honeypot

        if website:
            return Response({"success": True}, status=status.HTTP_200_OK)

        if not name or not email or not message:
            return Response(
                {"error": "Meno, email a správa sú povinné."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Neplatný email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = f"Nový kontakt z webu Ludimus – {name}"

        text_message = f"""
Nový kontakt z webu Ludimus

Meno: {name}
Klub: {club if club else "-"}
Email: {email}
Telefón: {phone if phone else "-"}

Správa:
{message}
""".strip()

        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["support@ludimus.sk"],
            fail_silently=False,
        )

        return Response(
            {"success": True, "message": "Správa bola úspešne odoslaná."},
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        print("CONTACT_FORM_ERROR:", str(e))
        traceback.print_exc()
        return Response(
            {"error": f"Správu sa nepodarilo odoslať. Detail: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["POST"])
@permission_classes([AllowAny])
def trial_request_view(request):
    try:
        name = (request.data.get("name") or "").strip()
        club = (request.data.get("club") or "").strip()
        email = (request.data.get("email") or "").strip()
        phone = (request.data.get("phone") or "").strip()
        members_count = (request.data.get("membersCount") or "").strip()
        note = (request.data.get("note") or "").strip()
        website = (request.data.get("website") or "").strip()  # honeypot

        # 🛡️ anti-spam
        if website:
            return Response({"success": True}, status=status.HTTP_200_OK)

        # ❗ validácia
        if not name or not club or not email:
            return Response(
                {"error": "Meno, klub a email sú povinné."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Neplatný email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 📧 email obsah
        subject = f"Žiadosť o skúšobnú verziu – {club}"

        text_message = f"""
Nová žiadosť o 30-dňovú skúšobnú verziu

Meno: {name}
Klub: {club}
Email: {email}
Telefón: {phone if phone else "-"}
Počet členov: {members_count if members_count else "-"}

Poznámka:
{note if note else "-"}
""".strip()

        # 📤 odoslanie
        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["support@ludimus.sk"],
            fail_silently=False,
        )

        return Response(
            {
                "success": True,
                "message": "Žiadosť bola úspešne odoslaná. Čoskoro sa vám ozveme.",
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        print("TRIAL_REQUEST_ERROR:", str(e))
        traceback.print_exc()

        return Response(
            {"error": f"Server error: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    

from datetime import timedelta, date
from collections import Counter

from django.utils import timezone
from django.db.models import Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Category, Training, TrainingAttendance, User


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coach_overview_view(request):
    user = request.user

    coach_categories = Category.objects.filter(
        user_roles__user=user,
        user_roles__role='coach'
    ).distinct()

    if not coach_categories.exists():
        return Response({
            "summary": {
                "total_trainings": 0,
                "average_attendance_percent": 0,
                "total_players": 0,
                "present_count": 0,
                "absent_count": 0,
            },
            "categories": [],
            "attendance_trend": [],
            "player_attendance": [],
            "recent_trainings": [],
            "top_players": [],
            "bottom_players": [],
            "attendance_by_weekday": [],
            "attendance_by_category": [],
            "attendance_by_location": [],
            "absence_reasons": [],
            "top_absence_reasons": [],
            "least_absence_reasons": [],
            "absences_by_player": [],
            "recent_absences": [],
            "engagement_summary": {
                "low_attendance_players_count": 0,
                "perfect_attendance_players_count": 0,
                "frequently_absent_players_count": 0,
            },
        })

    category_id = request.GET.get("category_id")
    period = request.GET.get("period", "30days")

    try:
        min_attendance_percent = float(request.GET.get("min_attendance_percent", 0))
    except ValueError:
        return Response({"error": "Neplatný min_attendance_percent"}, status=400)

    selected_categories = coach_categories

    if category_id:
        try:
            category_id = int(category_id)
        except ValueError:
            return Response({"error": "Neplatné category_id"}, status=400)

        if not coach_categories.filter(id=category_id).exists():
            return Response({"error": "Nemáš prístup k tejto kategórii"}, status=403)

        selected_categories = coach_categories.filter(id=category_id)

    now = timezone.now()

    # len minulé + aktuálne tréningy, budúce sa vôbec nerátajú
    trainings = Training.objects.filter(
        category__in=selected_categories,
        date__lte=now
    ).select_related("category")

    if period == "30days":
        trainings = trainings.filter(date__gte=now - timedelta(days=30))
    elif period == "90days":
        trainings = trainings.filter(date__gte=now - timedelta(days=90))
    elif period == "season":
        if now.month >= 6:
            season_start = date(now.year, 6, 1)
            season_end = date(now.year + 1, 5, 31)
        else:
            season_start = date(now.year - 1, 6, 1)
            season_end = date(now.year, 5, 31)

        trainings = trainings.filter(date__date__range=(season_start, season_end))
    elif period == "all":
        pass
    else:
        return Response({"error": "Neplatný period"}, status=400)

    trainings = trainings.order_by("date")

    players = User.objects.filter(
        roles__category__in=selected_categories,
        roles__role='player'
    ).distinct()

    total_players = players.count()
    total_trainings = trainings.count()

    attendances = TrainingAttendance.objects.filter(
        training__in=trainings,
        user__in=players
    ).select_related("user", "training", "training__category")

    present_count = attendances.filter(status='present').count()
    absent_count = attendances.filter(status='absent').count()

    average_attendance_percent = 0
    if total_trainings > 0 and total_players > 0:
        possible_slots = total_trainings * total_players
        average_attendance_percent = round((present_count / possible_slots) * 100, 1)

    attendance_trend = []
    for training in trainings:
        training_attendances = attendances.filter(training=training)
        present = training_attendances.filter(status='present').count()
        absent = training_attendances.filter(status='absent').count()

        category_players_count = players.filter(
            roles__category=training.category,
            roles__role='player'
        ).distinct().count()

        percent = 0
        if category_players_count > 0:
            percent = round((present / category_players_count) * 100, 1)

        attendance_trend.append({
            "training_id": training.id,
            "date": training.date.isoformat(),
            "category_id": training.category.id,
            "category_name": training.category.name,
            "description": training.description,
            "location": training.location,
            "present": present,
            "absent": absent,
            "attendance_percent": percent,
        })

    player_attendance = []
    for player in players:
        player_attendances = attendances.filter(user=player)

        player_present = player_attendances.filter(status='present').count()
        player_absent = player_attendances.filter(status='absent').count()

        player_category_ids = player.roles.filter(
            role='player',
            category__in=selected_categories
        ).values_list('category_id', flat=True).distinct()

        player_trainings_count = trainings.filter(category_id__in=player_category_ids).count()

        denominator = player_trainings_count if player_trainings_count > 0 else player_attendances.count()
        attendance_percent = round((player_present / denominator) * 100, 1) if denominator > 0 else 0

        player_attendance.append({
            "player_id": player.id,
            "name": f"{player.first_name} {player.last_name}".strip() or player.username,
            "number": player.number,
            "attendance_percent": attendance_percent,
            "present_count": player_present,
            "absent_count": player_absent,
            "trainings_count": denominator,
        })

    filtered_player_attendance = [
        p for p in player_attendance
        if p["attendance_percent"] >= min_attendance_percent
    ]
    filtered_player_attendance.sort(key=lambda x: x["attendance_percent"], reverse=True)

    recent_trainings = list(reversed(attendance_trend[-8:]))

    top_players = filtered_player_attendance[:5]
    bottom_players = sorted(filtered_player_attendance, key=lambda x: x["attendance_percent"])[:5]

    weekday_names = {
        0: "Pondelok",
        1: "Utorok",
        2: "Streda",
        3: "Štvrtok",
        4: "Piatok",
        5: "Sobota",
        6: "Nedeľa",
    }

    attendance_by_weekday = []
    for weekday in range(7):
        weekday_trainings = [t for t in trainings if t.date.weekday() == weekday]
        if not weekday_trainings:
            continue

        weekday_training_ids = [t.id for t in weekday_trainings]
        weekday_present = attendances.filter(training_id__in=weekday_training_ids, status='present').count()

        weekday_possible_slots = 0
        for t in weekday_trainings:
            weekday_possible_slots += players.filter(
                roles__category=t.category,
                roles__role='player'
            ).distinct().count()

        avg_percent = round((weekday_present / weekday_possible_slots) * 100, 1) if weekday_possible_slots > 0 else 0

        attendance_by_weekday.append({
            "weekday": weekday_names[weekday],
            "trainings_count": len(weekday_trainings),
            "average_attendance_percent": avg_percent,
        })

    attendance_by_category = []
    for category in selected_categories.order_by("name"):
        category_trainings = trainings.filter(category=category)
        if not category_trainings.exists():
            continue

        category_players_count = players.filter(
            roles__category=category,
            roles__role='player'
        ).distinct().count()

        category_present = attendances.filter(
            training__category=category,
            status='present'
        ).count()

        possible_slots = category_trainings.count() * category_players_count
        avg_percent = round((category_present / possible_slots) * 100, 1) if possible_slots > 0 else 0

        attendance_by_category.append({
            "category_id": category.id,
            "category_name": category.name,
            "trainings_count": category_trainings.count(),
            "average_attendance_percent": avg_percent,
        })

    location_map = {}
    for item in attendance_trend:
        location = item["location"] or "Nezadané"
        if location not in location_map:
            location_map[location] = {
                "location": location,
                "trainings_count": 0,
                "attendance_sum": 0,
            }

        location_map[location]["trainings_count"] += 1
        location_map[location]["attendance_sum"] += item["attendance_percent"]

    attendance_by_location = []
    for _, item in location_map.items():
        attendance_by_location.append({
            "location": item["location"],
            "trainings_count": item["trainings_count"],
            "average_attendance_percent": round(item["attendance_sum"] / item["trainings_count"], 1),
        })

    attendance_by_location.sort(key=lambda x: x["trainings_count"], reverse=True)

    # dôvody absencií
    absence_reason_qs = (
        attendances
        .filter(status='absent')
        .exclude(reason__isnull=True)
        .exclude(reason__exact='')
        .values('reason')
        .annotate(count=Count('id'))
        .order_by('-count', 'reason')
    )

    absence_reasons = [
        {
            "reason": item["reason"],
            "count": item["count"],
        }
        for item in absence_reason_qs
    ]

    top_absence_reasons = absence_reasons[:5]
    least_absence_reasons = list(reversed(absence_reasons[-5:])) if absence_reasons else []

    # absencie podľa hráča
    absences_by_player = []
    for player in player_attendance:
        if player["absent_count"] > 0:
            absences_by_player.append({
                "player_id": player["player_id"],
                "name": player["name"],
                "absent_count": player["absent_count"],
            })

    absences_by_player.sort(key=lambda x: x["absent_count"], reverse=True)
    absences_by_player = absences_by_player[:10]

    # posledné absencie
    recent_absence_qs = (
        attendances
        .filter(status='absent')
        .select_related('user', 'training', 'training__category')
        .order_by('-training__date')[:10]
    )

    recent_absences = [
        {
            "player_name": f"{a.user.first_name} {a.user.last_name}".strip() or a.user.username,
            "category_name": a.training.category.name,
            "training_date": a.training.date.isoformat(),
            "location": a.training.location,
            "reason": a.reason or "Bez dôvodu",
        }
        for a in recent_absence_qs
    ]

    engagement_summary = {
        "low_attendance_players_count": len([p for p in player_attendance if p["attendance_percent"] < 10]),
        "perfect_attendance_players_count": len([p for p in player_attendance if p["attendance_percent"] == 100]),
        "frequently_absent_players_count": len([p for p in player_attendance if p["absent_count"] >= 3]),
    }

    return Response({
        "summary": {
            "total_trainings": total_trainings,
            "average_attendance_percent": average_attendance_percent,
            "total_players": total_players,
            "present_count": present_count,
            "absent_count": absent_count,
        },
        "filters": {
            "min_attendance_percent": min_attendance_percent,
        },
        "categories": [
            {"id": c.id, "name": c.name}
            for c in selected_categories.order_by("name")
        ],
        "attendance_trend": attendance_trend,
        "player_attendance": filtered_player_attendance,
        "recent_trainings": recent_trainings,
        "top_players": top_players,
        "bottom_players": bottom_players,
        "attendance_by_weekday": attendance_by_weekday,
        "attendance_by_category": attendance_by_category,
        "attendance_by_location": attendance_by_location[:6],
        "absence_reasons": absence_reasons,
        "top_absence_reasons": top_absence_reasons,
        "least_absence_reasons": least_absence_reasons,
        "absences_by_player": absences_by_player,
        "recent_absences": recent_absences,
        "engagement_summary": engagement_summary,
    })


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import CategoryVoteReminderSetting, Category, Role, Training
from .serializers import (
    CategoryVoteReminderSettingSerializer,
    CategoryVoteReminderSettingUpsertSerializer,
)
from .tasks import rebuild_training_vote_reminders

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def category_vote_reminder_settings_view(request):
    coach_category_ids = list(
        request.user.roles.filter(role=Role.COACH).values_list("category_id", flat=True)
    )

    if request.method == "GET":
        settings_qs = CategoryVoteReminderSetting.objects.filter(
            category_id__in=coach_category_ids,
            club=request.user.club,
        ).select_related("category", "club")

        existing = {s.category_id: s for s in settings_qs}
        result = []

        for category_id in coach_category_ids:
            if category_id in existing:
                result.append(existing[category_id])
            else:
                category = Category.objects.get(id=category_id)
                pseudo = CategoryVoteReminderSetting(
                    club=request.user.club,
                    category=category,
                    enabled=False,
                    reminder_hours=[],
                )
                result.append(pseudo)

        serializer = CategoryVoteReminderSettingSerializer(result, many=True)
        return Response(serializer.data)

    serializer = CategoryVoteReminderSettingUpsertSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    category_id = serializer.validated_data["category_id"]
    enabled = serializer.validated_data["enabled"]
    reminder_hours = serializer.validated_data.get("reminder_hours", [])

    is_coach = request.user.roles.filter(
        category_id=category_id,
        role=Role.COACH
    ).exists()

    if not is_coach:
        return Response(
            {"error": "Nemáš oprávnenie spravovať pripomienky pre túto kategóriu."},
            status=403
        )

    category = get_object_or_404(Category, id=category_id, club=request.user.club)

    setting, _ = CategoryVoteReminderSetting.objects.get_or_create(
        category=category,
        defaults={
            "club": request.user.club,
        }
    )

    setting.club = request.user.club
    setting.enabled = enabled
    setting.reminder_hours = reminder_hours
    setting.updated_by = request.user
    setting.save()

    # prepočítať budúce tréningy v tejto kategórii
    future_trainings = Training.objects.filter(
        club=request.user.club,
        category=category,
        date__gt=timezone.now(),
    )

    for training in future_trainings:
        rebuild_training_vote_reminders(training)

    return Response(CategoryVoteReminderSettingSerializer(setting).data, status=200)