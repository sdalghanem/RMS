# signals.py
from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.contrib.contenttypes.models import ContentType

from .models import AuditLog, Profile
User = get_user_model()

GROUP_NAMES = {
    Profile.Roles.DONOR: "donor",
    Profile.Roles.ACCOUNTANT: "accountant",
    Profile.Roles.CASHIER: "cashier",
    Profile.Roles.SYSTEM_ADMIN: "system_admin",  # ✅ جديد

}

def ensure_groups_exist():
    for name in GROUP_NAMES.values():
        Group.objects.get_or_create(name=name)

def sync_user_group(profile: Profile):
    ensure_groups_exist()
    user = profile.user
    # أزل المستخدم من الجروبات التي نديرها
    user.groups.remove(*Group.objects.filter(name__in=GROUP_NAMES.values()))
    # أضفه للجروب المطابق لدوره
    group_name = GROUP_NAMES.get(profile.role)
    if group_name:
        group = Group.objects.get(name=group_name)
        user.groups.add(group)

@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    ensure_groups_exist()

# 🔻 احذف (أو علّق) مستقبِل إنشاء البروفايل على User لتفادي القيم المكررة
# @receiver(post_save, sender=User)
# def create_or_update_profile(sender, instance, created, **kwargs):
#     if created:
#         Profile.objects.create(
#             user=instance,
#             phone="0500000000",
#             national_number="0000000000",
#             role=Profile.Roles.DONOR,
#         )

@receiver(post_save, sender=Profile)
def update_user_group_on_profile_save(sender, instance: Profile, **kwargs):
    sync_user_group(instance)







SENSITIVE_KEYS = {"password", "password1", "password2"}

def _cleanup():
    cutoff = timezone.now() - timedelta(days=90)
    AuditLog.objects.filter(ts__lt=cutoff).delete()

def audit(user, action, entity, entity_id=None, extra=None):
    AuditLog.objects.create(
        user=user if isinstance(user, User) else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        extra=extra or None,
    )
    _cleanup()

# ===== مصادقة =====
@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    audit(user, AuditLog.Actions.LOGIN, "auth", user.id, extra={"ip": request.META.get("REMOTE_ADDR")})

@receiver(user_logged_out)
def on_user_logout(sender, request, user, **kwargs):
    audit(user, AuditLog.Actions.LOGOUT, "auth", getattr(user, "id", None), extra={"ip": request.META.get("REMOTE_ADDR")})

@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    identity = None
    if isinstance(credentials, dict):
        identity = credentials.get("username")
    audit(None, AuditLog.Actions.LOGIN_FAILED, "auth", identity, extra={"ip": request.META.get("REMOTE_ADDR") if request else None})

# ===== كل الموديلات (إنشاء/تحديث/حذف) =====
# نلتقط جميع الـ post_save/post_delete ونستثني AuditLog نفسه لتجنّب الحلقة
@receiver(post_save, dispatch_uid="audit_all_models_save")
def on_any_model_saved(sender, instance, created, **kwargs):
    if sender is AuditLog:
        return
    # اسم الكيان من ContentType
    ct = ContentType.objects.get_for_model(sender, for_concrete_model=False)
    entity = ct.model  # مثل "user", "profile", "donation"...
    # نحاول استخراج المفتاح
    entity_id = getattr(instance, "pk", None)

    # صاحب العملية (إن أمكن لاحقاً عبر middleware نربط request.user بالثريد)
    user = getattr(instance, "_audit_user", None)  # ستُحقن من الميدلوير إن توفّر
    action = AuditLog.Actions.CREATE if created else AuditLog.Actions.UPDATE
    audit(user, action, entity, entity_id)

@receiver(post_delete, dispatch_uid="audit_all_models_delete")
def on_any_model_deleted(sender, instance, **kwargs):
    if sender is AuditLog:
        return
    ct = ContentType.objects.get_for_model(sender, for_concrete_model=False)
    entity = ct.model
    entity_id = getattr(instance, "pk", None)
    user = getattr(instance, "_audit_user", None)
    audit(user, AuditLog.Actions.DELETE, entity, entity_id)
