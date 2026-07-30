from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import get_object_or_404, render
from django.db.models import Sum ,  Min
from Management.forms import LoginForm
from Management.models import Profile , Beneficiary , BeneficiarySponsorHistory
from Accounting.models import BeneficiarySupportEntry
from decimal import Decimal
#from Accounting.models import FinancialSponsorshipInvoice
from Accounting.models import (
    BeneficiarySupportEntry,
    FinancialSponsorshipInvoice,
    FinancialSponsorshipAllocation,
)
from django.db.models import Q



def login_view(request):
    if request.user.is_authenticated:
        if request.user.profile.role == Profile.Roles.SPONSOR:
            return redirect("Donation:dashboard")
        return redirect("Management:home")

    form = LoginForm(request, data=request.POST or None)

    if request.method == "POST":

        if form.is_valid():

            user = form.get_user()

            # السماح للكفلاء فقط
            if user.profile.role != Profile.Roles.DONOR:
                messages.error(request, "هذه الصفحة مخصصة للداعمين فقط.")
                return redirect("Donation:login")

            login(request, user)

            remember = form.cleaned_data.get("remember_me")
            if not remember:
                request.session.set_expiry(0)

            next_url = request.GET.get("next") or request.POST.get("next")

            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
            ):
                return redirect(next_url)

            return redirect("Donation:dashboard")

        messages.error(request, "بيانات الدخول غير صحيحة.")

    return render(
        request,
        "Donation/login.html",
        {
            "form": form,
            "title": "دخول الداعمين",
        },
    )

@login_required(login_url='Donation:login')
def dashboard(request):
    """
    الصفحة الرئيسية للداعم
    """

    profile = request.user.profile

    # ==========================
    # المكفولون
    # ==========================

    beneficiaries = (
        Beneficiary.objects
        .filter(donor=profile)
        .order_by("first_name")[:5]
    )

    beneficiaries_count = Beneficiary.objects.filter(
        donor=profile
    ).count()

    # ==========================
    # جميع عمليات الاستفادة
    # ==========================

    # support_entries = (
    #     BeneficiarySupportEntry.objects
    #     .filter(beneficiary__donor=profile)
    #     .select_related(
    #         "beneficiary",
    #         "sub_program",
    #         "main_program",
    #     )
    # )
        # ==========================
# جميع عمليات الاستفادة حسب فترة الكفالة
# ==========================

    histories = (
        BeneficiarySponsorHistory.objects
        .filter(
            donor=profile,
        )
        .select_related("beneficiary")
    )

    support_entries = BeneficiarySupportEntry.objects.none()

    for history in histories:

        qs = BeneficiarySupportEntry.objects.filter(
            beneficiary=history.beneficiary,
            created_at__date__gte=history.start_date,
        )

        if history.end_date:
            qs = qs.filter(
                created_at__date__lte=history.end_date
            )

        support_entries = support_entries | qs

    support_entries = (
        support_entries
        .select_related(
            "beneficiary",
            "sub_program",
            "main_program",
        )
    )
    # ==========================
    # إجمالي الدعم
    # ==========================

    total_support = (
        support_entries.aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    # ==========================
    # عدد مرات الاستفادة
    # ==========================

    support_count = support_entries.count()

    # ==========================
    # عدد البرامج
    # ==========================

    programs_count = (
        support_entries
        .values("sub_program")
        .distinct()
        .count()
    )

    # ==========================
    # آخر عمليات الاستفادة
    # ==========================

    latest_disbursements = (
        support_entries
        .order_by("-created_at")[:5]
    )

    context = {

        "title": "الرئيسية",

        "beneficiaries": beneficiaries,

        "beneficiaries_count": beneficiaries_count,

        "total_support": total_support,

        "support_count": support_count,

        "programs_count": programs_count,

        "latest_disbursements": latest_disbursements,

    }

    return render(
        request,
        "Donation/dashboard.html",
        context,
    )


@login_required(login_url='Donation:login')
def beneficiaries(request):
    """
    قائمة المكفولين
    """
    beneficiaries = Beneficiary.objects.filter(
    donor=request.user.profile).order_by("first_name")

    context = {
        "beneficiaries": beneficiaries,
        "title": "المكفولون",
    }

    return render(
        request,
        "Donation/beneficiaries.html",
        context,
    )


@login_required(login_url='Donation:login')
def beneficiary_detail(request, pk):
    """
    تفاصيل مكفول للداعم الحالي
    """

    # نتأكد أن المستفيد يتبع لهذا الداعم فقط
    beneficiary = get_object_or_404(
        Beneficiary,
        pk=pk,
        donor=request.user.profile,
    )
    # أول تاريخ تم فيه ربط هذا المستفيد بهذا الكافل
    allocation = (
        FinancialSponsorshipAllocation.objects
        .filter(
            beneficiary=beneficiary,
            sponsorship_invoice__sponsor=request.user.profile,
        )
        .order_by("created_at")
        .first()
    )

    support_entries = BeneficiarySupportEntry.objects.filter(
        beneficiary=beneficiary
    )

    # إذا وجدنا بداية للكفالة نحسب الدعم من ذلك التاريخ فقط
    if allocation:
        support_entries = support_entries.filter(
            created_at__gte=allocation.sponsorship_invoice.start_date
        )

    # support_entries = (
    #     support_entries
    #     .select_related(
    #         "sub_program",
    #         "main_program",
    #     )
    #     .order_by("-created_at")
    # )
    # =====================================
# فترة الكفالة الحالية لهذا الداعم
# =====================================

    history = (
    BeneficiarySponsorHistory.objects
    .filter(
        beneficiary=beneficiary,
        donor=request.user.profile,
    )
    .order_by("-start_date")
    .first()
    )

    support_entries = BeneficiarySupportEntry.objects.filter(
    beneficiary=beneficiary
    )

    if history:

        support_entries = support_entries.filter(
            created_at__date__gte=history.start_date,
        )

        if history.end_date:
            support_entries = support_entries.filter(
                created_at__date__lte=history.end_date,
            )

    support_entries = (
        support_entries
        .select_related(
            "sub_program",
            "main_program",
        )
        .order_by("-created_at")
    )
        # جميع عمليات الدعم للمستفيد
    # support_entries = (
    #     BeneficiarySupportEntry.objects
    #     .filter(beneficiary=beneficiary)
    #     .select_related(
    #         "sub_program",
    #         "main_program",
    #     )
    #     .order_by("-created_at")
    # )

    # إجمالي ما استفاد منه
    total_support = (
        support_entries.aggregate(
            total=Sum("amount")
        )["total"] or 0
    )

    # عدد عمليات الصرف
    support_count = support_entries.count()

    # أسماء البرامج بدون تكرار
    programs = (
        support_entries
        .values_list("sub_program__name", flat=True)
        .distinct()
    )

    # عدد البرامج
    programs_count = programs.count()

    context = {
        "title": "تفاصيل المكفول",

        "beneficiary": beneficiary,

        "support_entries": support_entries,

        "total_support": total_support,

        "support_count": support_count,

        "programs": programs,

        "programs_count": programs_count,
    }

    return render(
        request,
        "Donation/beneficiary_detail.html",
        context,
    )






@login_required(login_url='Donation:login')
def invoices(request):
    """
    عرض جميع سندات الكفالة الخاصة بالداعم
    """

    profile = request.user.profile

    invoices = (
        FinancialSponsorshipInvoice.objects
        .filter(sponsor=profile)
        .select_related(
            "invoice",
            "payment_plan",
        )
        .order_by("-invoice__date")
    )

    context = {
        "title": "السندات",
        "invoices": invoices,
    }

    return render(
        request,
        "Donation/invoices.html",
        context,
    )


# @login_required(login_url='Donation:login')
# def profile(request):
#     """
#     الملف الشخصي
#     """

#     context = {
#         "title": "الملف الشخصي",
#     }

#     return render(request, "Donation/profile.html", context)


from django.shortcuts import get_object_or_404


@login_required(login_url='Donation:login')
def invoice_detail(request, pk):
    """
    تفاصيل سند الكفالة
    """

    invoice = get_object_or_404(
        FinancialSponsorshipInvoice.objects.select_related(
            "invoice",
            "payment_plan",
            "sponsor",
        ),
        pk=pk,
        sponsor=request.user.profile,
    )

    allocations = (
        invoice.allocations
        .select_related(
            "beneficiary",
            "balance_entry",
        )
    )

    beneficiaries_summary = []

    total_support = 0
    total_support_count = 0
    total_programs_set = set()

    for allocation in allocations:

        beneficiary = allocation.beneficiary

        history = (
            BeneficiarySponsorHistory.objects
            .filter(
                beneficiary=beneficiary,
                donor=request.user.profile,
            )
            .order_by("-start_date")
            .first()
        )

        if not history:
            continue

        supports = BeneficiarySupportEntry.objects.filter(
            beneficiary=beneficiary,
            created_at__date__gte=history.start_date,
        )

        if history.end_date:
            supports = supports.filter(
                created_at__date__lte=history.end_date
            )

        beneficiary_total = (
            supports.aggregate(
                total=Sum("amount")
            )["total"] or 0
        )

        beneficiary_count = supports.count()

        beneficiary_programs = (
            supports.values("sub_program")
            .distinct()
            .count()
        )

        last_support = (
            supports.order_by("-created_at")
            .first()
        )

        total_support += beneficiary_total
        total_support_count += beneficiary_count

        total_programs_set.update(
            supports.values_list(
                "sub_program_id",
                flat=True,
            )
        )

        beneficiaries_summary.append({

            "beneficiary": beneficiary,

            "start_date": history.start_date,

            "end_date": history.end_date,

            "total_support": beneficiary_total,

            "support_count": beneficiary_count,

            "programs_count": beneficiary_programs,

            "last_support": last_support,

        })

    context = {

        "title": "تفاصيل السند",

        "invoice": invoice,

        "allocations": allocations,

        "beneficiaries_summary": beneficiaries_summary,

        "total_support": total_support,

        "total_support_count": total_support_count,

        "total_programs": len(total_programs_set),

    }

    return render(
        request,
        "Donation/invoice_detail.html",
        context,
    )

@login_required(login_url="Donation:login")
def profile(request):
    """
    الملف الشخصي للداعم
    """
    profile = request.user.profile
    if request.GET.get("password_changed"):
        messages.success(request, "تم تغيير كلمة المرور بنجاح.")
        

    # ==========================
    # عدد المكفولين الحاليين
    # ==========================

    beneficiaries_count = Beneficiary.objects.filter(
        donor=profile
    ).count()

    # ==========================
    # جميع السندات
    # ==========================

    invoices = (
        FinancialSponsorshipInvoice.objects
        .filter(sponsor=profile)
        .select_related(
            "invoice",
            "payment_plan",
        )
        .order_by("-invoice__date")
    )

    invoices_count = invoices.count()

    # ==========================
    # إجمالي قيمة السندات
    # ==========================

    total_sponsorship = sum(
        invoice.total_amount
        for invoice in invoices
    )

    # ==========================
    # إجمالي استفادة المكفولين
    # ==========================

    from decimal import Decimal

    total_support = Decimal("0.00")

    histories = BeneficiarySponsorHistory.objects.filter(
        donor=profile
    ).select_related("beneficiary")

    for history in histories:

        qs = BeneficiarySupportEntry.objects.filter(
            beneficiary=history.beneficiary,
            created_at__date__gte=history.start_date,
        )

        if history.end_date:
            qs = qs.filter(
                created_at__date__lte=history.end_date
            )

        amount = qs.aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        total_support += amount
    # ==========================
    # تاريخ أول كفالة
    # ==========================

    first_sponsorship = (
        BeneficiarySponsorHistory.objects
        .filter(
            donor=profile
        )
        .aggregate(
            first=Min("start_date")
        )["first"]
    )

    context = {

        "title": "الملف الشخصي",

        "profile": profile,

        "beneficiaries_count": beneficiaries_count,

        "invoices": invoices[:5],

        "invoices_count": invoices_count,

        "total_sponsorship": total_sponsorship,

        "total_support": total_support,

        "first_sponsorship": first_sponsorship,

    }

    return render(
        request,
        "Donation/profile.html",
        context,
    )

