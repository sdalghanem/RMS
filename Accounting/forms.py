from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

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

class GeneralDonationInvoiceForm(forms.ModelForm):

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
class FinancialSponsorshipInvoiceForm(forms.ModelForm):

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

class DonorUserCreateForm(UserCreationForm):

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
        label="اسم الأب (اختياري)",
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
        label="اسم الجد (اختياري)",
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

    class Meta(UserCreationForm.Meta):

        model = User

        fields = (
            "email",
            "first_name",
            "father_name",
            "grandpa_name",
            "last_name",
            "password1",
            "password2",
            "phone",
            "national_number",
        )

    # =================================================
    # تهيئة الفورم
    # =================================================

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields[
            "password1"
        ].widget.attrs.update(
            {
                "class": "form-control",
            }
        )

        self.fields[
            "password2"
        ].widget.attrs.update(
            {
                "class": "form-control",
            }
        )

    # =================================================
    # التحقق من الجوال
    # =================================================

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

        return national

    # =================================================
    # الحفظ
    # =================================================

    def save(self, commit=True):

        user = super().save(
            commit=False
        )

        email = self.cleaned_data.get(
            "email"
        )

        user.email = email

        if not user.username:

            user.username = email

        user.first_name = (
            self.cleaned_data.get(
                "first_name",
                ""
            )
        )

        user.last_name = (
            self.cleaned_data.get(
                "last_name",
                ""
            )
        )

        if commit:

            user.save()

            phone = (
                self.cleaned_data.get(
                    "phone"
                )
            )

            national = (
                self.cleaned_data.get(
                    "national_number"
                )
            )

            father_name = (
                self.cleaned_data.get(
                    "father_name",
                    ""
                )
            )

            grandpa_name = (
                self.cleaned_data.get(
                    "grandpa_name",
                    ""
                )
            )

            profile, created = (
                Profile.objects.get_or_create(
                    user=user,
                    defaults={
                        "phone": phone,
                        "national_number": national,
                        "father_name": father_name,
                        "grandpa_name": grandpa_name,
                        "role": Profile.Roles.DONOR,
                    },
                )
            )

            if not created:

                profile.phone = phone

                profile.national_number = (
                    national
                )

                profile.father_name = (
                    father_name
                )

                profile.grandpa_name = (
                    grandpa_name
                )

                profile.role = (
                    Profile.Roles.DONOR
                )

                profile.save()

        return user