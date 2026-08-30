# core/admin.py
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from django.utils.html import format_html

from .models import Profile, AuditLog, Beneficiary , PaymentPlan
from django.db.models import Sum
from .models import MainProgram, SubProgram , BeneficiarySponsorHistory
class BeneficiarySponsorHistoryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "beneficiary",
        "donor",
        "start_date",
        "end_date",
        "assigned_by",
    )

    list_filter = (
        "start_date",
        "end_date",
    )

    search_fields = (
        "beneficiary__first_name",
        "beneficiary__father_name",
        "beneficiary__grand_name",
        "beneficiary__last_name",
        "beneficiary__national_number",
        "donor__user__first_name",
        "donor__user__last_name",
        "donor__national_number",
    )

    ordering = (
        "-start_date",
        "-id",
    )

    date_hierarchy = "start_date"

    autocomplete_fields = (
        "beneficiary",
        "donor",
        "assigned_by",
    )
from .forms import SubProgramForm, SubProgramInlineFormSet

User = get_user_model()


class SubProgramInline(admin.TabularInline):
    model = SubProgram
    form = SubProgramForm
    formset = SubProgramInlineFormSet
    extra = 0
    fields = ("name", "allocated_amount", "spent_amount", "remaining_display", "description")
    readonly_fields = ("remaining_display",)

    # 🔒 اجعل spent_amount للقراءة فقط لمدير النظام
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if request.user.groups.filter(name="system_admin").exists():
            ro.append("spent_amount")
            ro.append("allocated_amount")
        return ro

    def remaining_display(self, obj):
        if not obj.pk:
            return "-"
        remaining = (obj.allocated_amount or 0) - (obj.spent_amount or 0)
        # نسبة الصرف
        pct = 0
        if (obj.allocated_amount or 0) > 0:
            pct = int(round((obj.spent_amount or 0) * 100 / obj.allocated_amount))
            pct = max(0, min(pct, 100))

        bar = (
            f'<div style="background:#eee;border-radius:6px;overflow:hidden;height:10px;width:140px">'
            f'  <div style="height:10px;width:{pct}%;background:#4caf50"></div>'
            f'</div>'
        )
        return format_html(f"{remaining:,.2f} ريال {bar}")
    remaining_display.short_description = "المتبقي (فرعي)"


@admin.register(MainProgram)
class MainProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "total_donation_amount", "remaining_amount", "created_at")

    def get_fields(self, request, obj=None):
        fields = ["name", "description", "total_donation_amount"]
        if request.user.groups.filter(name="system_admin").exists():
            fields = ["name", "description"]
        return fields

    def save_model(self, request, obj, form, change):
        if request.user.groups.filter(name="system_admin").exists():
            obj.total_donation_amount = 0
            obj.remaining_amount = 0
        super().save_model(request, obj, form, change)


@admin.register(SubProgram)
class SubProgramAdmin(admin.ModelAdmin):
    # 👁️ أضفنا spent_amount للعرض
    list_display = ("name", "main_program", "allocated_amount", "spent_amount", "pct_spent")

    # ✅ أظهر spent_amount في النموذج (إلا لمدير النظام نجعله قراءة فقط/نخفيه)
    def get_fields(self, request, obj=None):
        fields = ["main_program", "name", "description", "allocated_amount", "spent_amount"]
        if request.user.groups.filter(name="system_admin").exists():
            # مدير النظام لا يتعامل مع مبالغ
            fields = ["main_program", "name", "description"]
        return fields

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if request.user.groups.filter(name="system_admin").exists():
            ro.extend(["allocated_amount", "spent_amount"])
        return ro

    # شريط نسبة مبسّط في قائمة الأدمن
    def pct_spent(self, obj: SubProgram):
        alloc = obj.allocated_amount or 0
        spent = obj.spent_amount or 0
        if alloc <= 0:
            return "-"
        pct = max(0, min(int(round(spent * 100 / alloc)), 100))
        color = "#4caf50" if pct < 80 else ("#ff9800" if pct < 95 else "#e54848")
        bar = (
            f'<div style="background:#eee;border-radius:6px;overflow:hidden;height:10px;width:120px">'
            f'  <div style="height:10px;width:{pct}%;background:{color}"></div>'
            f'</div>'
        )
        return format_html(f"{pct}% {bar}")
    pct_spent.short_description = "نسبة الصرف"

    def save_model(self, request, obj, form, change):
        # حماية إضافية: مدير النظام لا يغيّر مبالغ
        if request.user.groups.filter(name="system_admin").exists():
            # لا نعدل القيم المالية هنا؛ اتركها كما هي/صفر
            if not change:
                obj.allocated_amount = 0
                obj.spent_amount = 0
        super().save_model(request, obj, form, change)


@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("id", "first_name", "last_name", "gender", "donor", "national_number", "created_at")
    search_fields = ("first_name", "father_name", "grand_name", "last_name", "national_number", "donor__user__username", "donor__user__email")
    list_filter = ("gender", "education_level", "health_status", "type_disease", "type_housing", "beneficiary_rank", "donor")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "ts", "user", "action", "entity", "entity_id")
    list_filter = ("action", "entity")
    search_fields = ("user__username", "user__email", "entity", "entity_id", "extra")
    date_hierarchy = "ts"
    ordering = ("-ts",)
    readonly_fields = ("user", "action", "entity", "entity_id", "extra", "ts")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user_link", "phone", "role", "national_number", "created_at")
    list_editable = ("role",)
    list_filter = ("role", ("created_at", admin.DateFieldListFilter))
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name", "phone", "national_number", "father_name", "grandpa_name")
    ordering = ("-created_at",)
    list_per_page = 25
    autocomplete_fields = ("user",)
    fieldsets = (
        ("المستخدم", {"fields": ("user", "role")}),
        ("البيانات الشخصية", {"fields": ("phone", "national_number", "father_name", "grandpa_name")}),
        ("التواريخ", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")

    def user_link(self, obj: Profile):
        if not obj.user_id:
            return "-"
        url = reverse("admin:%s_%s_change" % (User._meta.app_label, User._meta.model_name), args=[obj.user_id])
        full_name = obj.user.get_full_name() or obj.user.username
        return format_html('<a href="{}">{}</a>', url, full_name)
    user_link.short_description = "المستخدم"

    @admin.action(description="تعيين الدور: كفيل (donor)")
    def make_donor(self, request, queryset):
        changed = 0
        for p in queryset:
            if p.role != Profile.Roles.DONOR:
                p.role = Profile.Roles.DONOR
                p.save(update_fields=["role"])
                changed += 1
        self.message_user(request, f"تم تحديث الدور إلى كفيل لعدد {changed} سجل.")

    @admin.action(description="تعيين الدور: محاسب (accountant)")
    def make_accountant(self, request, queryset):
        changed = 0
        for p in queryset:
            if p.role != Profile.Roles.ACCOUNTANT:
                p.role = Profile.Roles.ACCOUNTANT
                p.save(update_fields=["role"])
                changed += 1
        self.message_user(request, f"تم تحديث الدور إلى محاسب لعدد {changed} سجل.")

    @admin.action(description="تعيين الدور: كاشير (cashier)")
    def make_cashier(self, request, queryset):
        changed = 0
        for p in queryset:
            if p.role != Profile.Roles.CASHIER:
                p.role = Profile.Roles.CASHIER
                p.save(update_fields=["role"])
                changed += 1
        self.message_user(request, f"تم تحديث الدور إلى كاشير لعدد {changed} سجل.")
    actions = ["make_donor", "make_accountant", "make_cashier"]


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fk_name = "user"
    extra = 0
    fields = ("role", "phone", "national_number", "father_name", "grandpa_name", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "email", "first_name", "last_name", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")


admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(PaymentPlan)
class PaymentPlanAdmin(admin.ModelAdmin):

    list_display = (
        "amount",
        "duration_months",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "duration_months",
    )

    search_fields = (
    "amount",
    "duration_months",
)

    ordering = (
        "amount",
    )

    list_per_page = 30

    readonly_fields = (
        "created_at",
    )

    fieldsets = (
        (
            "بيانات الخطة",
            {
                "fields": (
                    "amount",
                    "duration_months",
                    "is_active",
                )
            },
        ),
        (
            "بيانات النظام",
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                ),
            },
        ),
    )

@admin.register(BeneficiarySponsorHistory)
class BeneficiarySponsorHistoryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "beneficiary",
        "donor",
        "start_date",
        "end_date",
        "assigned_by",
    )

    list_filter = (
        "start_date",
        "end_date",
    )

    search_fields = (
        "beneficiary__first_name",
        "beneficiary__father_name",
        "beneficiary__grand_name",
        "beneficiary__last_name",
        "beneficiary__national_number",
        "donor__user__first_name",
        "donor__user__last_name",
        "donor__national_number",
    )

    ordering = (
        "-start_date",
        "-id",
    )

    date_hierarchy = "start_date"

    autocomplete_fields = (
        "beneficiary",
        "donor",
        "assigned_by",
    )