from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import permission_required
from django.views.decorators.http import require_POST
from .views import role_required
from .models import Profile
# Management/views_programs.py

from django.db.models import (
    Sum,
    F,
    Value,
    DecimalField,
    Q,
    Case,
    When,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, ListView, DetailView
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect

from .models import MainProgram, SubProgram
from .forms import MainProgramForm, SubProgramForm


# ============================================================
# قائمة البرامج
# ============================================================

@method_decorator(role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]), name="dispatch")
class ProgramListView(LoginRequiredMixin , ListView):

    template_name = "Management/programs/list.html"
    context_object_name = "programs"
    paginate_by = 12

    def get_queryset(self):

        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()

        dec12 = DecimalField(
            max_digits=12,
            decimal_places=2
        )

        dec7 = DecimalField(
            max_digits=7,
            decimal_places=2
        )

        qs = (
            MainProgram.objects
            .annotate(
                allocated_sum=Coalesce(
                    Sum("sub_programs__allocated_amount"),
                    Value(0, output_field=dec12),
                    output_field=dec12,
                ),
                spent_sum=Coalesce(
                    Sum("sub_programs__spent_amount"),
                    Value(0, output_field=dec12),
                    output_field=dec12,
                ),
                total_cap=Coalesce(
                    F("total_donation_amount"),
                    Value(0, output_field=dec12),
                    output_field=dec12,
                ),
                program_status=Case(
                    When(
                        is_active=True,
                        then=Value("نشط")
                    ),
                    default=Value("موقوف"),
                ),
            )
        )

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(description__icontains=q)
            )

        qs = qs.annotate(
            pct=Case(
                When(
                    total_cap__gt=Value(
                        0,
                        output_field=dec12
                    ),
                    then=ExpressionWrapper(
                        (
                            F("spent_sum")
                            * Value(
                                100,
                                output_field=dec7
                            )
                        )
                        / F("total_cap"),
                        output_field=dec7,
                    ),
                ),
                default=Value(
                    0,
                    output_field=dec7
                ),
                output_field=dec7,
            )
        )

        if status == "healthy":
            qs = qs.filter(
                pct__lt=Value(
                    80,
                    output_field=dec7
                )
            )

        elif status == "warning":
            qs = qs.filter(
                pct__gte=Value(
                    80,
                    output_field=dec7
                ),
                pct__lt=Value(
                    95,
                    output_field=dec7
                ),
            )

        elif status == "critical":
            qs = qs.filter(
                pct__gte=Value(
                    95,
                    output_field=dec7
                ),
                pct__lt=Value(
                    99.5,
                    output_field=dec7
                ),
            )

        elif status == "exhausted":
            qs = qs.filter(
                pct__gte=Value(
                    99.5,
                    output_field=dec7
                )
            )

        return qs.order_by("-created_at")


# ============================================================
# تفاصيل البرنامج
# ============================================================

@method_decorator(role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]), name="dispatch")
class ProgramDetailView(LoginRequiredMixin , DetailView):

    model = MainProgram
    template_name = "Management/programs/detail.html"
    context_object_name = "program"

    def get_queryset(self):

        dec12 = DecimalField(
            max_digits=12,
            decimal_places=2
        )

        return (
            MainProgram.objects
            .annotate(
                allocated_sum=Coalesce(
                    Sum("sub_programs__allocated_amount"),
                    Value(0, output_field=dec12),
                    output_field=dec12,
                ),
                spent_sum=Coalesce(
                    Sum("sub_programs__spent_amount"),
                    Value(0, output_field=dec12),
                    output_field=dec12,
                ),
            )
            .prefetch_related("sub_programs")
        )

    def get_context_data(self, **kwargs):

        ctx = super().get_context_data(**kwargs)
        program = self.object

        dec12 = DecimalField(
            max_digits=12,
            decimal_places=2
        )

        aggs = program.sub_programs.aggregate(
            allocated=Coalesce(
                Sum("allocated_amount"),
                Value(0, output_field=dec12),
                output_field=dec12,
            ),
            spent=Coalesce(
                Sum("spent_amount"),
                Value(0, output_field=dec12),
                output_field=dec12,
            ),
        )

        total = program.total_donation_amount or 0
        spent = aggs["spent"] or 0
        allocated = aggs["allocated"] or 0
        remaining = total - spent

        pct = (
            spent * 100 / total
            if total
            else 0
        )

        ctx["summary"] = {
            "total": total,
            "allocated": allocated,
            "spent": spent,
            "remaining": remaining,
            "pct": pct,
        }

        ctx["sub_programs"] = (
            program.sub_programs
            .annotate(
                remaining=ExpressionWrapper(
                    F("allocated_amount")
                    - Coalesce(
                        F("spent_amount"),
                        Value(0, output_field=dec12),
                    ),
                    output_field=dec12,
                )
            )
            .order_by("id")
        )

        return ctx


# ============================================================
# إضافة برنامج أساسي
# ============================================================


@method_decorator(role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]), name="dispatch")
@method_decorator(permission_required("Management.add_mainprogram", raise_exception=True), name="dispatch")
class MainProgramCreateView(LoginRequiredMixin , CreateView):

    model = MainProgram
    form_class = MainProgramForm
    template_name = "Management/programs/create.html"

    def get_form(self, form_class=None):

        form = super().get_form(form_class)
        form.request = self.request

        return form

    def form_valid(self, form):

        self.object = form.save()

        messages.success(
            self.request,
            "تم إضافة البرنامج الأساسي بنجاح."
        )

        return HttpResponseRedirect(
            self.get_success_url()
        )

    def get_success_url(self):

        return reverse(
            "Management:program_detail",
            kwargs={
                "pk": self.object.pk
            }
        )


# ============================================================
# إضافة برنامج فرعي
# ============================================================


@method_decorator(role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]), name="dispatch")
@method_decorator(permission_required("Management.add_subprogram", raise_exception=True), name="dispatch")
class SubProgramCreateView(LoginRequiredMixin , CreateView):

    model = SubProgram
    form_class = SubProgramForm
    template_name = "Management/programs/sub_create.html"

    def get_initial(self):

        initial = super().get_initial()

        mp = self.request.GET.get("main_program")

        if mp:
            initial["main_program"] = mp

        return initial

    def get_form(self, form_class=None):

        form = super().get_form(form_class)
        form.request = self.request

        return form

    def get_context_data(self, **kwargs):

        ctx = super().get_context_data(**kwargs)

        mp = (
            self.request.GET.get("main_program")
            or self.get_initial().get("main_program")
        )

        ctx["main_program_id"] = mp

        return ctx

    def form_valid(self, form):

        self.object = form.save()

        messages.success(
            self.request,
            "تم إضافة البرنامج الفرعي بنجاح."
        )

        return HttpResponseRedirect(
            self.get_success_url()
        )

    def get_success_url(self):

        return reverse(
            "Management:program_detail",
            kwargs={
                "pk": self.object.main_program_id
            }
        )


# ============================================================
# تفعيل / إيقاف البرنامج
# ============================================================

@login_required
@permission_required("Management.change_mainprogram", raise_exception=True)
@require_POST
def program_toggle(request, pk):

    program = get_object_or_404(
        MainProgram,
        pk=pk
    )

    program.is_active = not program.is_active

    program.save(
        update_fields=["is_active"]
    )

    if program.is_active:
        messages.success(
            request,
            "تم تفعيل البرنامج بنجاح."
        )
    else:
        messages.success(
            request,
            "تم إيقاف البرنامج بنجاح."
        )

    return redirect(
        "Management:program_list"
    )