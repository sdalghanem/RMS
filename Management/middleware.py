import json
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.urls import resolve
from .models import AuditLog
from django.contrib.auth import get_user_model

User = get_user_model()
SENSITIVE_KEYS = {"password", "password1", "password2", "csrfmiddlewaretoken"}

class AuditMiddleware(MiddlewareMixin):
    """
    - يسجل كل طلب HTTP (method, path, status, user, params)
    - يخفي الحقول الحساسة
    - يحقن user في الكائنات التي تُنشأ/تتعدل داخل نفس الطلب عبر set_on_save (اختياري)
    """

    def _scrub(self, data):
        if not isinstance(data, dict):
            return None
        clean = {}
        for k, v in data.items():
            if k in SENSITIVE_KEYS:
                clean[k] = "***"
            else:
                # قلل الحجم: خذ 500 حرف بالكثير
                if isinstance(v, (list, tuple)):
                    v = v[:20]
                elif isinstance(v, str) and len(v) > 500:
                    v = v[:500] + "...(+truncated)"
                clean[k] = v
        return clean

    def process_view(self, request, view_func, view_args, view_kwargs):
        # خزّن معلومات أولية للاستخدام في process_response
        request._audit_info = {
            "start": timezone.now().isoformat(),
            "path": request.path,
            "method": request.method,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "resolver": None,
            "GET": self._scrub(request.GET.dict()) if request.GET else None,
            "POST": self._scrub(request.POST.dict()) if request.method == "POST" else None,
        }
        try:
            match = resolve(request.path_info)
            request._audit_info["resolver"] = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Exception:
            pass
        return None

    def process_response(self, request, response):
        info = getattr(request, "_audit_info", None)
        if info is None:
            return response

        try:
            # سجّل الطلب
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=AuditLog.Actions.REQUEST,
                entity="http",
                entity_id=info.get("resolver") or info.get("path"),
                extra={
                    "method": info.get("method"),
                    "path": info.get("path"),
                    "status": getattr(response, "status_code", None),
                    "GET": info.get("GET"),
                    "POST": info.get("POST"),
                },
            )
            # تنظيف دوري خفيف
            from datetime import timedelta
            from django.utils import timezone
            AuditLog.objects.filter(ts__lt=timezone.now() - timedelta(days=90)).delete()
        except Exception:
            # لا تعطل الطلب بسبب التدقيق
            pass

        return response
