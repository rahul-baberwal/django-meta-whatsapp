"""
django_meta_whatsapp.views
"""
from __future__ import annotations
import json, csv, io, datetime
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import (CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView)
from django import forms
from django.db import models
from django.db.models import Count, Q, Sum

from .models import (
    WhatsAppAccount, WhatsAppCampaign, WhatsAppCampaignRecipient,
    WhatsAppContact, WhatsAppConversation, WhatsAppMessage,
    WhatsAppTemplate, WhatsAppWebhookLog, WhatsAppAPIKey, WhatsAppLabel,
    WhatsAppCatalogProduct, WhatsAppBlockedUser, WhatsAppSignup,
    WhatsAppFlow, WhatsAppFlowResponse,
)
from .utils import (
    run_campaign_async, send_text_message, send_location_message,
    send_media_message, upload_media, sync_templates_from_meta, push_template_to_meta,
    sync_catalog_products,
)


class WALoginMixin(LoginRequiredMixin):
    @property
    def login_url(self):
        from django.conf import settings
        wa_login = getattr(settings, "WHATSAPP", {}).get("LOGIN_URL")
        if wa_login:
            return wa_login
        return getattr(settings, "LOGIN_URL", "/accounts/login/")

    def get_wa_account(self):
        aid = self.request.session.get("wa_account_id")
        if aid:
            return WhatsAppAccount.objects.filter(id=aid).first()
        return WhatsAppAccount.objects.filter(is_active=True).first()


# ── Dashboard ──────────────────────────────────────────────────
class DashboardView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/dashboard.html"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        acc_id = self.request.session.get("wa_account_id")
        conv_qs = WhatsAppConversation.objects.filter(account_id=acc_id) if acc_id else WhatsAppConversation.objects.all()
        camp_qs = WhatsAppCampaign.objects.filter(account_id=acc_id) if acc_id else WhatsAppCampaign.objects.all()
        msg_qs = WhatsAppMessage.objects.filter(account_id=acc_id) if acc_id else WhatsAppMessage.objects.all()

        ctx.update({
            "total_contacts": WhatsAppContact.objects.count(),
            "total_conversations": conv_qs.count(),
            "unread_count": conv_qs.filter(unread_count__gt=0).count(),
            "total_campaigns": camp_qs.count(),
            "running_campaigns": camp_qs.filter(status="running").count(),
            "messages_today": msg_qs.filter(timestamp__date=timezone.now().date()).count(),
            "recent_conversations": conv_qs.select_related("contact").order_by("-last_message_at")[:5],
            "recent_campaigns": camp_qs.order_by("-created_at")[:5],
        })
        return ctx


# ── Inbox ──────────────────────────────────────────────────────
class InboxView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/inbox.html"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        acc_id = self.request.session.get("wa_account_id")
        qs = WhatsAppConversation.objects.select_related("contact").order_by("-last_message_at")
        if acc_id:
            qs = qs.filter(account_id=acc_id)
        q = self.request.GET.get("q", "").strip()
        label = self.request.GET.get("label", "").strip()
        if q:
            qs = qs.filter(Q(phone_number__icontains=q) | Q(contact__name__icontains=q))
        if label:
            qs = qs.filter(label__name=label)
        ctx.update({
            "conversations": qs,
            "search_q": q,
            "active_label": label,
            "all_labels": WhatsAppLabel.objects.all()
        })
        return ctx


class ChatRoomView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/chat_room.html"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        phone = self.kwargs["phone_number"]
        conversation = WhatsAppConversation.objects.filter(phone_number=phone).first()
        if conversation:
            conversation.unread_count = 0
            conversation.save(update_fields=["unread_count"])
        ctx.update({
            "phone_number": phone,
            "conversation": conversation,
            "chat_messages": WhatsAppMessage.objects.filter(phone_number=phone, is_deleted=False).select_related("reply_to").order_by("timestamp"),
            "contact": WhatsAppContact.objects.filter(phone=phone).first(),
            "all_labels": WhatsAppLabel.objects.all(),
        })
        return ctx


class SendMessageView(WALoginMixin, View):
    def post(self, request, phone_number, *args, **kwargs):
        body = request.POST.get("body", "").strip()
        reply_to_id = request.POST.get("reply_to_id")
        media_file = request.FILES.get("media_file")
        send_loc = request.POST.get("send_location") == "1"
        lat = request.POST.get("latitude")
        lon = request.POST.get("longitude")
        loc_name = request.POST.get("location_name", "")
        loc_addr = request.POST.get("location_address", "")
        account = self._account(request)
        try:
            reply_to_msg = None
            reply_meta_id = None
            if reply_to_id:
                reply_to_msg = WhatsAppMessage.objects.filter(id=reply_to_id).first()
                if reply_to_msg:
                    reply_meta_id = reply_to_msg.message_id
            conv, _ = WhatsAppConversation.objects.get_or_create(phone_number=phone_number, defaults={"account": account, "last_message_at": timezone.now()})
            if send_loc and lat and lon:
                resp = send_location_message(phone_number, float(lat), float(lon), name=loc_name, address=loc_addr, reply_message_id=reply_meta_id, account=account)
                mid = resp.get("messages", [{}])[0].get("id")
                WhatsAppMessage.objects.create(conversation=conv, account=account, phone_number=phone_number, message_type="location", message_body=loc_name or f"{lat},{lon}", direction="outbound", message_id=mid, location_latitude=float(lat), location_longitude=float(lon), location_name=loc_name, location_address=loc_addr, reply_to=reply_to_msg, status="sent")
            elif media_file:
                ct = media_file.content_type
                mtype = "image" if ct.startswith("image/") else "video" if ct.startswith("video/") else "audio" if ct.startswith("audio/") else "document"
                mid_id = upload_media(media_file, ct, account=account)
                resp = send_media_message(phone_number, mid_id, mtype, filename=media_file.name, reply_message_id=reply_meta_id, account=account)
                mid = resp.get("messages", [{}])[0].get("id")
                WhatsAppMessage.objects.create(conversation=conv, account=account, phone_number=phone_number, message_type=mtype, message_body=body or f"[{mtype.capitalize()}]", direction="outbound", message_id=mid, media_file=media_file, media_id=mid_id, reply_to=reply_to_msg, status="sent")
            else:
                resp = send_text_message(phone_number, body, reply_message_id=reply_meta_id, account=account)
                mid = resp.get("messages", [{}])[0].get("id")
                WhatsAppMessage.objects.create(conversation=conv, account=account, phone_number=phone_number, message_type="text", message_body=body, direction="outbound", message_id=mid, reply_to=reply_to_msg, status="sent")
            conv.last_message_at = timezone.now()
            conv.save(update_fields=["last_message_at"])
            messages.success(request, "Message sent.")
        except Exception as e:
            messages.error(request, f"Failed to send: {e}")
        return redirect("django_meta_whatsapp:chat_room", phone_number=phone_number)

    def _account(self, request):
        aid = request.POST.get("account_id") or request.session.get("wa_account_id")
        if aid:
            return WhatsAppAccount.objects.filter(pk=aid, is_active=True).first()
        return WhatsAppAccount.objects.filter(is_active=True).first()


class DeleteMessageView(WALoginMixin, View):
    def post(self, request, pk, *args, **kwargs):
        msg = get_object_or_404(WhatsAppMessage, pk=pk)
        msg.is_deleted = True
        msg.save(update_fields=["is_deleted"])
        return redirect("django_meta_whatsapp:chat_room", phone_number=msg.phone_number)


class UpdateConversationLabelView(WALoginMixin, View):
    def post(self, request, pk, *args, **kwargs):
        conv = get_object_or_404(WhatsAppConversation, pk=pk)
        label_name = request.POST.get("label", "").strip()
        if label_name:
            lbl, _ = WhatsAppLabel.objects.get_or_create(name=label_name)
            conv.label = lbl
        else:
            conv.label = None
        conv.save(update_fields=["label"])
        return JsonResponse({"status": "ok"})

# ── Labels ──────────────────────────────────────────────────
class LabelForm(forms.ModelForm):
    color_type = forms.ChoiceField(
        choices=[("preset", "Preset Color"), ("custom", "Custom Hex Code")],
        widget=forms.RadioSelect(attrs={"class": "h-4 w-4 text-emerald-600 border-gray-300 focus:ring-emerald-500"}),
        initial="preset"
    )
    preset_color = forms.ChoiceField(
        choices=[
            ("slate", "Slate"), ("red", "Red"), ("orange", "Orange"),
            ("amber", "Amber"), ("emerald", "Emerald"), ("teal", "Teal"),
            ("cyan", "Cyan"), ("blue", "Blue"), ("indigo", "Indigo"),
            ("violet", "Violet"), ("fuchsia", "Fuchsia"), ("pink", "Pink"),
            ("rose", "Rose"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500"})
    )
    custom_color = forms.CharField(
        max_length=7, required=False,
        widget=forms.TextInput(attrs={"type": "color", "class": "h-10 w-full rounded-lg cursor-pointer"})
    )

    class Meta:
        model = WhatsAppLabel
        fields = ["name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            c = self.instance.color
            if c.startswith("#"):
                self.initial["color_type"] = "custom"
                self.initial["custom_color"] = c
            else:
                self.initial["color_type"] = "preset"
                self.initial["preset_color"] = c

    def clean(self):
        cleaned_data = super().clean()
        ctype = cleaned_data.get("color_type")
        if ctype == "preset":
            cleaned_data["color"] = cleaned_data.get("preset_color")
        else:
            c_color = cleaned_data.get("custom_color")
            if not c_color:
                self.add_error("custom_color", "Custom color is required.")
            cleaned_data["color"] = c_color
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.color = self.cleaned_data.get("color")
        if commit:
            instance.save()
        return instance

class LabelListView(WALoginMixin, ListView):
    model = WhatsAppLabel
    template_name = "django_meta_whatsapp/label_list.html"
    context_object_name = "labels"
    ordering = ["name"]

class LabelCreateView(WALoginMixin, CreateView):
    model = WhatsAppLabel
    form_class = LabelForm
    template_name = "django_meta_whatsapp/label_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:label_list")
    def form_valid(self, form):
        messages.success(self.request, "Label created.")
        return super().form_valid(form)

class LabelUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppLabel
    form_class = LabelForm
    template_name = "django_meta_whatsapp/label_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:label_list")
    def form_valid(self, form):
        messages.success(self.request, "Label updated.")
        return super().form_valid(form)

class LabelDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppLabel
    template_name = "django_meta_whatsapp/label_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:label_list")


# ── Contacts ───────────────────────────────────────────────────
class ContactListView(WALoginMixin, ListView):
    model = WhatsAppContact
    template_name = "django_meta_whatsapp/contact_list.html"
    context_object_name = "contacts"
    paginate_by = 25
    def get_queryset(self):
        qs = WhatsAppContact.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(phone__icontains=q)|Q(name__icontains=q)|Q(email__icontains=q))
        
        lbl = self.request.GET.get("label", "").strip()
        if lbl:
            qs = qs.filter(labels__name=lbl)
            
        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_labels"] = WhatsAppLabel.objects.all().order_by("name")
        return context

class ContactCreateView(WALoginMixin, CreateView):
    model = WhatsAppContact
    fields = ["phone","name","email","labels","notes"]
    template_name = "django_meta_whatsapp/contact_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")
    
    def post(self, request, *args, **kwargs):
        data = request.POST.copy()
        labels = data.getlist('labels')
        processed_labels = []
        for val in labels:
            if not val.isdigit():
                lbl, _ = WhatsAppLabel.objects.get_or_create(name=val)
                processed_labels.append(str(lbl.id))
            else:
                processed_labels.append(val)
        data.setlist('labels', processed_labels)
        request.POST = data
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, "Contact saved.")
        return super().form_valid(form)

class ContactUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppContact
    fields = ["phone","name","email","labels","notes","opted_out"]
    template_name = "django_meta_whatsapp/contact_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")

    def post(self, request, *args, **kwargs):
        data = request.POST.copy()
        labels = data.getlist('labels')
        processed_labels = []
        for val in labels:
            if not val.isdigit():
                lbl, _ = WhatsAppLabel.objects.get_or_create(name=val)
                processed_labels.append(str(lbl.id))
            else:
                processed_labels.append(val)
        data.setlist('labels', processed_labels)
        request.POST = data
        return super().post(request, *args, **kwargs)

class ContactDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppContact
    template_name = "django_meta_whatsapp/contact_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")

class ContactImportView(WALoginMixin, View):
    template_name = "django_meta_whatsapp/contact_import.html"
    def get(self, request):
        if request.GET.get('sample') == '1':
            response = HttpResponse("Phone,Name,Email,Labels\n+1234567890,John Doe,john@example.com,\"vip, lead\"", content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="sample_contacts.csv"'
            return response
        return render(request, self.template_name)
    def post(self, request):
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Upload a CSV file.")
            return render(request, self.template_name)
        text = f.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        created = updated = skipped = 0
        for row in reader:
            # case insensitive keys
            row_lower = {k.lower().strip(): v for k, v in row.items() if k}
            phone = (row_lower.get("phone") or "").strip()
            if not phone:
                skipped += 1; continue
            name = (row_lower.get("name") or "").strip()
            email = (row_lower.get("email") or "").strip()
            labels_raw = (row_lower.get("labels") or row_lower.get("tags") or "").strip()
            label_names = [t.strip() for t in labels_raw.split(",") if t.strip()]
            
            contact = WhatsAppContact.objects.filter(phone=phone).first()
            if contact:
                if name: contact.name = name
                if email: contact.email = email
                contact.save()
                updated += 1
            else:
                contact = WhatsAppContact.objects.create(phone=phone, name=name, email=email)
                created += 1
                
            if label_names:
                for lbl_name in label_names:
                    lbl, _ = WhatsAppLabel.objects.get_or_create(name=lbl_name)
                    contact.labels.add(lbl)
        messages.success(request, f"Import done — {created} created, {updated} updated, {skipped} skipped.")
        return redirect("django_meta_whatsapp:contact_list")

class ContactExportView(WALoginMixin, View):
    def get(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="whatsapp_contacts.csv"'
        w = csv.writer(response)
        w.writerow(["phone","name","email","labels","opted_out","created_at"])
        for c in WhatsAppContact.objects.prefetch_related('labels').all():
            w.writerow([c.phone,c.name,c.email,",".join(l.name for l in c.labels.all()),c.opted_out,c.created_at])
        return response


# ── Templates ──────────────────────────────────────────────────
class TemplateListView(WALoginMixin, ListView):
    model = WhatsAppTemplate
    template_name = "django_meta_whatsapp/template_list.html"
    context_object_name = "templates"
    paginate_by = 20
    def get_queryset(self):
        qs = WhatsAppTemplate.objects.all()
        acc_id = self.request.session.get("wa_account_id")
        if acc_id: qs = qs.filter(account_id=acc_id)
        q = self.request.GET.get("q","").strip()
        s = self.request.GET.get("status","").strip()
        if q: qs = qs.filter(name__icontains=q)
        if s: qs = qs.filter(status=s)
        return qs
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({"status_choices": WhatsAppTemplate.STATUS_CHOICES, "search_q": self.request.GET.get("q",""), "active_status": self.request.GET.get("status","")})
        return ctx

class TemplateCreateView(WALoginMixin, CreateView):
    model = WhatsAppTemplate
    fields = ["name","language","category","header","body_text","footer_text","buttons"]
    template_name = "django_meta_whatsapp/template_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:template_list")

    def form_valid(self, form):
        acc_id = self.request.session.get("wa_account_id")
        if acc_id:
            form.instance.account_id = acc_id
        else:
            form.instance.account = WhatsAppAccount.objects.filter(is_active=True).first()
        return super().form_valid(form)

class TemplateUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppTemplate
    fields = ["name","language","category","header","body_text","footer_text","buttons"]
    template_name = "django_meta_whatsapp/template_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:template_list")

class TemplateDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppTemplate
    template_name = "django_meta_whatsapp/template_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:template_list")

class TemplateSyncFromMetaView(WALoginMixin, View):
    def post(self, request, *args, **kwargs):
        aid = request.session.get("wa_account_id")
        account = WhatsAppAccount.objects.filter(pk=aid).first() if aid else WhatsAppAccount.objects.filter(is_active=True).first()
        try:
            data = sync_templates_from_meta(account=account)
            synced = 0
            for t in data:
                body_c = next((c for c in t.get("components",[]) if c["type"]=="BODY"), {})
                WhatsAppTemplate.objects.update_or_create(account=account, name=t["name"], language=t.get("language","en"), defaults={"meta_template_id":t.get("id",""),"category":t.get("category","MARKETING"),"status":t.get("status","PENDING"),"body_text":body_c.get("text","")})
                synced += 1
            messages.success(request, f"Synced {synced} templates from Meta.")
        except Exception as e:
            messages.error(request, f"Sync failed: {e}")
        return redirect("django_meta_whatsapp:template_list")

class TemplatePushToMetaView(WALoginMixin, View):
    def post(self, request, pk, *args, **kwargs):
        tmpl = get_object_or_404(WhatsAppTemplate, pk=pk)
        try:
            res = push_template_to_meta(tmpl)
            tmpl.status = "PENDING"
            if res and "id" in res:
                tmpl.meta_template_id = res["id"]
            tmpl.save()
            messages.success(request, f"Template '{tmpl.name}' submitted to Meta.")
        except Exception as e:
            messages.error(request, f"Push failed: {e}")
        return redirect("django_meta_whatsapp:template_list")



# ── Catalog ────────────────────────────────────────────────────
class CatalogProductListView(WALoginMixin, ListView):
    model = WhatsAppCatalogProduct
    template_name = "django_meta_whatsapp/catalog_list.html"
    context_object_name = "products"
    paginate_by = 20
    def get_queryset(self):
        qs = WhatsAppCatalogProduct.objects.all()
        acc_id = self.request.session.get("wa_account_id")
        if acc_id: qs = qs.filter(account_id=acc_id)
        q = self.request.GET.get("q", "").strip()
        if q: qs = qs.filter(Q(name__icontains=q) | Q(retailer_id__icontains=q) | Q(catalog_id__icontains=q))
        return qs
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_q"] = self.request.GET.get("q", "")
        return ctx

class CatalogProductCreateView(WALoginMixin, CreateView):
    model = WhatsAppCatalogProduct
    fields = ["catalog_id", "retailer_id", "name", "price", "image_url", "is_active"]
    template_name = "django_meta_whatsapp/catalog_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:catalog_list")
    
    def get_initial(self):
        initial = super().get_initial()
        acc_id = self.request.session.get("wa_account_id")
        account = WhatsAppAccount.objects.filter(pk=acc_id).first() if acc_id else WhatsAppAccount.objects.filter(is_active=True).first()
        if account and account.default_catalog_id:
            initial["catalog_id"] = account.default_catalog_id
        return initial

    def form_valid(self, form):
        acc_id = self.request.session.get("wa_account_id")
        if acc_id: form.instance.account_id = acc_id
        else: form.instance.account = WhatsAppAccount.objects.filter(is_active=True).first()
        messages.success(self.request, "Product added successfully.")
        return super().form_valid(form)

class CatalogProductUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppCatalogProduct
    fields = ["catalog_id", "retailer_id", "name", "price", "image_url", "is_active"]
    template_name = "django_meta_whatsapp/catalog_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:catalog_list")
    def form_valid(self, form):
        messages.success(self.request, "Product updated.")
        return super().form_valid(form)

class CatalogProductDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppCatalogProduct
    template_name = "django_meta_whatsapp/catalog_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:catalog_list")

class CatalogProductSyncView(WALoginMixin, View):
    template_name = "django_meta_whatsapp/catalog_sync.html"
    def get(self, request):
        aid = request.session.get("wa_account_id")
        account = WhatsAppAccount.objects.filter(pk=aid).first() if aid else WhatsAppAccount.objects.filter(is_active=True).first()
        context = {"default_catalog_id": account.default_catalog_id if account else ""}
        return render(request, self.template_name, context)
    def post(self, request):
        aid = request.session.get("wa_account_id")
        account = WhatsAppAccount.objects.filter(pk=aid).first() if aid else WhatsAppAccount.objects.filter(is_active=True).first()
        
        catalog_id = request.POST.get("catalog_id", "").strip()
        if not catalog_id and account and account.default_catalog_id:
            catalog_id = account.default_catalog_id
            
        if not catalog_id:
            messages.error(request, "Catalog ID is required. Either provide it here or set it in your account settings.")
            return render(request, self.template_name)
            
        try:
            res = sync_catalog_products(catalog_id=catalog_id, account=account)
            messages.success(request, f"Successfully synced {res.get('synced', 0)} products from Meta.")
        except Exception as e:
            messages.error(request, f"Sync failed: {e}")
        return redirect("django_meta_whatsapp:catalog_list")


# ── Campaigns ──────────────────────────────────────────────────
class CampaignListView(WALoginMixin, ListView):
    model = WhatsAppCampaign
    template_name = "django_meta_whatsapp/campaign_list.html"
    context_object_name = "campaigns"
    paginate_by = 20
    def get_queryset(self):
        qs = WhatsAppCampaign.objects.select_related("template").all()
        acc_id = self.request.session.get("wa_account_id")
        if acc_id: qs = qs.filter(account_id=acc_id)
        s = self.request.GET.get("status","").strip()
        q = self.request.GET.get("q","").strip()
        t_id = self.request.GET.get("template_id","").strip()
        if s: qs = qs.filter(status=s)
        if q: qs = qs.filter(name__icontains=q)
        if t_id: qs = qs.filter(template_id=t_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        acc_id = self.request.session.get("wa_account_id")
        templates = WhatsAppTemplate.objects.filter(account_id=acc_id) if acc_id else WhatsAppTemplate.objects.all()
        ctx.update({
            "status_choices": WhatsAppCampaign.STATUS_CHOICES, 
            "active_status": self.request.GET.get("status",""),
            "search_q": self.request.GET.get("q",""),
            "active_template": self.request.GET.get("template_id",""),
            "templates": templates
        })
        return ctx

class CampaignCreateView(WALoginMixin, CreateView):
    model = WhatsAppCampaign
    fields = ["name","template","audience_type","audience_filters","csv_file","parameter_mappings","scheduled_at"]
    template_name = "django_meta_whatsapp/campaign_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:campaign_list")
    def get_context_data(self, **kwargs):
        from django.conf import settings
        ctx = super().get_context_data(**kwargs)
        wa = getattr(settings, "WHATSAPP", {})
        ctx["audience_choices"] = list(wa.get("AUDIENCES", {}).keys()) + ["contacts","csv"]
        # Named contact filters defined in settings for the dropdown UI
        ctx["contact_filters"] = wa.get("CONTACT_FILTERS", {})
        return ctx

    def form_valid(self, form):
        acc_id = self.request.session.get("wa_account_id")
        if acc_id:
            form.instance.account_id = acc_id
        else:
            form.instance.account = WhatsAppAccount.objects.filter(is_active=True).first()
        return super().form_valid(form)

class CampaignUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppCampaign
    fields = ["name","template","audience_type","audience_filters","csv_file","parameter_mappings","scheduled_at"]
    template_name = "django_meta_whatsapp/campaign_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:campaign_list")
    def get_context_data(self, **kwargs):
        from django.conf import settings
        ctx = super().get_context_data(**kwargs)
        wa = getattr(settings, "WHATSAPP", {})
        ctx["audience_choices"] = list(wa.get("AUDIENCES", {}).keys()) + ["contacts","csv"]
        ctx["contact_filters"] = wa.get("CONTACT_FILTERS", {})
        return ctx

class CampaignDetailView(WALoginMixin, DetailView):
    model = WhatsAppCampaign
    template_name = "django_meta_whatsapp/campaign_detail.html"
    context_object_name = "campaign"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recipients"] = self.object.recipients.order_by("-sent_at")[:100]
        return ctx

class CampaignDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppCampaign
    template_name = "django_meta_whatsapp/campaign_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:campaign_list")

class CampaignRunView(WALoginMixin, View):
    def post(self, request, pk, *args, **kwargs):
        campaign = get_object_or_404(WhatsAppCampaign, pk=pk)
        if campaign.status not in ("draft","scheduled","failed"):
            messages.error(request, f"Cannot run a '{campaign.status}' campaign.")
            return redirect("django_meta_whatsapp:campaign_list")
        try:
            result = run_campaign_async(campaign.pk, account_id=campaign.account_id)
            if result.get("queued"):
                messages.success(request, "Campaign queued.")
            else:
                messages.success(request, f"Done — sent: {result.get('sent',0)}, failed: {result.get('failed',0)}.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("django_meta_whatsapp:campaign_list")


# ── Analytics ──────────────────────────────────────────────────
class AnalyticsView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/analytics.html"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()
        last_30 = today - datetime.timedelta(days=29)
        acc_id = self.request.session.get("wa_account_id")
        msg_qs = WhatsAppMessage.objects.filter(account_id=acc_id) if acc_id else WhatsAppMessage.objects.all()
        camp_qs = WhatsAppCampaign.objects.filter(account_id=acc_id) if acc_id else WhatsAppCampaign.objects.all()

        ctx.update({
            "total_sent": msg_qs.filter(direction="outbound").count(),
            "total_delivered": msg_qs.filter(status="delivered").count(),
            "total_read": msg_qs.filter(status="read").count(),
            "total_failed": msg_qs.filter(status="failed").count(),
            "campaign_stats": camp_qs.filter(status="completed").aggregate(s=Sum("sent_count"), d=Sum("delivered_count"), r=Sum("read_count"), f=Sum("failed_count")),
            "recent_campaigns": camp_qs.filter(status="completed").order_by("-completed_at")[:10],
        })
        daily = (msg_qs.filter(timestamp__date__gte=last_30).extra(select={"day":"DATE(timestamp)"}).values("day").annotate(count=Count("id")).order_by("day"))
        ctx["daily_chart_labels"] = json.dumps([str(d["day"]) for d in daily])
        ctx["daily_chart_data"] = json.dumps([d["count"] for d in daily])
        return ctx


# ── Webhook ────────────────────────────────────────────────────
@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    def get(self, request, *args, **kwargs):
        from django.conf import settings
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe":
            matched = WhatsAppAccount.objects.filter(verify_token=token, is_active=True).exists()
            if not matched:
                wa = getattr(settings, "WHATSAPP", {})
                fallback = wa.get("VERIFY_TOKEN") or getattr(settings, "META_WA_VERIFY_TOKEN", "whatsapp_verify")
                matched = token == fallback
            if matched:
                return HttpResponse(challenge)
            return HttpResponse("Forbidden", status=403)
        return HttpResponse("Bad Request", status=400)

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body.decode("utf-8"))
            WhatsAppWebhookLog.objects.create(payload=data)
            self._process(data)
            return JsonResponse({"status": "ok"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    def _process(self, data):
        from .signals import whatsapp_message_received, whatsapp_user_subscribed
        from django.utils import timezone
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Handle In-App Signups
                if change.get("field") == "in_app_signup" or "in_app_signup" in value:
                    signup_data = value if change.get("field") == "in_app_signup" else value.get("in_app_signup", {})
                    wa_id = signup_data.get("wa_id")
                    signup_id = signup_data.get("signup_id")
                    if wa_id and signup_id:
                        signup = WhatsAppSignup.objects.filter(signup_id=signup_id).first()
                        if signup:
                            signup.subscriber_count += 1
                            signup.save(update_fields=["subscriber_count"])
                            contact, _ = WhatsAppContact.objects.get_or_create(phone=f"+{wa_id}")
                            contact.subscribed_via_signup = signup
                            contact.subscribed_at = timezone.now()
                            contact.save()
                            if signup.auto_add_to_label:
                                contact.labels.add(signup.auto_add_to_label)
                            whatsapp_user_subscribed.send(sender=self.__class__, contact=contact, signup=signup)
                    continue

                phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                account = WhatsAppAccount.objects.filter(phone_number_id=phone_number_id).first()
                for status_obj in value.get("statuses", []):
                    mid = status_obj.get("id"); sv = status_obj.get("status")
                    if mid and sv:
                        WhatsAppMessage.objects.filter(message_id=mid).update(status=sv)
                        WhatsAppCampaignRecipient.objects.filter(message_id=mid).update(status=sv)
                for msg in value.get("messages", []):
                    # Detect WhatsApp Flow completions (nfm_reply)
                    if msg.get("type") == "interactive":
                        interactive = msg.get("interactive", {})
                        if interactive.get("type") == "nfm_reply":
                            self._save_flow_response(msg, account)
                            continue
                    db_msg = self._save_message(msg, account)
                    if db_msg:
                        whatsapp_message_received.send(sender=self.__class__, message=db_msg)

    def _save_message(self, msg, account):
        from django.utils.timezone import make_aware
        msg_id = msg.get("id")
        if WhatsAppMessage.objects.filter(message_id=msg_id).exists():
            return None
        from_num = msg.get("from", "")
        ts = int(msg.get("timestamp", 0))
        msg_type = msg.get("type", "text")
        body = ""; media_id = None; mime_type = None
        lat = lon = None; loc_name = loc_addr = ""
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")
        elif msg_type == "button":
            body = msg.get("button", {}).get("text", "")
        elif msg_type == "interactive":
            itype = msg.get("interactive", {}).get("type")
            body = msg.get("interactive", {}).get("button_reply" if itype=="button_reply" else "list_reply", {}).get("title", "")
        elif msg_type == "location":
            loc = msg.get("location", {})
            lat = loc.get("latitude"); lon = loc.get("longitude")
            loc_name = loc.get("name", ""); loc_addr = loc.get("address", "")
            body = loc_name or f"📍 {lat},{lon}"
        elif msg_type in ("image","video","document","audio","voice","sticker"):
            mo = msg.get(msg_type, {})
            media_id = mo.get("id"); mime_type = mo.get("mime_type")
            body = mo.get("caption","") or f"[{msg_type.capitalize()}]"
        elif msg_type == "reaction":
            body = msg.get("reaction", {}).get("emoji", "")
        else:
            body = f"[{msg_type.capitalize()}]"
        tz_dt = make_aware(datetime.datetime.fromtimestamp(ts))
        ctx = msg.get("context", {}); reply_to_db = None
        if ctx.get("id"):
            reply_to_db = WhatsAppMessage.objects.filter(message_id=ctx["id"]).first()
        conv, _ = WhatsAppConversation.objects.get_or_create(phone_number=from_num, defaults={"account":account,"last_message_at":tz_dt})
        conv.last_message_at = tz_dt; conv.unread_count = (conv.unread_count or 0) + 1
        conv.save(update_fields=["last_message_at","unread_count"])
        WhatsAppContact.objects.get_or_create(phone=from_num)
        return WhatsAppMessage.objects.create(
            conversation=conv, account=account, phone_number=from_num, message_id=msg_id,
            message_type=msg_type if msg_type != "voice" else "audio",
            message_body=body, direction="inbound", timestamp=tz_dt, status="delivered",
            media_id=media_id, media_mime_type=mime_type,
            location_latitude=lat, location_longitude=lon,
            location_name=loc_name, location_address=loc_addr,
            reply_to=reply_to_db, raw_payload=msg,
        )

    def _save_flow_response(self, msg, account):
        """Parse a completed WhatsApp Flow submission and store it."""
        from .signals import whatsapp_flow_completed
        from django.utils.timezone import make_aware
        try:
            nfm = msg.get("interactive", {}).get("nfm_reply", {})
            raw_json = nfm.get("response_json", "{}")
            response_data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            flow_token = response_data.pop("flow_token", "")
            from_num = msg.get("from", "")

            # Try to match to a WhatsAppFlow by token or any known flow for this account
            flow_obj = None
            if flow_token:
                flow_obj = WhatsAppFlow.objects.filter(
                    account=account
                ).filter(
                    responses__flow_token=flow_token
                ).first()
            if not flow_obj and account:
                # Best-effort: match by most recent flow
                flow_obj = WhatsAppFlow.objects.filter(account=account).order_by("-created_at").first()

            conv = WhatsAppConversation.objects.filter(phone_number=from_num).first()

            response_obj = WhatsAppFlowResponse.objects.create(
                flow=flow_obj,
                conversation=conv,
                phone_number=from_num,
                response_data=response_data,
                flow_token=flow_token,
                raw_payload=msg,
            )

            # Update completion stats
            if flow_obj:
                WhatsAppFlow.objects.filter(pk=flow_obj.pk).update(
                    completion_count=models.F("completion_count") + 1
                )

            whatsapp_flow_completed.send(sender=self.__class__, response=response_obj)
        except Exception:
            pass  # Never break webhook processing over flow parsing errors


# ── Accounts / Settings ────────────────────────────────────────
class AccountListView(WALoginMixin, ListView):
    model = WhatsAppAccount
    template_name = "django_meta_whatsapp/account_list.html"
    context_object_name = "accounts"

class AccountCreateView(WALoginMixin, CreateView):
    model = WhatsAppAccount
    fields = ["name","access_token","phone_number_id","waba_id","verify_token","default_catalog_id","is_active"]
    template_name = "django_meta_whatsapp/account_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:account_list")

    def form_valid(self, form):
        token = form.cleaned_data.get("access_token")
        if token:
            try:
                import requests
                resp = requests.get(f"https://graph.facebook.com/v25.0/me?fields=id,name,picture.type(large)&access_token={token}", timeout=5).json()
                if resp.get("name"):
                    form.instance.profile_name = resp["name"]
                if "picture" in resp and "data" in resp["picture"] and "url" in resp["picture"]["data"]:
                    form.instance.profile_picture_url = resp["picture"]["data"]["url"]
            except Exception:
                pass
        return super().form_valid(form)

class AccountUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppAccount
    fields = ["name","access_token","phone_number_id","waba_id","verify_token","default_catalog_id","is_active"]
    template_name = "django_meta_whatsapp/account_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:account_list")

    def form_valid(self, form):
        token = form.cleaned_data.get("access_token")
        if token:
            try:
                import requests
                resp = requests.get(f"https://graph.facebook.com/v25.0/me?fields=id,name,picture.type(large)&access_token={token}", timeout=5).json()
                if resp.get("name"):
                    form.instance.profile_name = resp["name"]
                if "picture" in resp and "data" in resp["picture"] and "url" in resp["picture"]["data"]:
                    form.instance.profile_picture_url = resp["picture"]["data"]["url"]
            except Exception:
                pass
        return super().form_valid(form)

class AccountDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppAccount
    template_name = "django_meta_whatsapp/account_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:account_list")

class SetGlobalAccountView(WALoginMixin, View):
    def post(self, request, *args, **kwargs):
        account_id = request.POST.get("account_id")
        next_url = request.POST.get("next", "")
        if account_id:
            request.session["wa_account_id"] = int(account_id)
            messages.success(request, "Active account updated.")
        return redirect(next_url or "django_meta_whatsapp:dashboard")


# ── In-App Signups ─────────────────────────────────────────────
class SignupListView(WALoginMixin, ListView):
    model = WhatsAppSignup
    template_name = "django_meta_whatsapp/signup_list.html"
    context_object_name = "signups"

    def get_queryset(self):
        acc = self.get_wa_account()
        return WhatsAppSignup.objects.filter(account=acc) if acc else WhatsAppSignup.objects.none()

class SignupCreateView(WALoginMixin, CreateView):
    model = WhatsAppSignup
    fields = ["display_name", "signup_message", "confirmation_message", "privacy_policy_url", "website_url", "promo_code", "auto_add_to_label"]
    template_name = "django_meta_whatsapp/signup_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:signup_list")

    def form_valid(self, form):
        acc = self.get_wa_account()
        if not acc:
            messages.error(self.request, "No active WhatsApp account selected.")
            return self.form_invalid(form)
            
        form.instance.account = acc
        try:
            from .utils import create_signup
            res = create_signup(
                display_name=form.cleaned_data["display_name"],
                signup_message=form.cleaned_data["signup_message"],
                confirmation_message=form.cleaned_data["confirmation_message"],
                privacy_policy_url=form.cleaned_data["privacy_policy_url"],
                website_url=form.cleaned_data.get("website_url", ""),
                promo_code=form.cleaned_data.get("promo_code", ""),
                account=acc
            )
            form.instance.signup_id = res.get("id")
            messages.success(self.request, "Signup link created successfully.")
        except Exception as e:
            messages.error(self.request, f"Error creating signup on Meta: {e}")
            return self.form_invalid(form)
            
        return super().form_valid(form)

class SignupUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppSignup
    fields = ["confirmation_message", "promo_code", "auto_add_to_label"]
    template_name = "django_meta_whatsapp/signup_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:signup_list")

    def form_valid(self, form):
        acc = self.get_wa_account()
        try:
            from .utils import update_signup
            update_signup(
                signup_id=form.instance.signup_id,
                confirmation_message=form.cleaned_data["confirmation_message"],
                promo_code=form.cleaned_data["promo_code"],
                account=acc
            )
            messages.success(self.request, "Signup link updated.")
        except Exception as e:
            messages.error(self.request, f"Error updating signup on Meta: {e}")
            return self.form_invalid(form)
            
        return super().form_valid(form)

class SignupDisableView(WALoginMixin, View):
    def post(self, request, pk, *args, **kwargs):
        signup = get_object_or_404(WhatsAppSignup, pk=pk)
        acc = self.get_wa_account()
        if signup.account != acc:
            messages.error(request, "Unauthorized")
            return redirect("django_meta_whatsapp:signup_list")
            
        try:
            from .utils import disable_signup
            disable_signup(signup.signup_id, account=acc)
            signup.status = "DISABLED"
            signup.save(update_fields=["status"])
            messages.success(request, "Signup link disabled.")
        except Exception as e:
            messages.error(request, f"Error disabling signup: {e}")
        return redirect("django_meta_whatsapp:signup_list")


# ── API Keys ───────────────────────────────────────────────────
class APIKeyListView(WALoginMixin, ListView):
    model = WhatsAppAPIKey
    template_name = "django_meta_whatsapp/apikey_list.html"
    context_object_name = "api_keys"

class APIKeyCreateView(WALoginMixin, CreateView):
    model = WhatsAppAPIKey
    fields = ["name"]
    template_name = "django_meta_whatsapp/apikey_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:apikey_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.update({
                "class": "w-full border border-gray-300 rounded-lg shadow-sm focus:border-emerald-500 focus:ring-emerald-500 px-4 py-2"
            })
        return form

class APIKeyDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppAPIKey
    template_name = "django_meta_whatsapp/apikey_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:apikey_list")


# ── REST API endpoints ─────────────────────────────────────────
class _APIAuth:
    def _ok(self, request):
        key = request.headers.get("X-API-Key") or request.GET.get("api_key")
        return bool(key and WhatsAppAPIKey.objects.filter(key=key, is_active=True).exists())

class APISendMessageView(_APIAuth, View):
    def post(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        try:
            d = json.loads(request.body)
            acc = WhatsAppAccount.objects.filter(pk=d.get("account_id")).first() if d.get("account_id") else None
            return JsonResponse({"status":"sent","result": send_text_message(d["phone"], d["message"], account=acc)})
        except Exception as e:
            return JsonResponse({"error":str(e)},status=400)

class APISendLocationView(_APIAuth, View):
    def post(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        try:
            d = json.loads(request.body)
            return JsonResponse({"status":"sent","result": send_location_message(d["phone"],float(d["latitude"]),float(d["longitude"]),name=d.get("name",""),address=d.get("address",""))})
        except Exception as e:
            return JsonResponse({"error":str(e)},status=400)

class APISendTemplateView(_APIAuth, View):
    def post(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        try:
            from .utils import send_template_message, build_template_components
            d = json.loads(request.body)
            comps = build_template_components(body_params=d.get("body_params"), header_params=d.get("header_params"))
            return JsonResponse({"status":"sent","result": send_template_message(d["phone"],d["template_name"],language_code=d.get("language","en"),components=comps or None)})
        except Exception as e:
            return JsonResponse({"error":str(e)},status=400)

class APIChatsView(_APIAuth, View):
    def get(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        return JsonResponse({"conversations": list(WhatsAppConversation.objects.values("id","phone_number","label","unread_count","last_message_at").order_by("-last_message_at")[:50])})

class APICampaignListView(_APIAuth, View):
    def get(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        return JsonResponse({"campaigns": list(WhatsAppCampaign.objects.values("id","name","status","sent_count","failed_count","created_at").order_by("-created_at")[:50])})

class APITemplateDetailsView(WALoginMixin, View):
    def get(self, request, pk, *args, **kwargs):
        tmpl = get_object_or_404(WhatsAppTemplate, pk=pk)
        return JsonResponse({
            "id": tmpl.id,
            "name": tmpl.name,
            "language": tmpl.language,
            "header": tmpl.header,
            "body_text": tmpl.body_text,
            "footer_text": tmpl.footer_text,
            "buttons": tmpl.buttons,
        })

# ─────────────────────────────────────────────
# Blocked Users
# ─────────────────────────────────────────────

class BlockedUserListView(WALoginMixin, ListView):
    model = WhatsAppBlockedUser
    template_name = "django_meta_whatsapp/blocked_user_list.html"
    context_object_name = "blocked_users"
    paginate_by = 50

    def get_queryset(self):
        qs = WhatsAppBlockedUser.objects.filter(account=self.get_wa_account())
        return qs.order_by("-blocked_at")

class SyncBlockedUsersView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/blocked_sync.html"

    def post(self, request, *args, **kwargs):
        from .utils import sync_blocked_users_from_meta
        try:
            synced = sync_blocked_users_from_meta(account=self.get_wa_account())
            messages.success(request, f"Successfully synced {synced} blocked users from Meta.")
        except Exception as e:
            messages.error(request, f"Failed to sync: {e}")
        return redirect("django_meta_whatsapp:blocked_list")

class BlockUserView(WALoginMixin, View):
    def post(self, request, phone, *args, **kwargs):
        from .utils import block_users
        try:
            res = block_users([phone], account=self.get_wa_account())
            failed = res.get("block_users", {}).get("failed_users", [])
            if failed:
                err = failed[0].get("errors", [{}])[0].get("message", "Unknown error")
                messages.error(request, f"Failed to block {phone}: {err}")
            else:
                messages.success(request, f"User {phone} has been blocked.")
        except Exception as e:
            messages.error(request, f"Error blocking user: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))

class UnblockUserView(WALoginMixin, View):
    def post(self, request, phone, *args, **kwargs):
        from .utils import unblock_users
        try:
            unblock_users([phone], account=self.get_wa_account())
            messages.success(request, f"User {phone} has been unblocked.")
        except Exception as e:
            messages.error(request, f"Error unblocking user: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))

class BulkBlockUsersView(WALoginMixin, View):
    def post(self, request, *args, **kwargs):
        from .utils import block_users
        phones = request.POST.getlist("phones")
        if not phones:
            messages.error(request, "No phones selected.")
            return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))
        try:
            res = block_users(phones, account=self.get_wa_account())
            added = len(res.get("block_users", {}).get("added_users", []))
            failed = len(res.get("block_users", {}).get("failed_users", []))
            msg = f"Blocked {added} users."
            if failed:
                msg += f" Failed to block {failed} users (e.g., haven't messaged in 24h)."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"Error bulk blocking: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))

class BulkUnblockUsersView(WALoginMixin, View):
    def post(self, request, *args, **kwargs):
        from .utils import unblock_users
        phones = request.POST.getlist("phones")
        if not phones:
            messages.error(request, "No phones selected.")
            return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))
        try:
            unblock_users(phones, account=self.get_wa_account())
            messages.success(request, f"Unblocked {len(phones)} users.")
        except Exception as e:
            messages.error(request, f"Error bulk unblocking: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'django_meta_whatsapp:contact_list'))

class APIBlockUserView(_APIAuth, View):
    def post(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        from .utils import block_users
        try:
            d = json.loads(request.body)
            phone = d.get("phone")
            account = WhatsAppAccount.objects.filter(is_active=True).first()
            if not phone: return JsonResponse({"error":"Phone required"},status=400)
            res = block_users([phone], account=account)
            return JsonResponse({"status":"success", "meta_response": res})
        except Exception as e:
            return JsonResponse({"error":str(e)},status=400)

class APIUnblockUserView(_APIAuth, View):
    def delete(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        from .utils import unblock_users
        try:
            d = json.loads(request.body)
            phone = d.get("phone")
            account = WhatsAppAccount.objects.filter(is_active=True).first()
            if not phone: return JsonResponse({"error":"Phone required"},status=400)
            res = unblock_users([phone], account=account)
            return JsonResponse({"status":"success", "meta_response": res})
        except Exception as e:
            return JsonResponse({"error":str(e)},status=400)

class APIBlockedUserListView(_APIAuth, View):
    def get(self, request, *args, **kwargs):
        if not self._ok(request): return JsonResponse({"error":"Unauthorized"},status=401)
        account = WhatsAppAccount.objects.filter(is_active=True).first()
        users = list(WhatsAppBlockedUser.objects.filter(account=account, is_active=True).values("phone_number", "blocked_at", "reason"))
        return JsonResponse({"blocked_users": users})


# ── WhatsApp Flows ─────────────────────────────────────────────

class FlowListView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/flow_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        acc = self.get_wa_account()
        qs = WhatsAppFlow.objects.filter(account=acc) if acc else WhatsAppFlow.objects.none()
        q = self.request.GET.get("q", "").strip()
        s = self.request.GET.get("status", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        if s:
            qs = qs.filter(status=s)
        ctx.update({
            "flows": qs,
            "status_choices": WhatsAppFlow.STATUS_CHOICES,
            "search_q": q,
            "active_status": s,
        })
        return ctx


class FlowCreateView(WALoginMixin, View):
    template_name = "django_meta_whatsapp/flow_form.html"

    def get(self, request):
        from .flows import FLOW_TEMPLATES
        return render(request, self.template_name, {
            "flow_templates": FLOW_TEMPLATES,
            "category_choices": WhatsAppFlow.CATEGORY_CHOICES,
        })

    def post(self, request):
        from .flows import create_flow, FLOW_TEMPLATES
        acc = self.get_wa_account()
        name = request.POST.get("name", "").strip()
        categories = request.POST.getlist("categories")
        is_dynamic = request.POST.get("is_dynamic") == "1"
        endpoint_uri = request.POST.get("endpoint_uri", "").strip()
        flow_json_raw = request.POST.get("flow_json", "").strip()
        starter = request.POST.get("starter_template", "")

        if not name:
            messages.error(request, "Flow name is required.")
            return redirect("django_meta_whatsapp:flow_create")
        if not categories:
            messages.error(request, "Select at least one category.")
            return redirect("django_meta_whatsapp:flow_create")

        # Resolve flow JSON
        try:
            if starter and starter in FLOW_TEMPLATES:
                flow_json = FLOW_TEMPLATES[starter]["json"]
                if not categories:
                    categories = FLOW_TEMPLATES[starter]["categories"]
            elif flow_json_raw:
                flow_json = json.loads(flow_json_raw)
            else:
                flow_json = {"version": "7.2", "screens": []}
        except json.JSONDecodeError as e:
            messages.error(request, f"Invalid Flow JSON: {e}")
            return redirect("django_meta_whatsapp:flow_create")

        # Create on Meta
        try:
            res = create_flow(name=name, categories=categories, account=acc)
            meta_flow_id = res.get("id", "")
        except Exception as e:
            messages.error(request, f"Failed to create flow on Meta: {e}")
            return redirect("django_meta_whatsapp:flow_create")

        flow = WhatsAppFlow.objects.create(
            account=acc,
            name=name,
            meta_flow_id=meta_flow_id,
            categories=categories,
            flow_json=flow_json,
            is_dynamic=is_dynamic,
            endpoint_uri=endpoint_uri,
        )
        messages.success(request, f"Flow '{name}' created successfully (ID: {meta_flow_id}).")
        return redirect("django_meta_whatsapp:flow_detail", pk=flow.pk)


class FlowDetailView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/flow_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        flow = get_object_or_404(WhatsAppFlow, pk=self.kwargs["pk"])
        ctx.update({
            "flow": flow,
            "flow_json_str": json.dumps(flow.flow_json, indent=2),
            "recent_responses": flow.responses.order_by("-completed_at")[:5],
            "response_count": flow.responses.count(),
        })
        return ctx


class FlowUploadView(WALoginMixin, View):
    """Upload / replace the flow JSON on Meta (DRAFT only)."""

    def post(self, request, pk):
        from .flows import upload_flow_json
        flow = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()

        # Allow updating the local JSON first
        flow_json_raw = request.POST.get("flow_json", "").strip()
        if flow_json_raw:
            try:
                flow.flow_json = json.loads(flow_json_raw)
                flow.save(update_fields=["flow_json", "updated_at"])
            except json.JSONDecodeError as e:
                messages.error(request, f"Invalid Flow JSON: {e}")
                return redirect("django_meta_whatsapp:flow_detail", pk=pk)

        if not flow.meta_flow_id:
            messages.error(request, "This flow has no Meta ID. It may not have been created on Meta yet.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)

        try:
            res = upload_flow_json(flow, account=acc)
            errors = res.get("validation_errors", [])
            flow.validation_errors = errors
            flow.save(update_fields=["validation_errors", "updated_at"])
            if errors:
                messages.warning(request, f"JSON uploaded but has {len(errors)} validation error(s). Fix them before publishing.")
            else:
                messages.success(request, "Flow JSON uploaded successfully — no validation errors.")
        except Exception as e:
            messages.error(request, f"Upload failed: {e}")
        return redirect("django_meta_whatsapp:flow_detail", pk=pk)


class FlowPublishView(WALoginMixin, View):
    def post(self, request, pk):
        from .flows import publish_flow
        flow = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()
        if not flow.can_publish:
            messages.error(request, "Only DRAFT flows with a Meta ID can be published.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)
        try:
            publish_flow(flow.meta_flow_id, account=acc)
            flow.status = "PUBLISHED"
            flow.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Flow '{flow.name}' is now PUBLISHED.")
        except Exception as e:
            messages.error(request, f"Publish failed: {e}")
        return redirect("django_meta_whatsapp:flow_detail", pk=pk)


class FlowDeprecateView(WALoginMixin, View):
    def post(self, request, pk):
        from .flows import deprecate_flow
        flow = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()
        if not flow.can_deprecate:
            messages.error(request, "Only PUBLISHED flows can be deprecated.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)
        try:
            deprecate_flow(flow.meta_flow_id, account=acc)
            flow.status = "DEPRECATED"
            flow.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Flow '{flow.name}' has been deprecated.")
        except Exception as e:
            messages.error(request, f"Deprecate failed: {e}")
        return redirect("django_meta_whatsapp:flow_detail", pk=pk)


class FlowDeleteView(WALoginMixin, View):
    def post(self, request, pk):
        from .flows import delete_flow
        flow = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()
        if not flow.can_delete:
            messages.error(request, "Only DRAFT flows can be deleted.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)
        try:
            if flow.meta_flow_id:
                delete_flow(flow.meta_flow_id, account=acc)
            flow.delete()
            messages.success(request, "Flow deleted.")
        except Exception as e:
            messages.error(request, f"Delete failed: {e}")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)
        return redirect("django_meta_whatsapp:flow_list")


class FlowCloneView(WALoginMixin, View):
    """Clone a flow — copies the JSON into a new DRAFT."""

    def post(self, request, pk):
        from .flows import create_flow
        original = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()
        new_name = f"{original.name} (Copy)"
        try:
            res = create_flow(name=new_name, categories=original.categories, account=acc)
            meta_flow_id = res.get("id", "")
        except Exception as e:
            messages.error(request, f"Failed to create clone on Meta: {e}")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)

        clone = WhatsAppFlow.objects.create(
            account=acc,
            name=new_name,
            meta_flow_id=meta_flow_id,
            categories=list(original.categories),
            flow_json=dict(original.flow_json),
            is_dynamic=original.is_dynamic,
            endpoint_uri=original.endpoint_uri,
            status="DRAFT",
        )
        messages.success(request, f"Cloned as '{new_name}'.")
        return redirect("django_meta_whatsapp:flow_detail", pk=clone.pk)


class SendFlowView(WALoginMixin, View):
    """Send a published flow as an interactive message to a phone number."""

    def post(self, request, pk):
        from .flows import send_flow_message
        flow = get_object_or_404(WhatsAppFlow, pk=pk)
        acc = self.get_wa_account()
        phone = request.POST.get("phone", "").strip()
        cta_text = request.POST.get("cta_text", "Open Form").strip()
        header_text = request.POST.get("header_text", "").strip()
        body_text = request.POST.get("body_text", "Please complete the form.").strip()
        footer_text = request.POST.get("footer_text", "").strip()
        mode = "draft" if flow.status == "DRAFT" else "published"

        if not phone:
            messages.error(request, "Phone number is required.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)
        if not flow.meta_flow_id:
            messages.error(request, "This flow has no Meta ID — create it on Meta first.")
            return redirect("django_meta_whatsapp:flow_detail", pk=pk)

        try:
            send_flow_message(
                phone=phone,
                flow_id=flow.meta_flow_id,
                cta_text=cta_text,
                header_text=header_text,
                body_text=body_text,
                footer_text=footer_text,
                mode=mode,
                account=acc,
            )
            WhatsAppFlow.objects.filter(pk=pk).update(
                sent_count=models.F("sent_count") + 1
            )
            messages.success(request, f"Flow message sent to {phone}.")
        except Exception as e:
            messages.error(request, f"Send failed: {e}")
        return redirect("django_meta_whatsapp:flow_detail", pk=pk)


class FlowResponseListView(WALoginMixin, TemplateView):
    template_name = "django_meta_whatsapp/flow_response_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        flow = get_object_or_404(WhatsAppFlow, pk=self.kwargs["pk"])
        responses = flow.responses.order_by("-completed_at")
        q = self.request.GET.get("q", "").strip()
        if q:
            responses = responses.filter(phone_number__icontains=q)
        ctx.update({
            "flow": flow,
            "responses": responses,
            "search_q": q,
            "total_count": flow.responses.count(),
            "unprocessed_count": flow.responses.filter(processed=False).count(),
        })
        return ctx
