import json
from django.test import TestCase, Client
from django.urls import reverse
from django_meta_whatsapp.models import (
    WhatsAppAccount,
    WhatsAppAPIKey,
    WhatsAppConversation,
    WhatsAppMessage,
)

class WebhookViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.account = WhatsAppAccount.objects.create(
            name="Verify Test Business",
            access_token="eaax_test_token",
            phone_number_id="123456789",
            waba_id="987654321",
            verify_token="custom_verify_token"
        )

    def test_webhook_verification_success(self):
        url = reverse("django_meta_whatsapp:webhook")
        response = self.client.get(url, {
            "hub.mode": "subscribe",
            "hub.verify_token": "custom_verify_token",
            "hub.challenge": "12345"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "12345")

    def test_webhook_verification_fallback_success(self):
        url = reverse("django_meta_whatsapp:webhook")
        # settings.py configured with test_verify_token in runtests.py
        response = self.client.get(url, {
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "challenge_fallback"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "challenge_fallback")

    def test_webhook_verification_forbidden(self):
        url = reverse("django_meta_whatsapp:webhook")
        response = self.client.get(url, {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "12345"
        })
        self.assertEqual(response.status_code, 403)

    def test_webhook_post_message_received(self):
        url = reverse("django_meta_whatsapp:webhook")
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "entry_id_1",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "16505553333",
                                    "phone_number_id": "123456789"
                                },
                                "contacts": [{"profile": {"name": "Test User"}, "wa_id": "919876543210"}],
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.HBgLOTE5ODc2NTQzMjEwFQIAERgSQ0ZBMjEyOTUxMTZFODE3NDUzAA==",
                                        "timestamp": "1672531199",
                                        "text": {"body": "Hello agent!"},
                                        "type": "text"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify message created
        msg = WhatsAppMessage.objects.filter(phone_number="919876543210").first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message_body, "Hello agent!")
        self.assertEqual(msg.direction, "inbound")
        
        # Verify conversation created
        conv = WhatsAppConversation.objects.filter(phone_number="919876543210").first()
        self.assertIsNotNone(conv)
        self.assertEqual(conv.unread_count, 1)

class RESTAPIViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_key = WhatsAppAPIKey.objects.create(name="Test REST Key")
        self.account = WhatsAppAccount.objects.create(
            name="Verify Test Business",
            access_token="eaax_test_token",
            phone_number_id="123456789",
            waba_id="987654321"
        )

    def test_api_unauthorized(self):
        url = reverse("django_meta_whatsapp:api_chats")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_api_authorized_get_chats(self):
        url = reverse("django_meta_whatsapp:api_chats")
        # Create a mock conversation
        WhatsAppConversation.objects.create(phone_number="919876543210")
        
        response = self.client.get(url, HTTP_X_API_KEY=self.api_key.key)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("conversations", data)
        self.assertEqual(len(data["conversations"]), 1)
        self.assertEqual(data["conversations"][0]["phone_number"], "919876543210")


class UpdateConversationLabelViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.client = Client()
        self.user = User.objects.create_user(username="agent", password="password")
        self.client.force_login(self.user)
        self.conv = WhatsAppConversation.objects.create(phone_number="919876543210")

    def test_update_label_success(self):
        url = reverse("django_meta_whatsapp:update_label", kwargs={"pk": self.conv.pk})
        response = self.client.post(url, {"label": "new_label"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        
        self.conv.refresh_from_db()
        self.assertIsNotNone(self.conv.label)
        self.assertEqual(self.conv.label.name, "new_label")

    def test_update_label_clear(self):
        from django_meta_whatsapp.models import WhatsAppLabel
        lbl = WhatsAppLabel.objects.create(name="some_label")
        self.conv.label = lbl
        self.conv.save()

        url = reverse("django_meta_whatsapp:update_label", kwargs={"pk": self.conv.pk})
        response = self.client.post(url, {"label": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        
        self.conv.refresh_from_db()
        self.assertIsNone(self.conv.label)
