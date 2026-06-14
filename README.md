<div align="center">
  <img src="https://raw.githubusercontent.com/rahul-baberwal/django-meta-whatsapp/main/docs/django-meta-whatsapp.png" width="100" height="100" alt="django-meta-whatsapp logo">
  <h1>django-meta-whatsapp</h1>
  <p><strong>A production-ready WhatsApp Cloud Platform engine for Django.</strong></p>
  
  [![PyPI](https://img.shields.io/pypi/v/django-meta-whatsapp?style=flat-square&color=22c55e)](https://pypi.org/project/django-meta-whatsapp/)
  [![Latest on Django Packages](https://img.shields.io/badge/PyPI-django--meta--whatsapp-tags-8c3c26.svg?style=flat-square)](https://djangopackages.org/packages/p/django-meta-whatsapp/)
  [![Python](https://img.shields.io/pypi/pyversions/django-meta-whatsapp?style=flat-square)](https://pypi.org/project/django-meta-whatsapp/)
  [![Django](https://img.shields.io/badge/Django-3.2%20%7C%204.0%20%7C%205.0-092E20.svg?style=flat-square)](https://pypi.org/project/django-meta-whatsapp/)
  [![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://github.com/rahul-baberwal/django-meta-whatsapp/blob/main/LICENSE)
</div>

<br/>

**`django-meta-whatsapp`** is not just an API wrapper—it's a fully-featured, drop-in CRM and messaging platform that lives entirely within your existing Django project. It provides a beautiful Tailwind UI for managing conversations, blasting marketing campaigns, handling webhooks, and syncing contacts without requiring third-party SaaS subscriptions.

---

## ✨ Features

- 📨 **Live Unified Inbox**: A sleek, real-time chat interface to talk to your customers directly from your Django admin dashboard.
- 🚀 **Marketing Campaigns**: Schedule and send bulk messages using approved WhatsApp Templates. Track delivery, read rates, and bounce rates.
- 👥 **Contact Management**: Import CSVs, assign dynamic colored **Labels**, and auto-sync users who subscribe via WhatsApp deep-links.
- 🚫 **Blocked User Sync**: Automatically detect and sync users who block your business so you never waste API calls on blocked numbers.
- 🧩 **Template Sync**: Pull all your approved WhatsApp message templates directly from Meta with one click.
- 🔗 **In-App Signups**: Create and manage `wa.me` deep links so users can instantly opt-in to marketing messages.
- ⚡ **Webhooks Engine**: Built-in webhook endpoints to automatically ingest incoming messages, delivery receipts, and status updates.

## 📦 Installation

This package is fully managed via `uv` or `pip`.

```bash
# Using uv (Recommended)
uv add django-meta-whatsapp

# Using pip
pip install django-meta-whatsapp
```

## ⚙️ Configuration

Add the app to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    "django_meta_whatsapp",
]
```

Include the URLs in your `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    # ...
    path("whatsapp/", include("django_meta_whatsapp.urls", namespace="django_meta_whatsapp")),
]
```

Add your WhatsApp Cloud API credentials to `settings.py`:

```python
# Required
WHATSAPP_API_TOKEN = "EAA..."
WHATSAPP_PHONE_NUMBER_ID = "1234567890"
WHATSAPP_WEBHOOK_VERIFY_TOKEN = "your_secure_random_string"

# Optional Customizations
WHATSAPP_DASHBOARD_NAME = "My Business CRM"
WHATSAPP_DASHBOARD_LOGO = "https://yourwebsite.com/logo.png"
```

Run migrations:

```bash
python manage.py migrate
```

## 🚀 Quickstart

1. Visit `/whatsapp/` in your browser.
2. If you haven't set up your credentials in `settings.py`, the UI will prompt you to create a **WhatsApp Account** object via the dashboard.
3. Configure your Meta App Webhook URL to point to `https://yourdomain.com/whatsapp/webhook/` using your `WHATSAPP_WEBHOOK_VERIFY_TOKEN`.
4. Sync your templates from the **Templates** tab.
5. Start chatting from the **Inbox**!

## 📖 Full Documentation

For advanced setup, webhook handling, and UI customization, please see the full documentation at:
**[https://rahul-baberwal.github.io/django-meta-whatsapp](https://rahul-baberwal.github.io/django-meta-whatsapp)**

---

<div align="center">
  Crafted with ❤️ by <a href="https://rahulbaberwal.com">Rahul Baberwal</a>
</div>