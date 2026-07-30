from django.urls import path
from . import views
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy
app_name = "Donation"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("", views.dashboard, name="dashboard"),
    path("beneficiaries/", views.beneficiaries, name="beneficiaries"),
    path(
        "beneficiaries/<int:pk>/",
        views.beneficiary_detail,
        name="beneficiary_detail",
    ),
    path("invoices/", views.invoices, name="invoices"),
    path("profile/", views.profile, name="profile"),
    path(
    "beneficiaries/<int:pk>/",
    views.beneficiary_detail,
    name="beneficiary_detail",
),
path(
    "invoices/<int:pk>/",
    views.invoice_detail,
    name="invoice_detail",
),
path(
    "profile/",
    views.profile,
    name="profile",
),


path(
    "password/change/",
    PasswordChangeView.as_view(
        template_name="Donation/password_change.html",
        success_url="/donation/profile/?password_changed=1"
    ),
    name="password_change",
),
]