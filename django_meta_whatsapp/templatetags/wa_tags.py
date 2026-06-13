from django import template
from django_meta_whatsapp.models import WhatsAppAccount

register = template.Library()

@register.inclusion_tag("django_meta_whatsapp/tags/account_selector.html", takes_context=True)
def wa_account_selector(context):
    request = context.get("request")
    accounts = WhatsAppAccount.objects.filter(is_active=True).order_by("name")
    
    active_account_id = request.session.get("wa_account_id") if request else None
    active_account = None
    
    if active_account_id:
        active_account = accounts.filter(id=active_account_id).first()
        
    if not active_account and accounts.exists():
        active_account = accounts.first()
        if request:
            request.session["wa_account_id"] = active_account.id
            
    return {
        "accounts": accounts,
        "active_account": active_account,
        "request": request,
    }

@register.simple_tag
def has_any_accounts():
    return WhatsAppAccount.objects.exists()

@register.simple_tag
def wa_dashboard_name():
    from django.conf import settings
    return getattr(settings, "META_WHATSAPP_DASHBOARD_NAME", "WhatsApp")

@register.simple_tag
def wa_dashboard_icon():
    from django.conf import settings
    return getattr(settings, "META_WHATSAPP_DASHBOARD_ICON", "message-circle")

@register.simple_tag
def wa_dashboard_logo():
    from django.conf import settings
    return getattr(settings, "META_WHATSAPP_DASHBOARD_LOGO", None)
