
# Managment/urls.py
from django.urls import path, reverse_lazy
from django.contrib.auth.decorators import login_required
from django.urls import path
from .views import dashboard,create_user_with_profile , users_list ,update_user_role ,delete_user , edit_user_contact ,home , login_view , logout_view , accountant_home , donor_home , cashier_home , my_profile
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView
from .views import beneficiaries_list, beneficiary_create , beneficiary_update , beneficiary_delete , beneficiaries_import , beneficiaries_bulk_assign , beneficiaries_template , beneficiary_detail , beneficiaries_bulk_change_education
from .views_programs import ProgramListView, ProgramDetailView , MainProgramCreateView , SubProgramCreateView , program_toggle 
from . import views_payment_plans # سنضع الفيوز في ملف منفصل منظم

app_name = "Management"

urlpatterns = [
    path("", home, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),

    path("users/create/", create_user_with_profile, name="create_user_with_profile"),
    path("users/", users_list, name="users_list"),  # ✅ صفحة القائمة
    path("users/<int:user_id>/role/", update_user_role, name="update_user_role"),
    path("users/<int:user_id>/delete/", delete_user, name="delete_user"),
    path("users/<int:user_id>/edit/", edit_user_contact, name="edit_user_contact"),  # ← جديد


    # صفحات تجريبية للأدوار الأخرى
    path("accountant/", accountant_home, name="accountant_home"),
    path("donor/", donor_home, name="donor_home"),
    path("cashier/", cashier_home, name="cashier_home"),

    path("me/", my_profile, name="my_profile"),
     # ✅ تغيير كلمة المرور داخل التطبيق (أسماء واضحة وتابعة لـ Management)
    path(
        "password/change/",
        login_required(PasswordChangeView.as_view(
            template_name="Management/password_change_form.html",
            success_url=reverse_lazy("Management:password_change_done")
        )),
        name="password_change",
    ),
    path(
        "password/change/done/",
        login_required(PasswordChangeDoneView.as_view(
            template_name="Management/password_change_done.html"
        )),
        name="password_change_done",
    ),

    path("beneficiaries/", beneficiaries_list, name="beneficiaries_list"),
    path("beneficiaries/new/", beneficiary_create, name="beneficiary_create"),
    path("beneficiaries/<int:pk>/edit/", beneficiary_update, name="beneficiary_update"),
    path("beneficiaries/<int:pk>/delete/", beneficiary_delete, name="beneficiary_delete"),
    path("beneficiaries/import/", beneficiaries_import, name="beneficiaries_import"),
    path("beneficiaries/bulk-assign/", beneficiaries_bulk_assign, name="beneficiaries_bulk_assign"),
    path("beneficiaries/template/", beneficiaries_template, name="beneficiaries_template"),

    path("beneficiaries/<int:pk>/", beneficiary_detail, name="beneficiary_detail"),
    path("beneficiaries/bulk-change-education/", beneficiaries_bulk_change_education, name="beneficiaries_bulk_change_education"),

    path("programs/", ProgramListView.as_view(), name="program_list"),
    path("programs/new/", MainProgramCreateView.as_view(), name="program_create"),
    path("programs/<int:pk>/", ProgramDetailView.as_view(), name="program_detail"),
    path("programs/<int:pk>/sub/new/", SubProgramCreateView.as_view(), name="subprogram_create_from_detail"),
    path("programs/sub/new/", SubProgramCreateView.as_view(), name="subprogram_create"),

    path("payment-plans/", views_payment_plans.payment_plan_list, name="payment_plan_list"),
    path("payment-plans/new/", views_payment_plans.payment_plan_create, name="payment_plan_create"),

        # الجديد: تعديل + حذف
    path("payment-plans/<int:pk>/edit/", views_payment_plans.payment_plan_update, name="payment_plan_update"),
    path("payment-plans/<int:pk>/delete/", views_payment_plans.payment_plan_delete, name="payment_plan_delete"),


    path(
    "programs/<int:pk>/toggle/", program_toggle, name="program_toggle",
),
path(
    "dashboard/",
    dashboard,
    name="dashboard",
),
]
