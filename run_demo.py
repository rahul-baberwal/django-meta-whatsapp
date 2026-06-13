import os
import sys
import django
from django.conf import settings
from django.core.management import execute_from_command_line

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY='demo-secret-key',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        INSTALLED_APPS=[
            'django.contrib.admin',
            'django.contrib.auth',
            'django.contrib.contenttypes',
            'django.contrib.sessions',
            'django.contrib.messages',
            'django.contrib.staticfiles',
            'django_meta_whatsapp',
        ],
        MIDDLEWARE=[
            'django.middleware.security.SecurityMiddleware',
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.middleware.common.CommonMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'django.contrib.messages.middleware.MessageMiddleware',
            'django.middleware.clickjacking.XFrameOptionsMiddleware',
        ],
        TEMPLATES=[{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [os.path.join(BASE_DIR, 'templates')],
            'APP_DIRS': True,
            'OPTIONS': {
                'context_processors': [
                    'django.template.context_processors.debug',
                    'django.template.context_processors.request',
                    'django.contrib.auth.context_processors.auth',
                    'django.contrib.messages.context_processors.messages',
                ],
            },
        }],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
            }
        },
        STATIC_URL='/static/',
        WHATSAPP={
            'WEBHOOK_VERIFY_TOKEN': 'demo_verify_token',
        }
    )

from django.urls import path, include
from django.http import HttpResponseRedirect

def home(request):
    return HttpResponseRedirect('/whatsapp/')

urlpatterns = [
    path('', home),
    path('whatsapp/', include('django_meta_whatsapp.urls', namespace='django_meta_whatsapp')),
]

if __name__ == '__main__':
    django.setup()
    # Create migrations and migrate
    execute_from_command_line(['manage.py', 'makemigrations', 'django_meta_whatsapp'])
    execute_from_command_line(['manage.py', 'migrate'])
    
    # Run the server
    execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])
