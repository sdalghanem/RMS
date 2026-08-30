# Management/urls.py

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordChangeView,
    PasswordChangeDoneView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.urls import path, reverse_lazy

from .views import (
    landing_page,
    help_page,
    dashboard,
    create_user_with_profile,
    users_list,
    update_user_role,
    delete_user,
    edit_user_contact,
    login_view,
    logout_view,
    accountant_home,
    donor_home,
    cashier_home,
    my_profile,
    sponsorships_list,
    beneficiaries_list,
    beneficiary_create,
    beneficiary_update,
    beneficiary_delete,
    beneficiaries_import,
    beneficiaries_bulk_assign,
    beneficiaries_template,
    beneficiary_detail,
    beneficiaries_bulk_change_education,
    sponsorship_edit_dates ,
)

from .views_programs import (
    ProgramListView,
    ProgramDetailView,
    MainProgramCreateView,
    SubProgramCreateView,
    program_toggle,
)

from . import views_payment_plans


app_name = "Management"


urlpatterns = [

    # =========================
    # الصفحة الرئيسية والدخول
    # =========================
    
    path(
        "",
        landing_page,
        name="landing",
    ),

    path(
        "login/",
        login_view,
        name="login",
    ),

    path(
        "logout/",
        logout_view,
        name="logout",
    ),

    path(
        "dashboard/",
        dashboard,
        name="dashboard",
    ),

    path(
        "help/",
        help_page,
        name="help",
    ),

    # =========================
    # الحساب الشخصي
    # =========================

    path(
        "me/",
        my_profile,
        name="my_profile",
    ),

    # =========================
    # تغيير كلمة المرور
    # =========================

    path(
        "password/change/",
        login_required(
            PasswordChangeView.as_view(
                template_name="Management/password_change_form.html",
                success_url=reverse_lazy(
                    "Management:password_change_done"
                ),
            )
        ),
        name="password_change",
    ),

    path(
        "password/change/done/",
        login_required(
            PasswordChangeDoneView.as_view(
                template_name="Management/password_change_done.html"
            )
        ),
        name="password_change_done",
    ),

    # =========================
    # استعادة كلمة المرور
    # =========================

    path(
        "password/reset/",
        PasswordResetView.as_view(
            template_name="Management/password_reset_form.html",
            email_template_name="Management/password_reset_email.txt",
            html_email_template_name="Management/password_reset_email.html",
            subject_template_name="Management/password_reset_subject.txt",
            success_url=reverse_lazy(
                "Management:password_reset_done"
            ),
        ),
        name="password_reset",
    ),

    path(
        "password/reset/done/",
        PasswordResetDoneView.as_view(
            template_name="Management/password_reset_done.html"
        ),
        name="password_reset_done",
    ),

    path(
        "password/reset/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="Management/password_reset_confirm.html",
            success_url=reverse_lazy(
                "Management:password_reset_complete"
            ),
        ),
        name="password_reset_confirm",
    ),

    path(
        "password/reset/complete/",
        PasswordResetCompleteView.as_view(
            template_name="Management/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    # =========================
    # إدارة المستخدمين
    # =========================

    path(
        "users/",
        users_list,
        name="users_list",
    ),

    path(
        "users/create/",
        create_user_with_profile,
        name="create_user_with_profile",
    ),

    path(
        "users/<int:user_id>/role/",
        update_user_role,
        name="update_user_role",
    ),

    path(
        "users/<int:user_id>/edit/",
        edit_user_contact,
        name="edit_user_contact",
    ),

    path(
        "users/<int:user_id>/delete/",
        delete_user,
        name="delete_user",
    ),

    # =========================
    # لوحات الأدوار
    # =========================

    path(
        "accountant/",
        accountant_home,
        name="accountant_home",
    ),

    path(
        "donor/",
        donor_home,
        name="donor_home",
    ),

    path(
        "cashier/",
        cashier_home,
        name="cashier_home",
    ),

    # =========================
    # المستفيدون
    # =========================

    path(
        "beneficiaries/",
        beneficiaries_list,
        name="beneficiaries_list",
    ),

    path(
        "beneficiaries/new/",
        beneficiary_create,
        name="beneficiary_create",
    ),

    path(
        "beneficiaries/import/",
        beneficiaries_import,
        name="beneficiaries_import",
    ),

    path(
        "beneficiaries/template/",
        beneficiaries_template,
        name="beneficiaries_template",
    ),

    path(
        "beneficiaries/bulk-assign/",
        beneficiaries_bulk_assign,
        name="beneficiaries_bulk_assign",
    ),

    path(
        "beneficiaries/bulk-change-education/",
        beneficiaries_bulk_change_education,
        name="beneficiaries_bulk_change_education",
    ),

    path(
        "beneficiaries/<int:pk>/",
        beneficiary_detail,
        name="beneficiary_detail",
    ),

    path(
        "beneficiaries/<int:pk>/edit/",
        beneficiary_update,
        name="beneficiary_update",
    ),

    path(
        "beneficiaries/<int:pk>/delete/",
        beneficiary_delete,
        name="beneficiary_delete",
    ),

    # =========================
    # البرامج
    # =========================

    path(
        "programs/",
        ProgramListView.as_view(),
        name="program_list",
    ),

    path(
        "programs/new/",
        MainProgramCreateView.as_view(),
        name="program_create",
    ),

    path(
        "programs/<int:pk>/",
        ProgramDetailView.as_view(),
        name="program_detail",
    ),

    path(
        "programs/<int:pk>/sub/new/",
        SubProgramCreateView.as_view(),
        name="subprogram_create_from_detail",
    ),

    path(
        "programs/sub/new/",
        SubProgramCreateView.as_view(),
        name="subprogram_create",
    ),

    path(
        "programs/<int:pk>/toggle/",
        program_toggle,
        name="program_toggle",
    ),

    # =========================
    # خطط السداد
    # =========================

    path(
        "payment-plans/",
        views_payment_plans.payment_plan_list,
        name="payment_plan_list",
    ),

    path(
        "payment-plans/new/",
        views_payment_plans.payment_plan_create,
        name="payment_plan_create",
    ),

    path(
        "payment-plans/<int:pk>/edit/",
        views_payment_plans.payment_plan_update,
        name="payment_plan_update",
    ),

    path(
        "payment-plans/<int:pk>/delete/",
        views_payment_plans.payment_plan_delete,
        name="payment_plan_delete",
    ),

    # =========================
    # الكفالات
    # =========================

    path(
        "sponsorships/",
        sponsorships_list,
        name="sponsorships_list",
    ),
    path(
    "sponsorships/<int:pk>/edit-dates/",
    sponsorship_edit_dates,
    name="sponsorship_edit_dates",
),
]