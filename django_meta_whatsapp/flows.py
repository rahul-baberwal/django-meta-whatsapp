"""
django_meta_whatsapp.flows
~~~~~~~~~~~~~~~~~~~~~~~~~~
All Meta Graph API calls related to WhatsApp Flows.

Functions mirror the pattern used in utils.py: they accept an optional `account`
argument and resolve the active account / token internally if not provided.
"""
from __future__ import annotations
import json
import io
from typing import Any


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

_GRAPH_BASE = "https://graph.facebook.com/v21.0"


def _get_account(account=None):
    """Return a WhatsAppAccount, falling back to the first active one."""
    if account:
        return account
    from .models import WhatsAppAccount
    return WhatsAppAccount.objects.filter(is_active=True).first()


def _token(account) -> str:
    acc = _get_account(account)
    if not acc:
        raise ValueError("No active WhatsApp account found. Configure one in Settings → Accounts.")
    return acc.access_token


def _waba_id(account) -> str:
    acc = _get_account(account)
    if not acc or not acc.waba_id:
        raise ValueError("WhatsApp Business Account ID (WABA ID) is not set on the account.")
    return acc.waba_id


def _phone_id(account) -> str:
    acc = _get_account(account)
    if not acc or not acc.phone_number_id:
        raise ValueError("Phone Number ID is not set on the account.")
    return acc.phone_number_id


def _raise_for(resp):
    """Raise a descriptive ValueError for non-2xx Graph API responses."""
    if not resp.ok:
        try:
            err = resp.json().get("error", {})
            msg = err.get("error_user_msg") or err.get("message") or resp.text
        except Exception:
            msg = resp.text
        raise ValueError(f"Meta API error {resp.status_code}: {msg}")
    return resp.json()


# ─────────────────────────────────────────────
# Flow CRUD
# ─────────────────────────────────────────────

def create_flow(name: str, categories: list[str], account=None) -> dict:
    """
    Create a new Flow on Meta and return its ID.

    POST /WABA_ID/flows
    Returns: {"id": "1234567890123456"}
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{_waba_id(acc)}/flows"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}", "Content-Type": "application/json"},
        json={"name": name, "categories": categories},
        timeout=15,
    )
    return _raise_for(resp)


def upload_flow_json(flow_obj, account=None) -> dict:
    """
    Upload (or replace) the Flow JSON for an existing draft flow.

    POST /FLOW_ID/assets  (multipart/form-data)
    Returns: {"success": true, "validation_errors": [...]}
    """
    import requests
    acc = _get_account(account)
    if not flow_obj.meta_flow_id:
        raise ValueError("This flow has no Meta Flow ID yet — create it on Meta first.")

    flow_json_str = json.dumps(flow_obj.flow_json, indent=2)
    url = f"{_GRAPH_BASE}/{flow_obj.meta_flow_id}/assets"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}"},
        files={
            "name": (None, "flow.json"),
            "asset_type": (None, "FLOW_JSON"),
            "file": ("flow.json", io.BytesIO(flow_json_str.encode("utf-8")), "application/json"),
        },
        timeout=30,
    )
    return _raise_for(resp)


def get_flow(meta_flow_id: str, account=None) -> dict:
    """
    Fetch a single flow's details including status and validation errors.

    GET /FLOW_ID?fields=id,name,status,categories,validation_errors
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{meta_flow_id}"
    resp = requests.get(
        url,
        params={"fields": "id,name,status,categories,validation_errors", "access_token": _token(acc)},
        timeout=15,
    )
    return _raise_for(resp)


def list_flows_from_meta(account=None) -> list:
    """
    List all Flows for the WABA.

    GET /WABA_ID/flows
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{_waba_id(acc)}/flows"
    resp = requests.get(
        url,
        params={"access_token": _token(acc)},
        timeout=15,
    )
    data = _raise_for(resp)
    return data.get("data", [])


def publish_flow(meta_flow_id: str, account=None) -> dict:
    """
    Publish a DRAFT flow — transitions to PUBLISHED.

    POST /FLOW_ID/publish
    Returns: {"success": true}
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{meta_flow_id}/publish"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}"},
        timeout=15,
    )
    return _raise_for(resp)


def deprecate_flow(meta_flow_id: str, account=None) -> dict:
    """
    Deprecate a PUBLISHED flow — transitions to DEPRECATED.
    Deprecated flows can no longer be sent to new users.

    POST /FLOW_ID/deprecate
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{meta_flow_id}/deprecate"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}"},
        timeout=15,
    )
    return _raise_for(resp)


def delete_flow(meta_flow_id: str, account=None) -> dict:
    """
    Delete a DRAFT flow permanently from Meta.

    DELETE /FLOW_ID
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{meta_flow_id}"
    resp = requests.delete(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}"},
        timeout=15,
    )
    return _raise_for(resp)


# ─────────────────────────────────────────────
# Send a Flow message
# ─────────────────────────────────────────────

def send_flow_message(
    phone: str,
    flow_id: str,
    cta_text: str = "Open Form",
    header_text: str = "",
    body_text: str = "Please complete the form.",
    footer_text: str = "",
    screen: str = "",
    screen_data: dict | None = None,
    mode: str = "published",
    account=None,
) -> dict:
    """
    Send an interactive Flow message to a phone number.

    The message opens a native WhatsApp Flows screen when the CTA button is tapped.

    Args:
        phone:       Recipient phone number (e.g. "919876543210")
        flow_id:     Meta Flow ID
        cta_text:    Text on the call-to-action button
        header_text: Optional header above the message bubble
        body_text:   Main message body
        footer_text: Optional footer below the body
        screen:      Starting screen ID (blank = default first screen)
        screen_data: Data passed to the starting screen (for dynamic flows)
        mode:        "published" or "draft" (draft for testing)
        account:     WhatsAppAccount instance (resolved automatically if None)
    """
    import requests
    acc = _get_account(account)

    action_payload: dict[str, Any] = {
        "flow_id": flow_id,
        "flow_cta": cta_text,
        "flow_action": "navigate",
        "flow_message_version": "3",
        "mode": mode,
    }
    if screen:
        action_payload["flow_action_payload"] = {
            "screen": screen,
            "data": screen_data or {},
        }

    interactive: dict[str, Any] = {
        "type": "flow",
        "body": {"text": body_text},
        "action": {"name": "flow", "parameters": action_payload},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    url = f"{_GRAPH_BASE}/{_phone_id(acc)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone.lstrip("+"),
        "type": "interactive",
        "interactive": interactive,
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    return _raise_for(resp)


# ─────────────────────────────────────────────
# Dynamic Flows — RSA key upload
# ─────────────────────────────────────────────

def upload_rsa_public_key(public_key_pem: str, account=None) -> dict:
    """
    Upload an RSA public key to Meta — required for dynamic flows.
    Meta uses this key to encrypt data sent to your endpoint.

    Generate a key pair first:
        openssl genrsa -des3 -out private.pem 2048
        openssl rsa -in private.pem -pubout -out public.pem

    Then pass the contents of public.pem here.

    POST /PHONE_NUMBER_ID/whatsapp_business_encryption
    """
    import requests
    acc = _get_account(account)
    url = f"{_GRAPH_BASE}/{_phone_id(acc)}/whatsapp_business_encryption"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_token(acc)}"},
        data={"business_public_key": public_key_pem},
        timeout=15,
    )
    return _raise_for(resp)


# ─────────────────────────────────────────────
# Built-in starter Flow JSON templates
# ─────────────────────────────────────────────

FLOW_TEMPLATES = {
    "feedback": {
        "label": "Customer Feedback",
        "categories": ["CUSTOMER_SUPPORT"],
        "json": {
            "version": "7.2",
            "screens": [
                {
                    "id": "FEEDBACK_SCREEN",
                    "title": "Share Feedback",
                    "terminal": True,
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [
                            {
                                "type": "TextHeading",
                                "text": "How was your experience?"
                            },
                            {
                                "type": "RadioButtonsGroup",
                                "name": "rating",
                                "label": "Overall rating",
                                "required": True,
                                "data-source": [
                                    {"id": "5", "title": "⭐⭐⭐⭐⭐ Excellent"},
                                    {"id": "4", "title": "⭐⭐⭐⭐ Good"},
                                    {"id": "3", "title": "⭐⭐⭐ Average"},
                                    {"id": "2", "title": "⭐⭐ Poor"},
                                    {"id": "1", "title": "⭐ Terrible"},
                                ]
                            },
                            {
                                "type": "TextArea",
                                "name": "comments",
                                "label": "Any additional comments?",
                                "required": False,
                                "helper-text": "Optional"
                            },
                            {
                                "type": "Footer",
                                "label": "Submit Feedback",
                                "on-click-action": {
                                    "name": "complete",
                                    "payload": {
                                        "rating": "${form.rating}",
                                        "comments": "${form.comments}"
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
    },
    "lead_generation": {
        "label": "Lead Generation",
        "categories": ["LEAD_GENERATION"],
        "json": {
            "version": "7.2",
            "screens": [
                {
                    "id": "LEAD_SCREEN",
                    "title": "Get in Touch",
                    "terminal": True,
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [
                            {
                                "type": "TextHeading",
                                "text": "Tell us about yourself"
                            },
                            {
                                "type": "TextInput",
                                "name": "full_name",
                                "label": "Full Name",
                                "required": True,
                                "input-type": "text"
                            },
                            {
                                "type": "TextInput",
                                "name": "email",
                                "label": "Email Address",
                                "required": True,
                                "input-type": "email"
                            },
                            {
                                "type": "TextInput",
                                "name": "company",
                                "label": "Company (optional)",
                                "required": False,
                                "input-type": "text"
                            },
                            {
                                "type": "Dropdown",
                                "name": "interest",
                                "label": "I'm interested in",
                                "required": True,
                                "data-source": [
                                    {"id": "product_demo", "title": "Product Demo"},
                                    {"id": "pricing", "title": "Pricing Information"},
                                    {"id": "partnership", "title": "Partnership"},
                                    {"id": "other", "title": "Something else"},
                                ]
                            },
                            {
                                "type": "Footer",
                                "label": "Submit",
                                "on-click-action": {
                                    "name": "complete",
                                    "payload": {
                                        "full_name": "${form.full_name}",
                                        "email": "${form.email}",
                                        "company": "${form.company}",
                                        "interest": "${form.interest}"
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
    },
    "appointment": {
        "label": "Appointment Booking",
        "categories": ["APPOINTMENT_BOOKING"],
        "json": {
            "version": "7.2",
            "screens": [
                {
                    "id": "BOOKING_SCREEN",
                    "title": "Book Appointment",
                    "terminal": True,
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [
                            {
                                "type": "TextHeading",
                                "text": "Schedule your appointment"
                            },
                            {
                                "type": "TextInput",
                                "name": "name",
                                "label": "Your Name",
                                "required": True,
                                "input-type": "text"
                            },
                            {
                                "type": "DatePicker",
                                "name": "appointment_date",
                                "label": "Preferred Date",
                                "required": True
                            },
                            {
                                "type": "Dropdown",
                                "name": "time_slot",
                                "label": "Preferred Time",
                                "required": True,
                                "data-source": [
                                    {"id": "09:00", "title": "9:00 AM"},
                                    {"id": "10:00", "title": "10:00 AM"},
                                    {"id": "11:00", "title": "11:00 AM"},
                                    {"id": "14:00", "title": "2:00 PM"},
                                    {"id": "15:00", "title": "3:00 PM"},
                                    {"id": "16:00", "title": "4:00 PM"},
                                ]
                            },
                            {
                                "type": "TextArea",
                                "name": "notes",
                                "label": "Notes / Reason for visit",
                                "required": False
                            },
                            {
                                "type": "Footer",
                                "label": "Book Now",
                                "on-click-action": {
                                    "name": "complete",
                                    "payload": {
                                        "name": "${form.name}",
                                        "appointment_date": "${form.appointment_date}",
                                        "time_slot": "${form.time_slot}",
                                        "notes": "${form.notes}"
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
}
