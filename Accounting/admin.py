from django.contrib import admin
from django.db.models.deletion import ProtectedError
# Accounting/admin.py
from django.contrib import messages
from django.urls import path
from django.template.response import TemplateResponse
from django.db import transaction

from .models import (
    FundEntry,
    Invoice,
    GeneralDonationInvoice,
    FinancialSponsorshipInvoice,
    FinancialSponsorshipAllocation,
    SubProgramDisbursement,
)

from Management.models import Beneficiary, MainProgram, SubProgram 
from django.db.models import Sum
from .models import AllocationHistory

from Management.models import (
    Beneficiary,
    MainProgram,
    SubProgram,
    BeneficiarySponsorHistory,
    AuditLog,
)

from .models import (
        BeneficiarySupportEntry,
    PaymentPlan,
)

from .models import Invoice



# @admin.register(BeneficiarySponsorHistory)
# class BeneficiarySponsorHistoryAdmin(admin.ModelAdmin):

#     list_display = (
#         "beneficiary",
#         "donor",
#         "start_date",
#         "end_date",
#         "assigned_by",
#         "created_at",
#     )

#     list_display_links = (
#         "beneficiary",
#         "donor",
#     )

#     list_filter = (
#         "start_date",
#         "end_date",
#         "created_at",
#     )

#     search_fields = (
#         "beneficiary__first_name",
#         "beneficiary__father_name",
#         "beneficiary__last_name",
#         "donor__user__first_name",
#         "donor__user__last_name",
#         "donor__phone",
#         "donor__national_number",
#     )

#     date_hierarchy = "start_date"

#     ordering = (
#         "-start_date",
#         "-id",
#     )

#     readonly_fields = (
#         "created_at",
#     )

#     fieldsets = (
#         (
#             "بيانات الكفالة",
#             {
#                 "fields": (
#                     "beneficiary",
#                     "donor",
#                     "start_date",
#                     "end_date",
#                 )
#             },
#         ),
#         (
#             "بيانات الإسناد",
#             {
#                 "fields": (
#                     "assigned_by",
#                     "created_at",
#                 )
#             },
#         ),
#     )



class AccountingCleanupAdmin(admin.ModelAdmin):
    change_list_template = "admin/accounting_cleanup.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "cleanup/",
                self.admin_site.admin_view(self.cleanup_view),
                name="accounting-cleanup",
            ),
        ]
        return custom_urls + urls

    def cleanup_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "❌ تحتاج صلاحية Superuser.")
            return TemplateResponse(
                request,
                "admin/accounting_cleanup.html",
                {"title": "تنظيف بيانات المحاسبة"},
            )

        if request.method == "POST":
            delete_management = request.POST.get("delete_management") == "on"

            try:
                with transaction.atomic():

                    # ==========================================
                    # السجلات والتقارير
                    # ==========================================

                    AuditLog.objects.all().delete()


                    # ==========================================
                    # عمليات الصرف
                    # ==========================================

                    BeneficiarySupportEntry.objects.all().delete()

                    SubProgramDisbursement.objects.all().delete()

                    # ==========================================
                    # الكفالات
                    # ==========================================

                    FinancialSponsorshipAllocation.objects.all().delete()
                    FinancialSponsorshipInvoice.objects.all().delete()

                    BeneficiarySponsorHistory.objects.all().delete()

                    # ==========================================
                    # الفواتير
                    # ==========================================

                    GeneralDonationInvoice.objects.all().delete()
                    Invoice.objects.all().delete()

                    # ==========================================
                    # أرصدة المستفيدين
                    # ==========================================


                    # ==========================================
                    # سجل التخصيصات
                    # مهم جدًا قبل حذف البرامج
                    # ==========================================

                    AllocationHistory.objects.all().delete()


                    # ==========================================
                    # الحجوزات والحركات المالية
                    # ==========================================

                    FundEntry.objects.all().delete()

                    # ==========================================
                    # خطط الدفع
                    # ==========================================

                    PaymentPlan.objects.all().delete()

                    # ==========================================
                    # البرامج والمستفيدين
                    # ==========================================

                    if delete_management:

                        SubProgram.objects.all().delete()
                        MainProgram.objects.all().delete()

                        Beneficiary.objects.all().delete()

                messages.success(
                    request,
                    "✅ تم تنظيف بيانات النظام بنجاح"
                    + (
                        " + تم حذف البرامج والمستفيدين"
                        if delete_management
                        else ""
                    )
                )

            except ProtectedError as ex:
                messages.error(
                    request,
                    "❌ تعذر إكمال التنظيف بسبب وجود سجلات مرتبطة "
                    "ببيانات محمية. راجع العلاقات المرتبطة قبل الحذف."
                )

            except Exception as ex:
                messages.error(
                    request,
                    f"❌ حدث خطأ أثناء التنظيف: {ex}"
                )

        return TemplateResponse(
            request,
            "admin/accounting_cleanup.html",
            {
                "title": "تنظيف بيانات المحاسبة",
            },
         )
admin.site.register(FundEntry, AccountingCleanupAdmin)


# نسجل Admin وهمي فقط لإظهار الصفحة

# 🔹 1) صفحة الفاتورة الأساسية Invoice
@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "invoice_type",
        "receipt_kind",
        "payment_method",
        "date",
        "created_by",
    )

    list_filter = (
        "invoice_type",
        "receipt_kind",
        "payment_method",
        "date",
    )

    search_fields = (
        "number",
        "notes",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-date",
        "-id",
    )

    date_hierarchy = "date"

    list_per_page = 30

# 🔹 2) صفحة التبرعات العامة
@admin.register(GeneralDonationInvoice)
class GeneralDonationInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "supporter_name",
        "supporter_phone",
        "supporter_national_number",
        "amount",
    )
    search_fields = ("supporter_name", "supporter_phone", "supporter_national_number")
    ordering = ("-invoice__date",)


# 🔹 3) صفحة الكفالة المالية
@admin.register(FinancialSponsorshipInvoice)
class FinancialSponsorshipInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "get_sponsor_name",
        "payment_plan",
        "custom_amount",
        "start_date",
        "end_date",
    )
    search_fields = (
        "invoice__number",
        "sponsor__user__first_name",
        "sponsor__user__last_name",
        "sponsor__national_number",
    )
    ordering = ("-invoice__date",)

    def get_sponsor_name(self, obj):
        return obj.sponsor.user.get_full_name() or obj.sponsor.user.username
    get_sponsor_name.short_description = "الكافل"


# 🔹 4) صفحة التخصيصات
@admin.register(FinancialSponsorshipAllocation)
class FinancialSponsorshipAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "sponsorship_invoice",
        "beneficiary",
        "amount",
        "created_at",
    )
    search_fields = (
        "sponsorship_invoice__invoice__number",
        "beneficiary__first_name",
        "beneficiary__last_name",
        "beneficiary__national_number",
    )
    ordering = ("-created_at",)
