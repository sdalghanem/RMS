from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction, IntegrityError
from django.contrib.auth import get_user_model, login, logout
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.urls import resolve

from .forms import LoginForm, UserWithProfileCreateForm, UserContactEditForm
from .models import Profile , Beneficiary
from Accounting.models import FinancialSponsorshipInvoice
# أعلى الملف:
from .forms import BeneficiaryForm, BeneficiaryFilterForm, BeneficiaryImportForm, BeneficiariesBulkAssignForm , BeneficiariesBulkEducationForm
from django.views.decorators.http import require_http_methods
from django.db.models import Q
import json
from django.utils import timezone
from .models import BeneficiarySponsorHistory
from Accounting.models import FinancialSponsorshipAllocation
from django.db.models.functions import TruncMonth
from django.db.models import Sum
from decimal import Decimal
import json
User = get_user_model()

# -------------------------------------------------------------------
# 🔹 ديكوريتر لتقييد الوصول بالأدوار
# -------------------------------------------------------------------
def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            prof = getattr(user, "profile", None)
            if prof and prof.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("ليست لديك صلاحية الوصول إلى هذه الصفحة.")
        return _wrapped
    return decorator

# -------------------------------------------------------------------
# 🔹 أدوات التوجيه والصلاحيات
# -------------------------------------------------------------------
def _is_system_admin(user):
    prof = getattr(user, "profile", None)
    in_group = user.groups.filter(name="system_admin").exists()
    return user.is_superuser or in_group or (prof and prof.role == Profile.Roles.SYSTEM_ADMIN)

def _redirect_by_role(user):

    profile = getattr(user, "profile", None)

    if (
        user.is_superuser
        or user.groups.filter(
            name="system_admin"
        ).exists()
        or (
            profile
            and profile.role == Profile.Roles.SYSTEM_ADMIN
        )
    ):
        return redirect(
            "Management:dashboard"
        )

    role_redirects = {
        Profile.Roles.DONOR: "Donation:dashboard",
        Profile.Roles.ACCOUNTANT: "Accounting:accountant_home",
        Profile.Roles.CASHIER: "Accounting:cashier_home",
    }

    if profile:
        url_name = role_redirects.get(
            profile.role
        )

        if url_name:
            return redirect(url_name)

    return redirect(
        "Management:landing"
    )
# -------------------------------------------------------------------
# 🔹 صفحة تسجيل الدخول 	hmad@gmail.com
# -------------------------------------------------------------------
def login_view(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    form = LoginForm(request, data=request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # خيار "تذكرني"
            remember = form.cleaned_data.get("remember_me")
            if not remember:
                request.session.set_expiry(0)

            messages.success(request, "تم تسجيل الدخول بنجاح.")

            # احترام next إن كان مسموحًا
            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                if _user_allowed_for_url(user, next_url):
                    return redirect(next_url)
            # توجيه حسب الدور
            return _redirect_by_role(user)
        else:
            messages.error(request, "بيانات الدخول غير صحيحة. تأكد من الإيميل وكلمة المرور.")

    return render(request, "Management/login.html", {"form": form, "title": "تسجيل الدخول"})

# -------------------------------------------------------------------
# 🔹 تسجيل الخروج
# -------------------------------------------------------------------
@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "تم تسجيل الخروج بنجاح.")
    return redirect("Management:login")

# -------------------------------------------------------------------
# 🔹 الصفحة الرئيسية
# -------------------------------------------------------------------
def home(request):
    return render(request, "Management/home.html")

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from .models import MainProgram  # و Beneficiary إن وجد

@method_decorator(login_required, name="dispatch")
class HomeView(TemplateView):
    template_name = "Management/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["programs_count"] = MainProgram.objects.count()
        # ctx["beneficiaries_count"] = Beneficiary.objects.count()
        return ctx

# -------------------------------------------------------------------
# 🔹 إنشاء المستخدمين وإدارة الأدوار
# -------------------------------------------------------------------
def _user_in_group(user, name: str) -> bool:
    return user.groups.filter(name=name).exists()

def _allowed_creation_roles(for_user):
    if for_user.is_superuser:
        return [Profile.Roles.DONOR, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]
    if _user_in_group(for_user, "accountant"):
        return [Profile.Roles.DONOR]
    return []

@login_required
@permission_required("auth.add_user", raise_exception=True)
def create_user_with_profile(request):
    allowed_roles = _allowed_creation_roles(request.user)
    if not allowed_roles:
        raise PermissionDenied("ليست لديك صلاحية إنشاء هذا النوع من الحسابات.")

    if request.method == "POST":
        form = UserWithProfileCreateForm(request.POST, allowed_roles=allowed_roles)
        if form.is_valid():
            role = form.cleaned_data["role"]
            if role not in allowed_roles:
                raise PermissionDenied("لا يُسمح لك بإنشاء هذا الدور.")
            try:
                with transaction.atomic():
                    email = form.cleaned_data["email"].strip().lower()
                    user = User.objects.create_user(
                        username=email,
                        password=form.cleaned_data["password1"],
                        email=email,
                        first_name=form.cleaned_data["first_name"],
                        last_name=form.cleaned_data["last_name"],
                    )
                    Profile.objects.create(
                        user=user,
                        role=role,
                        phone=form.cleaned_data["phone"],
                        national_number=form.cleaned_data["national_number"],
                        father_name=form.cleaned_data.get("father_name") or "",
                        grandpa_name=form.cleaned_data.get("grandpa_name") or "",
                    )
                messages.success(request, "تم إنشاء المستخدم والبروفايل وربط الجروب بنجاح.")
                return redirect("Management:create_user_with_profile")
            except IntegrityError as ie:
                messages.error(request, f"تعذّر الحفظ بسبب تعارض بيانات فريدة: {ie}")
            except Exception as e:
                messages.error(request, f"حدث خطأ غير متوقع: {e}")
    else:
        form = UserWithProfileCreateForm(allowed_roles=allowed_roles)

    return render(request, "Management/create_user_with_profile.html", {"form": form, "title": "إضافة مستخدم جديد"})

# -------------------------------------------------------------------
# 🔹 قائمة المستخدمين (System Admin فقط)
# -------------------------------------------------------------------
@role_required([Profile.Roles.SYSTEM_ADMIN])
@login_required
@permission_required("auth.view_user", raise_exception=True)
def users_list(request):
    q = (request.GET.get("q") or "").strip()
    role = (request.GET.get("role") or "").strip()

    qs = User.objects.select_related("profile") \
        .filter(profile__isnull=False) \
        .exclude(profile__role=Profile.Roles.SYSTEM_ADMIN) \
        .order_by("-id")


    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(profile__phone__icontains=q)
            | Q(profile__national_number__icontains=q)
        )
    if role:
        qs = qs.filter(profile__role=role)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    roles = [
        (Profile.Roles.DONOR, "كافل"),
        (Profile.Roles.ACCOUNTANT, "محاسب"),
        (Profile.Roles.CASHIER, "موظف استقبال"),
    ]

    return render(request, "Management/users_list.html", {
        "page_obj": page_obj,
        "q": q,
        "role": role,
        "roles": roles,
        "title": "قائمة المستخدمين",
    })

# -------------------------------------------------------------------
# 🔹 تعديل / حذف / صلاحيات المستخدم
# -------------------------------------------------------------------
def _allowed_target_roles(for_user):
    if for_user.is_superuser:
        return [Profile.Roles.DONOR, Profile.Roles.ACCOUNTANT, Profile.Roles.CASHIER]
    if _user_in_group(for_user, "accountant"):
        return [Profile.Roles.DONOR]
    return []

@login_required
@permission_required("auth.change_user", raise_exception=True)
def update_user_role(request, user_id):
    if request.method != "POST":
        raise PermissionDenied("طريقة غير مسموحة.")
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id, profile__isnull=False)

    target_role = request.POST.get("role")
    allowed = _allowed_target_roles(request.user)
    if target_role not in allowed:
        raise PermissionDenied("لا تملك صلاحية تغيير الدور إلى هذا الخيار.")

    with transaction.atomic():
        user.profile.role = target_role
        user.profile.save()

    messages.success(request, "تم تحديث الدور بنجاح.")
    return redirect("Management:users_list")

@login_required
@permission_required("auth.delete_user", raise_exception=True)
def delete_user(request, user_id):
    if request.method != "POST":
        raise PermissionDenied("طريقة غير مسموحة.")
    if request.user.id == int(user_id):
        raise PermissionDenied("لا يمكنك حذف حسابك الشخصي.")

    user = get_object_or_404(User, pk=user_id)
    user.delete()
    messages.success(request, "تم حذف المستخدم.")
    return redirect("Management:users_list")

@login_required
@permission_required("auth.change_user", raise_exception=True)
def edit_user_contact(request, user_id):
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id, profile__isnull=False)

    if request.method == "POST":
        form = UserContactEditForm(request.POST, user=user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    new_email = form.cleaned_data["email"].strip().lower()
                    user.email = new_email
                    user.username = new_email
                    user.save(update_fields=["email", "username"])
                    user.profile.phone = form.cleaned_data["phone"]
                    user.profile.save(update_fields=["phone"])
                messages.success(request, "تم تحديث البيانات بنجاح.")
                return redirect("Management:users_list")
            except IntegrityError as ie:
                messages.error(request, f"فشل التعديل بسبب تعارض بيانات فريدة: {ie}")
            except Exception as e:
                messages.error(request, f"فشل التعديل: {e}")
        else:
            messages.error(request, "تحقق من الأخطاء في الحقول أدناه.")
    else:
        form = UserContactEditForm(user=user, initial={
            "email": user.email or user.username,
            "phone": user.profile.phone,
        })

    return render(request, "Management/edit_user_contact.html", {
        "form": form,
        "title": f"تعديل بيانات الاتصال — {user.first_name} {user.last_name}",
        "user_obj": user,
    })

# -------------------------------------------------------------------
# 🔹 صفحات تجريبية للأدوار الأخرى
# -------------------------------------------------------------------
@role_required([Profile.Roles.ACCOUNTANT])
def accountant_home(request):
    return render(request, "Management/role_home.html", {
        "title": "صفحة المحاسب",
        "heading": "مرحبًا بالمحاسب",
        "desc": "هذه صفحة تجريبية لصلاحيات المحاسب."
    })

@role_required([Profile.Roles.DONOR])
def donor_home(request):
    return render(request, "Management/role_home.html", {
        "title": "صفحة الكفيل",
        "heading": "مرحبًا بالكفيل",
        "desc": "هذه صفحة تجريبية لصلاحيات الكفيل."
    })

@role_required([Profile.Roles.CASHIER])
def cashier_home(request):
    return render(request, "Management/role_home.html", {
        "title": "صفحة الكاشير",
        "heading": "مرحبًا بالكاشير",
        "desc": "هذه صفحة تجريبية لصلاحيات الكاشير."
    })



@login_required
def my_profile(request):
    user = request.user
    if request.method == "POST":
        form = UserContactEditForm(request.POST, user=user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    new_email = form.cleaned_data["email"].strip().lower()
                    user.email = new_email
                    user.username = new_email
                    user.save(update_fields=["email", "username"])
                    user.profile.phone = form.cleaned_data["phone"]
                    user.profile.save(update_fields=["phone"])
                messages.success(request, "تم تحديث بيانات ملفك الشخصي بنجاح.")
                return redirect("Management:my_profile")
            except IntegrityError as ie:
                messages.error(request, f"فشل التعديل بسبب تعارض بيانات فريدة: {ie}")
        else:
            messages.error(request, "تحقق من الأخطاء في الحقول أدناه.")
    else:
        form = UserContactEditForm(
            user=user,
            initial={"email": user.email or user.username, "phone": user.profile.phone}
        )
    return render(request, "Management/my_profile.html", {"form": form, "title": "الملف الشخصي"})

#######################################################################################################################################



def _beneficiary_roles():
    return [Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT]

@role_required(_beneficiary_roles())
def beneficiaries_list(request):
    form = BeneficiaryFilterForm(request.GET or None)
    qs = Beneficiary.objects.select_related("donor","donor__user").all().order_by("-created_at")

    if form.is_valid():
        q = form.cleaned_data.get("q") or ""
        gender = form.cleaned_data.get("gender") or ""
        donor = form.cleaned_data.get("donor")
        edu = form.cleaned_data.get("education_level") or ""   # ← جديد

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                Q(father_name__icontains=q) | Q(grand_name__icontains=q) |
                Q(national_number__icontains=q)
            )
        if gender:
            qs = qs.filter(gender=gender)
        if donor:
            qs = qs.filter(donor=donor)
        if edu:                                           # ← جديد
            qs = qs.filter(education_level=edu)


    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = {
        "title": "قائمة المستفيدين",
        "form": form,
        "page_obj": page_obj,
    }

    bulk_form = BeneficiariesBulkAssignForm()
    bulk_edu_form = BeneficiariesBulkEducationForm()
    ctx = {
        "title": "قائمة المستفيدين",
        "form": form,
        "page_obj": page_obj,
        "bulk_form": bulk_form,   # ← أضفناه
        "bulk_edu_form": bulk_edu_form,   # ← جديد

    }

    return render(request, "Management/beneficiaries_list.html", ctx)

@role_required(_beneficiary_roles())
def beneficiary_create(request):
    if request.method == "POST":
        form = BeneficiaryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إضافة المستفيد بنجاح.")
            return redirect("Management:beneficiaries_list")
        messages.error(request, "تعذر الحفظ. تحقق من الحقول.")
    else:
        form = BeneficiaryForm()
    return render(request, "Management/beneficiary_form.html", {"form": form, "title": "إضافة مستفيد"})


@role_required(_beneficiary_roles())
def beneficiary_update(request, pk):
    obj = get_object_or_404(Beneficiary, pk=pk)

    if request.method == "POST":
        form = BeneficiaryForm(request.POST, instance=obj)

        if form.is_valid():

            old_donor = obj.donor

            try:
                with transaction.atomic():

                    beneficiary = form.save()

                    new_donor = beneficiary.donor

                    # إذا تغير الكافل
                    if old_donor != new_donor:

                        # إغلاق سجل الكافل السابق
                        if old_donor:
                            current_history = (
                                BeneficiarySponsorHistory.objects
                                .filter(
                                    beneficiary=beneficiary,
                                    donor=old_donor,
                                    end_date__isnull=True
                                )
                                .order_by("-start_date")
                                .first()
                            )

                            if current_history:
                                current_history.end_date = timezone.localdate()
                                current_history.save(update_fields=["end_date"])

                        # إنشاء سجل جديد للكافل الجديد
                        if new_donor:
                            BeneficiarySponsorHistory.objects.create(
                                beneficiary=beneficiary,
                                donor=new_donor,
                                start_date=timezone.localdate(),
                                assigned_by=request.user,
                            )

                messages.success(request, "تم تعديل بيانات المستفيد.")
                return redirect("Management:beneficiaries_list")

            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")

        else:
            messages.error(request, "تعذر الحفظ. تحقق من الحقول.")

    else:
        form = BeneficiaryForm(instance=obj)

    return render(
        request,
        "Management/beneficiary_form.html",
        {
            "form": form,
            "title": f"تعديل مستفيد — {obj.first_name} {obj.last_name}",
        },
    )
# @role_required(_beneficiary_roles())
# def beneficiary_update(request, pk):
#     obj = get_object_or_404(Beneficiary, pk=pk)
#     if request.method == "POST":
#         form = BeneficiaryForm(request.POST, instance=obj)
#         if form.is_valid():
#             form.save()
#             messages.success(request, "تم تعديل بيانات المستفيد.")
#             return redirect("Management:beneficiaries_list")
#         messages.error(request, "تعذر الحفظ. تحقق من الحقول.")
#     else:
#         form = BeneficiaryForm(instance=obj)
#     return render(request, "Management/beneficiary_form.html", {"form": form, "title": f"تعديل مستفيد — {obj.first_name} {obj.last_name}"})

@role_required(_beneficiary_roles())
@require_http_methods(["POST"])
def beneficiary_delete(request, pk):
    obj = get_object_or_404(Beneficiary, pk=pk)
    obj.delete()
    messages.success(request, "تم حذف المستفيد.")
    return redirect("Management:beneficiaries_list")

@role_required(_beneficiary_roles())
def beneficiaries_import(request):
    """
    يقبل رأس عربي نموذجي:
    الإسم/الاسم, النوع, رقم الهوية, (اختياري) العمر, الدخل, المرحلة الدراسية, الحالة الصحية, المرض, نوع المرض,
    (اختياري) تاريخ الميلاد بالميلادي / تاريخ الميلاد

    ما يحدث:
      - تفكيك الاسم إلى first_name/father_name/grand_name/last_name.
      - تطبيع النوع إلى (male/female).
      - التأكد من "رقم الهوية" وتحويل الأرقام العربية إلى إنجليزية ووجوب 10 أرقام.
      - (اختياري) ضبط المرحلة الدراسية/الحالة الصحية/المرض/نوع المرض إذا توفرت.
      - (جديد) قراءة "تاريخ الميلاد بالميلادي" (أو "تاريخ الميلاد"/مرادفات) وتحويله لتاريخ وكتابته في birth_date.
      - حساب العمر من الميلاد (للتحقّق فقط، لا يُخزّن لأنه @property).
      - استخدام update_or_create على national_number.
    """
    if request.method == "POST":
        form = BeneficiaryImportForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["file"]
            import openpyxl
            from datetime import date, datetime
            from dateutil.relativedelta import relativedelta
            import pandas as pd

            # خرائط التطبيع (مطابقة choices في المودل)
            GENDER_MAP = {
                "ذكر": "male", "انثى": "female", "أنثى": "female",
                "male": "male", "m": "male", "f": "female", "female": "female",
            }
            EDUCATION_MAP = {
                # طفل / روضة
                "طفل": "child", "رضيع": "child",
                "روضة": "kg", "رياض اطفال": "kg", "رياض الأطفال": "kg", "kg": "kg", "k.g": "kg",
                # ابتدائي
                "اول ابتدائي": "p1", "أول ابتدائي": "p1", "1 ابتدائي": "p1", "الاول ابتدائي": "p1", "grade 1": "p1",
                "ثاني ابتدائي": "p2", "2 ابتدائي": "p2", "grade 2": "p2",
                "ثالث ابتدائي": "p3", "3 ابتدائي": "p3", "grade 3": "p3",
                "رابع ابتدائي": "p4", "4 ابتدائي": "p4", "grade 4": "p4",
                "خامس ابتدائي": "p5", "5 ابتدائي": "p5", "grade 5": "p5",
                "سادس ابتدائي": "p6", "6 ابتدائي": "p6", "grade 6": "p6",
                # متوسط
                "اول متوسط": "m1", "أول متوسط": "m1", "1 متوسط": "m1", "grade 7": "m1",
                "ثاني متوسط": "m2", "2 متوسط": "m2", "grade 8": "m2",
                "ثالث متوسط": "m3", "3 متوسط": "m3", "grade 9": "m3",
                # ثانوي
                "اول ثانوي": "h1", "أول ثانوي": "h1", "1 ثانوي": "h1", "grade 10": "h1",
                "ثاني ثانوي": "h2", "2 ثانوي": "h2", "grade 11": "h2",
                "ثالث ثانوي": "h3", "3 ثانوي": "h3", "grade 12": "h3",
            }
            HEALTH_STATUS_MAP = {
                "سليم": "healthy", "healthy": "healthy",
                "مريض": "sick",   "sick": "sick",
            }
            DISEASE_TYPE_MAP = {
                "لا يوجد": "none", "بدون": "none",
                "مزمن": "chronic", "مستعصي": "chronic",
                "مؤقت": "temporary", "غير مستعصي": "temporary",
                "none": "none", "chronic": "chronic", "temporary": "temporary",
            }

            # مرادفات لتاريخ الميلاد
            DOB_CANDIDATES = {
                "تاريخ الميلاد بالميلادي", "تاريخ الميلاد", "ميلاد",
                "Birth Date", "Birthdate", "DOB", "Date of Birth", "DoB",
            }
            # مرادفات للاسم
            NAME_CANDIDATES = {"الإسم", "الاسم", "اسم", "اسم المستفيد", "الاسم الكامل", "Full Name", "Name"}
            # مرادفات للنوع
            GENDER_CANDIDATES = {"النوع", "الجنس", "Gender", "Sex"}
            # مرادفات للهوية
            NID_CANDIDATES = {"رقم الهوية", "الهوية", "National ID", "ID", "Identity Number"}

            # أدوات مساعدة
            def norm(map_, val, default=""):
                if val is None:
                    return default
                s = str(val).strip()
                if s in map_:
                    return map_[s]
                if s.lower() in map_:
                    return map_[s.lower()]
                s2 = " ".join(s.split())
                return map_.get(s2, default)

            AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
            def normalize_digits_to_en(s):
                if s is None:
                    return ""
                return str(s).translate(AR_DIGITS)

            def split_ar_name(full):
                """تفكيك الاسم العربي إلى أربعة أجزاء قدر الإمكان"""
                if not full:
                    return "", "", "", ""
                parts = [p for p in str(full).strip().split() if p]
                parts = (parts + ["", "", "", ""])[:4]
                # لو كلمتين فقط: أول/عائلة
                if parts[2] == "" and parts[3] == "" and len(parts) >= 2:
                    return parts[0], "", "", parts[1]
                return parts[0], parts[1], parts[2], parts[3]

            def parse_excel_date(val):
                """تحويل قيمة إكسل (نص/سيريال/Datetime) إلى datetime.date أو None"""
                if val is None:
                    return None
                if isinstance(val, (pd.Timestamp, datetime)):
                    return val.date()
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    try:
                        origin = pd.Timestamp("1899-12-30")
                        d = origin + pd.to_timedelta(int(val), unit="D")
                        return d.date()
                    except Exception:
                        pass
                d = pd.to_datetime(str(val), errors="coerce", dayfirst=True, infer_datetime_format=True)
                return d.date() if not pd.isna(d) else None

            def compute_age_years(dob, today=None):
                if not dob:
                    return None
                if today is None:
                    today = date.today()
                rd = relativedelta(today, dob)
                return rd.years
            # --- تطبيع عربي/أرقام + مطابقة مرحلة دراسية بالأنماط ---
            AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

            def normalize_digits_to_en(s):
                if s is None:
                    return ""
                return str(s).translate(AR_DIGITS)

            def ar_simplify(s: str) -> str:
                """تبسيط نص عربي: توحيد الألف/الهمزة، إزالة التطويل، مسافات زائدة، تحويل للأحرف الصغيرة."""
                if not s:
                    return ""
                s = normalize_digits_to_en(s)
                s = s.strip()
                # توحيد بعض الحروف
                s = (s
                    .replace("أ", "ا")
                    .replace("إ", "ا")
                    .replace("آ", "ا")
                    .replace("ة", "ه")
                    .replace("ى", "ي")
                    .replace("ـ", "")
                )
                # مسافات متتالية → فراغ واحد
                s = " ".join(s.split())
                return s.lower()

            def map_education(value):
                """
                يحوّل نص المرحلة الدراسية إلى one of:
                child, kg, p1..p6, m1..m3, h1..h3
                يدعم: (أول/اول/اولى/١/1) + (ابتدائي/متوسط/ثانوي) + grade N
                """
                if value is None or str(value).strip() == "":
                    return ""
                raw = str(value)
                t = ar_simplify(raw)

                # حالات سهلة
                if any(k in t for k in ["طفل", "رضيع"]):
                    return "child"
                if any(k in t for k in ["روضه", "روضة", "kg", "k.g"]):
                    return "kg"

                # إنجليزي: grade N
                import re
                m = re.search(r"\bgrade\s*(\d{1,2})\b", t)
                if m:
                    n = int(m.group(1))
                    if 1 <= n <= 6:  return f"p{n}"
                    if 7 <= n <= 9:  return f"m{n-6}"
                    if 10 <= n <= 12: return f"h{n-9}"
                    return ""

                # عربي بالأرقام أو الكلمات
                # استخراج رقم إن وُجد
                m2 = re.search(r"\b([1-6])\b", t)
                m_mid = re.search(r"\b([1-3])\b", t)
                # مؤشرات للمرحلة
                is_primary  = "ابتدائي" in t
                is_middle   = "متوسط"  in t
                is_high     = "ثانوي"  in t

                # كلمات ترتيب عربية
                WORD2NUM = {
                    "اول": 1, "الاول": 1, "اولى": 1,
                    "ثاني": 2, "الثاني": 2,
                    "ثالث": 3, "الثالث": 3,
                    "رابع": 4, "الرابع": 4,
                    "خامس": 5, "الخامس": 5,
                    "سادس": 6, "السادس": 6,
                }
                found_word_num = next((WORD2NUM[w] for w in WORD2NUM.keys() if w in t), None)

                # ابتدائي
                if is_primary:
                    n = None
                    if m2: n = int(m2.group(1))
                    if found_word_num: n = found_word_num
                    if n and 1 <= n <= 6:
                        return f"p{n}"
                    # لو ذكر "ابتدائي" بلا رقم → نتركه فارغ أفضل من تخمين
                    return ""

                # متوسط
                if is_middle:
                    n = None
                    if m_mid: n = int(m_mid.group(1))
                    if found_word_num and found_word_num in (1, 2, 3): n = found_word_num
                    if n and 1 <= n <= 3:
                        return f"m{n}"
                    return ""

                # ثانوي
                if is_high:
                    n = None
                    if m_mid: n = int(m_mid.group(1))
                    if found_word_num and found_word_num in (1, 2, 3): n = found_word_num
                    if n and 1 <= n <= 3:
                        return f"h{n}"
                    return ""

                return ""

            # اقرأ الملف (قيم الصيغ كأرقام)
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active

            # قراءة العناوين
            headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws.rows)]
            H = {h: i for i, h in enumerate(headers)}

            # دالة إيجاد أول مفتاح مطابق
            def find_key(candidates):
                # تطابق مباشر
                for cand in candidates:
                    if cand in H:
                        return cand
                # تطابق يحتوي
                for h in H.keys():
                    if any(cand.lower() in h.lower() for cand in candidates):
                        return h
                return None

            name_key   = find_key(NAME_CANDIDATES)
            gender_key = find_key(GENDER_CANDIDATES)
            nid_key    = find_key(NID_CANDIDATES)
            dob_key    = find_key(DOB_CANDIDATES)  # قد يكون None

            # تحقق من الأعمدة الإلزامية الدنيا
            missing = []
            if not name_key:   missing.append("الاسم")
            if not gender_key: missing.append("النوع")
            if not nid_key:    missing.append("رقم الهوية")
            if missing:
                messages.error(request, f"الأعمدة الإلزامية مفقودة أو غير معرّفة بوضوح: {', '.join(missing)}")
                return render(request, "Management/beneficiaries_import.html", {"form": form, "title": "استيراد مستفيدين"})

            # مفاتيح اختيارية أخرى
            edu_key       = find_key({"المرحلة الدراسية", "التعليم", "Education Level"})
            health_key    = find_key({"الحالة الصحية", "Health Status"})
            disease_key   = find_key({"المرض", "Disease"})
            dtype_key     = find_key({"نوع المرض", "Disease Type"})

            get_cell = lambda row, k: (row[H[k]].value if k and k in H else None)

            created, updated, skipped = 0, 0, 0
            errors = []

            for r, row in enumerate(ws.iter_rows(min_row=2), start=2):
                try:
                    full_name = get_cell(row, name_key)
                    gender_in = get_cell(row, gender_key)
                    nat_raw   = get_cell(row, nid_key)

                    # الهوية: تطبيع أرقام عربية → إنجليزية + تحقق 10 أرقام
                    nat = normalize_digits_to_en(nat_raw).strip()
                    if not nat.isdigit() or len(nat) != 10:
                        skipped += 1
                        errors.append(f"سطر {r}: رقم الهوية غير صالح.")
                        continue

                    # ابحث أو أنشئ بحسب رقم الهوية
                    obj, is_created = Beneficiary.objects.get_or_create(national_number=nat)

                    # الاسم
                    f, fa, gr, la = split_ar_name(full_name)
                    if f:  obj.first_name = str(f)
                    if fa: obj.father_name = str(fa)
                    if gr: obj.grand_name = str(gr)
                    # last_name مطلوب في المودل؛ استخدم المتوفر أو اتركه فارغًا كـ "" (مسموح تقنيًا)
                    obj.last_name = str(la) if la else (obj.last_name or "")

                    # الجنس
                    gnorm = norm(GENDER_MAP, gender_in, default="")
                    if gnorm:
                        obj.gender = gnorm

                    # المرحلة الدراسية (اختياري)
                    # edu_in = get_cell(row, edu_key)
                    # edu = norm(EDUCATION_MAP, edu_in, default="")
                    # if edu:
                    #     obj.education_level = edu
                    edu_in = get_cell(row, edu_key)
                    edu = norm(EDUCATION_MAP, edu_in, default="")
                    if not edu:
                        # محاولة تطبيع ذكي بالأنماط
                        edu = map_education(edu_in)
                    if edu in {"child","kg","p1","p2","p3","p4","p5","p6","m1","m2","m3","h1","h2","h3"}:
                        obj.education_level = edu

                    # الحالة الصحية (healthy/sick فقط)
                    health_in = get_cell(row, health_key)
                    hs = norm(HEALTH_STATUS_MAP, health_in, default="")
                    if hs:
                        obj.health_status = hs

                    # المرض ونوعه (اختياري)
                    dis_in = get_cell(row, disease_key)
                    if dis_in is not None:
                        obj.disease = str(dis_in).strip()
                    dtype_in = get_cell(row, dtype_key)
                    dtype = norm(DISEASE_TYPE_MAP, dtype_in, default="")
                    if dtype:
                        obj.type_disease = dtype

                    # (جديد) تاريخ الميلاد بالميلادي → birth_date
                    if dob_key:
                        dob_val = get_cell(row, dob_key)
                        dob = parse_excel_date(dob_val)
                        if dob:
                            obj.birth_date = dob
                            # حساب العمر (للتحقق/التقرير فقط، لا يُخزّن)
                            _ = compute_age_years(dob)

                    # تحقق أساسي: وجود first_name
                    if not obj.first_name:
                        skipped += 1
                        errors.append(f"سطر {r}: الاسم غير صالح/فارغ.")
                        continue

                    obj.save()
                    if is_created:
                        created += 1
                    else:
                        updated += 1

                except Exception as ex:
                    skipped += 1
                    errors.append(f"سطر {r}: خطأ غير متوقع — {ex}")

            msg = f"تم الاستيراد: مضافة {created} / محدثة {updated} / متجاوزة {skipped}."
            if errors:
                msg += f" أخطاء: {len(errors)} (أظهرنا أول 5)\n- " + "\n- ".join(errors[:5])
                messages.warning(request, msg)
            else:
                messages.success(request, msg)
            return redirect("Management:beneficiaries_list")

    else:
        form = BeneficiaryImportForm()

    return render(request, "Management/beneficiaries_import.html", {"form": form, "title": "استيراد مستفيدين"})

@role_required(_beneficiary_roles())
@require_http_methods(["POST"])
def beneficiaries_bulk_assign(request):

    form = BeneficiariesBulkAssignForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "تعذر تنفيذ عملية الإلحاق. تحقق من البيانات."
        )
        return redirect("Management:beneficiaries_list")

    sponsorship_invoice = form.cleaned_data["sponsorship_invoice"]

    ids_raw = (
        request.POST.get("selected_ids")
        or form.cleaned_data.get("ids")
        or ""
    )

    try:
        ids = [
            int(i.strip())
            for i in ids_raw.split(",")
            if i.strip().isdigit()
        ]
    except (TypeError, ValueError):
        ids = []

    # سند واحد = مستفيد واحد
    if len(ids) != 1:
        messages.error(
            request,
            "يجب اختيار مستفيد واحد فقط لإلحاقه بسند الكفالة."
        )
        return redirect("Management:beneficiaries_list")

    beneficiary_id = ids[0]
    today = timezone.localdate()

    with transaction.atomic():

        sponsorship_invoice = (
            FinancialSponsorshipInvoice.objects
            .select_for_update()
            .select_related(
                "invoice",
                "sponsor",
                "sponsor__user",
            )
            .get(pk=sponsorship_invoice.pk)
        )

        beneficiary = (
            Beneficiary.objects
            .select_for_update()
            .get(pk=beneficiary_id)
        )

        # السند يجب أن يكون ساريًا
        if (
            sponsorship_invoice.start_date > today
            or sponsorship_invoice.end_date < today
        ):
            messages.error(
                request,
                "سند الكفالة المحدد غير ساري حاليًا."
            )
            return redirect("Management:beneficiaries_list")

        # السند لا يمكن استخدامه لأكثر من مستفيد
        if FinancialSponsorshipAllocation.objects.filter(
            sponsorship_invoice=sponsorship_invoice
        ).exists():
            messages.error(
                request,
                "سند الكفالة هذا مرتبط بالفعل بمستفيد."
            )
            return redirect("Management:beneficiaries_list")

        # المستفيد لا يمكن أن يكون لديه كفالة سارية أخرى
        active_history = (
            BeneficiarySponsorHistory.objects
            .filter(
                beneficiary=beneficiary,
                start_date__lte=today,
                end_date__gte=today,
            )
            .select_related(
                "donor",
                "donor__user",
            )
            .first()
        )

        if active_history:

            donor_name = (
                active_history.donor.user.get_full_name()
                or active_history.donor.user.username
            )

            messages.error(
                request,
                (
                    "لا يمكن إلحاق المستفيد بسند جديد. "
                    f"لديه كفالة سارية حاليًا مع "
                    f"{donor_name} حتى "
                    f"{active_history.end_date:%Y-%m-%d}."
                ),
            )

            return redirect("Management:beneficiaries_list")

        # إنشاء تخصيص السند للمستفيد
        FinancialSponsorshipAllocation.objects.create(
            sponsorship_invoice=sponsorship_invoice,
            beneficiary=beneficiary,
            amount=sponsorship_invoice.total_amount,
        )

        # إنشاء سجل تاريخ الكفالة
        # نفس تواريخ السند
        BeneficiarySponsorHistory.objects.create(
            beneficiary=beneficiary,
            donor=sponsorship_invoice.sponsor,
            start_date=sponsorship_invoice.start_date,
            end_date=sponsorship_invoice.end_date,
            assigned_by=request.user,
        )

        # مؤقتًا للتوافق مع بقية النظام
        beneficiary.donor = sponsorship_invoice.sponsor
        beneficiary.save(update_fields=["donor"])

    sponsor_name = (
        sponsorship_invoice.sponsor.user.get_full_name()
        or sponsorship_invoice.sponsor.user.username
    )

    messages.success(
        request,
        (
            f"تم إلحاق المستفيد بنجاح بسند الكفالة "
            f"رقم {sponsorship_invoice.invoice.number} "
            f"مع الكافل {sponsor_name}."
        ),
    )

    return redirect("Management:beneficiaries_list")


@role_required(_beneficiary_roles())
def beneficiaries_template(request):
    """
    تنزيل قالب Excel بالأعمدة الصحيحة
    """
    import openpyxl
    from openpyxl import Workbook
    from django.http import HttpResponse

    wb = Workbook()
    ws = wb.active
    ws.title = "Beneficiaries"

    headers = [
        "first_name","father_name","grand_name","last_name","gender","birth_date",
        "education_level","health_status","disease","type_disease","type_housing",
        "housing_fee","beneficiary_rank","number_of_beneficiary_in_family",
        "national_number","donor_email"
    ]
    ws.append(headers)

    # مثال صف إرشادي (اختياري)
    ws.append(["أحمد","محمد","سعيد","القحطاني","ذكر","2010-01-01","primary","good","", "none","rent", "1500","child","3","1234567890","donor@example.com"])

    # حفظ إلى استجابة HTTP
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="beneficiaries_template.xlsx"'
    wb.save(response)
    return response




@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.ACCOUNTANT])
def beneficiary_detail(request, pk):
    b = get_object_or_404(Beneficiary.objects.select_related("donor","donor__user"), pk=pk)
    return render(request, "Management/beneficiary_detail.html", {
        "title": f"عرض مستفيد — {b.first_name} {b.last_name}",
        "b": b,
    })
from Management.utils.audit import AuditLog
@role_required(_beneficiary_roles())
@require_http_methods(["POST"])
def beneficiaries_bulk_change_education(request):
    form = BeneficiariesBulkEducationForm(request.POST)
    if form.is_valid():
        target_level = form.cleaned_data["education_level"]
        ids_raw = request.POST.get("selected_ids") or form.cleaned_data.get("ids") or ""
        try:
            ids = [int(x) for x in ids_raw.replace("[","").replace("]","").split(",") if str(x).strip().isdigit()]
        except Exception:
            ids = []

        if not ids:
            messages.error(request, "لم يتم تحديد مستفيدين.")
            return redirect("Management:beneficiaries_list")

        updated = Beneficiary.objects.filter(id__in=ids).update(education_level=target_level)
        messages.success(request, f"تم تغيير المرحلة الدراسية لـ {updated} مستفيد/ـين.")
        return redirect("Management:beneficiaries_list")

    messages.error(request, "تعذر تنفيذ العملية. تحقق من المدخلات.")
    return redirect("Management:beneficiaries_list")


# لوحة التحكم 
from Accounting.models import Invoice, FundEntry
from django.db.models import Sum
from datetime import timedelta

@role_required([Profile.Roles.SYSTEM_ADMIN])
def dashboard(request):

    User = get_user_model()

    today = timezone.localdate()
    expiring_date = today + timedelta(days=30)

    beneficiaries_count = Beneficiary.objects.count()

    sponsors_count = Profile.objects.filter(
        role=Profile.Roles.DONOR
    ).count()

    users_count = User.objects.count()

    programs_count = MainProgram.objects.count()

    invoices_count = Invoice.objects.count()

    # =====================================================
    # الكفالات
    # =====================================================

    sponsorships_total = FinancialSponsorshipInvoice.objects.count()

    sponsorships_active = FinancialSponsorshipInvoice.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
    ).count()

    sponsorships_expiring = FinancialSponsorshipInvoice.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
        end_date__lte=expiring_date,
    ).count()

    sponsorships_expired = FinancialSponsorshipInvoice.objects.filter(
        end_date__lt=today,
    ).count()

    # =====================================================
    # الإيرادات / الرصيد
    # =====================================================

    today_income = (
        FundEntry.objects.filter(
            created_at__date=today,
            type__in=[
                FundEntry.Types.GENERAL_DONATION_INCOME,
                FundEntry.Types.SPONSORSHIP_INCOME,
            ],
        ).aggregate(total=Sum("amount"))["total"] or 0
    )

    balance = FundEntry.total_balance()

    # =====================================================
    # إحصائيات الإيرادات لآخر 12 شهر
    # =====================================================

    now = timezone.now()

    start_date = (
        now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        ) - timedelta(days=330)
    )

    monthly_income = (
        FundEntry.objects.filter(
            created_at__gte=start_date,
            type__in=[
                FundEntry.Types.GENERAL_DONATION_INCOME,
                FundEntry.Types.SPONSORSHIP_INCOME,
            ],
        )
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    income_dict = {
        row["month"].strftime("%Y-%m"): float(row["total"])
        for row in monthly_income
    }

    chart_labels = []
    chart_values = []

    current = start_date.replace(day=1)

    while current <= now:

        key = current.strftime("%Y-%m")

        chart_labels.append(
            current.strftime("%m/%Y")
        )

        chart_values.append(
            income_dict.get(key, 0)
        )

        if current.month == 12:
            current = current.replace(
                year=current.year + 1,
                month=1
            )
        else:
            current = current.replace(
                month=current.month + 1
            )

    # =====================================================
    # آخر العمليات
    # =====================================================

    latest_operations = (
        FundEntry.objects
        .select_related(
            "created_by",
            "invoice",
            "beneficiary",
            "main_program",
            "sub_program",
        )
        .order_by("-created_at")[:10]
    )

    latest_activity = (
        AuditLog.objects
        .exclude(action=AuditLog.Actions.REQUEST)
        .exclude(action=AuditLog.Actions.LOGIN)
        .exclude(action=AuditLog.Actions.LOGOUT)
        .select_related("user")
        .order_by("-ts")[:10]
    )

    context = {
        "title": "لوحة تحكم مدير النظام",

        "beneficiaries_count": beneficiaries_count,
        "sponsors_count": sponsors_count,
        "users_count": users_count,
        "programs_count": programs_count,
        "invoices_count": invoices_count,

        "today_income": balance,

        # الكفالات
        "sponsorships_total": sponsorships_total,
        "sponsorships_active": sponsorships_active,
        "sponsorships_expiring": sponsorships_expiring,
        "sponsorships_expired": sponsorships_expired,

        "latest_operations": latest_operations,
        "latest_activity": latest_activity,

        "chart_labels": json.dumps(chart_labels),
        "chart_values": json.dumps(chart_values),
    }

    return render(
        request,
        "Management/dashboard.html",
        context,
    )

# صفحة هبوط


def landing_page(request):

    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    return render(
        request,
        "Management/landing.html",
    )


def help_page(request):
    return render(
        request,
        "Management/help.html",
    )

@role_required([Profile.Roles.SYSTEM_ADMIN, Profile.Roles.CASHIER])
def sponsorships_list(request):

    today = timezone.localdate()
    expiring_date = today + timedelta(days=30)

    sponsorships = (
        FinancialSponsorshipInvoice.objects
        .select_related(
            "invoice",
            "sponsor",
            "sponsor__user",
            "payment_plan",
        )
        .prefetch_related(
            "allocation",
            "allocation__beneficiary",
        )
        .order_by("-start_date", "-invoice__date")
    )

    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    # ---------------------------------------------------------
    # البحث
    # ---------------------------------------------------------

    if q:
        sponsorships = sponsorships.filter(
            Q(invoice__number__icontains=q)
            | Q(sponsor__user__first_name__icontains=q)
            | Q(sponsor__user__last_name__icontains=q)
            | Q(sponsor__user__username__icontains=q)
            | Q(allocation__beneficiary__first_name__icontains=q)
            | Q(allocation__beneficiary__father_name__icontains=q)
            | Q(allocation__beneficiary__grand_name__icontains=q)
            | Q(allocation__beneficiary__last_name__icontains=q)
        ).distinct()

    # ---------------------------------------------------------
    # فلترة الحالة
    # ---------------------------------------------------------

    if status_filter == "active":

        sponsorships = sponsorships.filter(
            start_date__lte=today,
            end_date__gte=today,
        )

    elif status_filter == "expiring":

        sponsorships = sponsorships.filter(
            start_date__lte=today,
            end_date__gte=today,
            end_date__lte=expiring_date,
        )

    elif status_filter == "expired":

        sponsorships = sponsorships.filter(
            end_date__lt=today,
        )

    elif status_filter == "pending":

        sponsorships = sponsorships.filter(
            start_date__gt=today,
        )

    # ---------------------------------------------------------
    # الإحصائيات
    # ---------------------------------------------------------

    total_count = FinancialSponsorshipInvoice.objects.count()

    active_count = FinancialSponsorshipInvoice.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
    ).count()

    expiring_count = FinancialSponsorshipInvoice.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
        end_date__lte=expiring_date,
    ).count()

    expired_count = FinancialSponsorshipInvoice.objects.filter(
        end_date__lt=today,
    ).count()

    pending_count = FinancialSponsorshipInvoice.objects.filter(
        start_date__gt=today,
    ).count()

    # ---------------------------------------------------------
    # تجهيز بيانات العرض
    # ---------------------------------------------------------

    sponsorship_list = []

    for sponsorship in sponsorships:

        # الحالة
        if sponsorship.start_date and today < sponsorship.start_date:

            status = "pending"

        elif sponsorship.end_date and today > sponsorship.end_date:

            status = "expired"

        elif (
            sponsorship.end_date
            and today <= sponsorship.end_date <= expiring_date
        ):

            status = "expiring"

        elif (
            sponsorship.start_date
            and sponsorship.end_date
            and sponsorship.start_date <= today <= sponsorship.end_date
        ):

            status = "active"

        else:

            status = "unknown"

        # التخصيص
        allocation = getattr(
            sponsorship,
            "allocation",
            None,
        )

        beneficiary = (
            allocation.beneficiary
            if allocation
            else None
        )

        # مدة الكفالة
        duration_months = (
            sponsorship.custom_duration_months
            or (
                sponsorship.payment_plan.duration_months
                if sponsorship.payment_plan_id
                and getattr(
                    sponsorship.payment_plan,
                    "duration_months",
                    None,
                )
                else None
            )
        )

        # نجهز قاموس للعرض بدل تعديل الموديل
        sponsorship_list.append(
            {
                "object": sponsorship,

                "invoice": sponsorship.invoice,

                "sponsor": sponsorship.sponsor,

                "beneficiary": beneficiary,

                "status": status,

                "duration_months": duration_months,

                "start_date": sponsorship.start_date,

                "end_date": sponsorship.end_date,

                "amount": sponsorship.total_amount,

                "allocated_amount": sponsorship.allocated_amount,

                "remaining_amount": sponsorship.remaining_amount,
            }
        )

    # ---------------------------------------------------------
    # Pagination
    # ---------------------------------------------------------

    paginator = Paginator(
        sponsorship_list,
        25,
    )

    page_number = request.GET.get("page")

    page_obj = paginator.get_page(
        page_number
    )

    # ---------------------------------------------------------
    # العرض
    # ---------------------------------------------------------

    return render(
        request,
        "Management/sponsorships_list.html",
        {
            "title": "إدارة الكفالات",

            "sponsorships": page_obj.object_list,

            "page_obj": page_obj,

            "total_count": total_count,

            "active_count": active_count,

            "expiring_count": expiring_count,

            "expired_count": expired_count,

            "pending_count": pending_count,

            "today": today,

            "expiring_date": expiring_date,
        },
    )