from django.urls import path
from . import views

app_name = "Accounting"

urlpatterns = [
    path(
    "cashier/",
    views.cashier_home,
    name="cashier_home",
    ) ,


    path("invoices/", views.cashier_invoices_list, name="cashier_invoices_list"),
    path("invoices/create/general/", views.invoice_create_general, name="invoice_create_general"),
    path("invoices/create/sponsorship/", views.invoice_create_sponsorship, name="invoice_create_sponsorship"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("sponsorships/<int:pk>/allocations/", views.sponsorship_allocations_manage, name="sponsorship_allocations_manage",),
    path(
        "sponsorships/<int:pk>/allocations/",
        views.sponsorship_allocations_manage,
        name="sponsorship_allocations_manage",
    ),
    path(
        "sponsorships/allocations/<int:pk>/delete/",
        views.sponsorship_allocation_delete,
        name="sponsorship_allocation_delete",
    ),
    path(
        "inquiry/sponsorship/",
        views.sponsorship_inquiry,
        name="sponsorship_inquiry",
    ),
        path(
        "sponsors/quick-create/",
        views.sponsor_quick_create,
        name="sponsor_quick_create",
    ),

    path("sponsors/", views.sponsors_list, name="sponsors_list"),
    path("api/sponsors/<int:pk>/update/", views.sponsor_quick_update, name="sponsor_quick_update"),

        # لوحة المحاسب
    path("accountant/", views.accountant_home, name="accountant_home"),

    # تخصيص الصندوق للبرنامج الرئيسي
    path("allocate/fund-to-main/", views.fund_to_main_allocate, name="fund_to_main_allocate"),

    # تحويل رئيسي → فرعي
    path("allocate/main-to-sub/", views.main_to_sub_allocate, name="main_to_sub_allocate"),

    # أوامر الصرف
    path("disbursement/create/", views.subprogram_disburse_create, name="subprogram_disburse_create"),

    # سجل الحركات
    path("ledger/", views.ledger, name="ledger"),

    # أرصدة البرامج
    path("program-balances/", views.program_balances, name="program_balances"),
    

    path("reservations/", views.fund_reservations_dashboard, name="fund_reservations_dashboard"),

    path("beneficiaries/supports/", views.beneficiary_supports_report, name="beneficiary_supports_report"),

    path("invoices/<int:pk>/edit/", views.invoice_update, name="invoice_update"),
    path("invoices/<int:pk>/delete/", views.invoice_delete, name="invoice_delete"),
    path(
    "reports/sponsorship/print/",
    views.sponsorship_report_print,
    name="sponsorship_report_print",
    ),
    
    path(
    "reports/sponsorship/",
    views.sponsorship_reports,
    name="sponsorship_reports",
),
]
