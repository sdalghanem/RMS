from django.contrib import admin

# Accounting/admin.py
from django.contrib import admin, messages
from django.urls import path
from django.template.response import TemplateResponse
from django.db import transaction

from .models import (
    FundEntry,
    Invoice,
    GeneralDonationInvoice,
    FinancialSponsorshipInvoice,
    FinancialSponsorshipAllocation,
    BeneficiaryBalanceEntry,
    FundToMainProgramAllocation,
    MainToSubProgramAllocation,
    SubProgramDisbursement,
    SubProgramDisbursementLine,
)

from Management.models import Beneficiary, MainProgram, SubProgram
from django.db.models import Sum
from .models import FundReservation

from Management.models import (
    Beneficiary,
    MainProgram,
    SubProgram,
    BeneficiarySponsorHistory,
    AuditLog,
)

from .models import (
    
    FundReservation,
    BeneficiarySupportEntry,
    SponsorshipReport,
    PaymentPlan,
)

from .models import Invoice

print("Invoice =", Invoice)
print("Type =", type(Invoice))

@admin.register(FundReservation)
class FundReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "source_type",
        "amount",
        "main_program",
        "sub_program",
        "beneficiary",
        "created_by",
        "note",
    )
    list_filter = ("source_type", "created_at")
    search_fields = (
        "note",
        "main_program__name",
        "sub_program__name",
        "beneficiary__first_name",
        "beneficiary__last_name",
        "beneficiary__national_number",
    )
    ordering = ("-created_at", "-id")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)

    actions = ["release_selected_reservations"]

    @admin.action(description="فك الحجز (إنشاء حركة عكسية) للسجلات المحددة")
    def release_selected_reservations(self, request, queryset):
        # نفك فقط السجلات الموجبة (حجز)
        qs = queryset.filter(amount__gt=0)
        created = 0

        for r in qs:
            FundReservation.objects.create(
                source_type=r.source_type,
                main_program=r.main_program,
                sub_program=r.sub_program,
                beneficiary=r.beneficiary,
                amount=-r.amount,
                reference=r.reference,
                note=f"فك حجز (من الأدمن) - عكس حجز #{r.id}",
                created_by=request.user,
            )
            created += 1

        self.message_user(request, f"تم إنشاء {created} حركة فك حجز بنجاح.")

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

            with transaction.atomic():

                AuditLog.objects.all().delete()

                SponsorshipReport.objects.all().delete()

                BeneficiarySupportEntry.objects.all().delete()

                SubProgramDisbursementLine.objects.all().delete()
                SubProgramDisbursement.objects.all().delete()

                FinancialSponsorshipAllocation.objects.all().delete()
                FinancialSponsorshipInvoice.objects.all().delete()
                GeneralDonationInvoice.objects.all().delete()
                Invoice.objects.all().delete()

                BeneficiaryBalanceEntry.objects.all().delete()

                MainToSubProgramAllocation.objects.all().delete()
                FundToMainProgramAllocation.objects.all().delete()

                FundReservation.objects.all().delete()
                FundEntry.objects.all().delete()

                BeneficiarySponsorHistory.objects.all().delete()

                if delete_management:
                    SubProgram.objects.all().delete()
                    MainProgram.objects.all().delete()
                PaymentPlan.objects.all().delete()
                Beneficiary.objects.all().delete()

            messages.success(
                request,
                "✅ تم حذف جميع بيانات المحاسبة بنجاح"
                + (" + بيانات البرامج والمستفيدين" if delete_management else "")
            )

        return TemplateResponse(
            request,
            "admin/accounting_cleanup.html",
            {"title": "تنظيف بيانات المحاسبة"},
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
