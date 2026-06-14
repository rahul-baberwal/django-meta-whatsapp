"""
django_meta_whatsapp.utils
~~~~~~~~~~~~~~~~~~~~~~~~~~
Low-level wrappers around the Meta WhatsApp Cloud API v22.0.
All functions accept an optional `account` (WhatsAppAccount instance).
When account=None the legacy single-account env-var / settings path is used.
"""

from __future__ import annotations

import os
import requests
from django.conf import settings

GRAPH_API_VERSION = "v22.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


# ─────────────────────────────────────────────
# Credential helpers
# ─────────────────────────────────────────────

def _get_credentials(account=None):
    """Return (access_token, phone_number_id) from account model or Django settings."""
    if account is not None:
        return account.access_token, account.phone_number_id

    wa_settings = getattr(settings, "WHATSAPP", {})
    token = (
        wa_settings.get("ACCESS_TOKEN")
        or getattr(settings, "META_WA_ACCESS_TOKEN", None)
        or os.environ.get("META_WA_ACCESS_TOKEN")
    )
    phone_id = (
        wa_settings.get("PHONE_NUMBER_ID")
        or getattr(settings, "META_WA_PHONE_NUMBER_ID", None)
        or os.environ.get("META_WA_PHONE_NUMBER_ID")
    )
    if not token or not phone_id:
        raise ValueError(
            "Missing Meta WhatsApp credentials. Set WHATSAPP['ACCESS_TOKEN'] and "
            "WHATSAPP['PHONE_NUMBER_ID'] in Django settings, or use a WhatsAppAccount instance."
        )
    return token, phone_id


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _normalize_phone(phone: str) -> str:
    """Strip + and ensure country code. Defaults to +91 for 10-digit numbers (India)."""
    number = str(phone).strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(number) == 10:
        number = f"91{number}"
    return number


def _raise_for_meta_error(response: requests.Response):
    """Parse Meta error JSON and raise with a human-readable message."""
    if response.status_code < 400:
        return
    try:
        err = response.json().get("error", {})
        user_msg = err.get("error_user_msg")
        user_title = err.get("error_user_title")
        details = err.get("error_data", {}).get("details", "")
        base = err.get("message") or response.text
        if user_msg:
            msg = f"{user_title}: {user_msg}" if user_title else user_msg
        elif details:
            msg = f"{base} (Details: {details})"
        else:
            msg = base
        raise Exception(msg)
    except Exception as e:
        if response.status_code >= 400:
            raise
        response.raise_for_status()


# ─────────────────────────────────────────────
# Text message
# ─────────────────────────────────────────────

def send_text_message(phone_number: str, text: str, reply_message_id: str | None = None, account=None) -> dict:
    """Send a plain text WhatsApp message."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    if reply_message_id:
        payload["context"] = {"message_id": reply_message_id}
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


# ─────────────────────────────────────────────
# Location message
# ─────────────────────────────────────────────

def send_location_message(
    phone_number: str,
    latitude: float,
    longitude: float,
    name: str = "",
    address: str = "",
    reply_message_id: str | None = None,
    account=None,
) -> dict:
    """
    Send a location pin to a WhatsApp contact.

    Parameters
    ----------
    phone_number : str
        Recipient's phone number (with or without country code).
    latitude : float
        Decimal degrees latitude.
    longitude : float
        Decimal degrees longitude.
    name : str, optional
        Location name shown in chat (e.g. "Our Store").
    address : str, optional
        Address text shown below the pin.
    """
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
        },
    }
    if reply_message_id:
        payload["context"] = {"message_id": reply_message_id}
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


# ─────────────────────────────────────────────
# Media upload
# ─────────────────────────────────────────────

def upload_media(file_obj, mime_type: str, account=None) -> str:
    """
    Upload a file to Meta and return the media_id string.
    Normalises .m4a mime type for Meta compatibility.
    """
    token, phone_id = _get_credentials(account)

    # Meta quirk: .m4a must be sent as audio/mp4
    filename = getattr(file_obj, "name", "file")
    if filename and filename.lower().endswith(".m4a"):
        mime_type = "audio/mp4"
    elif mime_type in ("audio/x-m4a", "audio/m4a"):
        mime_type = "audio/mp4"

    url = f"{GRAPH_BASE}/{phone_id}/media"
    file_obj.seek(0)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, file_obj.read(), mime_type)},
        data={"messaging_product": "whatsapp"},
        timeout=30,
    )
    _raise_for_meta_error(resp)
    return resp.json()["id"]


# ─────────────────────────────────────────────
# Media message
# ─────────────────────────────────────────────

def send_media_message(
    phone_number: str,
    media_id: str,
    media_type: str,
    caption: str = "",
    filename: str = "document",
    reply_message_id: str | None = None,
    account=None,
) -> dict:
    """Send an already-uploaded media file (image/video/audio/document)."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    media_obj: dict = {"id": media_id}
    if caption and media_type in ("image", "video", "document"):
        media_obj["caption"] = caption
    if media_type == "document":
        media_obj["filename"] = filename
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": media_type,
        media_type: media_obj,
    }
    if reply_message_id:
        payload["context"] = {"message_id": reply_message_id}
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


# ─────────────────────────────────────────────
# Template message
# ─────────────────────────────────────────────

def send_template_message(
    phone_number: str,
    template_name: str,
    language_code: str = "en",
    components: list | None = None,
    account=None,
) -> dict:
    """
    Send an approved WhatsApp template.

    Parameters
    ----------
    components : list, optional
        Pre-built Meta components list. If None, sends the template with no variables.
    """
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


def build_template_components(header_params=None, body_params=None, buttons=None) -> list:
    """
    Helper to build a Meta template components list from plain Python values.

    Parameters
    ----------
    header_params : list of str, optional
        Text variable values for the header (usually just one).
    body_params : list of str, optional
        Text variable values for the body, in order of {{1}}, {{2}} …
    buttons : list of dict, optional
        Each dict: {"index": 0, "sub_type": "url" | "quick_reply", "payload": "..."}

    Returns
    -------
    list
        Ready-to-pass components list.
    """
    components = []
    if header_params:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": str(p)} for p in header_params],
        })
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        })
    if buttons:
        for btn in buttons:
            components.append({
                "type": "button",
                "sub_type": btn.get("sub_type", "quick_reply"),
                "index": btn.get("index", 0),
                "parameters": [{"type": "payload", "payload": btn.get("payload", "")}],
            })
    return components


# ─────────────────────────────────────────────
# Template management (Meta Graph API)
# ─────────────────────────────────────────────

def sync_templates_from_meta(account=None) -> list:
    """
    Fetch all approved/pending templates from Meta and return as list of dicts.
    Caller is responsible for updating WhatsAppTemplate records.
    """
    token, _ = _get_credentials(account)
    wa_settings = getattr(settings, "WHATSAPP", {})
    waba_id = (
        getattr(account, "waba_id", None)
        or wa_settings.get("WABA_ID")
        or getattr(settings, "META_WABA_ID", None)
        or os.environ.get("META_WABA_ID")
    )
    if not waba_id:
        raise ValueError("WABA ID required to sync templates. Set WHATSAPP['WABA_ID'] in settings.")
    url = f"{GRAPH_BASE}/{waba_id}/message_templates?limit=100"
    resp = requests.get(url, headers=_headers(token), timeout=15)
    _raise_for_meta_error(resp)
    return resp.json().get("data", [])


def push_template_to_meta(template_obj, account=None) -> dict:
    """
    Create or update a WhatsAppTemplate on Meta.
    `template_obj` is a django_meta_whatsapp.models.WhatsAppTemplate instance.
    """
    token, _ = _get_credentials(account or template_obj.account)
    wa_settings = getattr(settings, "WHATSAPP", {})
    waba_id = (
        getattr(account or template_obj.account, "waba_id", None)
        or wa_settings.get("WABA_ID")
        or getattr(settings, "META_WABA_ID", None)
        or os.environ.get("META_WABA_ID")
    )
    components = []
    if template_obj.header:
        components.append({"type": "HEADER", **template_obj.header})
    components.append({"type": "BODY", "text": template_obj.body_text})
    if template_obj.footer_text:
        components.append({"type": "FOOTER", "text": template_obj.footer_text})
    if template_obj.buttons:
        components.append({"type": "BUTTONS", "buttons": template_obj.buttons})
    payload = {
        "name": template_obj.name,
        "language": template_obj.language,
        "category": template_obj.category,
        "components": components,
    }
    url = f"{GRAPH_BASE}/{waba_id}/message_templates"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


def delete_template_from_meta(template_name: str, account=None) -> dict:
    """Delete a template from Meta by name."""
    token, _ = _get_credentials(account)
    wa_settings = getattr(settings, "WHATSAPP", {})
    waba_id = (
        getattr(account, "waba_id", None)
        or wa_settings.get("WABA_ID")
        or getattr(settings, "META_WABA_ID", None)
        or os.environ.get("META_WABA_ID")
    )
    url = f"{GRAPH_BASE}/{waba_id}/message_templates?name={template_name}"
    resp = requests.delete(url, headers=_headers(token), timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()


# ─────────────────────────────────────────────
# Audience resolution
# ─────────────────────────────────────────────

def resolve_audience(campaign) -> list:
    """
    Return a list of dicts: [{"phone": "...", "name": "...", "params": {...}}, ...]

    Resolution order:
    1. WHATSAPP["CAMPAIGN_RESOLVER"] – full control
    2. WHATSAPP["AUDIENCES"][campaign.audience_type] – queryset provider
    3. campaign.audience_type == "contacts" – use WhatsAppContact records
    4. campaign.audience_type == "csv" – parse the campaign's csv_file

    The phone field name on the returned model rows is taken from
    WHATSAPP["PHONE_FIELD"] (default "phone") and name from
    WHATSAPP["NAME_FIELD"] (default "name").
    """
    from importlib import import_module
    wa_settings = getattr(settings, "WHATSAPP", {})

    # 1. Custom campaign resolver
    resolver_path = wa_settings.get("CAMPAIGN_RESOLVER")
    if resolver_path:
        module_path, func_name = resolver_path.rsplit(".", 1)
        module = import_module(module_path)
        resolver = getattr(module, func_name)
        return resolver(campaign)

    phone_field = wa_settings.get("PHONE_FIELD", "phone")
    name_field = wa_settings.get("NAME_FIELD", "name")

    # 2. Named audience provider
    audiences = wa_settings.get("AUDIENCES", {})
    provider_path = audiences.get(campaign.audience_type)
    if provider_path:
        module_path, func_name = provider_path.rsplit(".", 1)
        module = import_module(module_path)
        provider = getattr(module, func_name)
        qs = provider()
        recipients = []
        for obj in qs:
            phone = getattr(obj, phone_field, None)
            name = getattr(obj, name_field, "")
            if phone:
                recipients.append({"phone": str(phone), "name": str(name), "params": {}})
        return recipients

    # 3. Built-in: WhatsAppContact records
    if campaign.audience_type == "contacts":
        from .models import WhatsAppContact
        qs = WhatsAppContact.objects.filter(opted_out=False, is_blocked=False)
        if campaign.audience_filters:
            qs = qs.filter(**campaign.audience_filters)
        return [
            {"phone": c.normalized_phone, "name": c.display_name, "params": {}}
            for c in qs
        ]

    # 4. CSV
    if campaign.audience_type == "csv" and campaign.csv_file:
        import csv, io
        campaign.csv_file.seek(0)
        text = campaign.csv_file.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        recipients = []
        for row in reader:
            phone = row.get("phone") or row.get("Phone") or row.get("mobile") or ""
            name = row.get("name") or row.get("Name") or ""
            phone = phone.strip().replace("+", "").replace(" ", "")
            if len(phone) == 10:
                phone = f"91{phone}"
            if phone:
                recipients.append({"phone": phone, "name": name, "params": dict(row)})
        return recipients

    return []


# ─────────────────────────────────────────────
# Campaign runner
# ─────────────────────────────────────────────

def run_campaign(campaign_id: int, account=None) -> dict:
    """
    Synchronously execute a campaign.
    For large campaigns use run_campaign_async (Celery).
    """
    from .models import WhatsAppCampaign, WhatsAppCampaignRecipient
    from django.utils import timezone

    campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
    if not campaign.template:
        raise ValueError("Campaign has no template assigned.")

    campaign.status = "running"
    campaign.started_at = timezone.now()
    campaign.save(update_fields=["status", "started_at"])

    recipients = resolve_audience(campaign)
    campaign.total_count = len(recipients)
    campaign.save(update_fields=["total_count"])

    sent = delivered = failed = 0
    acc = account or campaign.account

    for r in recipients:
        recipient_obj = WhatsAppCampaignRecipient.objects.create(
            campaign=campaign,
            phone_number=r["phone"],
            name=r.get("name", ""),
            parameters=r.get("params", {}),
        )
        try:
            # Build components from parameter_mappings + resolved params
            body_params = []
            for idx in sorted(campaign.parameter_mappings.keys()):
                field = campaign.parameter_mappings[idx]
                val = r.get("params", {}).get(field) or r.get(field, "")
                body_params.append(str(val))

            components = build_template_components(body_params=body_params if body_params else None)
            resp = send_template_message(
                r["phone"],
                campaign.template.name,
                language_code=campaign.template.language,
                components=components or None,
                account=acc,
            )
            msg_id = resp.get("messages", [{}])[0].get("id")
            recipient_obj.status = "sent"
            recipient_obj.message_id = msg_id
            recipient_obj.sent_at = timezone.now()
            sent += 1
        except Exception as e:
            recipient_obj.status = "failed"
            recipient_obj.error_message = str(e)
            failed += 1
        recipient_obj.save()

    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.status = "completed"
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=["sent_count", "failed_count", "status", "completed_at"])

    return {"sent": sent, "failed": failed}


def run_campaign_async(campaign_id: int, account_id: int | None = None):
    """Fire the campaign via Celery if available, otherwise run synchronously."""
    use_celery = getattr(settings, "WHATSAPP_USE_CELERY", False)
    if use_celery:
        try:
            from .tasks import run_campaign_task
            run_campaign_task.delay(campaign_id, account_id)
            return {"queued": True}
        except ImportError:
            pass
    return run_campaign(campaign_id)


# ─────────────────────────────────────────────
# Product and Catalog Messages
# ─────────────────────────────────────────────

def sync_catalog_products(catalog_id: str, account=None) -> dict:
    """Fetch all products for a given Meta Catalog ID and update local mirror."""
    token, phone_id = _get_credentials(account)
    from .models import WhatsAppCatalogProduct
    
    url = f"{GRAPH_BASE}/{catalog_id}/products"
    params = {"fields": "id,name,price,image_url,currency", "limit": 100}
    
    synced_count = 0
    while url:
        resp = requests.get(url, headers=_headers(token), params=params, timeout=15)
        _raise_for_meta_error(resp)
        data = resp.json()
        
        for item in data.get("data", []):
            price_str = f"{item.get('price', '')} {item.get('currency', '')}".strip()
            WhatsAppCatalogProduct.objects.update_or_create(
                account=account,
                catalog_id=catalog_id,
                retailer_id=item.get("id"),
                defaults={
                    "name": item.get("name", "Unknown Product"),
                    "price": price_str,
                    "image_url": item.get("image_url", ""),
                    "is_active": True,
                }
            )
            synced_count += 1
            
        paging = data.get("paging", {})
        url = paging.get("next")
        params = None  # Next URL already includes paging params
        
    return {"synced": synced_count}

# ─────────────────────────────────────────────
# Blocked Users API
# ─────────────────────────────────────────────

def block_users(phone_numbers: list, account=None) -> dict:
    """
    Block up to 1,000 WhatsApp users in one call.
    Also updates local WhatsAppBlockedUser records.
    Returns Meta's response dict with added_users / failed_users.
    """
    from .models import WhatsAppBlockedUser, WhatsAppContact
    from django.utils import timezone
    
    token, phone_id = _get_credentials(account)
    url = f"{GRAPH_BASE}/{phone_id}/block_users"
    
    payload = {
        "messaging_product": "whatsapp",
        "block_users": [{"user": str(p)} for p in phone_numbers]
    }
    
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)
    data = resp.json()
    _raise_for_meta_error(resp)
    
    block_users_res = data.get("block_users", {})
    added = block_users_res.get("added_users", [])
    failed = block_users_res.get("failed_users", [])
    
    # Update local DB for successes
    for u in added:
        phone = u.get("input", "")
        wa_id = u.get("wa_id", "")
        WhatsAppBlockedUser.objects.update_or_create(
            account=account,
            phone_number=phone,
            defaults={
                "wa_id": wa_id,
                "is_active": True,
                "meta_error": "",
                "unblocked_at": None,
                "unblocked_by": ""
            }
        )
        WhatsAppContact.objects.filter(phone=phone).update(is_blocked=True)
        
    # Update local DB for failures (log error but don't mark active)
    for u in failed:
        phone = u.get("input", "")
        wa_id = u.get("wa_id", "")
        errors = u.get("errors", [])
        error_str = str(errors) if errors else "Unknown failure"
        WhatsAppBlockedUser.objects.update_or_create(
            account=account,
            phone_number=phone,
            defaults={
                "wa_id": wa_id,
                "is_active": False,
                "meta_error": error_str
            }
        )
        
    return data

def unblock_users(phone_numbers: list, account=None) -> dict:
    """
    Unblock WhatsApp users.
    Also marks local WhatsAppBlockedUser.is_active = False.
    """
    from .models import WhatsAppBlockedUser, WhatsAppContact
    from django.utils import timezone
    
    token, phone_id = _get_credentials(account)
    url = f"{GRAPH_BASE}/{phone_id}/block_users"
    
    payload = {
        "messaging_product": "whatsapp",
        "block_users": [{"user": str(p)} for p in phone_numbers]
    }
    
    resp = requests.delete(url, headers=_headers(token), json=payload, timeout=30)
    data = resp.json()
    _raise_for_meta_error(resp)
    
    block_users_res = data.get("block_users", {})
    removed = block_users_res.get("removed_users", [])
    
    for u in removed:
        phone = u.get("input", "")
        WhatsAppBlockedUser.objects.filter(account=account, phone_number=phone).update(
            is_active=False,
            unblocked_at=timezone.now()
        )
        WhatsAppContact.objects.filter(phone=phone).update(is_blocked=False)
        
    return data

def get_blocked_users(limit=100, after_cursor=None, account=None) -> dict:
    """
    Fetch blocked users from Meta with pagination.
    Returns raw Meta response with data[] and paging cursors.
    """
    token, phone_id = _get_credentials(account)
    url = f"{GRAPH_BASE}/{phone_id}/block_users?limit={limit}"
    if after_cursor:
        url += f"&after={after_cursor}"
        
    resp = requests.get(url, headers=_headers(token), timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def sync_blocked_users_from_meta(account=None) -> int:
    """
    Full sync — paginates through all blocked users on Meta
    and updates local WhatsAppBlockedUser table.
    Returns count of synced records.
    """
    from .models import WhatsAppBlockedUser, WhatsAppContact
    
    synced = 0
    after_cursor = None
    
    # First, optionally mark all existing local blocks as inactive 
    # to catch users that were unblocked outside the app, but since Meta's 
    # API only returns wa_ids (not phone numbers), it's tricky to map.
    # We will just insert/update the ones Meta returns.
    
    while True:
        data = get_blocked_users(limit=100, after_cursor=after_cursor, account=account)
        users = data.get("data", [])
        
        for u in users:
            wa_id = str(u.get("wa_id", ""))
            # Create a blocked record. We use wa_id as phone if we don't have it, 
            # as Meta's GET doesn't return the original phone number in all cases
            # (though wa_id is usually the number without the + sign).
            phone_number = f"+{wa_id}" if not wa_id.startswith("+") else wa_id
            
            WhatsAppBlockedUser.objects.update_or_create(
                account=account,
                phone_number=phone_number,
                defaults={
                    "wa_id": wa_id,
                    "is_active": True,
                    "meta_error": ""
                }
            )
            WhatsAppContact.objects.filter(phone=phone_number).update(is_blocked=True)
            synced += 1
            
        paging = data.get("paging", {})
        cursors = paging.get("cursors", {})
        after_cursor = cursors.get("after")
        if not after_cursor:
            break
            
    return synced

def send_single_product_message(phone_number: str, catalog_id: str, retailer_id: str, body: str, footer: str = "", account=None) -> dict:
    """Send a single-product message."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "product",
            "body": {"text": body},
            "action": {
                "catalog_id": catalog_id,
                "product_retailer_id": retailer_id
            }
        }
    }
    if footer:
        payload["interactive"]["footer"] = {"text": footer}
        
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def send_multi_product_message(phone_number: str, catalog_id: str, sections: list, header: str, body: str, footer: str = "", account=None) -> dict:
    """Send a multi-product message with sections."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "product_list",
            "header": {
                "type": "text",
                "text": header
            },
            "body": {"text": body},
            "action": {
                "catalog_id": catalog_id,
                "sections": sections
            }
        }
    }
    if footer:
        payload["interactive"]["footer"] = {"text": footer}
        
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def send_catalog_message(phone_number: str, thumbnail_retailer_id: str, body: str, footer: str = "", account=None) -> dict:
    """Send a catalog message showing the full catalog."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "catalog_message",
            "body": {"text": body},
            "action": {
                "name": "catalog_message",
                "parameters": {
                    "thumbnail_product_retailer_id": thumbnail_retailer_id
                }
            }
        }
    }
    if footer:
        payload["interactive"]["footer"] = {"text": footer}
        
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def send_product_carousel_message(phone_number: str, catalog_id: str, retailer_ids: list, body: str, account=None) -> dict:
    """Send a horizontally scrollable product carousel."""
    token, phone_id = _get_credentials(account)
    to = _normalize_phone(phone_number)
    items = [{"product_retailer_id": r_id} for r_id in retailer_ids]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "product_carousel",
            "body": {"text": body},
            "action": {
                "catalog_id": catalog_id,
                "sections": items
            }
        }
    }
    url = f"{GRAPH_BASE}/{phone_id}/messages"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def send_catalog_link_message(phone_number: str, wa_number: str, account=None) -> dict:
    """Send a simple text message containing the wa.me catalog link."""
    body = f"Browse our full catalog here: https://wa.me/c/{wa_number}"
    return send_text_message(phone_number, text=body, account=account)

# ─────────────────────────────────────────────
# In-App Signups (v22.0+)
# ─────────────────────────────────────────────

def create_signup(
    display_name: str,
    signup_message: str,
    confirmation_message: str,
    privacy_policy_url: str,
    website_url: str = "",
    promo_code: str = "",
    account=None
) -> dict:
    """Create a new In-App Signup link for the WABA."""
    token, _ = _get_credentials(account)
    if not account or not account.waba_id:
        raise ValueError("A configured WhatsAppAccount with a waba_id is required for Signups.")

    url = f"{GRAPH_BASE}/{account.waba_id}/signups"
    payload = {
        "display_name": display_name,
        "signup_message": signup_message,
        "confirmation_message": confirmation_message,
        "privacy_policy_url": privacy_policy_url,
    }
    if website_url:
        payload["website_url"] = website_url
    if promo_code:
        payload["promo_code"] = promo_code

    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def list_signups(account=None) -> list:
    """List all In-App Signup links for the WABA."""
    token, _ = _get_credentials(account)
    if not account or not account.waba_id:
        raise ValueError("A configured WhatsAppAccount with a waba_id is required for Signups.")

    url = f"{GRAPH_BASE}/{account.waba_id}/signups"
    resp = requests.get(url, headers=_headers(token), timeout=15)
    _raise_for_meta_error(resp)
    return resp.json().get("data", [])

def get_signup(signup_id: str, account=None) -> dict:
    """Get details of a specific In-App Signup link."""
    token, _ = _get_credentials(account)
    url = f"{GRAPH_BASE}/{signup_id}"
    resp = requests.get(url, headers=_headers(token), timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def update_signup(
    signup_id: str,
    promo_code: str = None,
    confirmation_message: str = None,
    account=None
) -> dict:
    """Update a signup link (only promo_code and confirmation_message are mutable)."""
    token, _ = _get_credentials(account)
    url = f"{GRAPH_BASE}/{signup_id}"
    payload = {}
    if promo_code is not None:
        payload["promo_code"] = promo_code
    if confirmation_message is not None:
        payload["confirmation_message"] = confirmation_message

    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

def disable_signup(signup_id: str, account=None) -> dict:
    """Disable a signup link."""
    token, _ = _get_credentials(account)
    url = f"{GRAPH_BASE}/{signup_id}"
    resp = requests.post(url, headers=_headers(token), json={"status": "DISABLED"}, timeout=15)
    _raise_for_meta_error(resp)
    return resp.json()

