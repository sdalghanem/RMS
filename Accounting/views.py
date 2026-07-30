from django.core.paginator import Paginator
from django.contrib import messages
# الموديل الجديد للفواتير في تطبيق Accounting
from .models import Invoice
# نستفيد من البروفايل والديكوريتر من تطبيق Management
from Management.views import role_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import (
    Invoice,
    GeneralDonationInvoice,
    FinancialSponsorshipInvoice,
    FinancialSponsorshipAllocation,
    FundEntry,
    FundToMainProgramAllocation,
    MainToSubProgramAllocation,
    SubProgramDisbursement,
    SubProgramDisbursementLine,
    FundReservation ,
    BeneficiaryBalanceEntry,
)
from django.core.exceptions import ValidationError
from .forms import GeneralDonationInvoiceForm, FinancialSponsorshipInvoiceForm , FinancialSponsorshipAllocationForm
from django.views.decorators.http import require_POST
from datetime import date
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from decimal import Decimal
from django.db.models import Sum, Q, F, Value, DecimalField, Case, When, ExpressionWrapper
from django.db.models.functions import Coalesce
from Management.models import Profile, MainProgram, SubProgram, Beneficiary

from django.utils import timezone

from django.db.models import OuterRef, Subquery

from django.db.models import Sum, Min
from Management.models import BeneficiarySponsorHistory
from Accounting.models import FinancialSponsorshipInvoice
from Management.models import AuditLog
from Management.utils.audit import log_activity

User = get_user_model()




#@login_required
def cashier_home(request):

    today = timezone.localdate()

    activities = (
        AuditLog.objects
        .filter(user=request.user)
        .exclude(
            action__in=[
                AuditLog.Actions.REQUEST,
                AuditLog.Actions.LOGIN,
                AuditLog.Actions.LOGOUT,
            ]
        )
        .only("action", "entity", "entity_id", "extra", "ts")
        .order_by("-ts")[:10]
    )
    donors_count = Profile.objects.filter(
        role=Profile.Roles.DONOR
    ).count()

    today = timezone.localdate()

    today_invoices = Invoice.objects.filter(
        date=today
    )

    today_invoice_count = today_invoices.count()

    today_income = (
    FundEntry.objects.filter(
        created_at__date=today,
        type__in=[
            FundEntry.Types.GENERAL_DONATION_INCOME,
            FundEntry.Types.SPONSORSHIP_INCOME,
        ]
        ).aggregate(total=Sum("amount"))["total"] or 0
    )
    latest_invoices = (
        Invoice.objects
        .select_related(
            "general_donation",
            "financial_sponsorship",
            "financial_sponsorship__sponsor",
            "financial_sponsorship__sponsor__user",
        )
        .order_by("-id")[:10]
    )
    context = {

        "today_invoices": 0,
        "today_amount": 0,
        "today_sponsors": 0,
        "pending_invoices": 0,
        "activities" :activities ,
        "recent_invoices": [],
        "donors_count": donors_count,
        "today_invoice_count": today_invoice_count,
        "today_income": today_income,
        "latest_invoices": latest_invoices,
        "today": timezone.localdate(),

    }

    return render(
        request,
        "Accounting/cashier_home.html",
        context,
    )
# def fund_available_balance():
#     from .models import FundEntry, FundToMainProgramAllocation, BeneficiaryBalanceEntry

#     fund_total = FundEntry.objects.aggregate(
#         t=Coalesce(Sum("amount"), Decimal("0.00"))
#     )["t"]

#     # (A) محجوز للمستفيدين = رصيد محافظهم الحالي
#     reserved_beneficiaries = BeneficiaryBalanceEntry.objects.aggregate(
#         t=Coalesce(Sum("amount"), Decimal("0.00"))
#     )["t"]

#     # (B) محجوز للبرامج الرئيسية = ما خُصص من الصندوق للبرامج
#     reserved_main_programs = FundToMainProgramAllocation.objects.aggregate(
#         t=Coalesce(Sum("amount"), Decimal("0.00"))
#     )["t"]

#     # المتاح = الصندوق - محفظة المستفيدين - تخصيصات البرامج
#     available = fund_total - reserved_beneficiaries - reserved_main_programs
#     if available < 0:
#         available = Decimal("0.00")

#     return available

def fund_available_balance():
    from .models import FundEntry, FundReservation
    from django.db.models import Sum
    from django.db.models.functions import Coalesce
    from decimal import Decimal

    fund_total = FundEntry.objects.aggregate(
        t=Coalesce(Sum("amount"), Decimal("0.00"))
    )["t"]

    reserved = FundReservation.objects.aggregate(
        t=Coalesce(Sum("amount"), Decimal("0.00"))
    )["t"]

    available = fund_total - reserved
    return max(available, Decimal("0.00"))



def generate_next_invoice_number(prefix="INV-"):
    """
    توليد رقم سند جديد متسلسل بالشكل:
    INV-0001, INV-0002, ...
    ويمكن تغيير البادئة prefix مثل:
    SP- للكفالات المالية
    GDN- للتبرعات العامة
    """
    last_invoice = (
        Invoice.objects
        .filter(number__startswith=prefix)
        .order_by("-id")
        .first()
    )

    if not last_invoice:
        return f"{prefix}0001"

    last_number = last_invoice.number.replace(prefix, "")
    try:
        last_int = int(last_number)
    except ValueError:
        # لو الرقم السابق كان بصيغة غير متوقعة
        return f"{prefix}0001"

    new_int = last_int + 1
    return f"{prefix}{new_int:04d}"


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
@require_POST
def sponsorship_allocation_delete(request, pk):
    """
    حذف تخصيص كفالة معيّن.
    """
    allocation = get_object_or_404(
        FinancialSponsorshipAllocation.objects.select_related("sponsorship_invoice"),
        pk=pk,
    )
    sponsorship = allocation.sponsorship_invoice  # نحتاجه للرجوع للصفحة

    allocation.delete()  # سيحذف أيضًا BeneficiaryBalanceEntry بسبب on_delete=CASCADE
    FundReservation.objects.create(
        source_type=FundReservation.Sources.BENEFICIARY,
        beneficiary=allocation.beneficiary,
        amount=-(allocation.amount or 0),   # ✅ فك الحجز
        reference=allocation,
        note="فك حجز تخصيص كفالة (حذف التخصيص)",
        created_by=request.user,
    )

    messages.success(request, "تم حذف التخصيص بنجاح.")
    return redirect("Accounting:sponsorship_allocations_manage", pk=sponsorship.pk)





# @role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
# def sponsorship_allocations_manage(request, pk):
#     sponsorship = get_object_or_404(
#         FinancialSponsorshipInvoice.objects.select_related(
#             "invoice",
#             "sponsor__user",
#         ),
#         pk=pk,
#     )

#     allocations = (
#         sponsorship.allocations
#         .select_related("beneficiary")
#         .order_by("-created_at")
#     )

#     # --------------------------------------
#     # 🔍 فلترة المستفيدين (عمر - وجود رصيد/دعم)
#     # --------------------------------------
#     age_min_raw = request.GET.get("age_min")
#     age_max_raw = request.GET.get("age_max")
#     has_alloc = request.GET.get("has_alloc") or "all"

#     # تحويل قيم العمر إلى int إن أمكن
#     try:
#         age_min = int(age_min_raw) if age_min_raw not in (None, "") else None
#     except ValueError:
#         age_min = None

#     try:
#         age_max = int(age_max_raw) if age_max_raw not in (None, "") else None
#     except ValueError:
#         age_max = None

#     # 👇 نجمع:
#     # 1) مجموع التخصيصات من "هذا السند" فقط (لعرضه في الجدول)
#     # 2) مجموع حركات الرصيد الكلي للمستفيد (BeneficiaryBalanceEntry) كرصد نهائي
#     base_qs = Beneficiary.objects.annotate(
#         # sponsorship_alloc_total_for_this=Sum(
#         #     "sponsorship_allocations__amount",
#         #     filter=Q(sponsorship_allocations__sponsorship_invoice=sponsorship),
#         # ),
#         balance_total=Sum("balance_entries__amount"),
#     )

#     beneficiaries_filtered = []

#     for b in base_qs:
#         age = b.age_years  # من الـ property في المودل

#         # فلترة بالعمر
#         if age_min is not None:
#             if age is None or age < age_min:
#                 continue
#         if age_max is not None:
#             if age is None or age > age_max:
#                 continue

#         # فلترة بوجود رصيد/دعم (من جميع الفواتير)
#         total_balance = b.balance_total or 0

#         if has_alloc == "yes" and total_balance <= 0:
#             continue
#         if has_alloc == "no" and total_balance > 0:
#             continue

#         beneficiaries_filtered.append(b)

#     # ترتيب بالاسم
#     beneficiaries_filtered.sort(key=lambda x: (x.last_name, x.first_name))

#     # --------------------------------------
#     # 🔁 إضافة تخصيص جديد
#     # --------------------------------------
#     if request.method == "POST":
#         form = FinancialSponsorshipAllocationForm(request.POST)
#         if form.is_valid():
#             allocation = form.save(commit=False)
#             allocation.sponsorship_invoice = sponsorship
#             try:
#                 allocation.save()
#                  # ✅ إضافة رصيد للمستفيد (محفظة داخلية) عند التخصيص
#                 from .models import BeneficiaryBalanceEntry  # تأكد موجود أعلى الملف أو داخل الفنكشن
#                 from django.db import IntegrityError
#                 try:
#                     BeneficiaryBalanceEntry.objects.create(
#                         beneficiary=allocation.beneficiary,
#                         amount=allocation.amount,
#                         type=BeneficiaryBalanceEntry.Types.SPONSORSHIP_ALLOCATION,
#                         allocation=allocation,
#                         program=None,
#                         description=f"تخصيص كفالة مالية - سند {sponsorship.invoice.number}",
#                         created_by=request.user,
#                     )
#                 except IntegrityError:
#                     # لو انضافت من قبل لأي سبب
#                     pass

               
# # بعد allocation.save() مباشرة



#             except ValidationError as e:
#                 if hasattr(e, "message_dict"):
#                     for _, errors in e.message_dict.items():
#                         for err in errors:
#                             form.add_error(None, err)
#                 else:
#                     form.add_error(None, e.message)
#             else:
#                 messages.success(request, "تم إضافة التخصيص بنجاح.")
#                 FundReservation.objects.create(
#                     source_type=FundReservation.Sources.BENEFICIARY,
#                     beneficiary=allocation.beneficiary,
#                     amount=allocation.amount,   # حجز
#                     reference=sponsorship.invoice.number,
#                     note="حجز كفالة مالية لمستفيد",
#                     created_by=request.user,
#                 )

#                 return redirect("Accounting:sponsorship_allocations_manage", pk=sponsorship.pk)
#     else:
#         form = FinancialSponsorshipAllocationForm()

#     context = {
#         "title": f"تخصيص مبلغ الكفالة - سند {sponsorship.invoice.number}",
#         "sponsorship": sponsorship,
#         "allocations": allocations,
#         "form": form,
#         "total_amount": sponsorship.total_amount,
#         "allocated_amount": sponsorship.allocated_amount,
#         "remaining_amount": sponsorship.remaining_amount,

#         # بيانات الفلتر + النتائج
#         "beneficiaries_filtered": beneficiaries_filtered,
#         "age_min": age_min_raw or "",
#         "age_max": age_max_raw or "",
#         "has_alloc": has_alloc,
#     }
#     return render(request, "Accounting/sponsorship_allocations_manage.html", context)
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsorship_allocations_manage(request, pk):
    sponsorship = get_object_or_404(
        FinancialSponsorshipInvoice.objects.select_related(
            "invoice",
            "sponsor__user",
        ),
        pk=pk,
    )

    allocations = (
        sponsorship.allocations
        .select_related("beneficiary")
        .order_by("-created_at")
    )

    # --------------------------------------
    # 🔍 فلترة المستفيدين (عمر - وجود رصيد/دعم)
    # --------------------------------------
    age_min_raw = request.GET.get("age_min")
    age_max_raw = request.GET.get("age_max")
    has_alloc = request.GET.get("has_alloc") or "all"

    try:
        age_min = int(age_min_raw) if age_min_raw not in (None, "") else None
    except ValueError:
        age_min = None

    try:
        age_max = int(age_max_raw) if age_max_raw not in (None, "") else None
    except ValueError:
        age_max = None

    base_qs = Beneficiary.objects.annotate(
        balance_total=Sum("balance_entries__amount"),
    )

    beneficiaries_filtered = []
    for b in base_qs:
        age = b.age_years

        if age_min is not None and (age is None or age < age_min):
            continue
        if age_max is not None and (age is None or age > age_max):
            continue

        total_balance = b.balance_total or 0
        if has_alloc == "yes" and total_balance <= 0:
            continue
        if has_alloc == "no" and total_balance > 0:
            continue

        beneficiaries_filtered.append(b)

    beneficiaries_filtered.sort(key=lambda x: (x.last_name, x.first_name))

    # --------------------------------------
    # 🔁 إضافة تخصيص جديد
    # --------------------------------------
    if request.method == "POST":
        form = FinancialSponsorshipAllocationForm(request.POST)
        if form.is_valid():
            allocation = form.save(commit=False)
            allocation.sponsorship_invoice = sponsorship

            try:
                with transaction.atomic():
                    # ✅✅✅ (خطوة 2) تحقق من "المتاح في الصندوق" قبل الحجز للمستفيد
                    # أي حجز جديد للمستفيد (FundReservation +) لازم يمر هنا
                    from .models import FundReservation

                    requested = allocation.amount or Decimal("0.00")
                    if requested <= 0:
                        raise ValidationError("مبلغ التخصيص يجب أن يكون أكبر من صفر.")

                    available = FundReservation.available_fund()
                    if requested > available:
                        raise ValidationError(
                            f"الرصيد المتاح في الصندوق لا يكفي لهذا التخصيص. المتاح حالياً: {available}"
                        )

                    # (باقي منطقك الطبيعي)
                    allocation.save()
                    FundReservation.objects.create(
                        source_type=FundReservation.Sources.BENEFICIARY,
                        beneficiary=allocation.beneficiary,
                        amount=allocation.amount,          # ✅ حجز موجب (يقفل من المتاح)
                        reference=allocation,              # الأفضل تربطه بالـ allocation نفسه
                        note=f"حجز كفالة مالية لمستفيد - سند {sponsorship.invoice.number}",
                        created_by=request.user,
                    )
            except ValidationError as e:
                if hasattr(e, "message_dict"):
                    for _, errors in e.message_dict.items():
                        for err in errors:
                            form.add_error(None, err)
                else:
                    form.add_error(None, str(e))
            else:
                messages.success(request, "تم إضافة التخصيص بنجاح.")
                return redirect("Accounting:sponsorship_allocations_manage", pk=sponsorship.pk)
    else:
        form = FinancialSponsorshipAllocationForm()

    context = {
        "title": f"تخصيص مبلغ الكفالة - سند {sponsorship.invoice.number}",
        "sponsorship": sponsorship,
        "allocations": allocations,
        "form": form,
        "total_amount": sponsorship.total_amount,
        "allocated_amount": sponsorship.allocated_amount,
        "remaining_amount": sponsorship.remaining_amount,

        "beneficiaries_filtered": beneficiaries_filtered,
        "age_min": age_min_raw or "",
        "age_max": age_max_raw or "",
        "has_alloc": has_alloc,
    }
    return render(request, "Accounting/sponsorship_allocations_manage.html", context)




# --------------------------------------------------
# 🧮 دالة توليد رقم سند تلقائيًا (INV-0001, INV-0002, ...)
# --------------------------------------------------
def generate_invoice_number():
    last_invoice = Invoice.objects.order_by("-id").first()
    if not last_invoice or not last_invoice.number.startswith("INV-"):
        next_number = 1
    else:
        try:
            last_seq = int(last_invoice.number.split("-")[1])
        except (IndexError, ValueError):
            last_seq = 0
        next_number = last_seq + 1

    return f"INV-{next_number:04d}"


# --------------------------------------------------
# قائمة الفواتير (لـ system_admin + cashier)
# --------------------------------------------------
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def cashier_invoices_list(request):
    invoices_qs = (
        Invoice.objects
        .select_related("general_donation", "financial_sponsorship", "created_by")
        .order_by("-created_at", "-id")
    )

    paginator = Paginator(invoices_qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "title": "الفواتير",
        "page_obj": page_obj,
    }
    return render(request, "Accounting/cashier_invoices_list.html", context)

@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def invoice_update(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("general_donation", "financial_sponsorship"),
        pk=pk
    )

    current_amount = Decimal("0.00")

    if invoice.invoice_type == Invoice.Types.GENERAL_DONATION and hasattr(invoice, "general_donation"):
        current_amount = invoice.general_donation.amount

    elif invoice.invoice_type == Invoice.Types.FINANCIAL_SPONSORSHIP and hasattr(invoice, "financial_sponsorship"):
        current_amount = invoice.financial_sponsorship.total_amount

    if request.method == "POST":
        amount_raw = (request.POST.get("amount") or "").strip()

        try:
            new_amount = Decimal(amount_raw)

            if new_amount <= 0:
                raise ValidationError("المبلغ يجب أن يكون أكبر من صفر.")

            with transaction.atomic():
                if invoice.invoice_type == Invoice.Types.GENERAL_DONATION:
                    general = invoice.general_donation
                    general.amount = new_amount
                    general.save(update_fields=["amount"])

                    FundEntry.objects.filter(invoice=invoice).update(
                        amount=new_amount,
                        description=f"تبرع عام من {general.supporter_name or 'داعم'} - سند {invoice.number}",
                    )

                elif invoice.invoice_type == Invoice.Types.FINANCIAL_SPONSORSHIP:
                    sponsorship = invoice.financial_sponsorship

                    allocated = sponsorship.allocated_amount
                    if new_amount < allocated:
                        raise ValidationError(
                            f"لا يمكن جعل المبلغ أقل من المخصص للمستفيدين. المخصص حالياً: {allocated} ر.س"
                        )

                    sponsorship.custom_amount = new_amount
                    sponsorship.save(update_fields=["custom_amount"])

                    FundEntry.objects.filter(invoice=invoice).update(
                        amount=new_amount,
                        description=f"دخل كفالة مالية من السند رقم {invoice.number}",
                    )

                messages.success(request, "تم تعديل مبلغ الفاتورة بنجاح.")
                return redirect("Accounting:invoice_detail", pk=invoice.pk)

        except (InvalidOperation, ValidationError) as e:
            messages.error(request, str(e))

    return render(request, "Accounting/invoice_amount_update.html", {
        "title": f"تعديل مبلغ السند {invoice.number}",
        "invoice": invoice,
        "current_amount": current_amount,
    })

@require_POST
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def invoice_delete(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("general_donation", "financial_sponsorship"),
        pk=pk
    )

    try:
        with transaction.atomic():

            # 🔒 شرط أمان (مهم حالياً)
            if invoice.invoice_type == Invoice.Types.FINANCIAL_SPONSORSHIP:
                sponsorship = getattr(invoice, "financial_sponsorship", None)

                if sponsorship and sponsorship.allocated_amount > 0:
                    messages.error(
                        request,
                        "لا يمكن حذف الفاتورة لوجود مبالغ مخصصة للمستفيدين."
                    )
                    return redirect("Accounting:cashier_invoices_list")

            # 🧹 حذف حركة الصندوق
            FundEntry.objects.filter(invoice=invoice).delete()

            # 🧹 حذف التفاصيل
            if hasattr(invoice, "general_donation"):
                invoice.general_donation.delete()

            if hasattr(invoice, "financial_sponsorship"):
                invoice.financial_sponsorship.delete()

            # 🧹 حذف الفاتورة
            invoice.delete()

            log_activity(
                user=request.user,
                action=AuditLog.Actions.DELETE,
                entity="Invoice",
                entity_id=pk,
                extra={
                    "invoice_number": invoice.number,
                },
            )

            messages.success(request, "تم حذف الفاتورة بنجاح.")

    except Exception as e:
        messages.error(request, f"حدث خطأ أثناء الحذف: {str(e)}")

    return redirect("Accounting:cashier_invoices_list")
# --------------------------------------------------
# إنشاء سند تبرع عام
# --------------------------------------------------
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def invoice_create_general(request):
    if request.method == "POST":
        form = GeneralDonationInvoiceForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data

            try:
                # السند الأساسي (رقم السند يدوي)
                invoice = Invoice.objects.create(
                    number=cleaned["number"],   # ⬅️ صار يدوي
                    date=cleaned["date"],
                    invoice_type=Invoice.Types.GENERAL_DONATION,
                    receipt_kind=Invoice.ReceiptKinds.RECEIPT,
                    payment_method=cleaned["payment_method"],
                    notes=cleaned["notes"],
                    created_by=request.user,
                )
            except IntegrityError:
                form.add_error("number", "رقم السند مستخدم مسبقاً.")
            else:
                # تفاصيل التبرع العام
                general = GeneralDonationInvoice.objects.create(
                    invoice=invoice,
                    bank_from=cleaned["bank_from"],
                    from_account_number=cleaned["from_account_number"],
                    to_account_number=cleaned["to_account_number"],
                    amount=cleaned["amount"],
                    amount_in_words=cleaned["amount_in_words"],
                    supporter_name=cleaned["supporter_name"],
                    supporter_phone=cleaned.get("supporter_phone"),
                    supporter_national_number=cleaned.get("supporter_national_number"),
                )

                # حركة دخل للصندوق العام
                FundEntry.objects.create(
                    invoice=invoice,
                    beneficiary=None,
                    main_program=None,
                    sub_program=None,
                    type=FundEntry.Types.GENERAL_DONATION_INCOME,
                    amount=general.amount,
                    description=f"تبرع عام من {general.supporter_name or 'داعم'} - سند {invoice.number}",
                    created_by=request.user,
                    voucher_number= cleaned["number"] ,

                )
                log_activity(
                    user=request.user,
                    action=AuditLog.Actions.CREATE,
                    entity=f"تبرع عام من {general.supporter_name or 'داعم'} - سند {invoice.number}",
                    entity_id=invoice.pk,
                    extra={
                        "invoice_number": invoice.number,
                        "amount": str(general.amount),
                        "supporter": general.supporter_name,
                        "payment_method": invoice.payment_method,
                    },
                )
                return redirect("Accounting:invoice_detail", pk=invoice.pk)
    else:
        form = GeneralDonationInvoiceForm()

    return render(request, "Accounting/invoice_general_form.html", {
        "title": "سند تبرع عام",
        "form": form,
    })



# --------------------------------------------------
# إنشاء سند كفالة مالية
# --------------------------------------------------



@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def invoice_create_sponsorship(request):
    if request.method == "POST":
        form = FinancialSponsorshipInvoiceForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            with transaction.atomic():
                try:
                    invoice = Invoice.objects.create(
                        number=cd["number"],   # ⬅️ يدوي
                        date=cd["date"],
                        invoice_type=Invoice.Types.FINANCIAL_SPONSORSHIP,
                        receipt_kind=Invoice.ReceiptKinds.RECEIPT,
                        payment_method=cd["payment_method"],
                        notes=cd.get("notes") or "",
                        created_by=request.user,
                    )
                except IntegrityError:
                    form.add_error("number", "رقم السند مستخدم مسبقاً.")
                else:
                    sponsorship: FinancialSponsorshipInvoice = form.save(commit=False)
                    sponsorship.invoice = invoice

                    # الخطة الجاهزة → تعبئة تلقائية
                    if not sponsorship.is_custom_plan and sponsorship.payment_plan:
                        plan = sponsorship.payment_plan
                        if getattr(plan, "amount", None) is not None:
                            sponsorship.custom_amount = plan.amount
                        if getattr(plan, "duration_months", None) is not None:
                            sponsorship.custom_duration_months = plan.duration_months

                    sponsorship.save()

                    # حركة دخل لصندوق الجمعية (الكفالة المالية)
                    FundEntry.objects.create(
                        invoice=invoice,
                        type=FundEntry.Types.SPONSORSHIP_INCOME,
                        amount=sponsorship.total_amount,
                        voucher_number=invoice.number,
                        description=f"دخل كفالة مالية من السند رقم {invoice.number}",
                        created_by=request.user,
                    )

                    log_activity(
                        user=request.user,
                        action=AuditLog.Actions.CREATE,
                        entity=f"انشاء سند كفالة مالية رقم {invoice.number}",
                        entity_id=invoice.pk,
                        extra={
                            "invoice_number": invoice.number,
                            "sponsor": str(sponsorship.sponsor),
                            "beneficiaries_count": sponsorship.allocations.count(),
                            "amount": str(sponsorship.total_amount),
                            "payment_method": invoice.payment_method,
                        },
                    )

                 
                    messages.success(request, "تم إنشاء سند الكفالة المالية بنجاح.")
                    return redirect("Accounting:invoice_detail", pk=invoice.pk)
    else:
        form = FinancialSponsorshipInvoiceForm()

    return render(request, "Accounting/invoice_sponsorship_form.html", {
        "title": "إنشاء سند كفالة مالية",
        "form": form,
    })





# --------------------------------------------------
# عرض سند (مع زر طباعة)
# --------------------------------------------------
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "general_donation",
            "financial_sponsorship",
            "financial_sponsorship__sponsor__user",
            "created_by",
        ),
        pk=pk,
    )

    context = {
        "title": f"سند {invoice.number}",
        "invoice": invoice,
    }
    return render(request, "Accounting/invoice_detail.html", context)


###############################################################################################


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsorship_inquiry(request):
    """
    صفحة الاستعلام عن كفالات كافل معيّن
    عن طريق رقم الجوال أو رقم الهوية.
    """
    query = (request.GET.get("q") or "").strip()
    donor = None
    results = []

    if query:
        # نفترض أن عندك في Profile حقول: phone و national_number
        donor_qs = Profile.objects.filter(
            role=Profile.Roles.DONOR
        ).filter(
            Q(national_number__iexact=query) |
            Q(phone__icontains=query)
        ).select_related("user")

        donor = donor_qs.first()

        if donor:
            log_activity(
                user=request.user,
                action=AuditLog.Actions.OTHER,
                entity="بحث عن كافل",
                entity_id=donor.pk,
                extra={
                    "donor": donor.user.get_full_name(),
                },
            )
        today = date.today()

        histories = (
            BeneficiarySponsorHistory.objects
            .filter(donor=donor)
            .select_related("beneficiary")
            .order_by("-start_date")
        )

        for h in histories:

            if h.start_date and h.end_date:
                if today < h.start_date:
                    status = "لم تبدأ بعد"
                elif today > h.end_date:
                    status = "منتهية"
                else:
                    status = "سارية"

            elif h.start_date:
                status = "سارية"

            else:
                status = "غير محددة"

            results.append({

                "beneficiary": h.beneficiary,

                "invoice": None,

                "start_date": h.start_date,

                "end_date": h.end_date,

                "duration_months": None,

                "status": status,

            })
    context = {
        "title": "استعلام عن الكفالات",
        "query": query,
        "donor": donor,
        "results": results,
    }
    return render(request, "Accounting/sponsorship_inquiry.html", context)





########################################################################################################################
#                                                                                                                      #
########################################################################################################################



from Accounting.forms import DonorUserCreateForm   # 👈 استيراد الفورم الجديد

@require_POST
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsor_quick_create(request):
    """
    إنشاء كافل جديد من المودل (بوب-أب) باستخدام DonorUserCreateForm
    ويرجع JSON بالنتيجة.
    """
    form = DonorUserCreateForm(request.POST)
    if not form.is_valid():
        errors = {}
        for field, field_errors in form.errors.items():
            errors[field] = " ".join(field_errors)
        return JsonResponse({"success": False, "errors": errors}, status=400)
    log_activity(
        user=request.user,
        action=AuditLog.Actions.UPDATE,
        entity="Invoice",
        entity_id=user.pk,
        extra={
            "invoice_number": user.number,
        },
    )
    user = form.save()
    profile = user.profile  # لأن عندنا OneToOne user.profile

    label = user.get_full_name() or user.username

    return JsonResponse(
        {
            "success": True,
            "id": profile.id,
            "label": label,
        }
    )



@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsors_list(request):
    """
    صفحة عرض الكفلاء داخل تطبيق المحاسبة (Accounting):
    - يُعرض فقط من لديهم role = DONOR
    - فيها بحث بسيط + ترقيم الصفحات
    """

    query = request.GET.get("q", "").strip()

    sponsors_qs = (
        Profile.objects
        .filter(role=Profile.Roles.DONOR)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )

    if query:
        sponsors_qs = sponsors_qs.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(phone__icontains=query) |
            Q(national_number__icontains=query)
        )

    paginator = Paginator(sponsors_qs, 25)  # ٢٥ كافل في الصفحة
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "title": "الكفلاء",
        "page_obj": page_obj,
        "query": query,
        "total_count": paginator.count,
    }
    return render(request, "Accounting/sponsors_list.html", context)




@require_POST
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsor_quick_update(request, pk):
    """
    تعديل بيانات كافل (User + Profile) من مودال في صفحة الكفلاء.
    """
    profile = get_object_or_404(Profile, pk=pk, role=Profile.Roles.DONOR)
    user = profile.user

    email = (request.POST.get("email") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    first_name = (request.POST.get("first_name") or "").strip()
    father_name = (request.POST.get("father_name") or "").strip()
    grandpa_name = (request.POST.get("grandpa_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    national_number = (request.POST.get("national_number") or "").strip()

    errors = {}

    # تحقق بسيط من الحقول الأساسية
    if not email:
        errors["email"] = "البريد الإلكتروني مطلوب."
    if not first_name:
        errors["first_name"] = "الاسم الأول مطلوب."
    if not last_name:
        errors["last_name"] = "اسم العائلة مطلوب."
    if not phone:
        errors["phone"] = "رقم الجوال مطلوب."
    if not national_number:
        errors["national_number"] = "رقم الهوية مطلوب."

    # تحقق من عدم تكرار البريد
    if email and User.objects.exclude(pk=user.pk).filter(email=email).exists():
        errors["email"] = "هذا البريد مستخدم لحساب آخر."

    # تحقق من عدم تكرار الجوال
    if phone and Profile.objects.exclude(pk=profile.pk).filter(phone=phone).exists():
        errors["phone"] = "هذا الجوال مستخدم لكافل آخر."

    # تحقق من عدم تكرار الهوية
    if national_number and Profile.objects.exclude(pk=profile.pk).filter(national_number=national_number).exists():
        errors["national_number"] = "هذه الهوية مستخدمة لكافل آخر."

    if errors:
        return JsonResponse({"success": False, "errors": errors}, status=400)

    # حفظ التعديلات
    user.email = email
    user.username = user.username or email  # ما نغيّر اليوزرنيم لو كان له قيمة
    user.first_name = first_name
    user.last_name = last_name
    user.save()

    profile.phone = phone
    profile.father_name = father_name
    profile.grandpa_name = grandpa_name
    profile.national_number = national_number
    profile.save()

    return JsonResponse({
        "success": True,
        "id": profile.pk,
        "label": user.get_full_name() or user.email,
        "message": "تم تحديث بيانات الكافل بنجاح."
    })

##############################################################################################################################

# ====== ACCOUNTANT VIEWS (Policy B) ======



# 1) لوحة المحاسب الرئيسية
@role_required([Profile.Roles.ACCOUNTANT])
def accountant_home(request):
    today = timezone.localdate()

    # رصيد الصندوق العام
    fund_balance = FundEntry.total_balance()

    # حركات اليوم
    today_qs = FundEntry.objects.filter(created_at__date=today)
    today_revenue = today_qs.filter(amount__gt=0).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    today_expense = today_qs.filter(amount__lt=0).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # ملخص البرامج الفرعية (مجموع مخصص / مصروف / متبقي)
    sub_agg = SubProgram.objects.aggregate(
        allocated_total=Sum("allocated_amount"),
        spent_total=Sum("spent_amount"),
    )
    allocated_total = sub_agg["allocated_total"] or Decimal("0.00")
    spent_total = sub_agg["spent_total"] or Decimal("0.00")
    remaining_total = allocated_total - spent_total

    # أعداد عامة سريعة
    main_programs_count = MainProgram.objects.count()
    sub_programs_count = SubProgram.objects.count()
    beneficiaries_count = Beneficiary.objects.count()

    # آخر حركات الصندوق
    last_fund_moves = (
        FundEntry.objects
        .select_related("main_program", "sub_program", "beneficiary", "created_by")
        .order_by("-created_at", "-id")[:5]
    )

    # آخر أوامر الصرف من البرامج الفرعية
    last_disbursements = (
        SubProgramDisbursement.objects
        .select_related("sub_program", "sub_program__main_program", "created_by")
        .order_by("-created_at", "-id")[:5]
    )

    context = {
        "title": "لوحة المحاسب",
        "today": today,
        "fund_balance": fund_balance,
        "today_revenue": today_revenue,
        "today_expense": today_expense,
        "allocated_total": allocated_total,
        "spent_total": spent_total,
        "remaining_total": remaining_total,
        "main_programs_count": main_programs_count,
        "sub_programs_count": sub_programs_count,
        "beneficiaries_count": beneficiaries_count,
        "last_fund_moves": last_fund_moves,
        "last_disbursements": last_disbursements,
    }
    return render(request, "Accounting/accountant_home.html", context)

# 2) تخصيص من الصندوق إلى برنامج رئيسي



# @role_required([Profile.Roles.ACCOUNTANT])
# def fund_to_main_allocate(request):
#     programs = MainProgram.objects.order_by("name")

#     # رصيد الصندوق الحالي
#     fund_balance = fund_available_balance()

#     # آخر 5 حركات على الصندوق
#     last_fund_moves = FundEntry.objects.order_by("-created_at", "-id")[:5]

#     if request.method == "POST":
#         main_program_id = request.POST.get("main_program")
#         amount_raw = (request.POST.get("amount") or "0").strip()
#         notes = (request.POST.get("notes") or "").strip()

#         try:
#             amount = Decimal(amount_raw)

#             if amount <= 0:
#                 raise ValidationError("أدخل مبلغ صحيح أكبر من صفر.")

#             # ✅ التحقق الصحيح: التخصيص من الصندوق → لازم لا يتجاوز رصيد الصندوق
#             if amount > (fund_balance or Decimal("0.00")):
#                 raise ValidationError("المبلغ أكبر من رصيد الصندوق العام.")

#             mp = MainProgram.objects.get(id=main_program_id)

#             alloc = FundToMainProgramAllocation(
#                 main_program=mp,
#                 amount=amount,
#                 notes=notes,
#                 created_by=request.user
#             )
#             alloc.save()

#             messages.success(request, "تم تخصيص رصيد للبرنامج الرئيسي بنجاح.")
#             FundReservation.objects.create(
#                 source_type=FundReservation.Sources.MAIN_PROGRAM,
#                 main_program=mp,
#                 amount=amount,
#                 reference=None,
#                 note="حجز ميزانية لبرنامج رئيسي",
#                 created_by=request.user,
#             )

#             return redirect("Accounting:fund_to_main_allocate")

#         except MainProgram.DoesNotExist:
#             messages.error(request, "البرنامج الرئيسي غير موجود.")
#         except (ValidationError, Exception) as e:
#             messages.error(request, getattr(e, "message", str(e)))

#     # إحصائيات البرامج الرئيسية (للعرض)
#     main_stats = (
#         MainProgram.objects
#         .annotate(
#             allocated_sum=Sum("sub_programs__allocated_amount"),
#             spent_sum=Sum("sub_programs__spent_amount"),
#         )
#         .order_by("name")
#     )

#     program_data = []
#     for p in main_stats:
#         program_data.append({
#             "id": p.id,
#             "name": p.name,
#             "total": p.total_donation_amount or Decimal("0.00"),
#             "allocated": p.allocated_sum or Decimal("0.00"),
#             "spent": p.spent_sum or Decimal("0.00"),
#         })

#     return render(request, "Accounting/fund_to_main_allocate.html", {
#         "title": "تخصيص الصندوق للبرنامج الرئيسي",
#         "programs": programs,
#         "fund_balance": fund_balance,
#         "last_fund_moves": last_fund_moves,
#         "program_data": program_data,
#     })
@role_required([Profile.Roles.ACCOUNTANT])
def fund_to_main_allocate(request):
    programs = MainProgram.objects.filter(is_active=True).order_by("name")

    # ✅ المتاح الحقيقي بالصندوق بعد الحجوزات (لا تعتمد على FundEntry فقط)
    fund_balance = FundReservation.available_fund()


    last_fund_moves = FundEntry.objects.order_by("-created_at", "-id")[:5]

    if request.method == "POST":
        main_program_id = request.POST.get("main_program")
        amount_raw = (request.POST.get("amount") or "0").strip()
        notes = (request.POST.get("notes") or "").strip()

        try:
            amount = Decimal(amount_raw)
            if amount <= 0:
                raise ValidationError("أدخل مبلغ صحيح أكبر من صفر.")

            # if amount > (fund_balance or Decimal("0.00")):
            #     raise ValidationError("المبلغ أكبر من المتاح في الصندوق العام بعد الحجوزات.")
            if amount > FundReservation.available_fund():
                raise ValidationError("المبلغ أكبر من رصيد الصندوق العام المتاح (بعد الحجوزات).")

            mp = MainProgram.objects.get(id=main_program_id)

            with transaction.atomic():
                alloc = FundToMainProgramAllocation.objects.create(
                    main_program=mp,
                    amount=amount,
                    notes=notes,
                    created_by=request.user
                )

                # ✅ حجز من الصندوق لصالح الرئيسي
                FundReservation.objects.create(
                    source_type=FundReservation.Sources.MAIN_PROGRAM,
                    main_program=mp,
                    amount=amount,
                    reference=alloc,  # الأفضل ربطها
                    note="حجز ميزانية لبرنامج رئيسي",
                    created_by=request.user,
                )

            messages.success(request, "تم تخصيص رصيد للبرنامج الرئيسي بنجاح.")
            return redirect("Accounting:fund_to_main_allocate")

        except MainProgram.DoesNotExist:
            messages.error(request, "البرنامج الرئيسي غير موجود.")
        except (InvalidOperation, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, str(e))

    main_stats = (
        MainProgram.objects
        .annotate(
            allocated_sum=Sum("sub_programs__allocated_amount"),
            spent_sum=Sum("sub_programs__spent_amount"),
        )
        .order_by("name")
    )

    program_data = []
    for p in main_stats:
        program_data.append({
            "id": p.id,
            "name": p.name,
            "total": p.total_donation_amount or Decimal("0.00"),
            "allocated": p.allocated_sum or Decimal("0.00"),
            "spent": p.spent_sum or Decimal("0.00"),
        })

    return render(request, "Accounting/fund_to_main_allocate.html", {
        "title": "تخصيص الصندوق للبرنامج الرئيسي",
        "programs": programs,
        "fund_balance": fund_balance,
        "last_fund_moves": last_fund_moves,
        "program_data": program_data,
    })
################################################################################


# 3) تحويل من برنامج رئيسي إلى فرعي
# 
@role_required([Profile.Roles.ACCOUNTANT])
def main_to_sub_allocate(request):
    programs = MainProgram.objects.filter(
            is_active=True,
        ).order_by("name")
    #sub_programs = SubProgram.objects.select_related("main_program").order_by("name")
    sub_programs = (
        SubProgram.objects
        .select_related("main_program")
        .filter(
            main_program__is_active=True,
        )
        .order_by("name")
    )
    last_allocs = (
        MainToSubProgramAllocation.objects
        .select_related("main_program", "sub_program")
        .order_by("-created_at", "-id")[:5]
    )

    if request.method == "POST":
        main_program_id = request.POST.get("main_program")
        sub_program_id = request.POST.get("sub_program")
        amount_raw = (request.POST.get("amount") or "0").strip()
        notes = (request.POST.get("notes") or "").strip()

        try:
            amount = Decimal(amount_raw)
            if amount <= 0:
                raise ValidationError("أدخل مبلغ صحيح أكبر من صفر.")

            mp = MainProgram.objects.get(id=main_program_id)
            #sp = SubProgram.objects.get(id=sub_program_id)
            sp = get_object_or_404(
                SubProgram,
                id=sub_program_id,

                main_program__is_active=True,
            )
            # ✅ تأكد الفرعي تابع للرئيسي
            if sp.main_program_id != mp.id:
                raise ValidationError("البرنامج الفرعي لا يتبع البرنامج الرئيسي المختار.")

            # ✅ رصيد الرئيسي المتاح من المحافظ (FundReservation) وليس total_donation_amount
            main_available = (
                FundReservation.objects
                .filter(source_type=FundReservation.Sources.MAIN_PROGRAM, main_program=mp)
                .aggregate(t=Sum("amount"))["t"]
                or Decimal("0.00")
            )

            if amount > main_available:
                raise ValidationError("المبلغ أكبر من المتاح في رصيد البرنامج الرئيسي.")

            with transaction.atomic():
                alloc = MainToSubProgramAllocation.objects.create(
                    main_program=mp,
                    sub_program=sp,
                    amount=amount,
                    notes=notes,
                    created_by=request.user
                )

                # تحرير من الرئيسي
                FundReservation.objects.create(
                    source_type=FundReservation.Sources.MAIN_PROGRAM,
                    main_program=mp,
                    amount=-amount,
                    reference=alloc,
                    note="تحويل إلى برنامج فرعي",
                    created_by=request.user,
                )

                # حجز للفرعي
                FundReservation.objects.create(
                    source_type=FundReservation.Sources.SUB_PROGRAM,
                    sub_program=sp,
                    amount=amount,
                    reference=alloc,
                    note="استلام من برنامج رئيسي",
                    created_by=request.user,
                )

            messages.success(request, "تم تحويل رصيد إلى البرنامج الفرعي بنجاح.")
            return redirect("Accounting:main_to_sub_allocate")

        except (MainProgram.DoesNotExist, SubProgram.DoesNotExist):
            messages.error(request, "تحقق من البرنامج الرئيسي/الفرعي.")
        except (InvalidOperation, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, str(e))

    main_stats = (
        MainProgram.objects
        .annotate(
            allocated_sum=Sum("sub_programs__allocated_amount"),
            spent_sum=Sum("sub_programs__spent_amount"),
        )
        .order_by("name")
    )

    program_data = []
    for p in main_stats:
        total = p.total_donation_amount or Decimal("0.00")
        allocated = p.allocated_sum or Decimal("0.00")
        spent = p.spent_sum or Decimal("0.00")
        available = total - allocated
        program_data.append({
            "id": p.id,
            "name": p.name,
            "total": total,
            "allocated": allocated,
            "spent": spent,
            "available": available if available > 0 else Decimal("0.00"),
        })

    sub_program_data = []
    for sp in sub_programs:
        sub_program_data.append({
            "id": sp.id,
            "name": sp.name,
            "main_id": sp.main_program_id,
            "allocated": sp.allocated_amount or Decimal("0.00"),
            "spent": sp.spent_amount or Decimal("0.00"),
        })

    return render(request, "Accounting/main_to_sub_allocate.html", {
        "title": "تحويل رئيسي → فرعي",
        "programs": programs,
        "sub_programs": sub_programs,
        "program_data": program_data,
        "sub_program_data": sub_program_data,
        "last_allocs": last_allocs,
    })


# 4) أمر صرف من برنامج فرعي لمستفيدين متعددين

# @role_required([Profile.Roles.ACCOUNTANT])
# def subprogram_disburse_create(request):
#     sub_programs = SubProgram.objects.select_related("main_program").order_by("name")

#     # -------- فلترة المستفيدين --------
#     beneficiaries_qs = Beneficiary.objects.order_by("first_name", "last_name")

#     # أسماء الفلاتر حسب المودل الحقيقي
#     education_level = (request.GET.get("education_level") or "").strip()
#     gender          = (request.GET.get("gender") or "").strip()          # ✅ جديد
#     health_status   = (request.GET.get("health_status") or "").strip()
#     type_disease    = (request.GET.get("type_disease") or "").strip()
#     disease_q       = (request.GET.get("disease_q") or "").strip()

#     if gender:  # ✅ جديد
#         beneficiaries_qs = beneficiaries_qs.filter(gender=gender)

#     if education_level:
#         beneficiaries_qs = beneficiaries_qs.filter(education_level=education_level)

#     if health_status:
#         beneficiaries_qs = beneficiaries_qs.filter(health_status=health_status)

#     if type_disease:
#         beneficiaries_qs = beneficiaries_qs.filter(type_disease=type_disease)

#     if disease_q:
#         beneficiaries_qs = beneficiaries_qs.filter(
#             Q(disease__icontains=disease_q) |
#             Q(type_disease__icontains=disease_q)
#         )

#     # قوائم الفلاتر (Choices من المودل)
#     education_levels = Beneficiary.EducationLevel.choices
#     health_statuses  = Beneficiary.HealthStatus.choices
#     disease_types    = Beneficiary.DiseaseType.choices

#     genders = Beneficiary.Gender.choices  # ✅ جديد

#     # -------- آخر أوامر الصرف --------
#     last_disbursements = (
#         SubProgramDisbursement.objects
#         .select_related("sub_program", "sub_program__main_program", "created_by")
#         .prefetch_related("lines", "lines__beneficiary")
#         .order_by("-created_at", "-id")[:5]
#     )


#     # -------- تنفيذ الصرف --------
#     if request.method == "POST":
#         sub_program_id = request.POST.get("sub_program")
#         voucher_number = (request.POST.get("voucher_number") or "").strip()
#         notes = (request.POST.get("notes") or "").strip()
#         beneficiary_ids = request.POST.getlist("beneficiary_ids[]")
#         amounts = request.POST.getlist("amounts[]")

#         try:
#             sp = SubProgram.objects.get(id=sub_program_id)

#             disb = SubProgramDisbursement.objects.create(
#                 sub_program=sp,
#                 voucher_number=voucher_number,
#                 notes=notes,
#                 created_by=request.user
#             )


#             lines = []
#             for bid, amt in zip(beneficiary_ids, amounts):
#                 if not bid:
#                     continue

#                 amt = Decimal(amt or "0")
#                 if amt <= 0:
#                     continue

#                 b = Beneficiary.objects.get(id=bid)
#                 lines.append(SubProgramDisbursementLine(
#                     disbursement=disb,
#                     beneficiary=b,
#                     amount=amt
#                 ))

#             if not lines:
#                 disb.delete()
#                 raise ValidationError("اختر مستفيدًا واحدًا على الأقل مع مبلغ صحيح.")

#             SubProgramDisbursementLine.objects.bulk_create(lines)

#             # تنفيذ الصرف (يفحص الرصيد ويخصم)
#             if not voucher_number:
#                 messages.error(request, "رقم السند مطلوب قبل تنفيذ الصرف.")
#                 return redirect("Accounting:subprogram_disburse_create")

#             disb.execute()

#             messages.success(
#                    request,
#                     f"تم تنفيذ الصرف بنجاح. رقم السند: {disb.voucher_number} — إجمالي الصرف: {disb.total_amount:.2f} ر.س"

#             )
#             return redirect("Accounting:subprogram_disburse_create")

#         except (SubProgram.DoesNotExist, Beneficiary.DoesNotExist):
#             messages.error(request, "تحقق من البرنامج الفرعي/المستفيدين.")
#         except (ValidationError, Exception) as e:
#             messages.error(request, getattr(e, "message", str(e)))

#     # -------- بيانات جاهزة للتمبلت لعرض تفاصيل الفرعي --------
#     sub_program_data = []
#     for sp in sub_programs:
#         allocated = sp.allocated_amount or Decimal("0.00")
#         spent = sp.spent_amount or Decimal("0.00")
#         remaining = allocated - spent
#         sub_program_data.append({
#             "id": sp.id,
#             "name": sp.name,
#             "main_name": sp.main_program.name if sp.main_program else "",
#             "allocated": allocated,
#             "spent": spent,
#             "remaining": remaining if remaining > 0 else Decimal("0.00"),
#         })

#     return render(request, "Accounting/subprogram_disburse_form.html", {
#         "title": "أمر صرف من برنامج فرعي",
#         "sub_programs": sub_programs,
#         "sub_program_data": sub_program_data,
#         "beneficiaries": beneficiaries_qs,

#         # ✅ الفلاتر الصحيحة
#         "education_levels": education_levels,
#         "health_statuses": health_statuses,
#         "disease_types": disease_types,
#         "genders": genders,

#        "filters": {
#             "education_level": education_level,
#             "gender": gender,                # ✅ جديد
#             "health_status": health_status,
#             "type_disease": type_disease,
#             "disease_q": disease_q,
#         },


#         "last_disbursements": last_disbursements,
#         "fund_balance": FundEntry.total_balance(),  # مرجعي للعرض
#     })


@role_required([Profile.Roles.ACCOUNTANT])
def subprogram_disburse_create(request):
    #sub_programs = SubProgram.objects.filter(main_program__is_active=True).select_related("main_program").order_by("name")
    sub_programs = (
            SubProgram.objects
            .filter(main_program__is_active=True)
            .select_related("main_program")
            .order_by("name")
        )
    # -------- فلترة المستفيدين + رصيد كل مستفيد --------
    beneficiaries_qs = (
        Beneficiary.objects
        .annotate(
            balance_total=Coalesce(
                Sum("balance_entries__amount"),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("first_name", "last_name")
    )

    education_level = (request.GET.get("education_level") or "").strip()
    gender          = (request.GET.get("gender") or "").strip()
    health_status   = (request.GET.get("health_status") or "").strip()
    type_disease    = (request.GET.get("type_disease") or "").strip()
    disease_q       = (request.GET.get("disease_q") or "").strip()

    if gender:
        beneficiaries_qs = beneficiaries_qs.filter(gender=gender)

    if education_level:
        beneficiaries_qs = beneficiaries_qs.filter(education_level=education_level)

    if health_status:
        beneficiaries_qs = beneficiaries_qs.filter(health_status=health_status)

    if type_disease:
        beneficiaries_qs = beneficiaries_qs.filter(type_disease=type_disease)

    if disease_q:
        beneficiaries_qs = beneficiaries_qs.filter(
            Q(disease__icontains=disease_q) |
            Q(type_disease__icontains=disease_q)
        )

    education_levels = Beneficiary.EducationLevel.choices
    health_statuses  = Beneficiary.HealthStatus.choices
    disease_types    = Beneficiary.DiseaseType.choices
    genders          = Beneficiary.Gender.choices

    # -------- آخر أوامر الصرف --------
    last_disbursements = (
        SubProgramDisbursement.objects
        .select_related("sub_program", "sub_program__main_program", "created_by")
        .prefetch_related("lines", "lines__beneficiary")
        .order_by("-created_at", "-id")[:5]
    )

    # -------- تنفيذ الصرف --------
    if request.method == "POST":
        sub_program_id = request.POST.get("sub_program")
        voucher_number = (request.POST.get("voucher_number") or "").strip()
        source_type    = (request.POST.get("source_type") or "sub_program").strip()
        notes          = (request.POST.get("notes") or "").strip()

        beneficiary_ids = request.POST.getlist("beneficiary_ids[]")
        amounts         = request.POST.getlist("amounts[]")

        try:
            sp = SubProgram.objects.get(id=sub_program_id)

            disb = SubProgramDisbursement.objects.create(
                sub_program=sp,
                voucher_number=voucher_number,
                source_type=source_type,
                notes=notes,
                created_by=request.user,
            )

            lines = []
            for bid, amt in zip(beneficiary_ids, amounts):
                if not bid:
                    continue
                amt = Decimal(amt or "0")
                if amt <= 0:
                    continue

                b = Beneficiary.objects.get(id=bid)
                lines.append(SubProgramDisbursementLine(
                    disbursement=disb,
                    beneficiary=b,
                    amount=amt
                ))

            if not lines:
                disb.delete()
                raise ValidationError("اختر مستفيدًا واحدًا على الأقل مع مبلغ صحيح.")

            # الصرف من رصيد المستفيد: مسموح لمستفيد واحد فقط
            if source_type == SubProgramDisbursement.SourceTypes.BENEFICIARY and len(lines) != 1:
                disb.delete()
                raise ValidationError("الصرف من رصيد المستفيد متاح لمستفيد واحد فقط في الأمر.")

            SubProgramDisbursementLine.objects.bulk_create(lines)

            if not voucher_number:
                messages.error(request, "رقم السند مطلوب قبل تنفيذ الصرف.")
                return redirect("Accounting:subprogram_disburse_create")

            disb.execute()

            messages.success(
                request,
                f"تم تنفيذ الصرف بنجاح. رقم السند: {disb.voucher_number} — إجمالي الصرف: {disb.total_amount:.2f} ر.س"
            )
            return redirect("Accounting:subprogram_disburse_create")

        except (SubProgram.DoesNotExist, Beneficiary.DoesNotExist):
            messages.error(request, "تحقق من البرنامج الفرعي/المستفيدين.")
        except (ValidationError, Exception) as e:
            messages.error(request, getattr(e, "message", str(e)))

    # -------- بيانات البرامج الفرعية للعرض في الكرت --------
    sub_program_data = []
    for sp in sub_programs:
        allocated = sp.allocated_amount or Decimal("0.00")
        spent     = sp.spent_amount or Decimal("0.00")
        remaining = allocated - spent
        sub_program_data.append({
            "id": sp.id,
            "name": sp.name,
            "main_name": sp.main_program.name if sp.main_program else "",
            "allocated": allocated,
            "spent": spent,
            "remaining": remaining if remaining > 0 else Decimal("0.00"),
        })

    return render(request, "Accounting/subprogram_disburse_form.html", {
        "title": "أمر صرف من برنامج فرعي",
        "sub_programs": sub_programs,
        "sub_program_data": sub_program_data,
        "beneficiaries": beneficiaries_qs,

        "education_levels": education_levels,
        "health_statuses": health_statuses,
        "disease_types": disease_types,
        "genders": genders,

        "filters": {
            "education_level": education_level,
            "gender": gender,
            "health_status": health_status,
            "type_disease": type_disease,
            "disease_q": disease_q,
        },

        "last_disbursements": last_disbursements,
        "fund_balance": FundEntry.total_balance(),  # مرجعي للعرض فقط
    })


from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from openpyxl import Workbook

from Management.models import Profile
from .models import FundEntry


from decimal import Decimal, InvalidOperation
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook

# @role_required([Profile.Roles.ACCOUNTANT])
# def ledger(request):
#     base_qs = (
#         FundEntry.objects
#         .select_related("invoice", "created_by")
#         .order_by("-created_at", "-id")
#     )

#     # Filters
#     type_filter = (request.GET.get("type") or "").strip()
#     date_from = (request.GET.get("date_from") or "").strip()
#     date_to = (request.GET.get("date_to") or "").strip()
#     q = (request.GET.get("q") or "").strip()
#     export = (request.GET.get("export") or "").strip()

#     movements = base_qs

#     # نوع الحركة
#     if type_filter:
#         if type_filter == "revenue":
#             movements = movements.filter(amount__gt=0)
#         elif type_filter == "expense":
#             movements = movements.filter(amount__lt=0)
#         else:
#             movements = movements.filter(type=type_filter)

#     # فلترة التاريخ
#     if date_from:
#         movements = movements.filter(created_at__date__gte=date_from)
#     if date_to:
#         movements = movements.filter(created_at__date__lte=date_to)

#     # بحث عام: (وصف + رقم سند voucher + رقم فاتورة invoice + مبلغ)
#     if q:
#         q_obj = (
#             Q(description__icontains=q) |
#             Q(voucher_number__icontains=q) |
#             Q(invoice__number__icontains=q)
#         )
#         try:
#             q_num = Decimal(q)
#             q_obj |= Q(amount=q_num)
#         except (InvalidOperation, TypeError):
#             pass

#         movements = movements.filter(q_obj)

#     # opening balance قبل أول حركة ضمن النتائج
#     first = movements.order_by("created_at", "id").values("created_at", "id").first()
#     opening = Decimal("0.00")
#     if first:
#         dt0 = first["created_at"]
#         id0 = first["id"]
#         opening = (
#             FundEntry.objects
#             .filter(Q(created_at__lt=dt0) | Q(created_at=dt0, id__lt=id0))
#             .aggregate(t=Sum("amount"))["t"]
#             or Decimal("0.00")
#         )

#     # تجهيز العرض
#     asc = list(movements.order_by("created_at", "id"))
#     running = opening

#     for m in asc:
#         # رقم السند: voucher أولاً ثم invoice.number
#         voucher = (m.voucher_number or "").strip()
#         if not voucher and m.invoice and getattr(m.invoice, "number", None):
#             voucher = str(m.invoice.number).strip()
#         m.display_voucher = voucher or "—"

#         # مصدر التغطية (عرض فقط) بدون تغيير الوصف الحقيقي
#         desc = (m.description or "")
#         if "(مصدر: ميزانية الفرعي)" in desc:
#             m.cover_source = "محفظة برنامج فرعي"
#         elif "(مصدر: محفظة المستفيد)" in desc or "محفظة المستفيد" in desc:
#             m.cover_source = "محفظة مستفيد"
#         else:
#             m.cover_source = "صندوق عام"

#         # الرصيد بعد الحركة
#         running += (m.amount or Decimal("0.00"))
#         m.balance_after = running

#     rows = list(reversed(asc))  # الأحدث أولاً

#     # Export Excel
#     if export == "1":
#         wb = Workbook()
#         ws = wb.active
#         ws.title = "Ledger"
#         ws.append(["رقم السند", "التاريخ", "مصدر التغطية", "نوع الحركة", "الوصف", "المبلغ", "الرصيد بعد الحركة"])

#         for m in rows:
#             ws.append([
#                 m.display_voucher,
#                 timezone.localtime(m.created_at).strftime("%Y-%m-%d"),  # ✅ بدون وقت
#                 getattr(m, "cover_source", "") or "",
#                 (m.get_type_display() if hasattr(m, "get_type_display") else (m.type or "")),
#                 (m.description or "").strip() or "—",  # ✅ الوصف الحقيقي
#                 float(m.amount or 0),
#                 float(m.balance_after or 0),
#             ])

#         resp = HttpResponse(
#             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#         )
#         resp["Content-Disposition"] = 'attachment; filename="ledger.xlsx"'
#         wb.save(resp)
#         return resp

#     return render(request, "Accounting/ledger.html", {
#         "title": "سجل الحركات المالية",
#         "movements": rows,
#         "filters": {"type": type_filter, "date_from": date_from, "date_to": date_to, "q": q},
#     })
@role_required([Profile.Roles.ACCOUNTANT])
def ledger(request):
    base_qs = (
        FundEntry.objects
        .select_related("invoice", "created_by")
        .order_by("-created_at", "-id")
    )

    type_filter = (request.GET.get("type") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    q = (request.GET.get("q") or "").strip()
    export = (request.GET.get("export") or "").strip()

    movements = base_qs

    if type_filter:
        if type_filter == "revenue":
            movements = movements.filter(amount__gt=0)
        elif type_filter == "expense":
            movements = movements.filter(amount__lt=0)
        else:
            movements = movements.filter(type=type_filter)

    if date_from:
        movements = movements.filter(created_at__date__gte=date_from)
    if date_to:
        movements = movements.filter(created_at__date__lte=date_to)

    if q:
        q_obj = (
            Q(description__icontains=q) |
            Q(voucher_number__icontains=q) |
            Q(invoice__number__icontains=q) |
            Q(invoice__notes__icontains=q)
        )
        try:
            q_num = Decimal(q)
            q_obj |= Q(amount=q_num)
        except (InvalidOperation, TypeError):
            pass

        movements = movements.filter(q_obj)

    first = movements.order_by("created_at", "id").values("created_at", "id").first()
    opening = Decimal("0.00")

    if first:
        dt0 = first["created_at"]
        id0 = first["id"]
        opening = (
            FundEntry.objects
            .filter(Q(created_at__lt=dt0) | Q(created_at=dt0, id__lt=id0))
            .aggregate(t=Sum("amount"))["t"]
            or Decimal("0.00")
        )

    asc = list(movements.order_by("created_at", "id"))
    running = opening

    for m in asc:
        voucher = (m.voucher_number or "").strip()
        if not voucher and m.invoice and getattr(m.invoice, "number", None):
            voucher = str(m.invoice.number).strip()
        m.display_voucher = voucher or "—"

        m.display_notes = (
            m.invoice.notes.strip()
            if m.invoice and getattr(m.invoice, "notes", None) and m.invoice.notes.strip()
            else "—"
        )

        desc = (m.description or "")
        if "(مصدر: ميزانية الفرعي)" in desc:
            m.cover_source = "محفظة برنامج فرعي"
        elif "(مصدر: محفظة المستفيد)" in desc or "محفظة المستفيد" in desc:
            m.cover_source = "محفظة مستفيد"
        else:
            m.cover_source = "صندوق عام"

        running += (m.amount or Decimal("0.00"))
        m.balance_after = running

    rows = list(reversed(asc))

    if export == "1":
        wb = Workbook()
        ws = wb.active
        ws.title = "Ledger"

        ws.append([
            "رقم السند",
            "التاريخ",
            "مصدر التغطية",
            "نوع الحركة",
            "الوصف",
            "الملاحظات",
            "المبلغ",
            "الرصيد بعد الحركة",
        ])

        for m in rows:
            ws.append([
                m.display_voucher,
                timezone.localtime(m.created_at).strftime("%Y-%m-%d"),
                getattr(m, "cover_source", "") or "",
                (m.get_type_display() if hasattr(m, "get_type_display") else (m.type or "")),
                (m.description or "").strip() or "—",
                getattr(m, "display_notes", "—"),
                float(m.amount or 0),
                float(m.balance_after or 0),
            ])

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp["Content-Disposition"] = 'attachment; filename="ledger.xlsx"'
        wb.save(resp)
        return resp

    return render(request, "Accounting/ledger.html", {
        "title": "سجل الحركات المالية",
        "movements": rows,
        "filters": {
            "type": type_filter,
            "date_from": date_from,
            "date_to": date_to,
            "q": q,
        },
    })

# 6) صفحة أرصدة البرامج للمحاسب (Program Balances)
@role_required([Profile.Roles.ACCOUNTANT])
def program_balances(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    main_program_id = request.GET.get("main_program", "").strip()

    dec12 = DecimalField(max_digits=12, decimal_places=2)
    dec7  = DecimalField(max_digits=7, decimal_places=2)

    qs = (
        MainProgram.objects
        .annotate(
            allocated_sum=Coalesce(Sum("sub_programs__allocated_amount"),
                                   Value(0, output_field=dec12), output_field=dec12),
            spent_sum=Coalesce(Sum("sub_programs__spent_amount"),
                               Value(0, output_field=dec12), output_field=dec12),
            total=Coalesce(F("total_donation_amount"),
                           Value(0, output_field=dec12), output_field=dec12),
        )
    )

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    if main_program_id:
        qs = qs.filter(id=main_program_id)

    qs = qs.annotate(
        remaining=ExpressionWrapper(F("total") - F("spent_sum"), output_field=dec12),
        pct=Case(
            When(total__gt=Value(0, output_field=dec12),
                 then=ExpressionWrapper(
                     (F("spent_sum") * Value(100, output_field=dec7)) / F("total"),
                     output_field=dec7
                 )),
            default=Value(0, output_field=dec7),
            output_field=dec7
        )
    )

    if status == "healthy":
        qs = qs.filter(pct__lt=Value(80, output_field=dec7))
    elif status == "warning":
        qs = qs.filter(pct__gte=Value(80, output_field=dec7),
                       pct__lt=Value(95, output_field=dec7))
    elif status == "critical":
        qs = qs.filter(pct__gte=Value(95, output_field=dec7),
                       pct__lt=Value(99.5, output_field=dec7))
    elif status == "exhausted":
        qs = qs.filter(pct__gte=Value(99.5, output_field=dec7))

    programs = []
    for p in qs.order_by("-created_at"):
        subs = []
        for sp in p.sub_programs.all().order_by("id"):
            allocated = sp.allocated_amount or Decimal("0.00")
            spent = sp.spent_amount or Decimal("0.00")
            rem = allocated - spent
            pct_sp = (spent * 100 / allocated) if allocated else Decimal("0.00")
            sp.remaining = rem
            sp.pct = pct_sp
            subs.append(sp)

        p.sub_programs_list = subs
        programs.append(p)

    summary = {
        "main_count": qs.count(),
        "sub_count": SubProgram.objects.filter(main_program__in=qs).count(),
        "total_main": qs.aggregate(t=Sum("total"))["t"] or Decimal("0.00"),
        "total_remaining": qs.aggregate(t=Sum("remaining"))["t"] or Decimal("0.00"),
    }

    main_programs = MainProgram.objects.order_by("name")

    return render(request, "Accounting/program_balances.html", {
        "title": "أرصدة البرامج",
        "programs": programs,
        "main_programs": main_programs,
        "summary": summary,
    })

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Q, Value, DecimalField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from Management.models import Beneficiary, MainProgram, SubProgram
from .models import FundEntry, FundReservation, BeneficiaryBalanceEntry
def _redirect_same(request):
    return redirect(request.path)


@role_required([Profile.Roles.ACCOUNTANT])
def fund_reservations_dashboard(request):
    """
    FundReservation Dashboard
    - يعرض: الصندوق + المحجوزات + المتاح
    - يعرض محافظ: مستفيد / رئيسي / فرعي
    - تحرير حجوزات:
        * تحرير جزئي/كامل للمستفيد/الفرعي/الرئيسي
        * منع تحرير الرئيسي إذا كان عليه فروع محجوزة أو فروع عليها صرف
    """

    # =========================
    # Helpers
    # =========================
    def d0(v):
        return v if v is not None else Decimal("0.00")

    def net_reserved_for(source_type, *, beneficiary_id=None, main_program_id=None, sub_program_id=None):
        qs = FundReservation.objects.filter(source_type=source_type)
        if beneficiary_id:
            qs = qs.filter(beneficiary_id=beneficiary_id)
        if main_program_id:
            qs = qs.filter(main_program_id=main_program_id)
        if sub_program_id:
            qs = qs.filter(sub_program_id=sub_program_id)

        return qs.aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

    def create_release_row(source_type, amount, *, beneficiary=None, main_program=None, sub_program=None, reference="", note=""):
        """
        amount (موجب) => ننشئ سطر تحرير بالسالب
        """
        if amount <= 0:
            return

        FundReservation.objects.create(
            source_type=source_type,
            beneficiary=beneficiary,
            main_program=main_program,
            sub_program=sub_program,
            amount=-amount,
            reference=reference or "",
            note=note or "تحرير حجز",
            created_by=request.user,
        )

    def parse_amount(raw: str) -> Decimal:
        try:
            v = Decimal((raw or "").strip())
            return v
        except (InvalidOperation, TypeError):
            return Decimal("0.00")

    # =========================
    # POST Actions (release)
    # =========================
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        source_type = (request.POST.get("source_type") or "").strip()
        obj_id = (request.POST.get("obj_id") or "").strip()

        # -------------------------
        # تحرير جزئي من تبويب المحافظ
        # -------------------------
        if action == "release_partial_wallet":
            amount = parse_amount(request.POST.get("amount"))
            if amount <= 0:
                messages.error(request, "أدخل مبلغ تحرير صحيح أكبر من صفر.")
                return _redirect_same(request)

            with transaction.atomic():
                # ---- Beneficiary ----
                if source_type == "beneficiary":
                    b = get_object_or_404(Beneficiary, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id))

                    if current <= 0:
                        messages.info(request, "لا يوجد حجز لتحريره.")
                        return _redirect_same(request)

                    release = min(amount, current)
                    create_release_row(
                        FundReservation.Sources.BENEFICIARY, release,
                        beneficiary=b,
                        reference=f"REL-BEN-{b.id}",
                        note="تحرير جزئي (محفظة المستفيد)"
                    )
                    messages.success(request, f"تم تحرير {release} ر.س من حجز المستفيد.")
                    return _redirect_same(request)

                # ---- Sub Program ----
                if source_type == "sub_program":
                    sp = get_object_or_404(SubProgram, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id))

                    if current <= 0:
                        messages.info(request, "لا يوجد حجز لتحريره.")
                        return _redirect_same(request)

                    if d0(sp.spent_amount) > 0:
                        messages.error(request, "لا يمكن تحرير حجز البرنامج الفرعي لأن عليه مصروفات.")
                        return _redirect_same(request)

                    release = min(amount, current)

                    create_release_row(
                        FundReservation.Sources.SUB_PROGRAM, release,
                        sub_program=sp,
                        reference=f"REL-SUB-{sp.id}",
                        note="تحرير جزئي (محفظة الفرعي)"
                    )

                    sp.allocated_amount = max(d0(sp.allocated_amount) - release, Decimal("0.00"))
                    sp.save(update_fields=["allocated_amount"])

                    messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الفرعي.")
                    return _redirect_same(request)

                # ---- Main Program ----
                # ---- Main Program ----
                if source_type == "main_program":
                    mp = get_object_or_404(MainProgram, id=obj_id)

                    # ❌ ممنوع تحرير الرئيسي إذا فيه أي فرعي عليه صرف أو حجز
                    subs_qs = SubProgram.objects.filter(main_program=mp)
                    if subs_qs.exists():
                        if subs_qs.filter(spent_amount__gt=0).exists():
                            messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
                            return _redirect_same(request)

                        sub_reserved_total = FundReservation.objects.filter(
                            source_type=FundReservation.Sources.SUB_PROGRAM,
                            sub_program__main_program=mp,
                        ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

                        if d0(sub_reserved_total) > 0:
                            messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
                            return _redirect_same(request)

                    # ✅ نحرر من ميزانية الرئيسي نفسها
                    budget_current = d0(mp.total_donation_amount)
                    if budget_current <= 0:
                        messages.info(request, "ميزانية البرنامج الرئيسي بالفعل 0.")
                        return _redirect_same(request)

                    release_budget = min(amount, budget_current)

                    # ✅ تحرير FundReservation فقط إذا كان فيه حجز فعلي
                    main_current = d0(net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id))
                    if main_current > 0:
                        create_release_row(
                            FundReservation.Sources.MAIN_PROGRAM, min(release_budget, main_current),
                            main_program=mp,
                            reference=f"REL-MAIN-{mp.id}",
                            note="تحرير جزئي (محفظة الرئيسي)"
                        )

                    # ✅ الأهم: تخفيض ميزانية الرئيسي فعليًا
                    mp.total_donation_amount = max(budget_current - release_budget, Decimal("0.00"))
                    mp.save(update_fields=["total_donation_amount"])

                    messages.success(request, f"تم تحرير {release_budget} ر.س من ميزانية البرنامج الرئيسي.")
                    return _redirect_same(request)


            messages.error(request, "نوع غير معروف.")
            return _redirect_same(request)

        # -------------------------
        # تحرير كامل من تبويب المحافظ
        # -------------------------
        if action == "release_all":
            with transaction.atomic():
                # ---- Beneficiary ----
                if source_type == "beneficiary":
                    b = get_object_or_404(Beneficiary, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id))
                    if current <= 0:
                        messages.info(request, "لا يوجد حجز لتحريره.")
                        return _redirect_same(request)

                    create_release_row(
                        FundReservation.Sources.BENEFICIARY, current,
                        beneficiary=b,
                        reference=f"REL-BEN-{b.id}",
                        note="تحرير كامل (محفظة المستفيد)"
                    )
                    messages.success(request, f"تم تحرير كامل حجز المستفيد ({current} ر.س).")
                    return _redirect_same(request)

                # ---- Sub Program ----
                if source_type == "sub_program":
                    sp = get_object_or_404(SubProgram, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id))
                    if current <= 0:
                        messages.info(request, "لا يوجد حجز لتحريره.")
                        return _redirect_same(request)

                    if d0(sp.spent_amount) > 0:
                        messages.error(request, "لا يمكن تحرير حجز الفرعي لأنه عليه مصروفات.")
                        return _redirect_same(request)

                    create_release_row(
                        FundReservation.Sources.SUB_PROGRAM, current,
                        sub_program=sp,
                        reference=f"REL-SUB-{sp.id}",
                        note="تحرير كامل (محفظة الفرعي)"
                    )

                    sp.allocated_amount = max(d0(sp.allocated_amount) - current, Decimal("0.00"))
                    sp.save(update_fields=["allocated_amount"])

                    messages.success(request, f"تم تحرير كامل حجز الفرعي ({current} ر.س).")
                    return _redirect_same(request)

                # ---- Main Program ----
                if source_type == "main_program":
                    mp = get_object_or_404(MainProgram, id=obj_id)
                    subs_qs = SubProgram.objects.filter(main_program=mp)

                    if subs_qs.filter(spent_amount__gt=0).exists():
                        messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
                        return _redirect_same(request)

                    sub_reserved_total = FundReservation.objects.filter(
                        source_type=FundReservation.Sources.SUB_PROGRAM,
                        sub_program__main_program=mp,
                    ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

                    if d0(sub_reserved_total) > 0:
                        messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
                        return _redirect_same(request)

                    main_current = d0(net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id))
                    budget_current = d0(mp.total_donation_amount)

                    if budget_current <= 0:
                        messages.info(request, "ميزانية البرنامج الرئيسي بالفعل 0.")
                        return _redirect_same(request)

                    # ✅ تحرير كامل = تصفير الميزانية
                    release_budget = budget_current

                    # تحرير FundReservation فقط إذا عليه حجز
                    if main_current > 0:
                        create_release_row(
                            FundReservation.Sources.MAIN_PROGRAM, min(main_current, release_budget),
                            main_program=mp,
                            reference=f"REL-MAIN-{mp.id}",
                            note="تحرير كامل (محفظة الرئيسي)"
                        )

                    mp.total_donation_amount = Decimal("0.00")
                    mp.save(update_fields=["total_donation_amount"])

                    messages.success(request, f"تم تحرير كامل ميزانية البرنامج الرئيسي ({release_budget} ر.س).")
                    return _redirect_same(request)

            messages.error(request, "نوع غير معروف.")
            return _redirect_same(request)

        # -------------------------
        # تحرير من سجل الحجوزات
        # -------------------------
        if action == "release_amount":
            amount = parse_amount(request.POST.get("amount"))
            reference = (request.POST.get("reference") or "").strip()

            if amount <= 0:
                messages.error(request, "مبلغ التحرير غير صحيح.")
                return _redirect_same(request)

            with transaction.atomic():
                if source_type == FundReservation.Sources.BENEFICIARY:
                    b = get_object_or_404(Beneficiary, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id))
                    release = min(amount, max(current, Decimal("0.00")))
                    create_release_row(
                        FundReservation.Sources.BENEFICIARY, release,
                        beneficiary=b,
                        reference=reference or f"REL-BEN-{b.id}",
                        note="تحرير جزئي (سجل الحجوزات)"
                    )
                    messages.success(request, f"تم تحرير {release} ر.س من حجز المستفيد.")
                    return _redirect_same(request)

                if source_type == FundReservation.Sources.SUB_PROGRAM:
                    sp = get_object_or_404(SubProgram, id=obj_id)
                    current = d0(net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id))
                    release = min(amount, max(current, Decimal("0.00")))

                    if d0(sp.spent_amount) > 0:
                        messages.error(request, "لا يمكن تحرير حجز البرنامج الفرعي لأن عليه مصروفات.")
                        return _redirect_same(request)

                    create_release_row(
                        FundReservation.Sources.SUB_PROGRAM, release,
                        sub_program=sp,
                        reference=reference or f"REL-SUB-{sp.id}",
                        note="تحرير جزئي (سجل الحجوزات)"
                    )

                    sp.allocated_amount = max(d0(sp.allocated_amount) - release, Decimal("0.00"))
                    sp.save(update_fields=["allocated_amount"])

                    messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الفرعي.")
                    return _redirect_same(request)

                if source_type == FundReservation.Sources.MAIN_PROGRAM:
                    mp = get_object_or_404(MainProgram, id=obj_id)
                    subs_qs = SubProgram.objects.filter(main_program=mp)

                    if subs_qs.filter(spent_amount__gt=0).exists():
                        messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
                        return _redirect_same(request)

                    sub_reserved_total = FundReservation.objects.filter(
                        source_type=FundReservation.Sources.SUB_PROGRAM,
                        sub_program__main_program=mp,
                    ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

                    if d0(sub_reserved_total) > 0:
                        messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
                        return _redirect_same(request)

                    budget_current = d0(mp.total_donation_amount)
                    if budget_current <= 0:
                        messages.info(request, "ميزانية البرنامج الرئيسي بالفعل 0.")
                        return _redirect_same(request)

                    release_budget = min(amount, budget_current)

                    # تحرير FundReservation فقط إذا عليه حجز فعلي
                    main_current = d0(net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id))
                    if main_current > 0:
                        create_release_row(
                            FundReservation.Sources.MAIN_PROGRAM, min(release_budget, main_current),
                            main_program=mp,
                            reference=reference or f"REL-MAIN-{mp.id}",
                            note="تحرير جزئي (سجل الحجوزات)"
                        )

                    mp.total_donation_amount = max(budget_current - release_budget, Decimal("0.00"))
                    mp.save(update_fields=["total_donation_amount"])

                    messages.success(request, f"تم تحرير {release_budget} ر.س من ميزانية البرنامج الرئيسي.")
                    return _redirect_same(request)


            messages.error(request, "نوع الحجز غير معروف.")
            return _redirect_same(request)

    # =========================
    # Summary
    # =========================
    fund_total = FundEntry.objects.aggregate(
        t=Coalesce(Sum("amount"), Value(Decimal("0.00")))
    )["t"]

    reserved_total = FundReservation.objects.aggregate(
        t=Coalesce(Sum("amount"), Value(Decimal("0.00")))
    )["t"]

    available_fund = FundReservation.available_fund()

    # =========================
    # Wallet tables (بدون تضخيم JOIN)
    # =========================

    # --- Beneficiaries ---
    bene_wallet_sq = (
        BeneficiaryBalanceEntry.objects
        .filter(beneficiary_id=OuterRef("pk"))
        .values("beneficiary_id")
        .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    bene_reserved_sq = (
        FundReservation.objects
        .filter(source_type=FundReservation.Sources.BENEFICIARY, beneficiary_id=OuterRef("pk"))
        .values("beneficiary_id")
        .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    beneficiaries = (
        Beneficiary.objects
        .annotate(
            wallet_balance=Coalesce(
                Subquery(bene_wallet_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
            reserved_from_fund=Coalesce(
                Subquery(bene_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
        )
        .order_by("first_name", "last_name")
    )

    beneficiaries_wallets = [
        b for b in beneficiaries
        if (d0(b.wallet_balance) != 0 or d0(b.reserved_from_fund) != 0)
    ]

    # --- Main Programs ---
    main_reserved_sq = (
        FundReservation.objects
        .filter(source_type=FundReservation.Sources.MAIN_PROGRAM, main_program_id=OuterRef("pk"))
        .values("main_program_id")
        .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    main_allocated_sq = (
        SubProgram.objects
        .filter(main_program_id=OuterRef("pk"))
        .values("main_program_id")
        .annotate(t=Coalesce(Sum("allocated_amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    main_has_sub_reserved_sq = (
        FundReservation.objects
        .filter(
            source_type=FundReservation.Sources.SUB_PROGRAM,
            sub_program__main_program_id=OuterRef("pk"),
        )
        .values("sub_program__main_program_id")
        .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    main_has_sub_spent_sq = (
        SubProgram.objects
        .filter(main_program_id=OuterRef("pk"))
        .values("main_program_id")
        .annotate(t=Coalesce(Sum("spent_amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    main_programs = (
        MainProgram.objects
        .annotate(
            allocated_sum=Coalesce(
                Subquery(main_allocated_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
            reserved_from_fund=Coalesce(
                Subquery(main_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
            sub_reserved_total=Coalesce(
                Subquery(main_has_sub_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
            sub_spent_total=Coalesce(
                Subquery(main_has_sub_spent_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            ),
        )
        .order_by("name")
    )
    main_program_wallets = list(main_programs)

    # --- Sub Programs ---
    sub_reserved_sq = (
        FundReservation.objects
        .filter(source_type=FundReservation.Sources.SUB_PROGRAM, sub_program_id=OuterRef("pk"))
        .values("sub_program_id")
        .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
        .values("t")[:1]
    )

    sub_programs = (
        SubProgram.objects
        .select_related("main_program")
        .annotate(
            reserved_from_fund=Coalesce(
                Subquery(sub_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Value(Decimal("0.00"))
            )
        )
        .order_by("name")
    )

    sub_program_wallets = [
        sp for sp in sub_programs
        if (d0(sp.allocated_amount) != 0 or d0(sp.spent_amount) != 0 or d0(sp.reserved_from_fund) != 0)
    ]

    # =========================
    # Reservations log filters
    # =========================
    filters = {
        "source_type": (request.GET.get("source_type") or "").strip(),
        "date_from": (request.GET.get("date_from") or "").strip(),
        "date_to": (request.GET.get("date_to") or "").strip(),
        "q": (request.GET.get("q") or "").strip(),
    }

    reservations = FundReservation.objects.select_related("beneficiary", "main_program", "sub_program").all()

    if filters["source_type"]:
        reservations = reservations.filter(source_type=filters["source_type"])

    if filters["date_from"]:
        reservations = reservations.filter(created_at__date__gte=filters["date_from"])
    if filters["date_to"]:
        reservations = reservations.filter(created_at__date__lte=filters["date_to"])

    if filters["q"]:
        q = filters["q"]
        reservations = reservations.filter(
            Q(reference__icontains=q) |
            Q(note__icontains=q) |
            Q(beneficiary__first_name__icontains=q) |
            Q(beneficiary__last_name__icontains=q) |
            Q(main_program__name__icontains=q) |
            Q(sub_program__name__icontains=q)
        )

    reservations = reservations.order_by("-created_at", "-id")[:500]

    return render(request, "Accounting/fund_reservations_dashboard.html", {
        "fund_total": fund_total,
        "reserved_total": reserved_total,
        "available_fund": available_fund,

        "beneficiaries_wallets": beneficiaries_wallets,
        "main_program_wallets": main_program_wallets,
        "sub_program_wallets": sub_program_wallets,

        "reservations": reservations,
        "filters": filters,
    })


# def _redirect_same(request):
#     return redirect(request.path)


# @role_required([Profile.Roles.ACCOUNTANT])
# def fund_reservations_dashboard(request):
#     """
#     FundReservation Dashboard
#     - يعرض: الصندوق + المحجوزات + المتاح
#     - يعرض محافظ: مستفيد / رئيسي / فرعي
#     - تحرير حجوزات:
#         * تحرير جزئي/كامل للمستفيد/الفرعي/الرئيسي
#         * منع تحرير الرئيسي إذا كان عليه فروع محجوزة أو فروع عليها صرف
#     """

#     # =========================
#     # Helpers
#     # =========================
#     def d0(v):
#         return v if v is not None else Decimal("0.00")

#     def net_reserved_for(source_type, *, beneficiary_id=None, main_program_id=None, sub_program_id=None):
#         qs = FundReservation.objects.filter(source_type=source_type)
#         if beneficiary_id:
#             qs = qs.filter(beneficiary_id=beneficiary_id)
#         if main_program_id:
#             qs = qs.filter(main_program_id=main_program_id)
#         if sub_program_id:
#             qs = qs.filter(sub_program_id=sub_program_id)

#         return qs.aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

#     def create_release_row(source_type, amount, *, beneficiary=None, main_program=None, sub_program=None, reference="", note=""):
#         """
#         amount (موجب) => ننشئ سطر تحرير بالسالب
#         """
#         if amount <= 0:
#             return

#         FundReservation.objects.create(
#             source_type=source_type,
#             beneficiary=beneficiary,
#             main_program=main_program,
#             sub_program=sub_program,
#             amount=-amount,
#             reference=reference or "",
#             note=note or "تحرير حجز",
#             created_by=request.user,
#         )

#     def parse_amount(raw: str) -> Decimal:
#         try:
#             v = Decimal((raw or "").strip())
#             return v
#         except (InvalidOperation, TypeError):
#             return Decimal("0.00")

#     # =========================
#     # POST Actions (release)
#     # =========================
#     if request.method == "POST":
#         action = (request.POST.get("action") or "").strip()
#         source_type = (request.POST.get("source_type") or "").strip()
#         obj_id = (request.POST.get("obj_id") or "").strip()

#         # -------------------------
#         # تحرير جزئي من تبويب المحافظ (NEW)
#         # -------------------------
#         if action == "release_partial_wallet":
#             amount = parse_amount(request.POST.get("amount"))
#             if amount <= 0:
#                 messages.error(request, "أدخل مبلغ تحرير صحيح أكبر من صفر.")
#                 return _redirect_same(request)

#             with transaction.atomic():
#                 # ---- Beneficiary ----
#                 if source_type == "beneficiary":
#                     b = get_object_or_404(Beneficiary, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id)

#                     if current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     release = min(amount, current)
#                     create_release_row(
#                         FundReservation.Sources.BENEFICIARY, release,
#                         beneficiary=b,
#                         reference=f"REL-BEN-{b.id}",
#                         note="تحرير جزئي (محفظة المستفيد)"
#                     )
#                     messages.success(request, f"تم تحرير {release} ر.س من حجز المستفيد.")
#                     return _redirect_same(request)

#                 # ---- Sub Program ----
#                 if source_type == "sub_program":
#                     sp = get_object_or_404(SubProgram, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id)

#                     if current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     if d0(sp.spent_amount) > 0:
#                         messages.error(request, "لا يمكن تحرير حجز البرنامج الفرعي لأن عليه مصروفات.")
#                         return _redirect_same(request)

#                     release = min(amount, current)

#                     create_release_row(
#                         FundReservation.Sources.SUB_PROGRAM, release,
#                         sub_program=sp,
#                         reference=f"REL-SUB-{sp.id}",
#                         note="تحرير جزئي (محفظة الفرعي)"
#                     )

#                     # تخفيض allocated_amount بنفس مقدار التحرير
#                     sp.allocated_amount = max(d0(sp.allocated_amount) - release, Decimal("0.00"))
#                     sp.save(update_fields=["allocated_amount"])

#                     messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الفرعي.")
#                     return _redirect_same(request)

#                 # ---- Main Program ----
#                 if source_type == "main_program":
#                     mp = get_object_or_404(MainProgram, id=obj_id)

#                     # ❌ شرطك الأساسي: ممنوع تحرير الرئيسي إذا فيه أي فرعي محجوز
#                     subs_qs = SubProgram.objects.filter(main_program=mp)
#                     if subs_qs.exists():
#                         # 1) ممنوع إذا أي فرعي عليه صرف
#                         if subs_qs.filter(spent_amount__gt=0).exists():
#                             messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
#                             return _redirect_same(request)

#                         # 2) ممنوع إذا أي فرعي عليه حجز
#                         sub_reserved_total = FundReservation.objects.filter(
#                             source_type=FundReservation.Sources.SUB_PROGRAM,
#                             sub_program__main_program=mp,
#                         ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

#                         if d0(sub_reserved_total) > 0:
#                             messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
#                             return _redirect_same(request)

#                     current = net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id)
#                     if current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     release = min(amount, current)

#                     create_release_row(
#                         FundReservation.Sources.MAIN_PROGRAM, release,
#                         main_program=mp,
#                         reference=f"REL-MAIN-{mp.id}",
#                         note="تحرير جزئي (محفظة الرئيسي)"
#                     )

#                     # تخفيض ميزانية الرئيسي
#                     mp.total_donation_amount = max(d0(mp.total_donation_amount) - release, Decimal("0.00"))
#                     mp.save(update_fields=["total_donation_amount"])

#                     messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الرئيسي.")
#                     return _redirect_same(request)

#             messages.error(request, "نوع غير معروف.")
#             return _redirect_same(request)

#         # -------------------------
#         # تحرير كامل من تبويب المحافظ
#         # -------------------------
#         if action == "release_all":
#             with transaction.atomic():
#                 # ---- Beneficiary ----
#                 if source_type == "beneficiary":
#                     b = get_object_or_404(Beneficiary, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id)
#                     if current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     create_release_row(
#                         FundReservation.Sources.BENEFICIARY, current,
#                         beneficiary=b,
#                         reference=f"REL-BEN-{b.id}",
#                         note="تحرير كامل (محفظة المستفيد)"
#                     )
#                     messages.success(request, f"تم تحرير كامل حجز المستفيد ({current} ر.س).")
#                     return _redirect_same(request)

#                 # ---- Sub Program ----
#                 if source_type == "sub_program":
#                     sp = get_object_or_404(SubProgram, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id)
#                     if current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     if d0(sp.spent_amount) > 0:
#                         messages.error(request, "لا يمكن تحرير حجز الفرعي لأنه عليه مصروفات.")
#                         return _redirect_same(request)

#                     create_release_row(
#                         FundReservation.Sources.SUB_PROGRAM, current,
#                         sub_program=sp,
#                         reference=f"REL-SUB-{sp.id}",
#                         note="تحرير كامل (محفظة الفرعي)"
#                     )

#                     sp.allocated_amount = max(d0(sp.allocated_amount) - current, Decimal("0.00"))
#                     sp.save(update_fields=["allocated_amount"])

#                     messages.success(request, f"تم تحرير كامل حجز الفرعي ({current} ر.س).")
#                     return _redirect_same(request)

#                 # ---- Main Program (ممنوع إذا عنده فروع محجوزة) ----
#                 if source_type == "main_program":
#                     mp = get_object_or_404(MainProgram, id=obj_id)
#                     subs_qs = SubProgram.objects.filter(main_program=mp)

#                     # ممنوع إذا أي فرعي عليه صرف
#                     if subs_qs.filter(spent_amount__gt=0).exists():
#                         messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
#                         return _redirect_same(request)

#                     # ممنوع إذا أي فرعي عليه حجز
#                     sub_reserved_total = FundReservation.objects.filter(
#                         source_type=FundReservation.Sources.SUB_PROGRAM,
#                         sub_program__main_program=mp,
#                     ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

#                     if d0(sub_reserved_total) > 0:
#                         messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
#                         return _redirect_same(request)

#                     main_current = net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id)
#                     if main_current <= 0:
#                         messages.info(request, "لا يوجد حجز لتحريره.")
#                         return _redirect_same(request)

#                     create_release_row(
#                         FundReservation.Sources.MAIN_PROGRAM, main_current,
#                         main_program=mp,
#                         reference=f"REL-MAIN-{mp.id}",
#                         note="تحرير كامل (محفظة الرئيسي)"
#                     )

#                     mp.total_donation_amount = max(d0(mp.total_donation_amount) - main_current, Decimal("0.00"))
#                     mp.save(update_fields=["total_donation_amount"])

#                     messages.success(request, f"تم تحرير كامل حجز البرنامج الرئيسي ({main_current} ر.س).")
#                     return _redirect_same(request)

#             messages.error(request, "نوع غير معروف.")
#             return _redirect_same(request)

#         # -------------------------
#         # تحرير من سجل الحجوزات (كما هو عندك)
#         # -------------------------
#         if action == "release_amount":
#             # هنا نخليه يشتغل، لكن نفس قواعد المنع للرئيسي (لا إذا فروع محجوزة)
#             amount = parse_amount(request.POST.get("amount"))
#             reference = (request.POST.get("reference") or "").strip()

#             if amount <= 0:
#                 messages.error(request, "مبلغ التحرير غير صحيح.")
#                 return _redirect_same(request)

#             with transaction.atomic():
#                 if source_type == FundReservation.Sources.BENEFICIARY:
#                     b = get_object_or_404(Beneficiary, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.BENEFICIARY, beneficiary_id=b.id)
#                     release = min(amount, max(current, Decimal("0.00")))
#                     create_release_row(
#                         FundReservation.Sources.BENEFICIARY, release,
#                         beneficiary=b,
#                         reference=reference or f"REL-BEN-{b.id}",
#                         note="تحرير جزئي (سجل الحجوزات)"
#                     )
#                     messages.success(request, f"تم تحرير {release} ر.س من حجز المستفيد.")
#                     return _redirect_same(request)

#                 if source_type == FundReservation.Sources.SUB_PROGRAM:
#                     sp = get_object_or_404(SubProgram, id=obj_id)
#                     current = net_reserved_for(FundReservation.Sources.SUB_PROGRAM, sub_program_id=sp.id)
#                     release = min(amount, max(current, Decimal("0.00")))

#                     if d0(sp.spent_amount) > 0:
#                         messages.error(request, "لا يمكن تحرير حجز البرنامج الفرعي لأن عليه مصروفات.")
#                         return _redirect_same(request)

#                     create_release_row(
#                         FundReservation.Sources.SUB_PROGRAM, release,
#                         sub_program=sp,
#                         reference=reference or f"REL-SUB-{sp.id}",
#                         note="تحرير جزئي (سجل الحجوزات)"
#                     )

#                     sp.allocated_amount = max(d0(sp.allocated_amount) - release, Decimal("0.00"))
#                     sp.save(update_fields=["allocated_amount"])

#                     messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الفرعي.")
#                     return _redirect_same(request)

#                 if source_type == FundReservation.Sources.MAIN_PROGRAM:
#                     mp = get_object_or_404(MainProgram, id=obj_id)
#                     subs_qs = SubProgram.objects.filter(main_program=mp)

#                     if subs_qs.filter(spent_amount__gt=0).exists():
#                         messages.error(request, "لا يمكن تحرير الرئيسي لأن بعض الفروع عليها مصروفات.")
#                         return _redirect_same(request)

#                     sub_reserved_total = FundReservation.objects.filter(
#                         source_type=FundReservation.Sources.SUB_PROGRAM,
#                         sub_program__main_program=mp,
#                     ).aggregate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["t"]

#                     if d0(sub_reserved_total) > 0:
#                         messages.error(request, "لا يمكن تحرير الرئيسي قبل تحرير جميع حجوزات البرامج الفرعية التابعة له.")
#                         return _redirect_same(request)

#                     current = net_reserved_for(FundReservation.Sources.MAIN_PROGRAM, main_program_id=mp.id)
#                     release = min(amount, max(current, Decimal("0.00")))

#                     create_release_row(
#                         FundReservation.Sources.MAIN_PROGRAM, release,
#                         main_program=mp,
#                         reference=reference or f"REL-MAIN-{mp.id}",
#                         note="تحرير جزئي (سجل الحجوزات)"
#                     )

#                     mp.total_donation_amount = max(d0(mp.total_donation_amount) - release, Decimal("0.00"))
#                     mp.save(update_fields=["total_donation_amount"])

#                     messages.success(request, f"تم تحرير {release} ر.س من حجز البرنامج الرئيسي.")
#                     return _redirect_same(request)

#             messages.error(request, "نوع الحجز غير معروف.")
#             return _redirect_same(request)

#     # =========================
#     # Summary
#     # =========================
#     fund_total = FundEntry.objects.aggregate(
#         t=Coalesce(Sum("amount"), Value(Decimal("0.00")))
#     )["t"]

#     reserved_total = FundReservation.objects.aggregate(
#         t=Coalesce(Sum("amount"), Value(Decimal("0.00")))
#     )["t"]

#     available_fund = FundReservation.available_fund()

#     # =========================
#     # Wallet tables (بدون تضخيم JOIN)
#     # =========================

#     # --- Beneficiaries ---
#     bene_wallet_sq = (
#         BeneficiaryBalanceEntry.objects
#         .filter(beneficiary_id=OuterRef("pk"))
#         .values("beneficiary_id")
#         .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     bene_reserved_sq = (
#         FundReservation.objects
#         .filter(source_type=FundReservation.Sources.BENEFICIARY, beneficiary_id=OuterRef("pk"))
#         .values("beneficiary_id")
#         .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     beneficiaries = (
#         Beneficiary.objects
#         .annotate(
#             wallet_balance=Coalesce(
#                 Subquery(bene_wallet_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#             reserved_from_fund=Coalesce(
#                 Subquery(bene_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#         )
#         .order_by("first_name", "last_name")
#     )

#     beneficiaries_wallets = [
#         b for b in beneficiaries
#         if (d0(b.wallet_balance) != 0 or d0(b.reserved_from_fund) != 0)
#     ]

#     # --- Main Programs ---
#     main_reserved_sq = (
#         FundReservation.objects
#         .filter(source_type=FundReservation.Sources.MAIN_PROGRAM, main_program_id=OuterRef("pk"))
#         .values("main_program_id")
#         .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     main_allocated_sq = (
#         SubProgram.objects
#         .filter(main_program_id=OuterRef("pk"))
#         .values("main_program_id")
#         .annotate(t=Coalesce(Sum("allocated_amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     # ✅ مؤشر يسمح/يمنع تحرير الرئيسي: ممنوع إذا فيه فروع محجوزة أو مصروفة
#     main_has_sub_reserved_sq = (
#         FundReservation.objects
#         .filter(
#             source_type=FundReservation.Sources.SUB_PROGRAM,
#             sub_program__main_program_id=OuterRef("pk"),
#         )
#         .values("sub_program__main_program_id")
#         .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     main_has_sub_spent_sq = (
#         SubProgram.objects
#         .filter(main_program_id=OuterRef("pk"))
#         .values("main_program_id")
#         .annotate(t=Coalesce(Sum("spent_amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     main_programs = (
#         MainProgram.objects
#         .annotate(
#             allocated_sum=Coalesce(
#                 Subquery(main_allocated_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#             reserved_from_fund=Coalesce(
#                 Subquery(main_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#             sub_reserved_total=Coalesce(
#                 Subquery(main_has_sub_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#             sub_spent_total=Coalesce(
#                 Subquery(main_has_sub_spent_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             ),
#         )
#         .order_by("name")
#     )
#     main_program_wallets = list(main_programs)

#     # --- Sub Programs ---
#     sub_reserved_sq = (
#         FundReservation.objects
#         .filter(source_type=FundReservation.Sources.SUB_PROGRAM, sub_program_id=OuterRef("pk"))
#         .values("sub_program_id")
#         .annotate(t=Coalesce(Sum("amount"), Value(Decimal("0.00"))))
#         .values("t")[:1]
#     )

#     sub_programs = (
#         SubProgram.objects
#         .select_related("main_program")
#         .annotate(
#             reserved_from_fund=Coalesce(
#                 Subquery(sub_reserved_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
#                 Value(Decimal("0.00"))
#             )
#         )
#         .order_by("name")
#     )

#     sub_program_wallets = [
#         sp for sp in sub_programs
#         if (d0(sp.allocated_amount) != 0 or d0(sp.spent_amount) != 0 or d0(sp.reserved_from_fund) != 0)
#     ]

#     # =========================
#     # Reservations log filters
#     # =========================
#     filters = {
#         "source_type": (request.GET.get("source_type") or "").strip(),
#         "date_from": (request.GET.get("date_from") or "").strip(),
#         "date_to": (request.GET.get("date_to") or "").strip(),
#         "q": (request.GET.get("q") or "").strip(),
#     }

#     reservations = FundReservation.objects.select_related("beneficiary", "main_program", "sub_program").all()

#     if filters["source_type"]:
#         reservations = reservations.filter(source_type=filters["source_type"])

#     if filters["date_from"]:
#         reservations = reservations.filter(created_at__date__gte=filters["date_from"])
#     if filters["date_to"]:
#         reservations = reservations.filter(created_at__date__lte=filters["date_to"])

#     if filters["q"]:
#         q = filters["q"]
#         reservations = reservations.filter(
#             Q(reference__icontains=q) |
#             Q(note__icontains=q) |
#             Q(beneficiary__first_name__icontains=q) |
#             Q(beneficiary__last_name__icontains=q) |
#             Q(main_program__name__icontains=q) |
#             Q(sub_program__name__icontains=q)
#         )

#     reservations = reservations.order_by("-created_at", "-id")[:500]

#     return render(request, "Accounting/fund_reservations_dashboard.html", {
#         "fund_total": fund_total,
#         "reserved_total": reserved_total,
#         "available_fund": available_fund,

#         "beneficiaries_wallets": beneficiaries_wallets,
#         "main_program_wallets": main_program_wallets,
#         "sub_program_wallets": sub_program_wallets,

#         "reservations": reservations,
#         "filters": filters,
#     })
from decimal import Decimal
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

@role_required([Profile.Roles.ACCOUNTANT])
def beneficiary_supports_report(request):
    from .models import BeneficiarySupportEntry

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    q = (request.GET.get("q") or "").strip()

    qs = BeneficiarySupportEntry.objects.select_related(
        "beneficiary", "sub_program", "main_program"
    ).order_by("-created_at", "-id")

    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    if q:
        qs = qs.filter(
            Q(voucher_number__icontains=q) |
            Q(note__icontains=q) |
            Q(beneficiary__first_name__icontains=q) |
            Q(beneficiary__last_name__icontains=q)
        )

    # تجميع لكل مستفيد
    per_beneficiary = (
        qs.values("beneficiary_id", "beneficiary__first_name", "beneficiary__last_name")
        .annotate(total=Coalesce(Sum("amount"), Decimal("0.00")))
        .order_by("-total")
    )

    # آخر 200 سجل تفصيلي للعرض
    latest = list(qs[:200])

    return render(request, "Accounting/beneficiary_supports_report.html", {
        "title": "تقرير دعم المستفيدين من محافظ البرامج",
        "filters": {"date_from": date_from, "date_to": date_to, "q": q},
        "per_beneficiary": per_beneficiary,
        "latest": latest,
    })

from datetime import date, datetime
from django.db.models import Sum

from Management.models import (
    Profile,
    BeneficiarySponsorHistory,
)

from Accounting.models import (
    BeneficiarySupportEntry,
)

from datetime import date, datetime
from django.db.models import Q, Sum
#@login_required
def sponsorship_report_print(request):

    donor_id = request.GET.get("donor")
    report_type = request.GET.get("report_type")

    year = int(request.GET.get("year") or date.today().year)

    quarter = request.GET.get("quarter")
    half = request.GET.get("half")

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    # -----------------------------------------
    # تحديد الفترة
    # -----------------------------------------

    if report_type == "year":

        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)

    elif report_type == "quarter":

        q = int(quarter)

        if q == 1:
            from_date = date(year, 1, 1)
            to_date = date(year, 3, 31)

        elif q == 2:
            from_date = date(year, 4, 1)
            to_date = date(year, 6, 30)

        elif q == 3:
            from_date = date(year, 7, 1)
            to_date = date(year, 9, 30)

        else:
            from_date = date(year, 10, 1)
            to_date = date(year, 12, 31)

    elif report_type == "half":

        if half == "1":

            from_date = date(year, 1, 1)
            to_date = date(year, 6, 30)

        else:

            from_date = date(year, 7, 1)
            to_date = date(year, 12, 31)

    else:

        from_date = datetime.strptime(
            from_date,
            "%Y-%m-%d"
        ).date()

        to_date = datetime.strptime(
            to_date,
            "%Y-%m-%d"
        ).date()

    donor = get_object_or_404(
        Profile,
        pk=donor_id
    )

    sponsor_history = (
        BeneficiarySponsorHistory.objects
        .filter(
            donor=donor,
            start_date__lte=to_date,
        )
        .filter(
            Q(end_date__isnull=True) |
            Q(end_date__gte=from_date)
        )
        .select_related(
            "beneficiary"
        )
        .order_by(
            "beneficiary__first_name",
            "beneficiary__last_name",
        )
    )

    beneficiaries = []

    grand_total = 0

    for history in sponsor_history:

        beneficiary = history.beneficiary

        supports = (
            BeneficiarySupportEntry.objects
            .filter(
                beneficiary=beneficiary,
                created_at__date__range=(
                    from_date,
                    to_date,
                ),
            )
            .select_related(
                "sub_program"
            )
            .order_by(
                "created_at"
            )
        )

        beneficiary_total = 0

        program_rows = []

        for support in supports:

            beneficiary_total += support.amount

            program_rows.append({

                "program_name":
                    support.sub_program.name,

                "description":
                    support.sub_program.description,

                "amount":
                    support.amount,

                "date":
                    support.created_at.date(),

            })
        beneficiaries.append({

            "beneficiary": beneficiary,

            "history": history,

            "programs": program_rows,

            "total": beneficiary_total,

            "support_count": len(program_rows),

        })

        grand_total += beneficiary_total

    context = {

        "title": "تقرير الكفالة",

        "donor": donor,

        "beneficiaries": beneficiaries,

        "grand_total": grand_total,

        "beneficiary_count": len(beneficiaries),

        "report_type": report_type,

        "year": year,

        "quarter": quarter,

        "half": half,

        "from_date": from_date,

        "to_date": to_date,

        "generated_at": datetime.now(),

    }
    log_activity(
        user=request.user,
        action=AuditLog.Actions.OTHER,
        entity="تقرير كفالة",
        entity_id=donor.pk,
        extra={
            "report_type": report_type,
            "from": str(from_date),
            "to": str(to_date),
        },
    )
    return render(

        request,

        "Accounting/sponsorship_report_print.html",

        context,

    )

    ###################################################################################3
from Management.models import Profile
from datetime import datetime

def sponsorship_reports(request):

    donors = Profile.objects.filter(
    role=Profile.Roles.DONOR
    ).select_related("user").order_by("user__first_name")
    context = {
        "title": "تقارير الكفالة",
        "donors": donors,
        "years":range(datetime.now().year,2020,-1),

    }

    return render(
        request,
        "Accounting/sponsorship_reports.html",
        context,
    )


