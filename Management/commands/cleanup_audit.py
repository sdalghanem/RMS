from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from Management.models import AuditLog

class Command(BaseCommand):
    help = "Delete audit logs older than 90 days"

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=90)
        deleted, _ = AuditLog.objects.filter(ts__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old audit logs"))
