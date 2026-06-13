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
from django.db.models import Count, Q, Sum

from .models import (
    WhatsAppAccount, WhatsAppCampaign, WhatsAppCampaignRecipient,
    WhatsAppContact, WhatsAppConversation, WhatsAppMessage,
    WhatsAppTemplate, WhatsAppWebhookLog, WhatsAppAPIKey,
)
from .utils import (
    run_campaign_async, send_text_message, send_location_message,
    send_media_message, upload_media, sync_templates_from_meta, push_template_to_meta,
)


class WALoginMixin(LoginRequiredMixin):
    @property
    def login_url(self):
        from django.conf import settings
        wa_login = getattr(settings, "WHATSAPP", {}).get("LOGIN_URL")
        if wa_login:
            return wa_login
        return getattr(settings, "LOGIN_URL", "/accounts/login/")


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
            qs = qs.filter(label=label)
        ctx.update({"conversations": qs, "search_q": q, "active_label": label, "label_choices": WhatsAppConversation.LABEL_CHOICES})
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
        conv.label = request.POST.get("label", "")
        conv.save(update_fields=["label"])
        return JsonResponse({"status": "ok"})


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
        return qs

class ContactCreateView(WALoginMixin, CreateView):
    model = WhatsAppContact
    fields = ["phone","name","email","tags","notes"]
    template_name = "django_meta_whatsapp/contact_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")
    def form_valid(self, form):
        messages.success(self.request, "Contact saved.")
        return super().form_valid(form)

class ContactUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppContact
    fields = ["phone","name","email","tags","notes","opted_out"]
    template_name = "django_meta_whatsapp/contact_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")

class ContactDeleteView(WALoginMixin, DeleteView):
    model = WhatsAppContact
    template_name = "django_meta_whatsapp/contact_confirm_delete.html"
    success_url = reverse_lazy("django_meta_whatsapp:contact_list")

class ContactImportView(WALoginMixin, View):
    template_name = "django_meta_whatsapp/contact_import.html"
    def get(self, request):
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
            phone = (row.get("phone") or row.get("Phone") or "").strip()
            if not phone:
                skipped += 1; continue
            name = (row.get("name") or row.get("Name") or "").strip()
            email = (row.get("email") or row.get("Email") or "").strip()
            tags_raw = (row.get("tags") or "").strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            _, was_created = WhatsAppContact.objects.update_or_create(phone=phone, defaults={"name":name,"email":email,"tags":tags})
            created += was_created; updated += not was_created
        messages.success(request, f"Import done — {created} created, {updated} updated, {skipped} skipped.")
        return redirect("django_meta_whatsapp:contact_list")

class ContactExportView(WALoginMixin, View):
    def get(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="whatsapp_contacts.csv"'
        w = csv.writer(response)
        w.writerow(["phone","name","email","tags","opted_out","created_at"])
        for c in WhatsAppContact.objects.all():
            w.writerow([c.phone,c.name,c.email,",".join(c.tags or []),c.opted_out,c.created_at])
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
            push_template_to_meta(tmpl)
            messages.success(request, f"Template '{tmpl.name}' submitted to Meta.")
        except Exception as e:
            messages.error(request, f"Push failed: {e}")
        return redirect("django_meta_whatsapp:template_list")


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
        from .signals import whatsapp_message_received
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                account = WhatsAppAccount.objects.filter(phone_number_id=phone_number_id).first()
                for status_obj in value.get("statuses", []):
                    mid = status_obj.get("id"); sv = status_obj.get("status")
                    if mid and sv:
                        WhatsAppMessage.objects.filter(message_id=mid).update(status=sv)
                        WhatsAppCampaignRecipient.objects.filter(message_id=mid).update(status=sv)
                for msg in value.get("messages", []):
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


# ── Accounts / Settings ────────────────────────────────────────
class AccountListView(WALoginMixin, ListView):
    model = WhatsAppAccount
    template_name = "django_meta_whatsapp/account_list.html"
    context_object_name = "accounts"

class AccountCreateView(WALoginMixin, CreateView):
    model = WhatsAppAccount
    fields = ["name","access_token","phone_number_id","waba_id","verify_token","is_active"]
    template_name = "django_meta_whatsapp/account_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:account_list")

class AccountUpdateView(WALoginMixin, UpdateView):
    model = WhatsAppAccount
    fields = ["name","access_token","phone_number_id","waba_id","verify_token","is_active"]
    template_name = "django_meta_whatsapp/account_form.html"
    success_url = reverse_lazy("django_meta_whatsapp:account_list")

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
