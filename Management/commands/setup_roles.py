from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.apps import apps

class Command(BaseCommand):
    help = "Create groups and assign permissions"

    def handle(self, *args, **kwargs):
        # عدّل أسماء التطبيقات أو الموديلات لو اختلفت
        Management = apps.get_app_config("Management")
        MainProgram = Management.get_model("MainProgram")
        SubProgram   = Management.get_model("SubProgram")

        # (اختياري) لو عندك موديلات مالية سمّيتها كذا:
        # Donation = Management.get_model("Donation")   # المدخولات
        # Expense  = Management.get_model("Expense")    # المصروفات

        # اجلب كل صلاحيات النماذج
        def perms_for(model):
            ct_perms = Permission.objects.filter(content_type__app_label=model._meta.app_label,
                                                 content_type__model=model._meta.model_name)
            return {p.codename: p for p in ct_perms}

        mp = perms_for(MainProgram)
        sp = perms_for(SubProgram)
        # dn = perms_for(Donation) if 'Donation' in locals() else {}
        # ex = perms_for(Expense)  if 'Expense'  in locals() else {}

        # مجموعات
        system_admin, _ = Group.objects.get_or_create(name="system_admin")
        accountant, _   = Group.objects.get_or_create(name="accountant")
        cashier, _      = Group.objects.get_or_create(name="cashier")
        donor, _        = Group.objects.get_or_create(name="donor")

        # مدير النظام: ينشئ/يعرض البرامج فقط (بدون تغيير/حذف)
        system_admin.permissions.set([
            mp.get("add_mainprogram"), mp.get("view_mainprogram"),
            sp.get("add_subprogram"),  sp.get("view_subprogram"),
            # عرض فقط على المالية (لو موجودة)
            # dn.get("view_donation"), ex.get("view_expense"),
        ])

        # المحاسب/أمين الصندوق: صلاحيات كاملة على المالية والبرامج الفرعية (حسب رغبتك)
        accountant.permissions.set(filter(None, [
            mp.get("view_mainprogram"),
            sp.get("add_subprogram"), sp.get("change_subprogram"), sp.get("delete_subprogram"), sp.get("view_subprogram"),
            # dn.get("add_donation"), dn.get("change_donation"), dn.get("delete_donation"), dn.get("view_donation"),
            # ex.get("add_expense"),  ex.get("change_expense"),  ex.get("delete_expense"),  ex.get("view_expense"),
        ]))
        cashier.permissions.set(accountant.permissions.all())

        # المتبرع: عرض فقط
        donor.permissions.set(filter(None, [
            mp.get("view_mainprogram"), sp.get("view_subprogram"),
            # dn.get("view_donation"),
        ]))

        self.stdout.write(self.style.SUCCESS("Groups & permissions configured."))
