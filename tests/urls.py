from django.urls import path, include

urlpatterns = [
    path("whatsapp/", include("django_meta_whatsapp.urls", namespace="django_meta_whatsapp")),
]
