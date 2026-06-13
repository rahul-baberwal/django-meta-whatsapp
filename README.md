# django-meta-whatsapp

A production-ready Django WhatsApp Cloud Platform you can drop into any Django project.

## Features

- **Inbox** — Real-time chat interface with media, location pins, reply threading, message status ticks
- **Contacts** — CSV import/export, tagging, opt-out management
- **Templates** — Create, edit, push to Meta, sync from Meta
- **Campaigns** — Bulk messaging with pluggable audience system, CSV support, scheduled sends
- **Analytics** — Delivery/read tracking, 30-day trend chart
- **Webhooks** — Automatic inbound message sync, status updates, reaction handling
- **REST APIs** — Send text, location, template; list chats/campaigns (API-key auth)
- **Django Admin** — Full admin panel for all models
- **Multi-account** — One Django project, multiple WhatsApp Business Accounts
- **Signals** — Hook into message received/sent and campaign completed events
- **Celery support** — Optional background campaign processing

---

## Installation

```bash
pip install django-meta-whatsapp
# or from source:
pip install -e .
```

Also install `django-tailwind-cli` (no Node required):
```bash
pip install django-tailwind-cli
```

---

## Quick Setup

### 1. settings.py

```python
INSTALLED_APPS = [
    ...
    "django_tailwind_cli",
    "django_meta_whatsapp",
]

# Single-account shortcut (alternative: use WhatsAppAccount model in dashboard)
WHATSAPP = {
    "ACCESS_TOKEN": "your_meta_access_token",
    "PHONE_NUMBER_ID": "your_phone_number_id",
    "WABA_ID": "your_waba_id",            # needed for template sync
    "VERIFY_TOKEN": "your_verify_token",  # for webhook verification
    "LOGIN_URL": "/accounts/login/",      # redirect for unauthenticated users
}
```

### 2. urls.py

```python
from django.urls import path, include

urlpatterns += [
    path("whatsapp/", include("django_meta_whatsapp.urls")),
]
```

### 3. Migrate

```bash
python manage.py migrate
```

### 4. Tailwind CSS

```bash
python manage.py tailwind build
```

Open `http://yoursite/whatsapp/` — done.

---

## Multi-Account Support

Add accounts in the **Settings → Accounts** dashboard. Each account has its own:
- Access Token
- Phone Number ID
- WABA ID
- Verify Token

The webhook endpoint (`/whatsapp/webhook/`) auto-routes to the correct account by `phone_number_id`.

---

## Pluggable Audience System

The package never assumes your user model. You control who receives campaigns.

### Option 1: Named audience providers

```python
# myapp/whatsapp_audiences.py
from myapp.models import Customer

def vip_customers():
    return Customer.objects.filter(total_orders__gt=10)

def inactive_users():
    return Customer.objects.filter(is_active=False)
```

```python
# settings.py
WHATSAPP = {
    ...
    "PHONE_FIELD": "mobile",      # field on your model that holds the phone number
    "NAME_FIELD": "full_name",    # field for the display name
    "AUDIENCES": {
        "VIP Customers": "myapp.whatsapp_audiences.vip_customers",
        "Inactive Users": "myapp.whatsapp_audiences.inactive_users",
    },
}
```

The campaign form will show these as audience choices.

### Option 2: Full campaign resolver

```python
# settings.py
WHATSAPP = {
    ...
    "CAMPAIGN_RESOLVER": "myapp.whatsapp_audiences.resolve_campaign",
}
```

```python
# myapp/whatsapp_audiences.py
def resolve_campaign(campaign):
    """
    Return list of dicts: [{"phone": "919...", "name": "...", "params": {...}}, ...]
    """
    if campaign.audience_type == "vip":
        qs = Customer.objects.filter(total_orders__gt=10)
        return [{"phone": c.mobile, "name": c.full_name, "params": {}} for c in qs]
    return []
```

### Option 3: Built-in WhatsAppContact list

Set `audience_type = "contacts"` — sends to all non-opted-out `WhatsAppContact` records.

### Option 4: CSV Upload

Set `audience_type = "csv"` and upload a CSV with `phone`, `name` columns in the campaign form.

---

## Sending Messages Programmatically

```python
from django_meta_whatsapp.utils import (
    send_text_message,
    send_location_message,
    send_template_message,
    send_media_message,
    upload_media,
    build_template_components,
)

# Text
send_text_message("919876543210", "Hello from Django!")

# Location pin
send_location_message(
    "919876543210",
    latitude=24.5854,
    longitude=73.7125,
    name="Udaipur Office",
    address="Hiran Magri, Udaipur, Rajasthan",
)

# Template with variables
components = build_template_components(body_params=["Rakesh", "ORD-1234"])
send_template_message("919876543210", "order_confirmation", components=components)

# Media
with open("invoice.pdf", "rb") as f:
    media_id = upload_media(f, "application/pdf")
send_media_message("919876543210", media_id, "document", filename="invoice.pdf")
```

---

## Signals

```python
from django.dispatch import receiver
from django_meta_whatsapp.signals import (
    whatsapp_message_received,
    whatsapp_message_sent,
    whatsapp_campaign_completed,
)

@receiver(whatsapp_message_received)
def on_inbound(sender, message, **kwargs):
    print(f"New message from {message.phone_number}: {message.message_body}")

@receiver(whatsapp_campaign_completed)
def on_campaign_done(sender, campaign, sent, failed, **kwargs):
    print(f"Campaign '{campaign.name}' finished: {sent} sent, {failed} failed")
```

---

## Celery (optional)

```python
# settings.py
WHATSAPP_USE_CELERY = True
```

Campaigns will be queued as Celery tasks instead of running synchronously.

---

## REST API

All endpoints require `X-API-Key` header (create keys in **Settings → API Keys**).

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/whatsapp/api/send-message/` | Send text message |
| POST | `/whatsapp/api/send-location/` | Send location pin |
| POST | `/whatsapp/api/send-template/` | Send approved template |
| GET  | `/whatsapp/api/chats/` | List recent conversations |
| GET  | `/whatsapp/api/campaigns/` | List campaigns |

### Send text
```http
POST /whatsapp/api/send-message/
X-API-Key: your-key
Content-Type: application/json

{"phone": "919876543210", "message": "Hello!"}
```

### Send location
```http
POST /whatsapp/api/send-location/
X-API-Key: your-key
Content-Type: application/json

{
  "phone": "919876543210",
  "latitude": 24.5854,
  "longitude": 73.7125,
  "name": "Our Store",
  "address": "Udaipur, Rajasthan"
}
```

### Send template
```http
POST /whatsapp/api/send-template/
X-API-Key: your-key
Content-Type: application/json

{
  "phone": "919876543210",
  "template_name": "order_confirmation",
  "language": "en",
  "body_params": ["Rakesh", "ORD-1234"]
}
```

---

## Webhook Configuration

Set your Meta webhook URL to:
```
https://yourdomain.com/whatsapp/webhook/
```

The verify token is either:
1. The `verify_token` field on a `WhatsAppAccount` (multi-account)
2. `WHATSAPP["VERIFY_TOKEN"]` in settings (single-account)

---

## Management Commands

```bash
# Sync templates from Meta
python manage.py wa_sync_templates

# Sync for a specific account
python manage.py wa_sync_templates --account-id 1
```

---

## Models Reference

| Model | Purpose |
|-------|---------|
| `WhatsAppAccount` | Multi-account credentials |
| `WhatsAppContact` | Contact directory |
| `WhatsAppConversation` | Grouped chat threads |
| `WhatsAppMessage` | Individual messages (text, media, location, etc.) |
| `WhatsAppTemplate` | Meta-approved message templates |
| `WhatsAppCampaign` | Bulk send campaigns |
| `WhatsAppCampaignRecipient` | Per-recipient status tracking |
| `WhatsAppMedia` | Uploaded media library |
| `WhatsAppWebhookLog` | Raw webhook event logs |
| `WhatsAppAPIKey` | REST API authentication keys |

---

## Environment Variables (alternative to settings.py)

```env
META_WA_ACCESS_TOKEN=EAAx...
META_WA_PHONE_NUMBER_ID=1234567890
META_WABA_ID=9876543210
META_WA_VERIFY_TOKEN=my_secret_verify_token
```

---

## License

MIT
