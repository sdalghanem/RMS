# Management/mixins.py
from django.core.exceptions import PermissionDenied

class RoleRequiredMixin:
    """
    يمنع الوصول للـ CBV إلا إن كان المستخدم ضمن الأدوار المسموح بها.
    الاستعمال:
      class MyView(RoleRequiredMixin, ListView):
          allowed_roles = ("system_admin",)
    """
    allowed_roles = tuple()

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            # نخلي login_required الموجود على الـ CBV يتكفل
            raise PermissionDenied

        # السوبر يوزر دائماً مسموح
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        # لو ما عنده بروفايل أو ما فيه role نمنع
        role = getattr(getattr(user, "profile", None), "role", None)
        if not role or (self.allowed_roles and role not in self.allowed_roles):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)
