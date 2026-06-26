"""
Custom signals emitted by django-meta-whatsapp.

Usage example in host project:

    from django_meta_whatsapp.signals import whatsapp_message_received

    @receiver(whatsapp_message_received)
    def handle_inbound(sender, message, **kwargs):
        print(message.phone_number, message.message_body)

    # WhatsApp Flows — fired when a user completes and submits a flow:
    from django_meta_whatsapp.signals import whatsapp_flow_completed

    @receiver(whatsapp_flow_completed)
    def handle_flow_submission(sender, response, **kwargs):
        # response is a WhatsAppFlowResponse instance
        print(response.phone_number, response.response_data)
        response.processed = True
        response.save(update_fields=["processed"])
"""
from django.dispatch import Signal

whatsapp_message_received = Signal()   # kwargs: message (WhatsAppMessage)
whatsapp_message_sent = Signal()       # kwargs: message (WhatsAppMessage)
whatsapp_campaign_completed = Signal() # kwargs: campaign (WhatsAppCampaign), sent, failed
whatsapp_user_subscribed = Signal()    # kwargs: contact (WhatsAppContact), signup (WhatsAppSignup)
whatsapp_flow_completed = Signal()     # kwargs: response (WhatsAppFlowResponse)

