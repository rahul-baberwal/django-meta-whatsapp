from django.db import models
from django.utils import timezone
import uuid


# ─────────────────────────────────────────────
# Encrypted Field Implementation
# ─────────────────────────────────────────────

class EncryptedTextField(models.TextField):
    """
    Symmetrically encrypts value before saving to database and decrypts it when retrieved.
    Uses cryptography's Fernet encryption.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fernet = None

    @property
    def fernet(self):
        if self._fernet is None:
            from django.conf import settings
            from django.core.exceptions import ImproperlyConfigured
            import base64
            import hashlib
            from cryptography.fernet import Fernet

            wa_settings = getattr(settings, "WHATSAPP", {})
            key_str = wa_settings.get("ENCRYPTION_KEY") or getattr(settings, "SECRET_KEY", "")
            if not key_str:
                raise ImproperlyConfigured(
                    "Encryption key is required. Set settings.SECRET_KEY or WHATSAPP['ENCRYPTION_KEY']."
                )
            key_bytes = key_str.encode("utf-8")
            hashed = hashlib.sha256(key_bytes).digest()
            derived_key = base64.urlsafe_b64encode(hashed)
            self._fernet = Fernet(derived_key)
        return self._fernet

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return value
        if not isinstance(value, str):
            value = str(value)
        encrypted_bytes = self.fernet.encrypt(value.encode("utf-8"))
        return encrypted_bytes.decode("ascii")

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            decrypted_bytes = self.fernet.decrypt(value.encode("ascii"))
            return decrypted_bytes.decode("utf-8")
        except Exception:
            # Fallback to returning raw value (useful if existing data is unencrypted)
            return value

    def to_python(self, value):
        if value is None:
            return value
        return value


# ─────────────────────────────────────────────
# Account
# ─────────────────────────────────────────────

class WhatsAppAccount(models.Model):
    """
    Supports multi-business: one Django project can host multiple WA accounts
    (e.g. Business A, Business B each get their own account row).
    """
    name = models.CharField(max_length=255, help_text="Friendly label, e.g. 'My Business'")
    access_token = EncryptedTextField(help_text="Meta permanent / system-user access token")
    phone_number_id = models.CharField(max_length=100)
    waba_id = models.CharField(max_length=100, blank=True)
    verify_token = models.CharField(max_length=255, default=uuid.uuid4, help_text="Webhook verify token")
    profile_name = models.CharField(max_length=255, blank=True, help_text="Fetched via Graph API")
    profile_picture_url = models.URLField(max_length=1024, blank=True, help_text="Fetched via Graph API")
    default_catalog_id = models.CharField(max_length=255, blank=True, help_text="Default Meta Commerce Catalog ID")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp Account"
        verbose_name_plural = "WhatsApp Accounts"

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────
# In-App Signups
# ─────────────────────────────────────────────

class WhatsAppSignup(models.Model):
    """
    Represents an In-App Signup deep link.
    One signup = one shareable wa.me/PHONE/signup/ID link.
    """
    STATUS_CHOICES = [("ACTIVE", "Active"), ("DISABLED", "Disabled")]

    account = models.ForeignKey(
        WhatsAppAccount, on_delete=models.CASCADE, related_name="signups"
    )
    signup_id = models.CharField(max_length=100, unique=True, blank=True,
        help_text="ID returned by Meta after creation")

    # Fields that go to Meta
    display_name = models.CharField(max_length=255,
        help_text="Internal label, not shown to users")
    signup_message = models.TextField(
        help_text="Pre-consent screen text shown to user in WhatsApp")
    confirmation_message = models.TextField(
        help_text="Sent to user after they subscribe. Use {{promo_code}} for promo.")
    privacy_policy_url = models.URLField(
        help_text="Immutable after creation on Meta")
    website_url = models.URLField(blank=True)
    promo_code = models.CharField(max_length=100, blank=True,
        help_text="Alphanumeric only. Replaces {{promo_code}} in confirmation message.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")

    # Local enhancements
    auto_add_to_label = models.ForeignKey(
        "WhatsAppLabel", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Automatically assign this label to users who subscribe via this link"
    )

    # Stats (updated from webhook)
    subscriber_count = models.PositiveIntegerField(default=0)

    tos_accepted = models.BooleanField(default=False,
        help_text="True after Terms of Service accepted on first creation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "In-App Signup"

    def __str__(self):
        return f"{self.display_name} [{self.status}]"

    def get_deep_link(self, phone_number: str) -> str:
        """Build the shareable wa.me deep link for a given phone number."""
        clean = str(phone_number).lstrip("+").replace(" ", "")
        return f"https://wa.me/{clean}/signup/{self.signup_id}"


# ─────────────────────────────────────────────
# Label
# ─────────────────────────────────────────────

class WhatsAppLabel(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default="gray", help_text="Tailwind color or hex")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Label"
        verbose_name_plural = "Labels"
        ordering = ["name"]

    def __str__(self):
        return self.name

# ─────────────────────────────────────────────
# Contact
# ─────────────────────────────────────────────

class WhatsAppContact(models.Model):
    phone = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    labels = models.ManyToManyField(WhatsAppLabel, blank=True, related_name="contacts")
    notes = models.TextField(blank=True)
    opted_out = models.BooleanField(default=False, help_text="Contact has opted out of marketing")
    is_blocked = models.BooleanField(default=False, help_text="Synced from WhatsAppBlockedUser — for fast inbox UI filtering")
    
    subscribed_via_signup = models.ForeignKey(
        "WhatsAppSignup", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="subscribers",
        help_text="Which signup link brought this contact in"
    )
    subscribed_at = models.DateTimeField(null=True, blank=True)

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
    label = models.ForeignKey(WhatsAppLabel, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations")
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


# ─────────────────────────────────────────────
# Catalog Product
# ─────────────────────────────────────────────

class WhatsAppCatalogProduct(models.Model):
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="catalog_products",
        null=True, blank=True,
    )
    catalog_id = models.CharField(max_length=255)
    retailer_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    price = models.CharField(max_length=100, blank=True)
    image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Catalog Product"
        unique_together = ("account", "catalog_id", "retailer_id")

    def __str__(self):
        return f"{self.name} ({self.catalog_id})"

# ─────────────────────────────────────────────
# Blocked Users
# ─────────────────────────────────────────────

class WhatsAppBlockedUser(models.Model):
    """
    Local mirror of Meta's block list.
    Source of truth is Meta — sync with GET /block_users.
    """
    account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="blocked_users",
    )
    phone_number = models.CharField(max_length=30)        # e.g. "+919876543210"
    wa_id = models.CharField(max_length=50, blank=True)   # Meta's wa_id (may differ from phone)

    blocked_at = models.DateTimeField(auto_now_add=True)
    blocked_by = models.CharField(max_length=255, blank=True,
        help_text="Username/email of agent who triggered the block")
    reason = models.TextField(blank=True,
        help_text="Internal note — spam, abuse, etc.")

    # Sync state
    is_active = models.BooleanField(default=True,
        help_text="False means unblocked — kept for audit history")
    unblocked_at = models.DateTimeField(null=True, blank=True)
    unblocked_by = models.CharField(max_length=255, blank=True)
    meta_error = models.TextField(blank=True,
        help_text="Stores error detail if Meta block call failed")

    class Meta:
        unique_together = [("account", "phone_number")]
        ordering = ["-blocked_at"]
        verbose_name = "Blocked User"

    def __str__(self):
        status = "blocked" if self.is_active else "unblocked"
        return f"{self.phone_number} [{status}]"
