from django.urls import path
from . import views

app_name = "django_meta_whatsapp"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Inbox
    path("inbox/", views.InboxView.as_view(), name="inbox"),
    path("inbox/<str:phone_number>/", views.ChatRoomView.as_view(), name="chat_room"),
    path("inbox/<str:phone_number>/send/", views.SendMessageView.as_view(), name="send_message"),
    path("inbox/message/<int:pk>/delete/", views.DeleteMessageView.as_view(), name="delete_message"),
    path("inbox/conversation/<int:pk>/label/", views.UpdateConversationLabelView.as_view(), name="update_label"),
    # Contacts
    path("contacts/", views.ContactListView.as_view(), name="contact_list"),
    path("contacts/add/", views.ContactCreateView.as_view(), name="contact_create"),
    path("contacts/<int:pk>/edit/", views.ContactUpdateView.as_view(), name="contact_update"),
    path("contacts/<int:pk>/delete/", views.ContactDeleteView.as_view(), name="contact_delete"),
    path("contacts/import/", views.ContactImportView.as_view(), name="contact_import"),
    path("contacts/export/", views.ContactExportView.as_view(), name="contact_export"),
    # Templates
    path("templates/", views.TemplateListView.as_view(), name="template_list"),
    path("templates/add/", views.TemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/edit/", views.TemplateUpdateView.as_view(), name="template_update"),
    path("templates/<int:pk>/delete/", views.TemplateDeleteView.as_view(), name="template_delete"),
    path("templates/sync/", views.TemplateSyncFromMetaView.as_view(), name="template_sync"),
    path("templates/<int:pk>/push/", views.TemplatePushToMetaView.as_view(), name="template_push"),
    # Campaigns
    path("campaigns/", views.CampaignListView.as_view(), name="campaign_list"),
    path("campaigns/add/", views.CampaignCreateView.as_view(), name="campaign_create"),
    path("campaigns/<int:pk>/", views.CampaignDetailView.as_view(), name="campaign_detail"),
    path("campaigns/<int:pk>/edit/", views.CampaignUpdateView.as_view(), name="campaign_update"),
    path("campaigns/<int:pk>/delete/", views.CampaignDeleteView.as_view(), name="campaign_delete"),
    path("campaigns/<int:pk>/run/", views.CampaignRunView.as_view(), name="campaign_run"),
    # Analytics
    path("analytics/", views.AnalyticsView.as_view(), name="analytics"),
    # Webhook
    path("webhook/", views.WebhookView.as_view(), name="webhook"),
    # Settings
    path("settings/accounts/", views.AccountListView.as_view(), name="account_list"),
    path("settings/accounts/set-global/", views.SetGlobalAccountView.as_view(), name="set_global_account"),
    path("settings/accounts/add/", views.AccountCreateView.as_view(), name="account_create"),
    path("settings/accounts/<int:pk>/edit/", views.AccountUpdateView.as_view(), name="account_update"),
    path("settings/accounts/<int:pk>/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    path("settings/api-keys/", views.APIKeyListView.as_view(), name="apikey_list"),
    path("settings/api-keys/add/", views.APIKeyCreateView.as_view(), name="apikey_create"),
    path("settings/api-keys/<int:pk>/delete/", views.APIKeyDeleteView.as_view(), name="apikey_delete"),
    # REST API
    path("api/send-message/", views.APISendMessageView.as_view(), name="api_send_message"),
    path("api/send-location/", views.APISendLocationView.as_view(), name="api_send_location"),
    path("api/send-template/", views.APISendTemplateView.as_view(), name="api_send_template"),
    path("api/chats/", views.APIChatsView.as_view(), name="api_chats"),
    path("api/campaigns/", views.APICampaignListView.as_view(), name="api_campaigns"),
    path("api/templates/<int:pk>/", views.APITemplateDetailsView.as_view(), name="api_template_details"),
]
