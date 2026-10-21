from functools import wraps
from django.http import HttpResponseForbidden
from django.utils import timezone
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



def donor_required(view):
    @login_required(login_url="Donation:login")
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != Profile.Roles.DONOR:
            return HttpResponseForbidden("هذه الصفحة مخصصة للداعمين فقط.")
        return view(request, *args, **kwargs)
    return wrapped


def _current_beneficiaries(profile):
    today = timezone.localdate()
    histories = BeneficiarySponsorHistory.objects.filter(
        donor=profile, start_date__lte=today,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
    return Beneficiary.objects.filter(pk__in=histories.values("beneficiary_id"))


def _valid_supports():
    return BeneficiarySupportEntry.objects.filter(
        Q(disbursement__is_reversed=False) | Q(disbursement__isnull=True)
    )


def _sponsored_supports(profile, beneficiary=None, start=None, end=None):
    histories = BeneficiarySponsorHistory.objects.filter(donor=profile)
    if beneficiary is not None:
        histories = histories.filter(beneficiary=beneficiary)
    periods = Q(pk__in=[])
    for history in histories:
        lower = max(history.start_date, start) if start else history.start_date
        upper = min(history.end_date, end) if history.end_date and end else history.end_date or end
        if upper and lower > upper:
            continue
        period = Q(beneficiary_id=history.beneficiary_id, created_at__date__gte=lower)
        if upper:
            period &= Q(created_at__date__lte=upper)
        periods |= period
    return _valid_supports().filter(periods)


def login_view(request):
    if request.user.is_authenticated:
        if getattr(getattr(request.user, "profile", None), "role", None) == Profile.Roles.DONOR:
            return redirect("Donation:dashboard")
        return redirect("Management:landing")

    form = LoginForm(request, data=request.POST or None)

    if request.method == "POST":

        if form.is_valid():

            user = form.get_user()

            # السماح للكفلاء فقط
            if getattr(getattr(user, "profile", None), "role", None) != Profile.Roles.DONOR:
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

@donor_required
def dashboard(request):
    """
    الصفحة الرئيسية للداعم
    """

    profile = request.user.profile

    # ==========================
    # المكفولون
    # ==========================

    beneficiaries = (
        _current_beneficiaries(profile)
        .order_by("first_name")[:5]
    )

    beneficiaries_count = _current_beneficiaries(profile).count()

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

    support_entries = _sponsored_supports(profile).select_related(
        "beneficiary", "sub_program", "main_program"
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


@donor_required
def beneficiaries(request):
    """
    قائمة المكفولين
    """
    beneficiaries = _current_beneficiaries(request.user.profile).order_by("first_name")

    context = {
        "beneficiaries": beneficiaries,
        "title": "المكفولون",
    }

    return render(
        request,
        "Donation/beneficiaries.html",
        context,
    )


@donor_required
def beneficiary_detail(request, pk):
    """
    تفاصيل مكفول للداعم الحالي
    """

    # نتأكد أن المستفيد يتبع لهذا الداعم فقط
    beneficiary = get_object_or_404(
        _current_beneficiaries(request.user.profile),
        pk=pk,
    )
    support_entries = _sponsored_supports(
        request.user.profile, beneficiary=beneficiary
    ).select_related("sub_program", "main_program").order_by("-created_at")

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






@donor_required
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


@donor_required
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
        FinancialSponsorshipAllocation.objects.filter(sponsorship_invoice=invoice)
        .select_related("beneficiary")
    )

    beneficiaries_summary = []

    total_support = 0
    total_support_count = 0
    total_programs_set = set()

    for allocation in allocations:

        beneficiary = allocation.beneficiary

        supports = _sponsored_supports(
            request.user.profile, beneficiary=beneficiary,
            start=invoice.start_date, end=invoice.end_date,
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

            "start_date": invoice.start_date,

            "end_date": invoice.end_date,

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

@donor_required
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

    beneficiaries_count = _current_beneficiaries(profile).count()

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

    total_support = _sponsored_supports(profile).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

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

