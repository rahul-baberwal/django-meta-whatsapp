from django.test import TestCase
from unittest.mock import patch, MagicMock
from django.core.files.base import ContentFile
from django_meta_whatsapp.models import (
    WhatsAppAccount,
    WhatsAppContact,
    WhatsAppTemplate,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
)
from django_meta_whatsapp.utils import (
    _normalize_phone,
    _get_credentials,
    build_template_components,
    send_text_message,
    send_location_message,
    send_template_message,
    resolve_audience,
    run_campaign,
)

class WhatsAppUtilsTests(TestCase):
    def setUp(self):
        self.account = WhatsAppAccount.objects.create(
            name="Test Business",
            access_token="eaax_test_token",
            phone_number_id="123456789",
            waba_id="987654321"
        )
        self.contact = WhatsAppContact.objects.create(
            phone="919876543210",
            name="John Doe"
        )
        self.template = WhatsAppTemplate.objects.create(
            account=self.account,
            name="hello_world",
            language="en",
            body_text="Hello {{1}}!"
        )

    def test_normalize_phone(self):
        self.assertEqual(_normalize_phone("9876543210"), "919876543210")
        self.assertEqual(_normalize_phone("+1 234-567-8900"), "12345678900")
        self.assertEqual(_normalize_phone("919876543210"), "919876543210")

    def test_get_credentials(self):
        token, phone_id = _get_credentials(self.account)
        self.assertEqual(token, "eaax_test_token")
        self.assertEqual(phone_id, "123456789")

    def test_build_template_components(self):
        components = build_template_components(
            header_params=["HeaderVal"],
            body_params=["BodyVal1", "BodyVal2"],
            buttons=[{"index": 0, "sub_type": "quick_reply", "payload": "ClickMe"}]
        )
        self.assertEqual(len(components), 3)
        self.assertEqual(components[0]["type"], "header")
        self.assertEqual(components[1]["type"], "body")
        self.assertEqual(components[2]["type"], "button")

    @patch("requests.post")
    def test_send_text_message(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "msg_123"}]}
        mock_post.return_value = mock_resp

        res = send_text_message("919876543210", "Hello there", account=self.account)
        self.assertEqual(res["messages"][0]["id"], "msg_123")
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_send_location_message(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "msg_loc"}]}
        mock_post.return_value = mock_resp

        res = send_location_message(
            "919876543210",
            12.34,
            56.78,
            name="My Shop",
            address="123 Main St",
            account=self.account
        )
        self.assertEqual(res["messages"][0]["id"], "msg_loc")
        mock_post.assert_called_once()

    def test_resolve_audience_contacts(self):
        campaign = WhatsAppCampaign.objects.create(
            account=self.account,
            name="Contacts Campaign",
            template=self.template,
            audience_type="contacts"
        )
        recipients = resolve_audience(campaign)
        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0]["phone"], "919876543210")
        self.assertEqual(recipients[0]["name"], "John Doe")

    def test_resolve_audience_csv(self):
        campaign = WhatsAppCampaign.objects.create(
            account=self.account,
            name="CSV Campaign",
            template=self.template,
            audience_type="csv"
        )
        csv_content = b"phone,name\n919876543210,Jane Doe\n919998887776,Bob Smith\n"
        campaign.csv_file.save("contacts.csv", ContentFile(csv_content))
        
        recipients = resolve_audience(campaign)
        self.assertEqual(len(recipients), 2)
        self.assertEqual(recipients[0]["phone"], "919876543210")
        self.assertEqual(recipients[0]["name"], "Jane Doe")
        self.assertEqual(recipients[1]["phone"], "919998887776")
        self.assertEqual(recipients[1]["name"], "Bob Smith")

    @patch("requests.post")
    def test_run_campaign(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "msg_campaign"}]}
        mock_post.return_value = mock_resp

        campaign = WhatsAppCampaign.objects.create(
            account=self.account,
            name="Bulk Promo",
            template=self.template,
            audience_type="contacts",
            parameter_mappings={"1": "name"}
        )
        
        result = run_campaign(campaign.id, account=self.account)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 0)
        
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "completed")
        self.assertEqual(campaign.sent_count, 1)

        # Check recipient row
        recipients = WhatsAppCampaignRecipient.objects.filter(campaign=campaign)
        self.assertEqual(recipients.count(), 1)
        self.assertEqual(recipients[0].status, "sent")
        self.assertEqual(recipients[0].message_id, "msg_campaign")

    @patch("requests.post")
    def test_push_standard_template_to_meta(self, mock_post):
        from django_meta_whatsapp.utils import push_template_to_meta
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "meta_tpl_id_123"}
        mock_post.return_value = mock_resp

        tmpl = WhatsAppTemplate.objects.create(
            account=self.account,
            name="welcome_user",
            language="en",
            category="MARKETING",
            body_text="Welcome {{1}}!",
            footer_text="Unsubscribe",
            buttons=[{"type": "QUICK_REPLY", "text": "Yes"}]
        )

        res = push_template_to_meta(tmpl, account=self.account)
        self.assertEqual(res["id"], "meta_tpl_id_123")

        # Verify POST payload sent to Meta
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["name"], "welcome_user")
        self.assertEqual(payload["category"], "MARKETING")
        self.assertEqual(len(payload["components"]), 3)
        self.assertEqual(payload["components"][0]["type"], "BODY")
        self.assertEqual(payload["components"][0]["text"], "Welcome {{1}}!")
        self.assertEqual(payload["components"][1]["type"], "FOOTER")
        self.assertEqual(payload["components"][1]["text"], "Unsubscribe")

    @patch("requests.post")
    def test_push_auth_template_to_meta(self, mock_post):
        from django_meta_whatsapp.utils import push_template_to_meta
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "meta_tpl_id_auth"}
        mock_post.return_value = mock_resp

        # 1. Test standard auth template (which defaults to COPY_CODE button)
        tmpl = WhatsAppTemplate.objects.create(
            account=self.account,
            name="auth_code",
            language="en",
            category="AUTHENTICATION",
            body_text="Your OTP is {{1}}.",
            footer_text="Expires in 10 minutes"
        )

        res = push_template_to_meta(tmpl, account=self.account)
        self.assertEqual(res["id"], "meta_tpl_id_auth")

        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["category"], "AUTHENTICATION")
        components = payload["components"]
        self.assertEqual(len(components), 3)

        # BODY should NOT have text, but add_security_recommendation = True
        body = next(c for c in components if c["type"] == "BODY")
        self.assertNotIn("text", body)
        self.assertTrue(body["add_security_recommendation"])

        # FOOTER should be converted to code_expiration_minutes
        footer = next(c for c in components if c["type"] == "FOOTER")
        self.assertEqual(footer["code_expiration_minutes"], 10)

        # BUTTONS should be converted to OTP type COPY_CODE
        buttons = next(c for c in components if c["type"] == "BUTTONS")
        self.assertEqual(buttons["buttons"][0]["type"], "OTP")
        self.assertEqual(buttons["buttons"][0]["otp_type"], "COPY_CODE")
