from django.core.management.base import BaseCommand
from django_meta_whatsapp.models import WhatsAppAccount, WhatsAppTemplate
from django_meta_whatsapp.utils import sync_templates_from_meta


class Command(BaseCommand):
    help = "Sync WhatsApp templates from Meta into the local database"

    def add_arguments(self, parser):
        parser.add_argument("--account-id", type=int, help="Sync only for a specific WhatsAppAccount PK")

    def handle(self, *args, **options):
        account_id = options.get("account_id")
        accounts = [WhatsAppAccount.objects.get(pk=account_id)] if account_id else list(WhatsAppAccount.objects.filter(is_active=True))
        if not accounts:
            self.stdout.write(self.style.WARNING("No active accounts found. Add an account in the dashboard first."))
            return
        for account in accounts:
            self.stdout.write(f"Syncing templates for account: {account.name} ...")
            try:
                data = sync_templates_from_meta(account=account)
                synced = 0
                for t in data:
                    body_c = next((c for c in t.get("components", []) if c["type"] == "BODY"), {})
                    WhatsAppTemplate.objects.update_or_create(
                        account=account,
                        name=t["name"],
                        language=t.get("language", "en"),
                        defaults={
                            "meta_template_id": t.get("id", ""),
                            "category": t.get("category", "MARKETING"),
                            "status": t.get("status", "PENDING"),
                            "body_text": body_c.get("text", ""),
                        },
                    )
                    synced += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Synced {synced} templates"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {e}"))
