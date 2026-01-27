# Managment/apps.py
from django.apps import AppConfig

class ManagementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "Management"
    verbose_name = "إدارة النظام"

    def ready(self):
        import Management.signals  # مهم: يحمّل السيجنلز عند تشغيل التطبيق
