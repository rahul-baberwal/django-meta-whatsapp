from django.contrib import admin
from .models import (
    WhatsAppAccount, WhatsAppContact, WhatsAppConversation, WhatsAppMessage,
    WhatsAppTemplate, WhatsAppCampaign, WhatsAppCampaignRecipient,
    WhatsAppMedia, WhatsAppWebhookLog, WhatsAppAPIKey,
)

@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    list_display = ["name","phone_number_id","is_active","created_at"]
    list_filter = ["is_active"]
    search_fields = ["name","phone_number_id"]

@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(admin.ModelAdmin):
    list_display = ["phone","name","email","opted_out","created_at"]
    list_filter = ["opted_out"]
    search_fields = ["phone","name","email"]

@admin.register(WhatsAppConversation)
class WhatsAppConversationAdmin(admin.ModelAdmin):
    list_display = ["phone_number","label","unread_count","is_resolved","last_message_at"]
    list_filter = ["label","is_resolved"]
    search_fields = ["phone_number"]

@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ["phone_number","direction","message_type","status","timestamp"]
    list_filter = ["direction","status","message_type"]
    search_fields = ["phone_number","message_body"]
    readonly_fields = ["raw_payload"]

@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ["name","language","category","status","created_at"]
    list_filter = ["status","category","language"]
    search_fields = ["name"]

@admin.register(WhatsAppCampaign)
class WhatsAppCampaignAdmin(admin.ModelAdmin):
    list_display = ["name","status","sent_count","failed_count","created_at"]
    list_filter = ["status"]
    search_fields = ["name"]

@admin.register(WhatsAppCampaignRecipient)
class WhatsAppCampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ["phone_number","campaign","status","sent_at"]
    list_filter = ["status"]
    search_fields = ["phone_number"]

@admin.register(WhatsAppMedia)
class WhatsAppMediaAdmin(admin.ModelAdmin):
    list_display = ["original_filename","media_type","media_id","uploaded_at"]
    list_filter = ["media_type"]

@admin.register(WhatsAppWebhookLog)
class WhatsAppWebhookLogAdmin(admin.ModelAdmin):
    list_display = ["received_at","processed","error"]
    list_filter = ["processed"]
    readonly_fields = ["payload"]

@admin.register(WhatsAppAPIKey)
class WhatsAppAPIKeyAdmin(admin.ModelAdmin):
    list_display = ["name","key","is_active","created_at"]
    list_filter = ["is_active"]
