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
            email="john@example.com"
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
        from django_meta_whatsapp.models import WhatsAppLabel
        lbl = WhatsAppLabel.objects.create(name="lead")
        conversation = WhatsAppConversation.objects.create(
            account=self.account,
            contact=self.contact,
            phone_number=self.contact.phone,
            label=lbl
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

    def test_whatsapp_account_access_token_encryption(self):
        from django.db import connection
        
        raw_token = "meta_secret_access_token_xyz"
        acc = WhatsAppAccount.objects.create(
            name="Secure Biz",
            access_token=raw_token,
            phone_number_id="112233",
            waba_id="445566"
        )
        
        # 1. Test model layer transparency (decryption on retrieval)
        acc.refresh_from_db()
        self.assertEqual(acc.access_token, raw_token)
        
        # 2. Test database layer storage (confirm it is encrypted)
        with connection.cursor() as cursor:
            cursor.execute("SELECT access_token FROM django_meta_whatsapp_whatsappaccount WHERE id = %s", [acc.id])
            db_value = cursor.fetchone()[0]
        
        # Assert that the value in the database is not the plain text token
        self.assertNotEqual(db_value, raw_token)
        # Assert that it is indeed encrypted (Fernet tokens start with 'gAAAA')
        self.assertTrue(db_value.startswith("gAAAA"))

        # 3. Test fallback mechanism (plain text value stored directly in DB can be read)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE django_meta_whatsapp_whatsappaccount SET access_token = %s WHERE id = %s",
                ["legacy_plain_token", acc.id]
            )
        
        acc.refresh_from_db()
        self.assertEqual(acc.access_token, "legacy_plain_token")


