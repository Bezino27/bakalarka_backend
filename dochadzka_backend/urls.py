from django.contrib import admin
from django.conf.urls import include
from django.urls import path
from dochadzka_app import urls as dochadzka_app_urls
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("api/", include(dochadzka_app_urls)),
    path("api/chat/", include("chat.urls")),
    path("api/password_reset/", include("django_rest_passwordreset.urls", namespace="password_reset")),

    path("admin/", admin.site.urls),
]

# ⬇️ Len pre vývoj – obsluhuje media súbory (PDF, obrázky...)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)