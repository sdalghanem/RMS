from django.views.decorators.http import require_GET
import csv
from django.contrib.auth import get_user_model
import io
from Management.sponsorship_ops import attach_sponsorship, create_sponsorship
from .services import financial_transaction
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from django.db.models import Prefetch
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from Management.models import (
    AuditLog,
    Beneficiary,
    BeneficiarySponsorHistory,
    MainProgram,
    Profile,
    SubProgram,
)
from Management.utils.audit import log_activity
from Management.views import role_required

from .forms import (
    DonorUserCreateForm,
    FinancialSponsorshipAllocationForm,
    FinancialSponsorshipInvoiceForm,
    GeneralDonationInvoiceForm,
)
from .models import (
    AllocationHistory,
    BeneficiarySupportEntry,
    FinancialSponsorshipAllocation,
    FinancialSponsorshipInvoice,
    FundEntry,
    GeneralDonationInvoice,
    Invoice,
    SubProgramDisbursement,
)
from .services import (
    allocate_to_main_program,
    allocate_to_sub_program,
    get_available_for_allocation,
    get_fund_balance,
    get_main_program_balance,
    get_sub_program_balance,
    release_from_main_program,
    release_from_sub_program,
    spend_from_sub_program,
    reverse_subprogram_disbursement
)

INVOICE_ROLES = [
    Profile.Roles.SYSTEM_ADMIN,
    Profile.Roles.CASHIER,
    Profile.Roles.ACCOUNTANT,
]

User = get_user_model()


#@login_required
@role_required(INVOICE_ROLES)
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



# --------------------------------------------------
# قائمة الفواتير (لـ system_admin + cashier)
# --------------------------------------------------
@role_required(INVOICE_ROLES)
def cashier_invoices_list(request):
    invoices_qs = (
        Invoice.objects
        .select_related("general_donation", "financial_sponsorship", "created_by")
        .order_by("-created_at", "-id")
    )

    query = (request.GET.get('q') or '').strip()[:150]
    if query:
        invoices_qs = invoices_qs.filter(
            Q(number__icontains=query)
            | Q(general_donation__supporter_name__icontains=query)
            | Q(financial_sponsorship__sponsor__user__first_name__icontains=query)
            | Q(financial_sponsorship__sponsor__user__last_name__icontains=query)
        )
    paginator = Paginator(invoices_qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "title": "الفواتير",
        "search_query": query,
        "page_obj": page_obj,
    }
    return render(request, "Accounting/cashier_invoices_list.html", context)

###############################################################################

# =============================================================
# تعديل مبلغ السند
# =============================================================

@role_required(INVOICE_ROLES)
@financial_transaction
def invoice_update(request, pk):
    """
    تعديل مبلغ السند.

    قواعد الأمان
    ---------------------------------------------------------

    التبرع العام:
    - نتحقق من الرصيد المتاح للتخصيص من صندوق الجمعية.
    - إذا كان المتاح أقل من مبلغ السند الحالي،
      فهذا يعني أن جزءًا من المبلغ لم يعد متاحًا،
      وبالتالي يمنع تعديل السند.
    - لا نقارن المبلغ الجديد مباشرة برصيد الصندوق
      لأن مبلغ السند الحالي موجود أصلًا ضمن الرصيد.

    الكفالة المالية:
    - إذا كان السند مرتبطًا بمستفيد عن طريق
      FinancialSponsorshipAllocation يمنع التعديل.
    - إذا لم يكن مرتبطًا بمستفيد يسمح بالتعديل.
    """

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "general_donation",
            "financial_sponsorship",
        ),
        pk=pk,
    )

    # =========================================================
    # تحديد المبلغ الحالي
    # =========================================================

    current_amount = Decimal("0.00")

    if (
        invoice.invoice_type == Invoice.Types.GENERAL_DONATION
        and hasattr(invoice, "general_donation")
    ):
        current_amount = (
            invoice.general_donation.amount
            or Decimal("0.00")
        )

    elif (
        invoice.invoice_type == Invoice.Types.FINANCIAL_SPONSORSHIP
        and hasattr(invoice, "financial_sponsorship")
    ):
        current_amount = (
            invoice.financial_sponsorship.total_amount
            or Decimal("0.00")
        )

    # =========================================================
    # تنفيذ التعديل
    # =========================================================

    if request.method == "POST":

        amount_raw = (
            request.POST.get("amount") or ""
        ).strip()

        try:

            new_amount = Decimal(amount_raw)

            if not new_amount.is_finite() or new_amount <= 0 or new_amount != new_amount.quantize(Decimal("0.01")):
                raise ValidationError(
                    "المبلغ يجب أن يكون أكبر من صفر."
                )

            with transaction.atomic():

                # -------------------------------------------------
                # إعادة جلب السند مع قفل السجل
                # -------------------------------------------------

                invoice = (
                    Invoice.objects
                    .select_for_update()
                    .select_related(
                        "general_donation",
                        "financial_sponsorship",
                    )
                    .get(pk=pk)
                )

                # =================================================
                # التبرع العام
                # =================================================

                if (
                    invoice.invoice_type
                    == Invoice.Types.GENERAL_DONATION
                ):

                    general = getattr(
                        invoice,
                        "general_donation",
                        None,
                    )

                    if not general:
                        raise ValidationError(
                            "تفاصيل التبرع العام غير موجودة."
                        )

                    current_amount = (
                        general.amount
                        or Decimal("0.00")
                    )

                    # -------------------------------------------------
                    # فحص المبلغ المتاح للتخصيص
                    #
                    # هذا هو الرصيد الذي يسمح لنا بمعرفة هل
                    # مبلغ التبرع ما زال متاحًا أم تم استخدامه.
                    # -------------------------------------------------

                    available_for_allocation = (
                        get_available_for_allocation()
                        or Decimal("0.00")
                    )

                    if available_for_allocation < current_amount:

                        raise ValidationError(
                            "لا يمكن تعديل سند التبرع العام، "
                            "لأن جزءًا من مبلغ التبرع تم استخدامه."
                        )

                    # -------------------------------------------------
                    # تعديل مبلغ التبرع
                    # -------------------------------------------------

                    general.amount = new_amount

                    general.save(
                        update_fields=["amount"]
                    )

                    # -------------------------------------------------
                    # تحديث حركة الدخل المرتبطة بالسند
                    # -------------------------------------------------

                    FundEntry.objects.filter(
                        invoice=invoice
                    ).update(
                        amount=new_amount,
                        description=(
                            f"تبرع عام من "
                            f"{general.supporter_name or 'داعم'} "
                            f"- سند {invoice.number}"
                        ),
                    )

                # =================================================
                # الكفالة المالية
                # =================================================

                elif (
                    invoice.invoice_type
                    == Invoice.Types.FINANCIAL_SPONSORSHIP
                ):

                    sponsorship = getattr(
                        invoice,
                        "financial_sponsorship",
                        None,
                    )

                    if not sponsorship:
                        raise ValidationError(
                            "تفاصيل الكفالة المالية غير موجودة."
                        )

                    # -------------------------------------------------
                    # التحقق من وجود تخصيص للمستفيد
                    # -------------------------------------------------

                    has_allocation = (
                        FinancialSponsorshipAllocation.objects
                        .filter(
                            sponsorship_invoice=sponsorship
                        )
                        .exists()
                    )

                    if get_available_for_allocation() < sponsorship.total_amount:
                        raise ValidationError("لا يمكن تعديل أو حذف دخل كفالة مستخدم في تخصيص أو صرف.")
                    if has_allocation:

                        raise ValidationError(
                            "لا يمكن تعديل سند الكفالة، "
                            "لأنه مرتبط بالفعل بمستفيد."
                        )

                    # -------------------------------------------------
                    # لا يوجد تخصيص
                    # يسمح بالتعديل
                    # -------------------------------------------------

                    sponsorship.custom_amount = new_amount

                    sponsorship.save(
                        update_fields=["custom_amount"]
                    )

                    # -------------------------------------------------
                    # تحديث حركة دخل الكفالة
                    # -------------------------------------------------

                    FundEntry.objects.filter(
                        invoice=invoice
                    ).update(
                        amount=new_amount,
                        description=(
                            f"دخل كفالة مالية "
                            f"من السند رقم {invoice.number}"
                        ),
                    )

                else:

                    raise ValidationError(
                        "نوع السند غير مدعوم للتعديل."
                    )

                # =================================================
                # نجاح العملية
                # =================================================

                messages.success(
                    request,
                    "تم تعديل مبلغ السند بنجاح."
                )

                return redirect(
                    "Accounting:invoice_detail",
                    pk=invoice.pk,
                )

        except (
            InvalidOperation,
            ValidationError,
        ) as e:

            messages.error(
                request,
                str(e),
            )

    # =========================================================
    # عرض صفحة التعديل
    # =========================================================

    return render(
        request,
        "Accounting/invoice_amount_update.html",
        {
            "title": f"تعديل مبلغ السند {invoice.number}",
            "invoice": invoice,
            "current_amount": current_amount,
        },
    )


# =============================================================
# حذف السند
# =============================================================

@require_POST
@role_required(INVOICE_ROLES)
@financial_transaction
def invoice_delete(request, pk):
    """
    حذف السند.

    قواعد الأمان
    ---------------------------------------------------------

    التبرع العام:
    - نتحقق من الرصيد المتاح للتخصيص.
    - إذا كان الرصيد المتاح أقل من مبلغ السند الحالي،
      فهذا يعني أن جزءًا من المبلغ لم يعد متاحًا،
      وبالتالي يمنع الحذف.

    الكفالة المالية:
    - إذا كان السند مرتبطًا بمستفيد عن طريق
      FinancialSponsorshipAllocation يمنع الحذف.
    - إذا لم يكن مرتبطًا بمستفيد يسمح بالحذف.
    """

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "general_donation",
            "financial_sponsorship",
        ),
        pk=pk,
    )

    try:

        with transaction.atomic():

            # -----------------------------------------------------
            # إعادة جلب السند مع قفل السجل
            # -----------------------------------------------------

            invoice = (
                Invoice.objects
                .select_for_update()
                .select_related(
                    "general_donation",
                    "financial_sponsorship",
                )
                .get(pk=pk)
            )

            invoice_number = invoice.number

            # =====================================================
            # التبرع العام
            # =====================================================

            if (
                invoice.invoice_type
                == Invoice.Types.GENERAL_DONATION
            ):

                general = getattr(
                    invoice,
                    "general_donation",
                    None,
                )

                if not general:
                    raise ValidationError(
                        "تفاصيل التبرع العام غير موجودة."
                    )

                current_amount = (
                    general.amount
                    or Decimal("0.00")
                )

                # -------------------------------------------------
                # التحقق من أن مبلغ التبرع ما زال متاحًا
                # للتخصيص من الصندوق.
                # -------------------------------------------------

                available_for_allocation = (
                    get_available_for_allocation()
                    or Decimal("0.00")
                )

                if available_for_allocation < current_amount:

                    raise ValidationError(
                        "لا يمكن حذف سند التبرع العام، "
                        "لأن جزءًا من مبلغ التبرع تم استخدامه."
                    )

            # =====================================================
            # الكفالة المالية
            # =====================================================

            elif (
                invoice.invoice_type
                == Invoice.Types.FINANCIAL_SPONSORSHIP
            ):

                sponsorship = getattr(
                    invoice,
                    "financial_sponsorship",
                    None,
                )

                if not sponsorship:
                    raise ValidationError(
                        "تفاصيل الكفالة المالية غير موجودة."
                    )

                # -------------------------------------------------
                # التحقق من ارتباط السند بمستفيد
                # -------------------------------------------------

                has_allocation = (
                    FinancialSponsorshipAllocation.objects
                    .filter(
                        sponsorship_invoice=sponsorship
                    )
                    .exists()
                )

                if get_available_for_allocation() < sponsorship.total_amount:
                    raise ValidationError("لا يمكن تعديل أو حذف دخل كفالة مستخدم في تخصيص أو صرف.")
                if has_allocation:

                    raise ValidationError(
                        "لا يمكن حذف سند الكفالة، "
                        "لأنه مرتبط بالفعل بمستفيد."
                    )

            else:

                raise ValidationError(
                    "نوع السند غير مدعوم للحذف."
                )

            # =====================================================
            # تنفيذ الحذف
            # =====================================================

            # -----------------------------------------------------
            # حذف حركة الصندوق المرتبطة بالسند
            # -----------------------------------------------------

            FundEntry.objects.filter(
                invoice=invoice
            ).delete()

            # -----------------------------------------------------
            # حذف تفاصيل التبرع العام
            # -----------------------------------------------------

            general = getattr(
                invoice,
                "general_donation",
                None,
            )

            if general:
                general.delete()

            # -----------------------------------------------------
            # حذف تفاصيل الكفالة
            # -----------------------------------------------------

            sponsorship = getattr(
                invoice,
                "financial_sponsorship",
                None,
            )

            if sponsorship:
                sponsorship.delete()

            # -----------------------------------------------------
            # حذف السند الأساسي
            # -----------------------------------------------------

            invoice.delete()

            # =====================================================
            # تسجيل العملية في سجل التدقيق
            # =====================================================

            log_activity(
                user=request.user,
                action=AuditLog.Actions.DELETE,
                entity="Invoice",
                entity_id=pk,
                extra={
                    "invoice_number": invoice_number,
                },
            )

            messages.success(
                request,
                "تم حذف السند بنجاح."
            )

    except ValidationError as e:

        messages.error(
            request,
            str(e),
        )

    except Exception as e:

        messages.error(
            request,
            f"حدث خطأ أثناء حذف السند: {str(e)}"
        )

    return redirect(
        "Accounting:cashier_invoices_list"
    )

# --------------------------------------------------
# إنشاء سند تبرع عام
# --------------------------------------------------
@role_required(INVOICE_ROLES)
@transaction.atomic
@financial_transaction
def invoice_create_general(request):
    if request.method == "POST":
        form = GeneralDonationInvoiceForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data

            try:
                # السند الأساسي (رقم السند يدوي)
                with transaction.atomic():
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



@role_required(INVOICE_ROLES)
@financial_transaction
def invoice_create_sponsorship(request):
    data = request.POST if request.method == "POST" else None
    form = FinancialSponsorshipInvoiceForm(data)
    if data:
        sponsor_id = data.get("sponsor", "")
        if sponsor_id.isdecimal():
            form.fields["sponsor"].queryset = Profile.objects.filter(pk=sponsor_id, role=Profile.Roles.DONOR).select_related("user")
        valid = form.is_valid()
        if "create_beneficiary" in data or any(key.startswith("new_beneficiary-") for key in data):
            form.add_error(None, "إنشاء المستفيدين متاح لمدير النظام من إدارة المستفيدين فقط.")
            valid = False
        if valid:
            cd = form.cleaned_data
            try:
                sponsorship = create_sponsorship(form, request.user, beneficiary=cd.get("beneficiary"))
                return redirect("Accounting:invoice_detail", pk=sponsorship.invoice_id)
            except IntegrityError:
                form.add_error(None, "تعذر الحفظ بسبب سجل مكرر. تحقق من رقم السند وهوية المستفيد.")
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
    return render(request, "Accounting/invoice_sponsorship_form.html", {
        "title": "إنشاء سند كفالة مالية", "form": form,
    })



# --------------------------------------------------
# عرض سند (مع زر طباعة)
# --------------------------------------------------
@role_required(INVOICE_ROLES)
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
def sponsor_detail(request, pk):

    sponsor = get_object_or_404(
        Profile.objects.select_related("user"),
        pk=pk,
        role=Profile.Roles.DONOR,
    )

    today = timezone.localdate()

    results = []

    active_count = 0
    expired_count = 0
    pending_count = 0

    # ---------------------------------------------------------
    # سجلات إسناد المستفيدين لهذا الكافل
    # ---------------------------------------------------------

    histories = (
        BeneficiarySponsorHistory.objects
        .filter(donor=sponsor)
        .select_related("beneficiary")
        .order_by("-start_date", "-id")
    )

    # ---------------------------------------------------------
    # جلب تخصيصات السندات لهذا الكافل دفعة واحدة
    # ---------------------------------------------------------

    allocations = (
        FinancialSponsorshipAllocation.objects
        .filter(
            sponsorship_invoice__sponsor=sponsor,
        )
        .select_related(
            "sponsorship_invoice",
            "sponsorship_invoice__invoice",
        )
    )

    # نربط:
    # المستفيد + بداية السند + نهاية السند
    # بالسند المالي
    allocation_map = {}

    for allocation in allocations:

        invoice = allocation.sponsorship_invoice

        key = (
            allocation.beneficiary_id,
            invoice.start_date,
            invoice.end_date,
        )

        allocation_map[key] = allocation

    # ---------------------------------------------------------
    # بناء النتائج
    # ---------------------------------------------------------

    for h in histories:

        if h.start_date and h.end_date:

            if today < h.start_date:

                status = "لم تبدأ بعد"
                pending_count += 1

            elif today > h.end_date:

                status = "منتهية"
                expired_count += 1

            else:

                status = "سارية"
                active_count += 1

        elif h.start_date:

            status = "سارية"
            active_count += 1

        else:

            status = "غير محددة"

        # -----------------------------------------------------
        # البحث عن السند المرتبط بهذا الإسناد
        # -----------------------------------------------------

        allocation = allocation_map.get(
            (
                h.beneficiary_id,
                h.start_date,
                h.end_date,
            )
        )

        invoice = (
            allocation.sponsorship_invoice.invoice
            if allocation
            else None
        )

        sponsorship_invoice = (
            allocation.sponsorship_invoice
            if allocation
            else None
        )

        results.append({

            "beneficiary": h.beneficiary,

            "invoice": invoice,

            "sponsorship_invoice": sponsorship_invoice,

            "start_date": h.start_date,

            "end_date": h.end_date,

            "display_duration": (
                sponsorship_invoice.display_duration
                if sponsorship_invoice
                else "—"
            ),

            "status": status,

        })

    return render(
        request,
        "Accounting/sponsor_detail.html",
        {
            "title": "ملف الكافل",

            "sponsor": sponsor,

            "results": results,

            "active_count": active_count,

            "expired_count": expired_count,

            "pending_count": pending_count,
        },
    )

########################################################################################################################
#                                                                                                                      #
########################################################################################################################


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsor_create_page(request):
    return render(
        request,
        "Accounting/sponsor_create.html",
    )

@require_POST
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
@transaction.atomic
def sponsor_quick_create(request):
    """
    إنشاء كافل جديد من DonorUserCreateForm
    وإرجاع JSON بالنتيجة.
    """

    form = DonorUserCreateForm(request.POST)

    # التحقق من البيانات
    if not form.is_valid():
        errors = {}

        for field, field_errors in form.errors.items():
            errors[field] = " ".join(field_errors)

        return JsonResponse(
            {
                "success": False,
                "errors": errors,
            },
            status=400,
        )

    # Roll back partial accounts if concurrent creation wins the unique constraint.
    try:
        user = form.save()
    except (IntegrityError, ValidationError):
        return JsonResponse({"success": False, "errors": {"__all__": "تعذر إنشاء الكافل. تحقق من البيانات والتكرار."}}, status=400)

    # Profile المرتبط بالمستخدم
    profile = user.profile

    # تسجيل العملية في سجل النشاط
    log_activity(
        user=request.user,
        action=AuditLog.Actions.CREATE,
        entity="Profile",
        entity_id=profile.id,
        extra={
            "sponsor_name": user.get_full_name() or user.username,
        },
    )

    label = user.get_full_name() or user.username

    return JsonResponse(
        {
            "success": True,
            "id": profile.id,
            "label": label,
        }
    )

###
def _sponsor_deletion_blocker(sponsor, account):
    if account.is_staff or account.is_superuser or account.groups.exclude(name="donor").exists() or account.user_permissions.exists():
        return "لا يمكن حذف حساب مرتبط بصلاحيات أخرى."
    # Check even nullable relations: deletion must never clear a historical FK.
    reasons = {
        "management.beneficiary": "لا يمكن حذف الكافل لوجود مستفيد مرتبط به.",
        "management.beneficiarysponsorhistory": "لا يمكن حذف الكافل لوجود كفالة حالية أو تاريخية.",
        "accounting.financialsponsorshipinvoice": "لا يمكن حذف الكافل لارتباطه بسند كفالة مالي.",
    }
    for obj in (sponsor, account):
        for relation in obj._meta.get_fields(include_hidden=True):
            if not relation.auto_created or not (relation.one_to_many or relation.one_to_one):
                continue
            model = relation.related_model
            if obj is account and model in (Profile, User.groups.through):
                continue
            if model._base_manager.filter(**{relation.field.attname: obj.pk}).exists():
                return reasons.get(model._meta.label_lower, "لا يمكن حذف الكافل لارتباط حسابه بسجلات محفوظة.")
    # General donations store the supporter's identity separately from Profile.
    identity = Q()
    if sponsor.national_number:
        identity |= Q(supporter_national_number=sponsor.national_number)
    if sponsor.phone:
        identity |= Q(supporter_phone=sponsor.phone)
    if identity and GeneralDonationInvoice.objects.filter(identity).exists():
        return "تعذر حذف الكافل لوجود سند تبرع يطابق بيانات هويته أو جواله."
    return None


@role_required([Profile.Roles.SYSTEM_ADMIN])
@require_POST
def delete_sponsor(request, pk):
    try:
        with transaction.atomic():
            sponsor = Profile.objects.select_for_update().filter(pk=pk, role=Profile.Roles.DONOR).first()
            if sponsor is None:
                reason = "الكافل غير موجود أو حُذف مسبقًا."
            else:
                account = User.objects.select_for_update().get(pk=sponsor.user_id)
                reason = _sponsor_deletion_blocker(sponsor, account)
                if not reason:
                    sponsor.delete()
                    account.delete()
    except IntegrityError:  # Includes ProtectedError and RestrictedError.
        reason = "تعذر حذف الكافل لأن سجلات أخرى مرتبطة به."
    if reason:
        messages.error(request, reason)
    else:
        messages.success(request, "تم حذف الكافل بنجاح.")
    return redirect("Accounting:sponsors_list")


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsors_list(request):
    query = request.GET.get("q", "").strip()

    sponsors_qs = (
        Profile.objects
        .filter(role=Profile.Roles.DONOR)
        .select_related("user")
        .order_by(
            "user__first_name",
            "user__last_name",
        )
    )

    # البحث
    if query:
        sponsors_qs = sponsors_qs.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(national_number__icontains=query)
            | Q(user__email__icontains=query)
        )

    # Pagination
    paginator = Paginator(sponsors_qs, 20)

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "Accounting/sponsors_list.html",
        {
            "title": "الكفلاء",

            # الصفحة الحالية
            "page_obj": page_obj,

            # البيانات التي يستخدمها التصميم الجديد
            "sponsors": page_obj.object_list,

            # البحث
            "query": query,

            # العدد الإجمالي
            "total_count": paginator.count,
        },
    )


@require_POST
@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
@transaction.atomic
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

    user.email = email
    user.username = user.username or email
    user.first_name = first_name
    user.last_name = last_name
    profile.phone = phone
    profile.father_name = father_name
    profile.grandpa_name = grandpa_name
    profile.national_number = national_number
    try:
        user.full_clean(exclude=["password"])
        profile.full_clean()
    except ValidationError as exc:
        return JsonResponse({"success": False, "errors": exc.message_dict}, status=400)
    user.save()
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
# تأكد أن هذه الموديلات مستوردة عندك
# from .models import (
#     FundEntry,
#     FinancialSponsorshipInvoice,
#     SubProgramDisbursement,
# )
# from Management.models import Profile, Beneficiary, MainProgram, SubProgram
# from .decorators import role_required


@role_required([Profile.Roles.ACCOUNTANT])
def accountant_home(request):

    today = timezone.localdate()

    # =====================================================
    # تحديد الفترة
    # =====================================================

    period = request.GET.get("period", "today").strip()

    from_date = today
    to_date = today

    if period == "week":

        from_date = today - timedelta(days=today.weekday())
        to_date = from_date + timedelta(days=6)

    elif period == "month":

        from_date = today.replace(day=1)

        if today.month == 12:
            next_month = today.replace(
                year=today.year + 1,
                month=1,
                day=1,
            )
        else:
            next_month = today.replace(
                month=today.month + 1,
                day=1,
            )

        to_date = next_month - timedelta(days=1)

    elif period == "year":

        from_date = date(today.year, 1, 1)
        to_date = date(today.year, 12, 31)

    elif period == "custom":

        custom_from = request.GET.get(
            "from_date",
            ""
        ).strip()

        custom_to = request.GET.get(
            "to_date",
            ""
        ).strip()

        try:

            from_date = datetime.strptime(
                custom_from,
                "%Y-%m-%d",
            ).date()

            to_date = datetime.strptime(
                custom_to,
                "%Y-%m-%d",
            ).date()

            if from_date > to_date:
                from_date, to_date = to_date, from_date

        except (ValueError, TypeError):

            period = "today"
            from_date = today
            to_date = today

    else:

        period = "today"
        from_date = today
        to_date = today

    # =====================================================
    # رصيد الصندوق الحالي
    # =====================================================

    fund_balance = (
        FundEntry.total_balance()
        or Decimal("0.00")
    )

    # =====================================================
    # حركات الصندوق ضمن الفترة
    # =====================================================

    period_fund_entries = (
        FundEntry.objects.filter(
            created_at__date__range=(
                from_date,
                to_date,
            )
        )
    )

    # =====================================================
    # إيرادات الفترة
    #
    # فقط الإيرادات الحقيقية:
    # - تبرعات عامة
    # - إيرادات كفالات
    #
    # لا نعتبر حركة العكس إيرادًا.
    # =====================================================

    period_revenue = (
        period_fund_entries
        .filter(
            amount__gt=0,
            type__in=[
                FundEntry.Types.GENERAL_DONATION_INCOME,
                FundEntry.Types.SPONSORSHIP_INCOME,
            ],
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    # =====================================================
    # مصروفات الفترة
    #
    # نعتمد على PROGRAM_EXPENSE فقط.
    #
    # المصروف الأصلي:
    #       -250
    #
    # العكس:
    #       +250
    #
    # لذلك نأخذ صافي PROGRAM_EXPENSE.
    # =====================================================

    period_expense_raw = (
        period_fund_entries
        .filter(
            type=FundEntry.Types.PROGRAM_EXPENSE,
        )
        .aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    period_expense = abs(
        period_expense_raw
    )

    # =====================================================
    # عدد الحركات ضمن الفترة
    # =====================================================

    period_movements_count = (
        period_fund_entries.count()
    )

    # =====================================================
    # البرامج
    #
    # أرصدة حالية وليست مرتبطة بالفترة
    # =====================================================

    sub_agg = SubProgram.objects.aggregate(
        allocated_total=Sum("allocated_amount"),
        spent_total=Sum("spent_amount"),
    )

    allocated_total = (
        sub_agg["allocated_total"]
        or Decimal("0.00")
    )

    spent_total = (
        sub_agg["spent_total"]
        or Decimal("0.00")
    )

    remaining_total = (
        allocated_total - spent_total
    )

    # =====================================================
    # إحصائيات النظام
    # =====================================================

    main_programs_count = (
        MainProgram.objects.count()
    )

    sub_programs_count = (
        SubProgram.objects.count()
    )

    beneficiaries_count = (
        Beneficiary.objects.count()
    )

   # =====================================================
# الكفالات
# =====================================================

    expiring_date = (
        today + timedelta(days=30)
    )

    sponsorships_total = (
        FinancialSponsorshipInvoice.objects.count()
    )

    sponsorships_expiring = (
        FinancialSponsorshipInvoice.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
            end_date__lte=expiring_date,
        ).count()
    )

    sponsorships_active = (
        FinancialSponsorshipInvoice.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
        ).exclude(
            end_date__lte=expiring_date,
        ).count()
    )

    sponsorships_expired = (
        FinancialSponsorshipInvoice.objects.filter(
            end_date__lt=today,
        ).count()
    )
    # =====================================================
    # آخر حركات الصندوق ضمن الفترة
    # =====================================================

    last_fund_moves = (
        FundEntry.objects
        .filter(
            created_at__date__range=(
                from_date,
                to_date,
            )
        )
        .select_related(
            "main_program",
            "sub_program",
            "beneficiary",
            "created_by",
        )
        .order_by(
            "-created_at",
            "-id",
        )[:5]
    )

    # =====================================================
    # آخر أوامر الصرف ضمن الفترة
    # =====================================================

    last_disbursements = (
        SubProgramDisbursement.objects
        .filter(
            created_at__date__range=(
                from_date,
                to_date,
            )
        )
        .select_related(
            "sub_program",
            "sub_program__main_program",
            "created_by",
        )
        .order_by(
            "-created_at",
            "-id",
        )[:5]
    )

    # =====================================================
    # اسم الفترة
    # =====================================================

    period_names = {
        "today": "اليوم",
        "week": "هذا الأسبوع",
        "month": "هذا الشهر",
        "year": "هذه السنة",
        "custom": "فترة مخصصة",
    }

    period_name = period_names.get(
        period,
        "اليوم",
    )

    # =====================================================
    # Context
    # =====================================================

    context = {

        "title": "لوحة المحاسب",

        # الفترة
        "period": period,
        "period_name": period_name,
        "from_date": from_date,
        "to_date": to_date,

        # الصندوق
        "available_for_allocation": get_available_for_allocation(),
        "fund_balance": fund_balance,

        # الفترة المالية
        "period_revenue": period_revenue,
        "period_expense": period_expense,
        "period_movements_count": period_movements_count,

        # البرامج
        "allocated_total": allocated_total,
        "spent_total": spent_total,
        "remaining_total": remaining_total,

        "main_programs_count": main_programs_count,
        "sub_programs_count": sub_programs_count,
        "beneficiaries_count": beneficiaries_count,

        # الكفالات
        "sponsorships_total": sponsorships_total,
        "sponsorships_active": sponsorships_active,
        "sponsorships_expiring": sponsorships_expiring,
        "sponsorships_expired": sponsorships_expired,

        "expiring_date": expiring_date,

        # الحركات
        "last_fund_moves": last_fund_moves,
        "last_disbursements": last_disbursements,
    }

    return render(
        request,
        "Accounting/accountant_home.html",
        context,
    )
#عكس عملية الصرف
@role_required([Profile.Roles.ACCOUNTANT])
def reverse_subprogram_disbursement_view(request, pk):

    if request.method != "POST":
        return redirect("Accounting:accountant_home")

    disbursement = get_object_or_404(
        SubProgramDisbursement,
        pk=pk,
    )

    reason = (
        request.POST.get("reason") or ""
    ).strip()

    if not reason:
        messages.error(
            request,
            "يجب كتابة سبب عكس الصرف."
        )
        return redirect(
            "Accounting:accountant_home"
        )

    try:

        reverse_subprogram_disbursement(
            disbursement=disbursement,
            user=request.user,
            reason=reason,
        )

        messages.success(
            request,
            f"تم عكس سند الصرف "
            f"{disbursement.voucher_number} "
            f"بنجاح وإعادة المبلغ إلى رصيد البرنامج."
        )

    except ValueError as ex:

        messages.error(
            request,
            str(ex)
        )

    except Exception as ex:

        messages.error(
            request,
            f"تعذر عكس السند: {ex}"
        )

    return redirect(
        "Accounting:accountant_home"
    )
# 2) تخصيص من الصندوق إلى برنامج رئيسي

# Accounting/views.py


@role_required([Profile.Roles.ACCOUNTANT])
def fund_to_main_allocate(request):
    from .bulk_allocation import allocate_percentages, allocation_token
    if request.method == "POST" and request.POST.get("mode") == "percent":
        try:
            created = allocate_percentages(request.POST, request.user)
        except ValueError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "تم تخصيص المبلغ." if created else "سبق تنفيذ هذا التخصيص.")
        return redirect("Accounting:fund_to_main_allocate")


    # =========================================================
    # سجل التخصيصات الكامل - AJAX داخل Modal
    # =========================================================
   

    # =========================================================
    # البرامج
    # =========================================================
    programs = (
        MainProgram.objects
        .filter(is_active=True)
        .order_by("name")
    )

    fund_balance = get_fund_balance()
    available_for_allocation = get_available_for_allocation()

    # آخر 3 تخصيصات فقط
    last_allocations = (
        AllocationHistory.objects
        .select_related(
            "to_main_program",
            "created_by",
        )
        .filter(
            action=AllocationHistory.Action.FUND_TO_MAIN
        )
        .order_by("-created_at", "-id")[:3]
    )

    # =========================================================
    # POST
    # =========================================================
    if request.method == "POST":

        main_program_id = request.POST.get("main_program")
        amount_raw = (
            request.POST.get("amount") or "0"
        ).strip()
        notes = (
            request.POST.get("notes") or ""
        ).strip()

        try:

            amount = Decimal(amount_raw)

            if amount <= 0:
                raise ValidationError(
                    "أدخل مبلغ صحيح أكبر من صفر."
                )

            mp = get_object_or_404(
                MainProgram,
                id=main_program_id,
                is_active=True,
            )

            allocate_to_main_program(
                main_program=mp,
                amount=amount,
                user=request.user,
                note=notes,
            )

            messages.success(
                request,
                "تم تخصيص المبلغ للبرنامج الرئيسي بنجاح."
            )

            return redirect(
                "Accounting:fund_to_main_allocate"
            )

        except MainProgram.DoesNotExist:

            messages.error(
                request,
                "البرنامج الرئيسي غير موجود."
            )

        except (InvalidOperation, ValidationError) as e:

            messages.error(
                request,
                str(e)
            )

        except Exception as e:

            messages.error(
                request,
                str(e)
            )

    # =========================================================
    # بيانات البرامج
    # =========================================================
    program_data = []

    for p in programs:

        allocated = (
            SubProgram.objects
            .filter(main_program=p)
            .aggregate(
                total=Coalesce(
                    Sum("allocated_amount"),
                    Decimal("0.00"),
                )
            )["total"]
        )

        program_data.append({
            "id": p.id,
            "name": p.name,

            "allocated": allocated,

            "available": get_main_program_balance(p),
        })
    allocation_history = (
    AllocationHistory.objects
    .select_related(
        "to_main_program",
        "created_by",
    )
    .filter(
        action=AllocationHistory.Action.FUND_TO_MAIN
    )
    .order_by("-created_at", "-id")[:5]
    )

    allocation_history_all = (
            AllocationHistory.objects
            .select_related(
                "to_main_program",
                "created_by",
            )
            .filter(
                action=AllocationHistory.Action.FUND_TO_MAIN
            )
            .order_by("-created_at", "-id")
        )
    return render(
        request,
        "Accounting/fund_to_main_allocate.html",
        {
            "title": "تخصيص الصندوق للبرنامج الرئيسي",
            "bulk_token": allocation_token(request.user),

            "programs": programs,

            "fund_balance": fund_balance,

            "available_for_allocation": (
                available_for_allocation
            ),

            "program_data": program_data,

            "allocation_history": allocation_history,

            "allocation_history_all": allocation_history_all,
        },
    )
    ################################################################################


# 3) تحويل من برنامج رئيسي إلى فرعي
# @role_required([Profile.Roles.ACCOUNTANT])
@role_required([Profile.Roles.ACCOUNTANT])
def main_to_sub_allocate(request):

    programs = (
        MainProgram.objects
        .filter(is_active=True)
        .order_by("name")
    )

    sub_programs = (
        SubProgram.objects
        .select_related("main_program")
        .filter(
            main_program__is_active=True,
        )
        .order_by("name")
    )

    if request.method == "POST":

        main_program_id = request.POST.get("main_program")
        sub_program_id = request.POST.get("sub_program")

        amount_raw = (
            request.POST.get("amount") or "0"
        ).strip()

        notes = (
            request.POST.get("notes") or ""
        ).strip()

        try:

            amount = Decimal(amount_raw)

            if amount <= 0:
                raise ValidationError(
                    "أدخل مبلغ صحيح أكبر من صفر."
                )

            mp = get_object_or_404(
                MainProgram,
                id=main_program_id,
                is_active=True,
            )

            sp = get_object_or_404(
                SubProgram,
                id=sub_program_id,
                main_program__is_active=True,
            )

            if sp.main_program_id != mp.id:
                raise ValidationError(
                    "البرنامج الفرعي لا يتبع البرنامج الرئيسي المختار."
                )

            allocate_to_sub_program(
                main_program=mp,
                sub_program=sp,
                amount=amount,
                user=request.user,
                note=notes,
            )

            messages.success(
                request,
                "تم تحويل الرصيد إلى البرنامج الفرعي بنجاح."
            )

            return redirect(
                "Accounting:main_to_sub_allocate"
            )

        except (InvalidOperation, ValidationError) as e:

            messages.error(
                request,
                str(e)
            )

        except Exception as e:

            messages.error(
                request,
                str(e)
            )

    # =========================================================
    # بيانات البرامج الرئيسية
    # =========================================================

    program_data = []

    for p in programs:

        available = get_main_program_balance(p)

        program_data.append({
            "id": p.id,
            "name": p.name,
            "available": available,
        })

    # =========================================================
    # بيانات البرامج الفرعية
    # =========================================================

    sub_program_data = []

    for sp in sub_programs:

        incoming = (
            AllocationHistory.objects
            .filter(
                action=AllocationHistory.Action.MAIN_TO_SUB,
                to_sub_program=sp,
            )
            .aggregate(
                total=Coalesce(
                    Sum("amount"),
                    Decimal("0.00"),
                )
            )["total"]
        )

        returned_to_main = (
            AllocationHistory.objects
            .filter(
                action=AllocationHistory.Action.SUB_TO_MAIN,
                from_sub_program=sp,
            )
            .aggregate(
                total=Coalesce(
                    Sum("amount"),
                    Decimal("0.00"),
                )
            )["total"]
        )

        allocated = (
            incoming
            - returned_to_main
        )

        # الرصيد الحقيقي للبرنامج الفرعي
        available = get_sub_program_balance(sp)

        # المصروف الفعلي
        spent = max(
            allocated - available,
            Decimal("0.00"),
        )

        sub_program_data.append({
            "id": sp.id,
            "name": sp.name,
            "main_id": sp.main_program_id,

            "allocated": allocated,
            "spent": spent,
            "available": available,
        })

    # =========================================================
    # آخر 5 تخصيصات
    # =========================================================

    allocation_history = (
        AllocationHistory.objects
        .select_related(
            "from_main_program",
            "to_sub_program",
            "created_by",
        )
        .filter(
            action=AllocationHistory.Action.MAIN_TO_SUB
        )
        .order_by(
            "-created_at",
            "-id",
        )[:5]
    )

    # =========================================================
    # كامل سجل التخصيصات
    # =========================================================

    allocation_history_all = (
        AllocationHistory.objects
        .select_related(
            "from_main_program",
            "to_sub_program",
            "created_by",
        )
        .filter(
            action=AllocationHistory.Action.MAIN_TO_SUB
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    return render(
        request,
        "Accounting/main_to_sub_allocate.html",
        {
            "title": "تحويل رئيسي إلى فرعي",

            "programs": programs,

            "sub_programs": sub_programs,

            "program_data": program_data,

            "sub_program_data": sub_program_data,

            "allocation_history": allocation_history,

            "allocation_history_all": allocation_history_all,
        },
    )



@role_required([Profile.Roles.ACCOUNTANT])
def subprogram_disburse_create(request):
    """
    إنشاء أمر صرف من برنامج فرعي.

    ملاحظة:
    الكفيل الحالي للمستفيد يُقرأ من BeneficiarySponsorHistory
    وليس من Beneficiary.donor.
    """

    # ---------------------------------------------------------
    # البرامج الفرعية النشطة
    # ---------------------------------------------------------
    sub_programs = (
        SubProgram.objects
        .filter(main_program__is_active=True)
        .select_related("main_program")
        .order_by("name")
    )

    today = timezone.localdate()

    # ---------------------------------------------------------
    # سجلات الكفالة السارية للمستفيدين
    # المصدر المعتمد للكفيل هو BeneficiarySponsorHistory
    # ---------------------------------------------------------
    active_sponsorships = (
        BeneficiarySponsorHistory.objects
        .filter(start_date__lte=today)
        .filter(
            Q(end_date__isnull=True)
            | Q(end_date__gte=today)
        )
        .select_related(
            "donor",
            "donor__user",
        )
        .order_by("-start_date", "-id")
    )

    # ---------------------------------------------------------
    # جلب المستفيدين
    #
    # لا نعتمد على Beneficiary.donor هنا.
    # الكفيل الحالي سيكون داخل:
    # active_sponsorship_list
    # ---------------------------------------------------------
    beneficiaries = (
        Beneficiary.objects
        .exclude(education_level__isnull=True)
        .exclude(education_level="")
        .prefetch_related(
            Prefetch(
                "sponsor_history",
                queryset=active_sponsorships,
                to_attr="active_sponsorship_list",
            )
        )
        .only(
            "id",
            "first_name",
            "father_name",
            "education_level",
            "gender",
            "health_status",
            "type_disease",
            "disease",
            "national_number",
        )
        .order_by("first_name", "father_name")
    )

    # ---------------------------------------------------------
    # تنفيذ الصرف
    # ---------------------------------------------------------
    if request.method == "POST":

        try:
            voucher_number = (
                request.POST.get("voucher_number") or ""
            ).strip()

            if not voucher_number:
                raise ValueError("رقم السند مطلوب.")

            notes = (
                request.POST.get("notes") or ""
            ).strip()

            sub_program = (
                SubProgram.objects
                .select_related("main_program")
                .get(pk=request.POST.get("sub_program"), main_program__is_active=True)
            )

            beneficiary_ids = request.POST.getlist("beneficiary_ids[]")
            amounts = request.POST.getlist("amounts[]")
            if len(beneficiary_ids) != len(amounts) or not beneficiary_ids:
                raise ValueError("قائمة المستفيدين والمبالغ غير متطابقة.")
            if len(set(beneficiary_ids)) != len(beneficiary_ids):
                raise ValueError("لا يمكن تكرار المستفيد في أمر الصرف.")


            # جلب المستفيدين المطلوب صرف المبالغ لهم
            beneficiaries_map = {
                b.id: b
                for b in Beneficiary.objects.filter(
                    id__in=beneficiary_ids
                )
            }

            beneficiaries_data = []

            for beneficiary_id, amount in zip(
                beneficiary_ids,
                amounts,
            ):

                if not beneficiary_id or not beneficiary_id.isdecimal():
                    raise ValueError("معرف المستفيد غير صحيح.")

                amount = Decimal(amount or "0")

                if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
                    raise ValueError("مبلغ الصرف غير صحيح.")

                beneficiary = beneficiaries_map.get(
                    int(beneficiary_id)
                )

                if not beneficiary:
                    raise ValueError("المستفيد غير موجود.")

                beneficiaries_data.append(
                    {
                        "beneficiary": beneficiary,
                        "amount": amount,
                    }
                )

            if not beneficiaries_data:
                raise ValueError(
                    "يجب اختيار مستفيد واحد على الأقل."
                )

            # تنفيذ عملية الصرف من خلال محرك المحاسبة الجديد
            spend_from_sub_program(
                sub_program=sub_program,
                beneficiaries=beneficiaries_data,
                voucher_number=voucher_number,
                user=request.user,
                note=notes,
            )

            messages.success(
                request,
                f"تم تنفيذ الصرف بنجاح. رقم السند: {voucher_number}"
            )

            return redirect(
                "Accounting:subprogram_disburse_create"
            )

        except ValueError as ex:
            messages.error(request, str(ex))

        except SubProgram.DoesNotExist:
            messages.error(
                request,
                "البرنامج الفرعي غير موجود."
            )

        except Beneficiary.DoesNotExist:
            messages.error(
                request,
                "أحد المستفيدين غير موجود."
            )

        except Exception as ex:
            messages.error(
                request,
                str(ex)
            )

    # ---------------------------------------------------------
    # بيانات البرامج الفرعية للواجهة
    # ---------------------------------------------------------
    sub_program_data = [
        {
            "id": sp.id,
            "name": sp.name,
            "main_name": sp.main_program.name,
            "balance": f"{get_sub_program_balance(sp):.2f}",
        }
        for sp in sub_programs
    ]

    # ---------------------------------------------------------
    # آخر عمليات الصرف
    # ---------------------------------------------------------
    last_disbursements = (
        SubProgramDisbursement.objects
        .select_related(
            "sub_program",
            "sub_program__main_program",
            "created_by",
        )
        .order_by(
            "-created_at",
            "-id",
        )[:10]
    )

    # ---------------------------------------------------------
    # عرض الصفحة
    # ---------------------------------------------------------
    return render(
        request,
        "Accounting/subprogram_disburse_form.html",
        {
            "title": "أمر صرف من برنامج فرعي",

            "sub_programs": sub_programs,
            "sub_program_data": sub_program_data,

            # المستفيدون مع سجل الكفالة الساري
            "beneficiaries": beneficiaries,

            "education_levels": (
                Beneficiary.EducationLevel.choices
            ),
            "health_statuses": (
                Beneficiary.HealthStatus.choices
            ),
            "disease_types": (
                Beneficiary.DiseaseType.choices
            ),
            "genders": (
                Beneficiary.Gender.choices
            ),

            "last_disbursements": last_disbursements,
        },
    )

@role_required([Profile.Roles.ACCOUNTANT])
def ledger(request):

    movements = (
        FundEntry.objects
        .select_related(
            "invoice",
            "created_by",
            "main_program",
            "sub_program",
            "beneficiary",
        )
        .order_by("-created_at", "-id")
    )

    # =========================
    # Filters
    # =========================

    today = timezone.localdate()

    period = (
        request.GET.get("period") or "month"
    ).strip()

    date_from = ""
    date_to = ""

    if period == "today":

        date_from = today
        date_to = today

    elif period == "week":

        date_from = today - timezone.timedelta(days=6)
        date_to = today

    elif period == "month":

        date_from = today.replace(day=1)
        date_to = today

    elif period == "year":

        date_from = today.replace(
            month=1,
            day=1,
        )
        date_to = today

    elif period == "custom":

        date_from = (
            request.GET.get("date_from") or ""
        ).strip()

        date_to = (
            request.GET.get("date_to") or ""
        ).strip()

    else:

        date_from = ""
        date_to = ""

    main_program = (
        request.GET.get("main_program") or ""
    ).strip()

    sub_program = (
        request.GET.get("sub_program") or ""
    ).strip()

    movement_type = (
        request.GET.get("type") or ""
    ).strip()

    q = (
        request.GET.get("q") or ""
    ).strip()

    export = request.GET.get("export")

    # =========================
    # Apply Filters
    # =========================

    if date_from:

        movements = movements.filter(
            created_at__date__gte=date_from,
        )

    if date_to:

        movements = movements.filter(
            created_at__date__lte=date_to,
        )

    if main_program:

        movements = movements.filter(
            main_program_id=main_program,
        )

    if sub_program:

        movements = movements.filter(
            sub_program_id=sub_program,
        )

    if movement_type:

        movements = movements.filter(
            type=movement_type,
        )

    if q:

        movements = movements.filter(
            Q(description__icontains=q)
            |
            Q(voucher_number__icontains=q)
            |
            Q(invoice__number__icontains=q)
        )

    # =========================
    # الحركات المعكوسة
    # =========================
    #
    # السند الأصلي:
    # SP-001 = -250
    #
    # السند المعكوس:
    # REV-SP-001 = +250
    #
    # لا نعتبر أي منهما إيرادًا أو مصروفًا
    # في الملخص المحاسبي.
    #
    # لكن تبقى الحركتان ظاهرتين في السجل.
    # =========================

    reversed_vouchers = set(
        SubProgramDisbursement.objects
        .filter(
            is_reversed=True,
        )
        .values_list(
            "voucher_number",
            flat=True,
        )
    )

    reversed_vouchers = {
        str(voucher)
        for voucher in reversed_vouchers
        if voucher
    }

    reversal_vouchers = {
        f"REV-{voucher}"
        for voucher in reversed_vouchers
    }

    # =========================
    # Summary
    # =========================

    # الإيرادات الحقيقية فقط
    #
    # نستبعد:
    # REV-SP-001
    # لأنها عملية عكس وليست إيرادًا جديدًا.
    # =========================

    income_queryset = (
        movements
        .filter(
            amount__gt=0,
        )
        .exclude(
            voucher_number__in=reversal_vouchers,
        )
    )

    total_income = (
        income_queryset
        .aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]
    )

    # =========================
    # المصروفات الحقيقية
    # =========================
    #
    # نستبعد السند الأصلي إذا أصبح معكوسًا.
    # =========================

    expense_queryset = (
        movements
        .filter(
            amount__lt=0,
        )
        .exclude(
            voucher_number__in=reversed_vouchers,
        )
    )

    total_expense = (
        expense_queryset
        .aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]
    )

    # =========================
    # الرصيد الحالي الحقيقي
    # =========================

    current_balance = (
        get_fund_balance()
    )

    # =========================
    # البرامج
    # =========================

    main_programs = (
        MainProgram.objects
        .filter(
            is_active=True,
        )
        .order_by("name")
    )

    sub_programs = (
        SubProgram.objects
        .filter(
            main_program__is_active=True,
        )
        .select_related(
            "main_program",
        )
        .order_by("name")
    )

    # =========================
    # Opening Balance
    # =========================

    first = (
        movements
        .order_by(
            "created_at",
            "id",
        )
        .values(
            "created_at",
            "id",
        )
        .first()
    )

    opening_balance = Decimal("0.00")

    if first:

        opening_balance = (
            FundEntry.objects
            .filter(
                Q(
                    created_at__lt=first["created_at"]
                )
                |
                Q(
                    created_at=first["created_at"],
                    id__lt=first["id"],
                )
            )
            .aggregate(
                total=Coalesce(
                    Sum("amount"),
                    Decimal("0.00"),
                )
            )["total"]
        )

    # =========================
    # Running Balance
    # =========================

    running_balance = opening_balance

    ordered = list(
        movements.order_by(
            "created_at",
            "id",
        )
    )

    for movement in ordered:

        movement.display_voucher = (
            movement.voucher_number
            or (
                movement.invoice.number
                if movement.invoice
                else "—"
            )
        )

        running_balance += movement.amount

        movement.balance_after = (
            running_balance
        )

        # =========================
        # تحديد هل الحركة معكوسة
        # =========================

        movement.is_reversal = (
            movement.voucher_number
            in reversal_vouchers
        )

        movement.is_reversed_original = (
            movement.voucher_number
            in reversed_vouchers
        )

    movements = list(
        reversed(ordered)
    )

    # =========================
    # Export
    # =========================

    if export == "1":

        wb = Workbook()

        ws = wb.active

        ws.title = "Ledger"

        ws.append([
            "السند",
            "التاريخ",
            "البرنامج الرئيسي",
            "البرنامج الفرعي",
            "نوع الحركة",
            "الوصف",
            "مدين",
            "دائن",
            "الرصيد",
        ])

        for movement in movements:

            ws.append([

                movement.display_voucher,

                timezone.localtime(
                    movement.created_at
                ).strftime(
                    "%Y-%m-%d %H:%M"
                ),

                (
                    movement.main_program.name
                    if movement.main_program
                    else ""
                ),

                (
                    movement.sub_program.name
                    if movement.sub_program
                    else ""
                ),

                movement.get_type_display(),

                movement.description or "",

                (
                    float(movement.amount)
                    if movement.amount > 0
                    else ""
                ),

                (
                    abs(float(movement.amount))
                    if movement.amount < 0
                    else ""
                ),

                float(
                    movement.balance_after
                ),
            ])

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

        response["Content-Disposition"] = (
            'attachment; filename="ledger.xlsx"'
        )

        wb.save(response)

        return response

    # =========================
    # Render
    # =========================

    return render(
        request,
        "Accounting/ledger.html",
        {
            "title": "سجل الحركات المالية",

            "movements": movements,

            "main_programs": main_programs,

            "sub_programs": sub_programs,

            "movement_types": (
                FundEntry.Types.choices
            ),

            "total_income": (
                total_income
                or Decimal("0.00")
            ),

            "total_expense": abs(
                total_expense
                or Decimal("0.00")
            ),

            "current_balance": (
                current_balance
            ),

            "filters": {
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "main_program": main_program,
                "sub_program": sub_program,
                "type": movement_type,
                "q": q,
            },
        },
    )

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


@role_required([Profile.Roles.ACCOUNTANT])
def fund_reservations_dashboard(request):

    # =========================================================
    # AJAX: سجل التحويلات الكامل
    # =========================================================
    if request.GET.get("transfer_history") == "1":

        history = (
            AllocationHistory.objects
            .select_related(
                "from_main_program",
                "to_main_program",
                "from_sub_program",
                "to_sub_program",
                "created_by",
            )
            .filter(
                action__in=[
                    AllocationHistory.Action.FUND_TO_MAIN,
                    AllocationHistory.Action.MAIN_TO_FUND,
                    AllocationHistory.Action.MAIN_TO_SUB,
                    AllocationHistory.Action.SUB_TO_MAIN,
                ]
            )
            .order_by("-created_at", "-id")
        )

        date_from = (
            request.GET.get("date_from") or ""
        ).strip()

        date_to = (
            request.GET.get("date_to") or ""
        ).strip()

        q = (
            request.GET.get("q") or ""
        ).strip()

        if date_from:
            history = history.filter(
                created_at__date__gte=date_from
            )

        if date_to:
            history = history.filter(
                created_at__date__lte=date_to
            )

        if q:
            history = history.filter(
                Q(note__icontains=q)
                | Q(reference__icontains=q)
                | Q(from_main_program__name__icontains=q)
                | Q(to_main_program__name__icontains=q)
                | Q(from_sub_program__name__icontains=q)
                | Q(to_sub_program__name__icontains=q)
                | Q(created_by__username__icontains=q)
                | Q(created_by__first_name__icontains=q)
                | Q(created_by__last_name__icontains=q)
            )

        results = []

        for item in history:

            if item.from_sub_program:
                from_name = item.from_sub_program.name
            elif item.from_main_program:
                from_name = item.from_main_program.name
            else:
                from_name = "الصندوق"

            if item.to_sub_program:
                to_name = item.to_sub_program.name
            elif item.to_main_program:
                to_name = item.to_main_program.name
            else:
                to_name = "الصندوق"

            if item.created_by:
                user_name = (
                    item.created_by.get_full_name()
                    or item.created_by.username
                )
            else:
                user_name = "—"

            results.append({
                "id": item.id,

                "date": timezone.localtime(
                    item.created_at
                ).strftime("%Y-%m-%d"),

                "time": timezone.localtime(
                    item.created_at
                ).strftime("%H:%M"),

                "from": from_name,
                "to": to_name,

                "amount": f"{item.amount:,.2f}",

                "note": item.note or "—",

                "user": user_name,

                "reference": (
                    item.reference
                    or "—"
                ),
            })

        return JsonResponse({
            "results": results,
            "count": len(results),
        })

    # =========================================================
    # الرصيد الحالي للصندوق
    # =========================================================

    fund_balance = get_fund_balance()

    available_for_allocation = (
        get_available_for_allocation()
    )

    # =========================================================
    # البرامج
    # =========================================================

    main_programs = (
        MainProgram.objects
        .filter(is_active=True)
        .order_by("name")
    )

    sub_programs = (
        SubProgram.objects
        .select_related("main_program")
        .filter(
            main_program__is_active=True
        )
        .order_by(
            "main_program__name",
            "name",
        )
    )

    # =========================================================
    # آخر التحويلات
    # =========================================================

    transfer_actions = [
        AllocationHistory.Action.FUND_TO_MAIN,
        AllocationHistory.Action.MAIN_TO_FUND,
        AllocationHistory.Action.MAIN_TO_SUB,
        AllocationHistory.Action.SUB_TO_MAIN,
    ]

    recent_transfers = (
        AllocationHistory.objects
        .select_related(
            "from_main_program",
            "to_main_program",
            "from_sub_program",
            "to_sub_program",
            "created_by",
        )
        .filter(
            action__in=transfer_actions
        )
        .order_by(
            "-created_at",
            "-id",
        )[:10]
    )

    # =========================================================
    # إحصائيات
    # =========================================================

    main_programs_count = (
        main_programs.count()
    )

    sub_programs_count = (
        sub_programs.count()
    )

    return render(
        request,
        "Accounting/fund_reservations_dashboard.html",
        {
            "title": "إدارة التخصيصات",

            "fund_balance": fund_balance,

            "available_for_allocation": (
                available_for_allocation
            ),

            "main_programs": main_programs,

            "sub_programs": sub_programs,

            "main_programs_count": (
                main_programs_count
            ),

            "sub_programs_count": (
                sub_programs_count
            ),

            "recent_transfers": (
                recent_transfers
            ),
        },
    )


@role_required([Profile.Roles.ACCOUNTANT])
def beneficiary_supports_report(request):

    today = timezone.localdate()

    period = (request.GET.get("period") or "month").strip()

    date_from = ""
    date_to = ""

    if period == "today":

        date_from = today
        date_to = today

    elif period == "week":

        date_from = today - timezone.timedelta(days=6)
        date_to = today

    elif period == "month":

        date_from = today.replace(day=1)
        date_to = today

    elif period == "year":

        date_from = today.replace(
            month=1,
            day=1,
        )
        date_to = today

    elif period == "custom":

        date_from = (
            request.GET.get("date_from") or ""
        ).strip()

        date_to = (
            request.GET.get("date_to") or ""
        ).strip()

    beneficiary_id = (
        request.GET.get("beneficiary") or ""
    ).strip()

    main_program_id = (
        request.GET.get("main_program") or ""
    ).strip()

    sub_program_id = (
        request.GET.get("sub_program") or ""
    ).strip()

    voucher = (
        request.GET.get("voucher") or ""
    ).strip()

    q = (
        request.GET.get("q") or ""
    ).strip()

    export = request.GET.get("export")

    # =========================
    # جميع العمليات
    # =========================

    entries = (
        BeneficiarySupportEntry.objects
        .select_related(
            "beneficiary",
            "main_program",
            "sub_program",
            "disbursement",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    if not beneficiary_id:
        entries = (
            BeneficiarySupportEntry.objects.none()
        )

    if date_from:

        entries = entries.filter(
            created_at__date__gte=date_from
        )

    if date_to:

        entries = entries.filter(
            created_at__date__lte=date_to
        )

    if beneficiary_id:

        entries = entries.filter(
            beneficiary_id=beneficiary_id
        )

    if main_program_id:

        entries = entries.filter(
            main_program_id=main_program_id
        )

    if sub_program_id:

        entries = entries.filter(
            sub_program_id=sub_program_id
        )

    if voucher:

        entries = entries.filter(
            voucher_number__icontains=voucher
        )

    if q:

        entries = entries.filter(
            Q(note__icontains=q)
            |
            Q(voucher_number__icontains=q)
        )

    # =========================
    # العمليات الفعلية فقط
    #
    # العملية التي تم عكسها
    # تبقى ظاهرة في السجل،
    # لكنها لا تدخل في الحسابات.
    # =========================

    active_entries = entries.filter(
        Q(disbursement__is_reversed=False)
        |
        Q(disbursement__isnull=True)
    )

    # =========================
    # الإحصائيات
    # =========================

    support_count = active_entries.count()

    total_support = (
        active_entries.aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]
        or Decimal("0.00")
    )

    last_support = active_entries.first()

    # =========================
    # المستفيد المحدد
    # =========================

    selected_beneficiary = None

    if beneficiary_id:

        selected_beneficiary = get_object_or_404(
            Beneficiary,
            pk=beneficiary_id,
        )

    # =========================
    # Export
    # =========================

    if export == "1":

        wb = Workbook()

        ws = wb.active

        ws.title = "Beneficiary Statement"

        ws.append([
            "التاريخ",
            "رقم السند",
            "البرنامج الرئيسي",
            "البرنامج الفرعي",
            "المبلغ",
            "الملاحظات",
        ])

        for entry in active_entries:

            ws.append([
                timezone.localtime(
                    entry.created_at
                ).strftime(
                    "%Y-%m-%d %H:%M"
                ),

                entry.voucher_number,

                (
                    entry.main_program.name
                    if entry.main_program
                    else ""
                ),

                (
                    entry.sub_program.name
                    if entry.sub_program
                    else ""
                ),

                float(entry.amount),

                entry.note or "",
            ])

        ws.append([])

        ws.append([
            "",
            "",
            "",
            "إجمالي الدعم",
            float(total_support),
            "",
        ])

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

        response["Content-Disposition"] = (
            'attachment; filename="beneficiary_statement.xlsx"'
        )

        wb.save(response)

        return response

    # =========================
    # Render
    # =========================

    return render(
        request,
        "Accounting/beneficiary_supports_report.html",
        {
            "title": "كشف حساب المستفيد",

            # نرسل جميع العمليات للجدول
            # حتى تبقى عملية العكس ظاهرة للتدقيق
            "entries": active_entries,

            "beneficiaries": (
                Beneficiary.objects
                .order_by(
                    "first_name",
                    "father_name",
                )
            ),

            "main_programs": (
                MainProgram.objects
                .filter(
                    is_active=True,
                )
                .order_by("name")
            ),

            "sub_programs": (
                SubProgram.objects
                .filter(
                    main_program__is_active=True,
                )
                .select_related(
                    "main_program",
                )
                .order_by("name")
            ),

            "selected_beneficiary": (
                selected_beneficiary
            ),

            "support_count": (
                support_count
            ),

            "total_support": (
                total_support
            ),

            "last_support": (
                last_support
            ),

            "filters": {
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "beneficiary": beneficiary_id,
                "main_program": main_program_id,
                "sub_program": sub_program_id,
                "voucher": voucher,
                "q": q,
            },
        },
    )
@role_required(INVOICE_ROLES)
def ajax_beneficiary_search(request):

    q = (request.GET.get("q") or "").strip()

    if len(q) < 2:
        return JsonResponse({"results": []})

    beneficiaries = Beneficiary.objects.all()
    for term in q.split():
        beneficiaries = beneficiaries.filter(
            Q(first_name__icontains=term) | Q(father_name__icontains=term) |
            Q(grand_name__icontains=term) | Q(last_name__icontains=term) |
            Q(national_number__icontains=term))
    beneficiaries = beneficiaries.order_by("first_name", "father_name")[:15]

    results = []

    from django.utils.dateparse import parse_date
    try:
        start = parse_date(request.GET.get("start_date") or "")
        end = parse_date(request.GET.get("end_date") or "")
    except ValueError:
        start = end = None

    for b in beneficiaries:

        blocked_reason = ""
        if request.GET.get("sponsorship") == "1":
            try:
                FinancialSponsorshipAllocation.validate_period(b.pk, start, end)
            except ValidationError as exc:
                blocked_reason = " ".join(exc.messages)

        results.append({
                "id": b.id,
                "name": " ".join(filter(None, (b.first_name, b.father_name, b.grand_name or b.last_name))),
                "identity_number": b.national_number or "",
                "blocked_reason": blocked_reason,
            })

    return JsonResponse({
        "results": results,
    })

#@login_required
@role_required([*INVOICE_ROLES, Profile.Roles.DONOR])
@require_GET
def sponsorship_report_print(request):
    from .report_views import sponsor_print
    return sponsor_print(request)

@role_required([*INVOICE_ROLES, Profile.Roles.DONOR])
@require_GET
def sponsorship_reports(request):
    from .report_views import setup
    return setup(request, association=False)


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT])
@require_GET
def association_reports(request):
    from .report_views import setup
    return setup(request, association=True)


@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT])
@require_GET
def association_report_print(request):
    from .report_views import association_print
    return association_print(request)



# 4) تحرير مبلغ من برنامج فرعي وإعادته إلى البرنامج الرئيسي

@role_required([Profile.Roles.ACCOUNTANT])
def release_sub_program(request):

    sub_programs = (
        SubProgram.objects
        .select_related("main_program")
        .filter(
            main_program__is_active=True,
        )
        .order_by(
            "main_program__name",
            "name",
        )
    )

    last_releases = (
        AllocationHistory.objects
        .select_related(
            "from_sub_program",
            "to_main_program",
            "created_by",
        )
        .filter(
            action=AllocationHistory.Action.SUB_TO_MAIN
        )
        .order_by(
            "-created_at",
            "-id",
        )[:10]
    )

    if request.method == "POST":

        sub_program_id = request.POST.get("sub_program")
        amount_raw = (
            request.POST.get("amount") or "0"
        ).strip()
        notes = (
            request.POST.get("notes") or ""
        ).strip()

        try:

            amount = Decimal(amount_raw)

            if amount <= 0:
                raise ValidationError(
                    "أدخل مبلغ صحيح أكبر من صفر."
                )

            sub_program = get_object_or_404(
                SubProgram.objects.select_related(
                    "main_program"
                ),
                id=sub_program_id,
                main_program__is_active=True,
            )

            release_from_sub_program(
                sub_program=sub_program,
                amount=amount,
                user=request.user,
                note=notes,
            )

            messages.success(
                request,
                "تم تحرير المبلغ وإعادته إلى البرنامج الرئيسي بنجاح."
            )

            return redirect(
                "Accounting:release_sub_program"
            )

        except (InvalidOperation, ValidationError) as e:

            messages.error(
                request,
                str(e)
            )

        except Exception as e:

            messages.error(
                request,
                str(e)
            )

    sub_program_data = []

    for sp in sub_programs:

        sub_program_data.append({
            "id": sp.id,
            "name": sp.name,
            "main_id": sp.main_program_id,
            "main_name": sp.main_program.name,

            "allocated": (
                sp.allocated_amount
                or Decimal("0.00")
            ),

            "spent": (
                sp.spent_amount
                or Decimal("0.00")
            ),

            "available": get_sub_program_balance(sp),
        })

    return render(
        request,
        "Accounting/release_sub_program.html",
        {
            "title": "تحرير من البرنامج الفرعي",

            "sub_programs": sub_programs,

            "sub_program_data": sub_program_data,

            "last_releases": last_releases,
        },
    )

# 5) تحرير مبلغ من البرنامج الرئيسي وإعادته إلى الرصيد المتاح في الصندوق

@role_required([Profile.Roles.ACCOUNTANT])
def release_main_program(request):

    programs = (
        MainProgram.objects
        .filter(is_active=True)
        .order_by("name")
    )

    last_releases = (
        AllocationHistory.objects
        .select_related(
            "from_main_program",
            "created_by",
        )
        .filter(
            action=AllocationHistory.Action.MAIN_TO_FUND
        )
        .order_by(
            "-created_at",
            "-id",
        )[:10]
    )

    if request.method == "POST":

        main_program_id = request.POST.get("main_program")
        amount_raw = (
            request.POST.get("amount") or "0"
        ).strip()
        notes = (
            request.POST.get("notes") or ""
        ).strip()

        try:

            amount = Decimal(amount_raw)

            if amount <= 0:
                raise ValidationError(
                    "أدخل مبلغ صحيح أكبر من صفر."
                )

            main_program = get_object_or_404(
                MainProgram,
                id=main_program_id,
                is_active=True,
            )

            release_from_main_program(
                main_program=main_program,
                amount=amount,
                user=request.user,
                note=notes,
            )

            messages.success(
                request,
                "تم تحرير المبلغ وإعادته إلى الرصيد المتاح في الصندوق بنجاح."
            )

            return redirect(
                "Accounting:release_main_program"
            )

        except (InvalidOperation, ValidationError) as e:

            messages.error(
                request,
                str(e)
            )

        except Exception as e:

            messages.error(
                request,
                str(e)
            )

    program_data = []

    for p in programs:

        # إجمالي ما تم تحويله من الرئيسي إلى البرامج الفرعية
        transferred_to_sub = AllocationHistory.objects.filter(
            action=AllocationHistory.Action.MAIN_TO_SUB,
            from_main_program=p,
        ).aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]

        # إجمالي ما عاد من البرامج الفرعية إلى الرئيسي
        returned_from_sub = AllocationHistory.objects.filter(
            action=AllocationHistory.Action.SUB_TO_MAIN,
            to_main_program=p,
        ).aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]

        # إجمالي الصرف الفعلي من البرامج الفرعية التابعة لهذا الرئيسي
        spent = BeneficiarySupportEntry.objects.filter(
            main_program=p,
        ).aggregate(
            total=Coalesce(
                Sum("amount"),
                Decimal("0.00"),
            )
        )["total"]

        # صافي المبلغ المحول إلى الفروع
        allocated_to_sub = (
            transferred_to_sub
            - returned_from_sub
        )

        # الرصيد المتاح فعليًا داخل الرئيسي
        available = get_main_program_balance(p)

        program_data.append({
            "id": p.id,
            "name": p.name,

            # إجمالي تخصيص البرنامج الرئيسي
            "total": (
                p.total_donation_amount
                or Decimal("0.00")
            ),

            # المبلغ الموجود في الفروع فعليًا
            "allocated": allocated_to_sub,

            # المصروف الفعلي للمستفيدين
            "spent": spent,

            # المتاح داخل البرنامج الرئيسي
            "available": available,
        })
        return render(
        request,
        "Accounting/release_main_program.html",
        {
            "title": "تحرير من البرنامج الرئيسي",

            "programs": programs,

            "program_data": program_data,

            "last_releases": last_releases,
        },
    )


# =========================================================
# البحث عن الكفلاء - AJAX / Select2
# =========================================================

@role_required(INVOICE_ROLES)
def sponsor_search(request):

    q = request.GET.get("q", "").strip()

    sponsors = (
        Profile.objects
        .filter(
            role=Profile.Roles.DONOR,
        )
        .select_related("user")
    )

    if q:

        sponsors = sponsors.filter(
            Q(user__first_name__icontains=q)
            | Q(father_name__icontains=q)
            | Q(grandpa_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
        )

    sponsors = sponsors.order_by(
        "user__first_name",
        "user__last_name",
    )[:30]

    results = []

    for sponsor in sponsors:

        parts = [
            sponsor.user.first_name,
            sponsor.father_name,
            sponsor.grandpa_name,
            sponsor.user.last_name,
        ]

        name = " ".join(
            str(part).strip()
            for part in parts
            if part and str(part).strip()
        )

        name = name or sponsor.user.username

        results.append({
            "id": sponsor.pk,
            "text": name,
        })

    return JsonResponse({
        "results": results,
    })

@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsors_import(request):
    columns = {
        "الاسم الكامل": "full_name",
        "رقم الجوال": "phone", "رقم الهوية": "national_number",
        "البريد الإلكتروني": "email",
    }
    aliases = {
        **columns,
        "الاسم الأول": "first_name", "اسم الأب": "father_name",
        "اسم الجد": "grandpa_name", "اسم العائلة": "last_name",
    }
    fields = DonorUserCreateForm().fields

    def duplicate_reasons(row, seen):
        from django.db.models.functions import Trim
        reasons = []
        profiles = Profile.objects.annotate(
            import_phone=Trim("phone"), import_national_number=Trim("national_number"))
        national_number = row.get("national_number", "")
        if national_number and (national_number in seen["national_number"] or profiles.filter(
                import_national_number=national_number).exists()):
            reasons.append("رقم الهوية")
        email = row.get("email", "")
        if email and (email in seen["email"] or get_user_model().objects.annotate(
                import_email=Trim("email"), import_username=Trim("username")).filter(
                Q(import_email__iexact=email) | Q(import_username__iexact=email)).exists()):
            reasons.append("البريد الإلكتروني")
        phone = row.get("phone", "")
        phone_variants = [phone]
        if len(phone) == 10 and phone.startswith("05") and phone.isdecimal():
            # Compare legacy nine-digit values without changing stored profiles.
            phone_variants.append(phone[1:])
        if phone and (phone in seen["phone"] or profiles.filter(import_phone__in=phone_variants).exists()):
            reasons.append("رقم الجوال")
        return reasons

    if request.method == "GET" and request.GET.get("template") == "1":
        output = io.StringIO(newline="")
        csv.writer(output).writerow(columns)
        response = HttpResponse(output.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="sponsors_template.csv"'
        return response
    summary = None
    error = None
    row_errors = []
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload or upload.size > 2 * 1024 * 1024:
            error = "اختر ملف CSV لا يتجاوز 2 ميجابايت."
        else:
            try:
                reader = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")), strict=True)
                headers = [aliases.get(name.strip(), name.strip()) for name in (reader.fieldnames or [])]
                required = {name for name in columns.values() if name != "full_name" and fields[name].required}
                required.update({"full_name"} if "full_name" in headers else {"first_name", "last_name"})
                missing = required - set(headers)
                if missing:
                    raise ValueError("أعمدة مطلوبة مفقودة: " + "، ".join(label for label, name in aliases.items() if name in missing))
                if len(headers) != len(set(headers)):
                    raise ValueError("توجد أسماء أعمدة مكررة. استخدم عمودًا واحدًا لكل حقل.")
                reader.fieldnames = headers
                rows = list(reader)
                if not rows:
                    raise ValueError("الملف لا يحتوي على بيانات كفلاء. أضف البيانات أسفل أسماء الأعمدة.")
                summary = {"added": 0, "duplicates": 0, "rejected": 0}
                seen = {name: set() for name in ("email", "phone", "national_number")}
                for row_number, row in enumerate(rows, start=2):
                    if None in row or any(value is None for value in row.values()):
                        summary["rejected"] += 1
                        if len(row_errors) < 50:
                            row_errors.append(f"السجل {row_number}: عدد القيم لا يطابق عدد الأعمدة.")
                        continue
                    row = {k: (v or "").strip() for k, v in row.items() if k and isinstance(v, str)}
                    row["email"] = row.get("email", "").lower()
                    phone = row.get("phone", "")
                    if len(phone) == 9 and phone.startswith("5") and phone.isdecimal():
                        row["phone"] = "0" + phone
                    if "full_name" in headers:
                        parts = row.get("full_name", "").split()
                        if len(parts) < 2:
                            summary["rejected"] += 1
                            if len(row_errors) < 50:
                                row_errors.append(f"الصف {row_number}: الاسم الكامل يجب أن يتكون من كلمتين على الأقل.")
                            continue
                        row.update(first_name=parts[0],
                                   father_name=parts[1] if len(parts) >= 3 else "",
                                   grandpa_name=parts[2] if len(parts) >= 4 else "",
                                   last_name=" ".join(parts[3:]) if len(parts) >= 4 else parts[-1])
                    duplicate = duplicate_reasons(row, seen)
                    if duplicate:
                        summary["duplicates"] += 1
                        if len(row_errors) < 50:
                            row_errors.append(f"الصف {row_number}: تم التجاوز بسبب تكرار: {'، '.join(duplicate)}.")
                        continue
                    form = DonorUserCreateForm(row)
                    if not form.is_valid():
                        summary["rejected"] += 1
                        if len(row_errors) < 50:
                            details = "، ".join(fields[name].label if name in fields else "البيانات" for name in form.errors)
                            row_errors.append(f"الصف {row_number}: بيانات مفقودة أو غير صحيحة في: {details}.")
                        continue
                    try:
                        form.save()
                    except (IntegrityError, ValidationError):
                        duplicate = duplicate_reasons(row, seen)
                        summary["duplicates" if duplicate else "rejected"] += 1
                        if len(row_errors) < 50:
                            reason = f"تم التجاوز بسبب تكرار: {'، '.join(duplicate)}." if duplicate else "تعذر إنشاء الكافل؛ تحقق من صحة البيانات."
                            row_errors.append(f"الصف {row_number}: {reason}")
                    else:
                        summary["added"] += 1
                        for name, values in seen.items():
                            if row.get(name):
                                values.add(row[name])
            except (UnicodeDecodeError, csv.Error):
                error = "تعذر قراءة الملف. استخدم CSV بترميز UTF-8 والأعمدة الموضحة."
            except ValueError as exc:
                error = str(exc)
    return render(request, "Accounting/sponsors_import.html", {
        "summary": summary, "error": error, "row_errors": row_errors,
        "columns": [{"label": label, "required": name == "full_name" or fields[name].required} for label, name in columns.items()],
    })


@role_required(INVOICE_ROLES)
@require_GET
def invoice_number_available(request):
    number = (request.GET.get("number") or "").strip()
    if not number or len(number) > Invoice._meta.get_field("number").max_length:
        return JsonResponse({"available": False, "error": "invalid"}, status=400)
    return JsonResponse({"available": not Invoice.objects.filter(number=number).exists()})
