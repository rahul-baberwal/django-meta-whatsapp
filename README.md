<div align="center">
  <img src="https://raw.githubusercontent.com/rahul-baberwal/django-meta-whatsapp/main/docs/django-meta-whatsapp.png" width="100" height="100" alt="django-meta-whatsapp logo">
  <h1>django-meta-whatsapp</h1>
  <p><strong>A production-ready WhatsApp Cloud Platform engine for Django.</strong></p>
  
  [![PyPI](https://img.shields.io/pypi/v/django-meta-whatsapp?style=flat-square&color=22c55e)](https://pypi.org/project/django-meta-whatsapp/)
  [![Latest on Django Packages](https://img.shields.io/badge/PyPI-django--meta--whatsapp-tags-8c3c26.svg?style=flat-square)](https://djangopackages.org/packages/p/django-meta-whatsapp/)
  [![Python](https://img.shields.io/pypi/pyversions/django-meta-whatsapp?style=flat-square)](https://pypi.org/project/django-meta-whatsapp/)
  [![Django](https://img.shields.io/badge/Django-4.0%20%7C%205.0%20%7C%205.1-092E20.svg?style=flat-square)](https://pypi.org/project/django-meta-whatsapp/)
  [![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://github.com/rahul-baberwal/django-meta-whatsapp/blob/main/LICENSE)
</div>

<br/>

**`django-meta-whatsapp`** is not just an API wrapper — it's a fully-featured, drop-in WhatsApp CRM and messaging platform that lives entirely within your existing Django project. Beautiful Tailwind UI, real-time inbox, bulk campaigns, webhook engine, and REST APIs — all without third-party SaaS subscriptions.

---

## ✨ Features

- 📨 **Live Unified Inbox** — Real-time chat interface with media, reply threading, and message status ticks.
- 🚀 **Marketing Campaigns** — Schedule and send bulk messages using approved WhatsApp Templates. Track delivery, read rates, and bounce rates.
- 👥 **Contact Management** — Import CSVs, assign dynamic colored **Labels**, and auto-sync users who subscribe via WhatsApp deep-links.
- 🎯 **Contact Filter Presets** — Define named audience filters in settings for one-click campaign targeting.
- 🔗 **User Model Integration** — Link your Django `User` model to `WhatsAppContact` with pluggable audience providers.
- 🚫 **Blocked User Sync** — Automatically detect and exclude users who block your business.
- 🧩 **Template Sync** — Pull all approved WhatsApp message templates directly from Meta with one click.
- 🔗 **In-App Signups** — Create and manage `wa.me` deep links so users can instantly opt-in.
- ⚡ **Webhooks Engine** — Built-in webhook endpoints to automatically ingest incoming messages, delivery receipts, and status updates.
- 🔑 **REST APIs** — Send text, location, template; list chats/campaigns (API-key auth).
- 🏢 **Multi-Account** — One Django project, multiple WhatsApp Business Accounts.

---

## 📦 Installation

```bash
# Using uv (Recommended)
uv add django-meta-whatsapp

# Using pip
pip install django-meta-whatsapp
```

## ⚙️ Configuration

**1. Add to `INSTALLED_APPS`:**

```python
INSTALLED_APPS = [
    # ...
    "django_meta_whatsapp",
]
```

**2. Mount URLs in `urls.py`:**

```python
from django.urls import path, include

urlpatterns = [
    # ...
    path("whatsapp/", include("django_meta_whatsapp.urls", namespace="django_meta_whatsapp")),
]
```

**3. Add `WHATSAPP` settings to `settings.py`:**

```python
WHATSAPP = {
    # ── Required ──────────────────────────────────────────
    "API_TOKEN": "EAA...",
    "PHONE_NUMBER_ID": "1234567890",
    "WEBHOOK_VERIFY_TOKEN": "your_secure_random_string",

    # ── UI Customization (optional) ───────────────────────
    "DASHBOARD_NAME": "My Business CRM",
    "DASHBOARD_LOGO": "https://yourwebsite.com/logo.png",

    # ── Audience Providers (optional) ─────────────────────
    # Map your own model querysets as named campaign audiences
    "PHONE_FIELD": "phone",       # field on your model with the phone number
    "NAME_FIELD": "name",         # field on your model with the display name
    "AUDIENCES": {
        "All Users":     "myapp.audiences.all_users",
        "VIP Customers": "myapp.audiences.vip_customers",
    },

    # ── Contact Filter Presets (optional) ─────────────────
    # Pre-defined filters shown as a dropdown in the Campaign form
    "CONTACT_FILTERS": {
        "VIP Customers":        '{"labels__name": "VIP"}',
        "Subscribed via Link":  '{"subscribed_via_signup__isnull": false}',
        "New This Month":       '{"created_at__gte": "2024-06-01"}',
    },

    # ── Security & Encryption (optional) ──────────────────
    # Derived from SECRET_KEY by default. Used to symmetrically encrypt access tokens in DB.
    "ENCRYPTION_KEY": "your_custom_secret_key_or_password",
}
```

**4. Run migrations:**

```bash
python manage.py migrate
```

**5. Credential Encryption (Secure-by-Default):**
Database-stored access tokens (in the `WhatsAppAccount` model) are automatically encrypted using symmetric encryption (`Fernet`).
- **Default Key:** The encryption key is derived automatically from your Django project's `SECRET_KEY`.
- **Custom Key:** To use a separate key, define `"ENCRYPTION_KEY"` inside your `WHATSAPP` settings.
- **Upgrades:** If you have existing plain text tokens, the database fallback will read them cleanly. Saving the account again will seamlessly encrypt it.

---

## 🚀 Quickstart

1. Visit `/whatsapp/` in your browser.
2. The UI will prompt you to add a **WhatsApp Account** if none exists.
3. Set your Meta App Webhook URL to `https://yourdomain.com/whatsapp/webhook/`.
4. Sync your templates from the **Templates** tab.
5. Start chatting from the **Inbox**!

---

## 🔗 Linking Your Django User Model

You can link `WhatsAppContact` to your existing `User` model without modifying the package. Three approaches are documented:

**Option A — Profile Model (recommended):**
```python
from django_meta_whatsapp.models import WhatsAppContact

class UserWhatsAppProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="whatsapp_profile")
    contact = models.OneToOneField(WhatsAppContact, on_delete=models.SET_NULL, null=True, blank=True)
```

**Option B — Query your User model directly as a campaign audience:**
```python
# myapp/audiences.py
from django.contrib.auth import get_user_model
User = get_user_model()

def all_users():
    return User.objects.filter(is_active=True, phone__isnull=False)
```

See the [full documentation](https://rahul-baberwal.github.io/django-meta-whatsapp) for signals-based auto-linking and more filter patterns.

---

## 🔑 REST API

All endpoints require an `X-API-Key` header (generated from the dashboard under **Settings → API Keys**).

```bash
# Send a text message
curl -X POST https://yourdomain.com/whatsapp/api/send-message/ \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"phone": "919876543210", "message": "Hello!"}'

# Send an approved template
curl -X POST https://yourdomain.com/whatsapp/api/send-template/ \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"phone": "919876543210", "template_name": "order_update", "language": "en", "body_params": ["Rahul", "ORD-999"]}'
```

---

## 📖 Full Documentation

**[https://rahul-baberwal.github.io/django-meta-whatsapp](https://rahul-baberwal.github.io/django-meta-whatsapp)**

---

## 📋 Changelog

### v1.0.5
- 🔒 **Database Credential Encryption** — Symmetrically encrypt `access_token` in database records (`WhatsAppAccount` model) using Fernet cryptography.
- ⚙️ **Custom Encryption Key** — Dynamically derived from `SECRET_KEY` by default, customizable via `WHATSAPP['ENCRYPTION_KEY']`.
- 🔄 **Plaintext Fallback** — Transparent migration with backward-compatibility for existing plaintext credentials.

### v1.0.4
- ✅ Updated README with complete settings reference and REST API examples
- ✅ Version badge added to docs (auto-updated each release)
- ✅ Django 4.0 / 5.0 / 5.1 + Python 3.9+ version tags corrected in docs & README

### v1.0.3
- ✅ Contact Filter Presets — define named filters in settings, auto-populate campaign form
- ✅ User model linking docs — 3 integration patterns with code examples
- ✅ Dashboard logo updated to custom PNG
- ✅ Sidebar scrollbar hidden for premium feel

### v1.0.2
- ✅ Single clean migration (`0001_initial.py`)
- ✅ Mintlify-style documentation site (`docs/index.html`)
- ✅ REST API documentation with cURL examples
- ✅ `pyproject.toml` + `uv` migration

### v1.0.1
- ✅ Label system with color picker (tom-select)
- ✅ Blocked user sync, In-App Signups, Catalog products
- ✅ WhatsApp Catalog product management

---

<div align="center">
  Crafted with ❤️ by <a href="https://rahulbaberwal.com">Rahul Baberwal</a>
</div>