"""
Optional Celery tasks.
Only imported when WHATSAPP_USE_CELERY = True and celery is installed.
"""
try:
    from celery import shared_task

    @shared_task(bind=True, max_retries=3, default_retry_delay=60)
    def run_campaign_task(self, campaign_id: int, account_id=None):
        from .utils import run_campaign
        from .models import WhatsAppAccount

        account = None
        if account_id:
            try:
                account = WhatsAppAccount.objects.get(pk=account_id)
            except WhatsAppAccount.DoesNotExist:
                pass
        try:
            return run_campaign(campaign_id, account=account)
        except Exception as exc:
            raise self.retry(exc=exc)

except ImportError:
    pass  # Celery not installed; tasks unavailable
