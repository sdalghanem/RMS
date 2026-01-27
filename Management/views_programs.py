# Management/views_programs.py
from django.db.models import Sum, F, Value, DecimalField, Q, Case, When, ExpressionWrapper
from django.db.models.functions import Coalesce

from .models import MainProgram, SubProgram

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView, DetailView
from django.urls import reverse
from django.http import HttpResponseRedirect
# ... باقي الاستيرادات ...
from .forms import MainProgramForm, SubProgramForm

from .mixins import RoleRequiredMixin  # 👈 أضف هذا

@method_decorator(login_required, name="dispatch")
class ProgramListView(RoleRequiredMixin ,ListView):
    template_name = "Management/programs/list.html"
    context_object_name = "programs"
    paginate_by = 12

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()  # all|healthy|warning|critical|exhausted

        dec12 = DecimalField(max_digits=12, decimal_places=2)
        dec7  = DecimalField(max_digits=7,  decimal_places=2)

        qs = (
            MainProgram.objects
            .annotate(
                allocated_sum=Coalesce(Sum("sub_programs__allocated_amount"),
                                       Value(0, output_field=dec12), output_field=dec12),
                spent_sum=Coalesce(Sum("sub_programs__spent_amount"),
                                   Value(0, output_field=dec12), output_field=dec12),
                total_cap=Coalesce(F("total_donation_amount"),
                                   Value(0, output_field=dec12), output_field=dec12),
            )
        )

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

        # نسبة الصرف = spent_sum * 100 / total_cap
        qs = qs.annotate(
            pct=Case(
                When(total_cap__gt=Value(0, output_field=dec12),
                     then=ExpressionWrapper(
                         (F("spent_sum") * Value(100, output_field=dec7)) / F("total_cap"),
                         output_field=dec7
                     )),
                default=Value(0, output_field=dec7),
                output_field=dec7
            )
        )

        # فلترة حسب الحالة
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

        return qs.order_by("-created_at")


@method_decorator(login_required, name="dispatch")
class ProgramDetailView(RoleRequiredMixin , DetailView):
    model = MainProgram
    template_name = "Management/programs/detail.html"
    context_object_name = "program"

    def get_queryset(self):
        dec12 = DecimalField(max_digits=12, decimal_places=2)
        return (
            MainProgram.objects
            .annotate(
                allocated_sum=Coalesce(Sum("sub_programs__allocated_amount"),
                                       Value(0, output_field=dec12), output_field=dec12),
                spent_sum=Coalesce(Sum("sub_programs__spent_amount"),
                                   Value(0, output_field=dec12), output_field=dec12),
            )
            .prefetch_related("sub_programs")
        )

    def get_context_data(self, **kwargs):
        """
        يمرّر sub_programs (مع remaining محسوب) وملخّص summary لاستخدامهما في القالب.
        """
        ctx = super().get_context_data(**kwargs)
        program: MainProgram = self.object

        dec12 = DecimalField(max_digits=12, decimal_places=2)

        # ملخص التجميع
        aggs = program.sub_programs.aggregate(
            allocated=Coalesce(Sum("allocated_amount"), Value(0, output_field=dec12), output_field=dec12),
            spent=Coalesce(Sum("spent_amount"), Value(0, output_field=dec12), output_field=dec12),
        )
        total = program.total_donation_amount or 0
        spent = aggs["spent"] or 0
        allocated = aggs["allocated"] or 0
        remaining = (total or 0) - (spent or 0)
        pct = (spent * 100 / total) if total else 0

        ctx["summary"] = {
            "total": total,
            "allocated": allocated,
            "spent": spent,
            "remaining": remaining,
            "pct": pct,
        }

        # البرامج الفرعية مع حقل remaining محسوب
        ctx["sub_programs"] = (
            program.sub_programs
            .annotate(
                remaining=ExpressionWrapper(
                    F("allocated_amount") - Coalesce(F("spent_amount"), Value(0, output_field=dec12)),
                    output_field=dec12
                )
            )
            .order_by("id")
        )

        return ctx


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("Management.add_mainprogram", raise_exception=True), name="dispatch")
class MainProgramCreateView(RoleRequiredMixin , CreateView):
    model = MainProgram
    form_class = MainProgramForm
    template_name = "Management/programs/create.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # احقِن request داخل الفورم (بدون تمرير kwargs)
        form.request = self.request
        # أخفِ حقل المبلغ لمدير النظام
        if self.request.user.groups.filter(name="system_admin").exists():
            form.fields.pop("total_donation_amount", None)
        return form

    def form_valid(self, form):
        obj = form.save(commit=False)
        if self.request.user.groups.filter(name="system_admin").exists():
            obj.total_donation_amount = 0
            obj.remaining_amount = 0
        else:
            obj.remaining_amount = obj.total_donation_amount or 0
        obj.save()

        # لا نستدعي super().form_valid لتجنّب save ثانٍ
        self.object = obj
        messages.success(self.request, "تم إضافة البرنامج الأساسي بنجاح.")
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("Management:program_detail", kwargs={"pk": self.object.pk})


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("Management.add_subprogram", raise_exception=True), name="dispatch")
class SubProgramCreateView(RoleRequiredMixin , CreateView):
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
        # إخفاء المخصص لمدير النظام
        if self.request.user.groups.filter(name="system_admin").exists():
            form.fields.pop("allocated_amount", None)
        return form

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # استخرج رقم البرنامج الرئيسي من GET أو initial
        mp = self.request.GET.get("main_program") or self.get_initial().get("main_program")
        ctx["main_program_id"] = mp
        return ctx

    def form_valid(self, form):
        obj = form.save(commit=False)
        if self.request.user.groups.filter(name="system_admin").exists():
            obj.allocated_amount = 0
        obj.save()

        # لا نستدعي super().form_valid لتجنّب save ثانٍ
        self.object = obj
        messages.success(self.request, "تم إضافة البرنامج الفرعي بنجاح.")
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("Management:program_detail", kwargs={"pk": self.object.main_program_id})
