"""
Custom signals emitted by django-meta-whatsapp.

Usage example in host project:

    from django_meta_whatsapp.signals import whatsapp_message_received

    @receiver(whatsapp_message_received)
    def handle_inbound(sender, message, **kwargs):
        print(message.phone_number, message.message_body)
"""
from django.dispatch import Signal

whatsapp_message_received = Signal()   # kwargs: message (WhatsAppMessage)
whatsapp_message_sent = Signal()       # kwargs: message (WhatsAppMessage)
whatsapp_campaign_completed = Signal() # kwargs: campaign (WhatsAppCampaign), sent, failed
