from django.test import TestCase
from django_meta_whatsapp.models import (
    WhatsAppAccount,
    WhatsAppContact,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppMedia,
    WhatsAppWebhookLog,
    WhatsAppAPIKey,
)
from django.utils import timezone

class WhatsAppModelTests(TestCase):
    def setUp(self):
        self.account = WhatsAppAccount.objects.create(
            name="Test Business",
            access_token="eaax_test_token",
            phone_number_id="123456789",
            waba_id="987654321"
        )
        self.contact = WhatsAppContact.objects.create(
            phone="+919876543210",
            name="John Doe",
            email="john@example.com",
            tags=["vip"]
        )

    def test_whatsapp_account_creation(self):
        self.assertEqual(str(self.account), "Test Business")
        self.assertTrue(self.account.is_active)
        self.assertIsNotNone(self.account.verify_token)

    def test_whatsapp_contact_properties(self):
        self.assertEqual(str(self.contact), "John Doe (+919876543210)")
        self.assertEqual(self.contact.display_name, "John Doe")
        self.assertEqual(self.contact.normalized_phone, "919876543210")

        # Test fallback to phone when name is empty
        contact_no_name = WhatsAppContact.objects.create(phone="9112345678")
        self.assertEqual(contact_no_name.display_name, "9112345678")

    def test_whatsapp_conversation_creation(self):
        conversation = WhatsAppConversation.objects.create(
            account=self.account,
            contact=self.contact,
            phone_number=self.contact.phone,
            label="lead"
        )
        self.assertEqual(str(conversation), f"Conversation with {self.contact.phone}")
        self.assertFalse(conversation.is_resolved)

    def test_whatsapp_message_properties(self):
        conversation = WhatsAppConversation.objects.create(
            account=self.account,
            contact=self.contact,
            phone_number=self.contact.phone
        )
        message = WhatsAppMessage.objects.create(
            conversation=conversation,
            account=self.account,
            phone_number=self.contact.phone,
            message_type="text",
            message_body="Hello World",
            direction="outbound",
            status="sent"
        )
        self.assertIn("[outbound] +919876543210", str(message))
        self.assertFalse(message.is_location)
        self.assertFalse(message.has_media)

        # Test location message
        loc_message = WhatsAppMessage.objects.create(
            conversation=conversation,
            account=self.account,
            phone_number=self.contact.phone,
            message_type="location",
            location_latitude=12.34,
            location_longitude=56.78
        )
        self.assertTrue(loc_message.is_location)

    def test_whatsapp_template_creation(self):
        template = WhatsAppTemplate.objects.create(
            account=self.account,
            name="welcome_template",
            language="en",
            body_text="Welcome {{1}}!",
            status="APPROVED"
        )
        self.assertEqual(str(template), "welcome_template (en) [APPROVED]")

    def test_whatsapp_campaign_creation(self):
        template = WhatsAppTemplate.objects.create(
            account=self.account,
            name="campaign_template",
            language="en",
            body_text="Hello {{1}}!"
        )
        campaign = WhatsAppCampaign.objects.create(
            account=self.account,
            name="Spring Sale",
            template=template,
            audience_type="contacts"
        )
        self.assertEqual(str(campaign), "Spring Sale [draft]")

        recipient = WhatsAppCampaignRecipient.objects.create(
            campaign=campaign,
            phone_number="919876543210",
            name="John Doe",
            status="pending"
        )
        self.assertEqual(str(recipient), f"919876543210 – Spring Sale [pending]")

    def test_whatsapp_webhook_log(self):
        log = WhatsAppWebhookLog.objects.create(
            payload={"object": "whatsapp_business_account"}
        )
        self.assertIn("Webhook @", str(log))
        self.assertFalse(log.processed)

    def test_api_key_creation(self):
        api_key = WhatsAppAPIKey.objects.create(name="Web App Key")
        self.assertEqual(str(api_key), "Web App Key (active)")
        self.assertEqual(len(str(api_key.key)), 36) # UUID string length

