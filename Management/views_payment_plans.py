# Management/views_payment_plans.py  (ملف جديد أو ضمّه لملف الفيوز عندك)
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import PaymentPlan
from .forms import PaymentPlanForm

# Management/views_payment_plans.py
from django.contrib import messages


def _require_superuser(request):
    if not request.user.is_authenticated:
        return False
    return request.user.is_superuser  # أو staff حسب ما تفضّل

@login_required
def payment_plan_list(request):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    plans = PaymentPlan.objects.order_by("-created_at")
    return render(request, "Management/payment_plans/list.html", {"plans": plans, "title": "إدارة الدفعات"})

@login_required
def payment_plan_create(request):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    if request.method == "POST":
        form = PaymentPlanForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse("Management:payment_plan_list"))
    else:
        form = PaymentPlanForm()
    return render(request, "Management/payment_plans/create.html", {"form": form, "title": "إضافة خطة دفع"})



def _require_superuser(request):
    return request.user.is_authenticated and request.user.is_superuser

@login_required
def payment_plan_list(request):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    plans = PaymentPlan.objects.order_by("-created_at")
    return render(request, "Management/payment_plans/list.html", {
        "plans": plans,
        "title": "إدارة الدفعات"
    })

@login_required
def payment_plan_create(request):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    if request.method == "POST":
        form = PaymentPlanForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تمت إضافة الخطة بنجاح.")
            return redirect(reverse("Management:payment_plan_list"))
        messages.error(request, "تحقق من الحقول.")
    else:
        form = PaymentPlanForm()
    return render(request, "Management/payment_plans/create.html", {
        "form": form,
        "title": "إضافة خطة دفع"
    })

@login_required
def payment_plan_update(request, pk):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    plan = get_object_or_404(PaymentPlan, pk=pk)
    if request.method == "POST":
        form = PaymentPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث الخطة بنجاح.")
            return redirect(reverse("Management:payment_plan_list"))
        messages.error(request, "تحقق من الحقول.")
    else:
        form = PaymentPlanForm(instance=plan)
    return render(request, "Management/payment_plans/edit.html", {
        "form": form,
        "title": f"تعديل: {plan}",
        "plan": plan,
    })

@login_required
def payment_plan_delete(request, pk):
    if not _require_superuser(request):
        return HttpResponseForbidden("غير مصرح")
    plan = get_object_or_404(PaymentPlan, pk=pk)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "تم حذف الخطة بنجاح.")
        return redirect(reverse("Management:payment_plan_list"))
    # GET -> صفحة تأكيد بسيطة (للأمان إن لم تعمل النافذة المنبثقة)
    return render(request, "Management/payment_plans/confirm_delete.html", {
        "title": "تأكيد الحذف",
        "plan": plan,
    })
