from Management.models import AuditLog


def log_activity(
    user,
    action,
    entity,
    entity_id=None,
    extra=None,
):
    """
    تسجيل نشاط في Audit Log
    """

    AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id else None,
        extra=extra or {},
    )