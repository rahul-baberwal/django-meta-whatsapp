from django.db import models
from django.utils import timezone
import uuid


# ─────────────────────────────────────────────
# Account
# ─────────────────────────────────────────────

class WhatsAppAccount(models.Model):
    """
    Supports multi-business: one Django project can host multiple WA accounts
    (e.g. Business A, Business B each get their own account row).
    """
    name = models.CharField(max_length=255, help_text="Friendly label, e.g. 'My Business'")
    access_token = models.TextField(help_text="Meta permanent / system-user access token")
    phone_number_id = models.CharField(max_length=100)
    waba_id = models.CharField(max_length=100, blank=True)
    verify_token = models.CharField(max_length=255, default=uuid.uuid4, help_text="Webhook verify token")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp Account"
        verbose_name_plural = "WhatsApp Accounts"

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────
# Contact
# ─────────────────────────────────────────────

class WhatsAppContact(models.Model):
    phone = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    tags = models.JSONField(default=list, blank=True, help_text='e.g. ["vip", "lead"]')
    notes = models.TextField(blank=True)
    opted_out = models.BooleanField(default=False, help_text="Contact has opted out of marketing")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name or self.phone} ({self.phone})"

    @property
    def display_name(self):
        return self.name or self.phone

    @property
    def normalized_phone(self):
        """Return phone without leading + for API calls."""
        return self.phone.lstrip("+")


# ─────────────────────────────────────────────
# Conversation
# ─────────────────────────────────────────────

class WhatsAppConversation(models.Model):
    LABEL_CHOICES = [
        ("lead", "Lead"),
        ("customer", "Customer"),
        ("vip", "VIP"),
        ("support", "Support"),
        ("spam", "Spam"),
    ]

    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True, blank=True,
    )
    contact = models.ForeignKey(
        WhatsAppContact,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True, blank=True,
    )
    # Fallback when contact record doesn't exist yet
    phone_number = models.CharField(max_length=30)
    label = models.CharField(max_length=20, choices=LABEL_CHOICES, blank=True)
    is_resolved = models.BooleanField(default=False)
    assigned_to = models.CharField(max_length=255, blank=True, help_text="Agent username or email")
    last_message_at = models.DateTimeField(null=True, blank=True)
    unread_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at"]
        verbose_name = "Conversation"

    def __str__(self):
        return f"Conversation with {self.phone_number}"


# ─────────────────────────────────────────────
# Message
# ─────────────────────────────────────────────

class WhatsAppMessage(models.Model):
    STATUS_CHOICES = [
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("read", "Read"),
        ("failed", "Failed"),
    ]
    TYPE_CHOICES = [
        ("text", "Text"),
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("document", "Document"),
        ("location", "Location"),
        ("template", "Template"),
        ("reaction", "Reaction"),
        ("sticker", "Sticker"),
        ("interactive", "Interactive"),
        ("button", "Button"),
        ("unknown", "Unknown"),
    ]

    conversation = models.ForeignKey(
        WhatsAppConversation,
        on_delete=models.SET_NULL,
        related_name="messages",
        null=True, blank=True,
    )
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.SET_NULL,
        related_name="messages",
        null=True, blank=True,
    )
    phone_number = models.CharField(max_length=30)
    message_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    message_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="text")
    message_body = models.TextField(blank=True)
    direction = models.CharField(max_length=10, choices=[("inbound", "Inbound"), ("outbound", "Outbound")])
    status = models.CharField(max_length=20, default="sent", choices=STATUS_CHOICES)

    # Media
    media_file = models.FileField(upload_to="whatsapp_media/", blank=True, null=True)
    media_id = models.CharField(max_length=255, blank=True, null=True, help_text="Meta media ID")
    media_url = models.URLField(max_length=1000, blank=True, null=True)
    media_mime_type = models.CharField(max_length=100, blank=True, null=True)
    media_filename = models.CharField(max_length=255, blank=True, null=True)

    # Location
    location_latitude = models.FloatField(null=True, blank=True)
    location_longitude = models.FloatField(null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    location_address = models.TextField(blank=True)

    # Reaction
    reaction_emoji = models.CharField(max_length=10, blank=True)
    reaction_to_message_id = models.CharField(max_length=255, blank=True)

    # Threading
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="replies",
    )

    timestamp = models.DateTimeField(default=timezone.now)
    is_deleted = models.BooleanField(default=False)
    raw_payload = models.JSONField(null=True, blank=True, help_text="Full webhook payload for debugging")

    class Meta:
        ordering = ["timestamp"]
        verbose_name = "Message"

    def __str__(self):
        return f"[{self.direction}] {self.phone_number} – {self.message_type} @ {self.timestamp:%Y-%m-%d %H:%M}"

    @property
    def is_location(self):
        return self.message_type == "location"

    @property
    def has_media(self):
        return self.message_type in ["image", "video", "audio", "document", "sticker"]


# ─────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────

class WhatsAppTemplate(models.Model):
    STATUS_CHOICES = [
        ("APPROVED", "Approved"),
        ("PENDING", "Pending"),
        ("REJECTED", "Rejected"),
        ("DRAFT", "Draft"),
    ]
    CATEGORY_CHOICES = [
        ("MARKETING", "Marketing"),
        ("UTILITY", "Utility"),
        ("AUTHENTICATION", "Authentication"),
    ]

    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="templates",
        null=True, blank=True,
    )
    name = models.CharField(max_length=512)
    meta_template_id = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=10, default="en")
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="MARKETING")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")

    # Components stored as JSON so the package stays generic
    header = models.JSONField(null=True, blank=True, help_text='{"type": "TEXT"|"IMAGE"|"VIDEO"|"DOCUMENT", "text": "..."}')
    body_text = models.TextField(help_text="Use {{1}}, {{2}} for variables")
    footer_text = models.CharField(max_length=255, blank=True)
    buttons = models.JSONField(default=list, blank=True, help_text='[{"type":"QUICK_REPLY","text":"Yes"}]')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("account", "name", "language")]
        verbose_name = "Template"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.language}) [{self.status}]"


# ─────────────────────────────────────────────
# Campaign
# ─────────────────────────────────────────────

class WhatsAppCampaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("scheduled", "Scheduled"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("paused", "Paused"),
    ]

    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="campaigns",
        null=True, blank=True,
    )
    name = models.CharField(max_length=255)
    template = models.ForeignKey(
        WhatsAppTemplate,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="campaigns",
    )
    # Audience: either a named provider key (from settings WHATSAPP["AUDIENCES"])
    # or "contacts" to use saved WhatsAppContact records, or "csv" for uploaded list
    audience_type = models.CharField(
        max_length=50, default="contacts",
        help_text="'contacts', 'csv', or an AUDIENCES key from settings"
    )
    audience_filters = models.JSONField(default=dict, blank=True, help_text="Extra filter kwargs passed to audience provider")
    csv_file = models.FileField(upload_to="whatsapp_campaign_csv/", blank=True, null=True)

    # Template variable mapping: {"1": "name", "2": "order_id"} – field names on the resolved object
    parameter_mappings = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    total_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    read_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Campaign"

    def __str__(self):
        return f"{self.name} [{self.status}]"


class WhatsAppCampaignRecipient(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("read", "Read"),
        ("failed", "Failed"),
    ]

    campaign = models.ForeignKey(WhatsAppCampaign, on_delete=models.CASCADE, related_name="recipients")
    phone_number = models.CharField(max_length=30)
    name = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(default=dict, blank=True, help_text="Resolved template variables for this recipient")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    message_id = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Campaign Recipient"

    def __str__(self):
        return f"{self.phone_number} – {self.campaign.name} [{self.status}]"


# ─────────────────────────────────────────────
# Media Library
# ─────────────────────────────────────────────

class WhatsAppMedia(models.Model):
    MEDIA_TYPES = [
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("document", "Document"),
    ]

    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="media",
    )
    file = models.FileField(upload_to="whatsapp_media_library/")
    media_id = models.CharField(max_length=255, blank=True, help_text="ID returned by Meta after upload")
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES)
    mime_type = models.CharField(max_length=100, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Media"
        verbose_name_plural = "Media Library"

    def __str__(self):
        return f"{self.media_type}: {self.original_filename or self.media_id}"


# ─────────────────────────────────────────────
# Webhook Log
# ─────────────────────────────────────────────

class WhatsAppWebhookLog(models.Model):
    received_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Webhook Log"

    def __str__(self):
        return f"Webhook @ {self.received_at:%Y-%m-%d %H:%M:%S} (processed={self.processed})"


# ─────────────────────────────────────────────
# API Key
# ─────────────────────────────────────────────

class WhatsAppAPIKey(models.Model):
    name = models.CharField(max_length=255)
    key = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API Key"

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"
