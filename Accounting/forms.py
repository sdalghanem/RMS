from django import forms
from django.contrib.auth import get_user_model
import secrets
from django.db import transaction
from django.db.models import Q

from .models import (
    GeneralDonationInvoice,
    FinancialSponsorshipInvoice,
    Invoice,
    FinancialSponsorshipAllocation,
)

from Management.models import (
    Profile,
    PaymentPlan,
    Beneficiary,
)


User = get_user_model()


# =====================================================
# تخصيص الكفالة المالية
# =====================================================

class FinancialSponsorshipAllocationForm(forms.ModelForm):

    class Meta:
        model = FinancialSponsorshipAllocation

        fields = [
            "beneficiary",
            "amount",
            "notes",
        ]

        labels = {
            "beneficiary": "المستفيد",
            "amount": "المبلغ المخصّص",
            "notes": "ملاحظات",
        }

        widgets = {
            "beneficiary": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                }
            ),

            "notes": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }


# =====================================================
# سند التبرع العام
# =====================================================

class InvoiceNumberMixin:
    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        if len(number) > Invoice._meta.get_field("number").max_length:
            raise forms.ValidationError("رقم السند يتجاوز الحد المسموح (20 حرفًا).")
        if Invoice.objects.filter(number=number).exists():
            raise forms.ValidationError("رقم السند مستخدم مسبقًا")
        return number


class GeneralDonationInvoiceForm(InvoiceNumberMixin, forms.ModelForm):

    number = forms.CharField(
        label="رقم السند",
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        )
    )

    # -------------------------------------------------
    # تاريخ السند
    # -------------------------------------------------

    date = forms.DateField(
        label="تاريخ السند",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    # -------------------------------------------------
    # وسيلة القبض
    # -------------------------------------------------

    payment_method = forms.ChoiceField(
        label="وسيلة القبض",
        choices=Invoice.PaymentMethods.choices,
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    # -------------------------------------------------
    # الملاحظات
    # -------------------------------------------------

    notes = forms.CharField(
        label="ملاحظات",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
            }
        ),
    )

    class Meta:

        model = GeneralDonationInvoice

        fields = [
            "amount",
            "amount_in_words",
            "bank_from",
            "from_account_number",
            "to_account_number",
            "supporter_name",
            "supporter_phone",
            "supporter_national_number",
        ]

        widgets = {

            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "amount_in_words": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "bank_from": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "from_account_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "to_account_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "supporter_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "supporter_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "supporter_national_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

        labels = {

            "bank_from": "البنك المحوّل منه",

            "from_account_number": (
                "رقم الحساب المحوّل منه"
            ),

            "to_account_number": (
                "الحساب المحوّل عليه"
            ),

            "amount": "المبلغ",

            "amount_in_words": (
                "المبلغ كتابة"
            ),

            "supporter_name": (
                "اسم الداعم"
            ),
        }


# =====================================================
# سند الكفالة المالية
# 
class FinancialSponsorshipInvoiceForm(InvoiceNumberMixin, forms.ModelForm):
    beneficiary = forms.ModelChoiceField(
        queryset=Beneficiary.objects.none(), required=False, label="المستفيد",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={"invalid_choice": "اختر مستفيدًا مسجلًا وصالحًا من نتائج البحث."},
    )


    number = forms.CharField(
        label="رقم السند",
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    date = forms.DateField(
        label="تاريخ السند",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    payment_method = forms.ChoiceField(
        label="وسيلة القبض الأساسية",
        choices=Invoice.PaymentMethods.choices,
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "id": "id_payment_method",
            }
        ),
    )

    notes = forms.CharField(
        label="ملاحظات",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
            }
        ),
    )

    # =====================================================
    # الكافل
    # =====================================================

    sponsor = forms.ModelChoiceField(
        queryset=Profile.objects.none(),
        label="الكافل",
        required=True,
        empty_label=None,
        widget=forms.Select(
            attrs={
                "class": "form-select sponsor-select",
                "id": "id_sponsor",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:

        model = FinancialSponsorshipInvoice

        fields = [
            "sponsor",
            "payment_plan",
            "is_custom_plan",
            "custom_amount",
            "custom_duration_months",
            "start_date",
            "end_date",
            "bank_from",
            "from_account_number",
            "to_account_number",
        ]

        widgets = {

            "payment_plan": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "is_custom_plan": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),

            "custom_amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                }
            ),

            "custom_duration_months": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),

            "start_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),

            "end_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),

            "bank_from": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "from_account_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "to_account_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

        labels = {

            "payment_plan": "نوع الكفالة (خطة)",

            "is_custom_plan": "خطة مخصّصة (أخرى)",

            "custom_amount": "مبلغ الكفالة (فعلي)",

            "custom_duration_months":
                "مدة الكفالة بالأشهر (فعلية)",

            "start_date": "تاريخ بداية الكفالة",

            "end_date": "تاريخ نهاية الكفالة",

            "bank_from": "البنك المحوّل منه",

            "from_account_number":
                "رقم الحساب المحوّل منه",

            "to_account_number":
                "الحساب المحوّل عليه",
        }

    # =====================================================
    # تهيئة الفورم
    # =====================================================

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        beneficiary_id = self.data.get(self.add_prefix("beneficiary"), "") if self.is_bound else ""
        if str(beneficiary_id).isascii() and str(beneficiary_id).isdecimal() and len(str(beneficiary_id)) < 19:
            self.fields["beneficiary"].queryset = Beneficiary.objects.filter(pk=beneficiary_id)
        self.fields["beneficiary"].label_from_instance = lambda b: " ".join(filter(None, (b.first_name, b.father_name, b.grand_name or b.last_name)))


        # الاسم الكامل للكافل
        self.fields["sponsor"].label_from_instance = (
            self.get_sponsor_name
        )

        # -------------------------------------------------
        # في حالة التعديل:
        # تحميل الكافل الحالي فقط حتى يظهر في الحقل
        # -------------------------------------------------

        sponsor_id = None

        if self.instance and self.instance.pk:
            sponsor_id = self.instance.sponsor_id

        if sponsor_id:

            self.fields["sponsor"].queryset = (
                Profile.objects
                .filter(
                    pk=sponsor_id,
                    role=Profile.Roles.DONOR,
                )
                .select_related("user")
            )

    # =====================================================
    # الاسم الكامل للكافل
    # =====================================================

    def clean(self):
        data = super().clean()
        plan = data.get("payment_plan")
        if data.get("is_custom_plan"):
            for field in ("custom_amount", "custom_duration_months"):
                if data.get(field) is None or data[field] <= 0:
                    self.add_error(field, "أدخل قيمة أكبر من صفر.")
            data["payment_plan"] = None
        elif not plan:
            self.add_error("payment_plan", "اختر نوع الكفالة.")
        elif not plan.is_active or plan.amount <= 0 or plan.duration_months <= 0:
            self.add_error("payment_plan", "الخطة غير متاحة أو قيمها غير صالحة.")
        else:
            data["custom_amount"] = plan.amount
            data["custom_duration_months"] = plan.duration_months
        if data.get("start_date") and data.get("end_date") and data["end_date"] <= data["start_date"]:
            self.add_error("end_date", "تاريخ النهاية يجب أن يكون بعد البداية.")
        return data

    @staticmethod
    def get_sponsor_name(obj):

        parts = [
            obj.user.first_name,
            obj.father_name,
            obj.grandpa_name,
            obj.user.last_name,
        ]

        name = " ".join(
            str(part).strip()
            for part in parts
            if part and str(part).strip()
        )

        return name or obj.user.username
# =====================================================
# إنشاء حساب كافل
# =====================================================

class DonorUserCreateForm(forms.ModelForm):

    """
    فورم خاص لإنشاء حساب كافل DONOR.

    ينشئ:
    User + Profile

    ويضبط الدور تلقائيًا على DONOR.
    """

    # -------------------------------------------------
    # البريد الإلكتروني
    # -------------------------------------------------

    email = forms.EmailField(
        label="البريد الإلكتروني (اسم المستخدم)",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "example@email.com",
            }
        ),
    )

    # -------------------------------------------------
    # الاسم الأول
    # -------------------------------------------------

    first_name = forms.CharField(
        label="الاسم الأول",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    # -------------------------------------------------
    # اسم الأب
    # -------------------------------------------------

    father_name = forms.CharField(
        label="اسم الأب (اختياري)", max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    # -------------------------------------------------
    # اسم الجد
    # -------------------------------------------------

    grandpa_name = forms.CharField(
        label="اسم الجد (اختياري)", max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    # -------------------------------------------------
    # اسم العائلة
    # -------------------------------------------------

    last_name = forms.CharField(
        label="اسم العائلة",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    # -------------------------------------------------
    # الجوال
    # -------------------------------------------------

    phone = forms.CharField(
        label="الجوال (05xxxxxxxx)",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "05xxxxxxxx",
                "maxlength": "10",
            }
        ),
    )

    # -------------------------------------------------
    # الهوية الوطنية
    # -------------------------------------------------

    national_number = forms.CharField(
        label="الهوية الوطنية (10 أرقام)",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "10 أرقام",
                "maxlength": "10",
            }
        ),
    )

    class Meta:

        model = User

        fields = (
            "email",
            "first_name",
            "father_name",
            "grandpa_name",
            "last_name",
            "phone",
            "national_number",
        )

    # =================================================
    # تهيئة الفورم
    # =================================================

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if len(email) > User._meta.get_field("username").max_length:
            raise forms.ValidationError("البريد الإلكتروني أطول من الحد المسموح.")
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError("البريد الإلكتروني مسجل مسبقًا.")
        return email

    def clean_phone(self):

        phone = self.cleaned_data.get(
            "phone"
        )

        if phone and Profile.objects.filter(
            phone=phone
        ).exists():

            raise forms.ValidationError(
                "رقم الجوال مسجّل مسبقًا في النظام."
            )

        Profile._meta.get_field("phone").clean(phone, None)
        return phone

    # =================================================
    # التحقق من الهوية
    # =================================================

    def clean_national_number(self):

        national = self.cleaned_data.get(
            "national_number"
        )

        if national and Profile.objects.filter(
            national_number=national
        ).exists():

            raise forms.ValidationError(
                "رقم الهوية مسجّل مسبقًا في النظام."
            )

        Profile._meta.get_field("national_number").clean(national, None)
        return national

    # =================================================
    # الحفظ
    # =================================================

    @transaction.atomic
    def save(self, commit=True):
        if self.instance.pk:
            raise ValueError("This form only creates new sponsors.")
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.set_password(secrets.token_urlsafe(32))
        if commit:
            user.full_clean()
            user.save()
            profile = Profile(user=user, role=Profile.Roles.DONOR,
                **{key: self.cleaned_data.get(key, "") for key in
                   ("phone", "national_number", "father_name", "grandpa_name")})
            profile.full_clean()
            profile.save()
        return user


class SponsorshipRenewalForm(FinancialSponsorshipInvoiceForm):
    def __init__(self, *args, previous, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("sponsor", "beneficiary", "date", "payment_method", "bank_from", "from_account_number", "to_account_number"):
            self.fields.pop(name, None)
        self.fields["payment_plan"].queryset = PaymentPlan.objects.filter(is_active=True)
        from datetime import timedelta
        self.initial.update({"start_date": previous.end_date + timedelta(days=1),
            "payment_plan": previous.payment_plan_id, "is_custom_plan": previous.is_custom_plan,
            "custom_amount": previous.custom_amount, "custom_duration_months": previous.custom_duration_months})
