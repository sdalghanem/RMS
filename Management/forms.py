from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from .models import (
    Profile,
    Beneficiary,
    MainProgram,
    SubProgram,
    PaymentPlan,
)

from Accounting.models import FinancialSponsorshipInvoice


User = get_user_model()


class SponsorshipInvoiceSelect(forms.Select):

    def create_option(
        self,
        name,
        value,
        label,
        selected,
        index,
        subindex=None,
        attrs=None,
    ):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex,
            attrs,
        )

        invoice = getattr(value, "instance", None)

        if invoice:
            sponsor_name = (
                invoice.sponsor.user.get_full_name()
                or invoice.sponsor.user.username
            )

            option["attrs"]["data-sponsor"] = sponsor_name
            option["attrs"]["data-amount"] = (
                f"{invoice.total_amount:,.2f} ر.س"
            )
            option["attrs"]["data-start"] = (
                invoice.start_date.isoformat()
                if invoice.start_date
                else "—"
            )
            option["attrs"]["data-end"] = (
                invoice.end_date.isoformat()
                if invoice.end_date
                else "—"
            )

        return option
    
# Mixin اختياري لتمرير request إلى الفورم عند الحاجة.
class RequestFormMixin:
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)  # 👈 يسحب request بأمان
        super().__init__(*args, **kwargs)

class MainProgramForm(RequestFormMixin, forms.ModelForm):

    class Meta:
        model = MainProgram

        fields = [
            "name",
            "description",
        ]

        labels = {
            "name": "اسم البرنامج الأساسي",
            "description": "الوصف",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "مثال: كفالة الأيتام",
                }
            ),

            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "وصف مختصر",
                }
            ),
        }

    def save(self, commit=True):

        obj = super().save(commit=False)

        # عند إنشاء البرنامج الأساسي يبدأ سقف التبرع بصفر
        if not obj.pk:
            obj.total_donation_amount = 0

        if commit:
            obj.save()

        return obj
    
class SubProgramForm(RequestFormMixin, forms.ModelForm):

    class Meta:
        model = SubProgram

        fields = [
            "main_program",
            "name",
            "description",
        ]

        labels = {
            "main_program": "البرنامج الأساسي",
            "name": "اسم البرنامج الفرعي",
            "description": "الوصف",
        }

        widgets = {
            "main_program": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "مثال: كسوة الشتاء",
                }
            ),

            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "وصف مختصر",
                }
            ),
        }

    def save(self, commit=True):

        obj = super().save(commit=False)

        # عند إنشاء البرنامج الفرعي يبدأ المبلغ المخصص بصفر
        if not obj.pk:
            obj.allocated_amount = 0

        if commit:
            obj.save()

        return obj
    
class BeneficiariesBulkEducationForm(forms.Form):
    education_level = forms.ChoiceField(
        label="المرحلة الدراسية الجديدة",
        choices=Beneficiary.EducationLevel.choices,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    ids = forms.CharField(widget=forms.HiddenInput, required=False)  # احتياطي لو احتجته

class UserWithProfileCreateForm(forms.Form):
    ROLE_CHOICES = [
        (Profile.Roles.DONOR, "كفيل"),
        (Profile.Roles.ACCOUNTANT, "محاسب"),
        (Profile.Roles.CASHIER, "كاشير"),
    ]
    role = forms.ChoiceField(
        label="نوع الحساب",
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        required=True,
    )

    # المستخدم (بدون username – سنستخدم email كاسم مستخدم)
    email = forms.EmailField(label="البريد الإلكتروني (اسم المستخدم)", required=True)
    first_name = forms.CharField(label="الاسم الأول", max_length=150, required=True)
    last_name  = forms.CharField(label="اسم العائلة", max_length=150, required=True)

    password1 = forms.CharField(
        label="كلمة المرور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=True,
    )
    password2 = forms.CharField(
        label="تأكيد كلمة المرور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=True,
    )

    # البروفايل
    phone = forms.CharField(label="الجوال (05xxxxxxxx)", max_length=10, required=True)
    national_number = forms.CharField(label="الهوية الوطنية (10 أرقام)", max_length=10, required=True)
    father_name  = forms.CharField(label="اسم الأب", max_length=50, required=False)     # اختياري
    grandpa_name = forms.CharField(label="اسم الجد", max_length=50, required=False)     # اختياري

    def __init__(self, *args, allowed_roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_roles is not None:
            self.fields["role"].choices = [(v, lbl) for (v, lbl) in self.ROLE_CHOICES if v in allowed_roles]
        # Bootstrap
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs.setdefault("class", "form-control")

    def _mild_password_checks(self, pwd: str):
        # تحقق بسيط: طول ≥ 8 + حرف + رقم
        if len(pwd) < 8:
            return "كلمة المرور يجب أن تكون 8 أحرف/أرقام على الأقل."
        has_letter = any(c.isalpha() for c in pwd)
        has_digit  = any(c.isdigit() for c in pwd)
        if not has_letter or not has_digit:
            return "كلمة المرور يجب أن تحتوي على حرف واحد ورقم واحد على الأقل."
        return None

    def clean(self):
        data = super().clean()

        # الإيميل=اسم المستخدم → تأكد من التفرد
        email = (data.get("email") or "").strip().lower()
        if not email:
            self.add_error("email", "الإيميل مطلوب.")
        else:
            # نستخدمه كـ username
            if User.objects.filter(username=email).exists():
                self.add_error("email", "الإيميل مستخدم كاسم دخول مسبقًا.")

        # كلمة المرور
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "تأكيد كلمة المرور لا يطابق.")
        if p1:
            msg = self._mild_password_checks(p1)
            if msg:
                self.add_error("password1", msg)

        # الجوال
        phone = data.get("phone") or ""
        if phone and (len(phone) != 10 or not phone.startswith("05") or not phone.isdigit()):
            self.add_error("phone", "أدخل رقم جوال صحيح بصيغة 05xxxxxxxx.")
        if phone and Profile.objects.filter(phone=phone).exists():
            self.add_error("phone", "رقم الجوال مسجل مسبقًا.")

        # الهوية
        nid = data.get("national_number") or ""
        if nid and (len(nid) != 10 or not nid.isdigit()):
            self.add_error("national_number", "رقم الهوية يجب أن يتكون من 10 أرقام.")
        if nid and Profile.objects.filter(national_number=nid).exists():
            self.add_error("national_number", "رقم الهوية مسجل مسبقًا.")

        return data
    

    
class UserContactEditForm(forms.Form):
    email = forms.EmailField(label="البريد الإلكتروني (اسم الدخول)", required=True)
    phone = forms.CharField(label="الجوال (05xxxxxxxx)", max_length=10, required=True)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user  # المستخدم الجاري تعديله
        # Bootstrap
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "form-control")

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if len(phone) != 10 or not phone.startswith("05") or not phone.isdigit():
            raise forms.ValidationError("أدخل رقم جوال صحيح بصيغة 05xxxxxxxx.")
        # تأكد من تفرده مع استثناء المستخدم الحالي
        qs = Profile.objects.filter(phone=phone)
        if self.user and hasattr(self.user, "profile"):
            qs = qs.exclude(pk=self.user.profile.pk)
        if qs.exists():
            raise forms.ValidationError("رقم الجوال مسجل مسبقًا.")
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("البريد الإلكتروني مطلوب.")
        # لأنه اسم الدخول أيضًا (username=email)
        qs = User.objects.filter(username=email)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("هذا البريد مستخدم كاسم دخول مسبقًا.")
        return email


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="البريد الإلكتروني",
        widget=forms.EmailInput(attrs={"autofocus": True, "class": "form-control"})
    )
    password = forms.CharField(
        label="كلمة المرور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "form-control"})
    )
    remember_me = forms.BooleanField(label="تذكرني", required=False)

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        """
        يسمح بتسجيل الدخول باستخدام البريد الإلكتروني أو اسم المستخدم.
        يتم تحويل البريد إلى username الفعلي قبل التحقق من كلمة المرور.
        """
        raw = self.data.get(self.add_prefix("username"), "")
        email_or_username = (raw or "").strip().lower()

        try:
            user_by_email = (
                User.objects
                .filter(email__iexact=email_or_username)
                .first()
            )

            if user_by_email:
                self.data = self.data.copy()
                self.data[self.add_prefix("username")] = user_by_email.username
        except Exception:
            pass

        cleaned_data = super().clean()

        if cleaned_data.get("username"):
            cleaned_data["username"] = cleaned_data["username"].strip().lower()

        return cleaned_data
    
    ##############################################################################################


class BeneficiaryForm(forms.ModelForm):
    """
    نموذج بيانات المستفيد.

    ملاحظة:
    الكفالة لا تُدار من هذا النموذج.
    الكفيل الحالي وتاريخ الكفالة مصدرهما BeneficiarySponsorHistory.
    """

    class Meta:
        model = Beneficiary
        fields = [
            "first_name","father_name","grand_name","last_name","gender","birth_date",
            "education_level","health_status","disease","type_disease",
            "type_housing","housing_fee","beneficiary_rank",
            "number_of_beneficiary_in_family","national_number"
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date", "class":"form-control"}),
            "housing_fee": forms.NumberInput(attrs={"step": "0.01", "class":"form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not getattr(f.widget, "attrs", None):
                f.widget.attrs = {}
            f.widget.attrs.setdefault("class", "form-control")

class BeneficiaryFilterForm(forms.Form):

    q = forms.CharField(
        required=False,
        label="بحث",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "ابحث بالاسم، الهوية، رقم الجوال أو اسم الكافل..."
            }
        )
    )

    gender = forms.ChoiceField(
        required=False,
        choices=[
            ("", "الجنس (الكل)")
        ] + list(Beneficiary.Gender.choices),
        widget=forms.Select(
            attrs={
                "class": "form-select"
            }
        )
    )

    donor = forms.ModelChoiceField(
        required=False,
        queryset=Profile.objects.filter(
            role=Profile.Roles.DONOR
        ).select_related("user"),
        label="الكافل",
        widget=forms.Select(
            attrs={
                "class": "form-select"
            }
        )
    )

    education_level = forms.ChoiceField(
        required=False,
        choices=[
            ("", "المرحلة الدراسية (الكل)")
        ] + list(Beneficiary.EducationLevel.choices),
        widget=forms.Select(
            attrs={
                "class": "form-select"
            }
        ),
        label="المرحلة الدراسية"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["donor"].label_from_instance = self.get_donor_name

    def get_donor_name(self, obj):
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
    
class BeneficiaryImportForm(forms.Form):
    file = forms.FileField(label="ملف Excel (xlsx)", widget=forms.FileInput(attrs={"accept":".xlsx"}))

class BeneficiariesBulkAssignForm(forms.Form):
    """
    إلحاق مستفيد واحد بسند كفالة مالية.

    القواعد:
    - سند كفالة واحد = مستفيد واحد.
    - لا تظهر إلا السندات السارية.
    - لا تظهر السندات المرتبطة بمستفيد سابقًا.
    - الكافل يؤخذ تلقائيًا من السند.
    """

    sponsorship_invoice = forms.ModelChoiceField(
        queryset=FinancialSponsorshipInvoice.objects.none(),
        label="سند الكفالة",
        required=True,
        empty_label="اختر سند الكفالة",
        widget=SponsorshipInvoiceSelect(
            attrs={
                "class": "form-select sponsorship-select",
            }
        ),
    )

    ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = timezone.localdate()

        queryset = (
            FinancialSponsorshipInvoice.objects
            .filter(
                start_date__lte=today,
                end_date__gte=today,
                allocation__isnull=True,
            )
            .select_related(
                "invoice",
                "sponsor",
                "sponsor__user",
            )
            .order_by(
                "end_date",
                "invoice__number",
            )
        )

        self.fields["sponsorship_invoice"].queryset = queryset

        self.fields[
            "sponsorship_invoice"
        ].label_from_instance = self._sponsorship_label

    @staticmethod
    def _sponsorship_label(obj):

        sponsor_name = (
            obj.sponsor.user.get_full_name()
            or obj.sponsor.user.username
        )

        return (
            f"سند #{obj.invoice.number} | "
            f"{sponsor_name} | "
            f"{obj.total_amount:,.2f} ر.س | "
            f"{obj.start_date:%Y-%m-%d} → "
            f"{obj.end_date:%Y-%m-%d}"
        )


# -------------------------------------------------------------------
# البرامج
# -------------------------------------------------------------------


class SubProgramInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # نجمع مبالغ المخصص لجميع النماذج غير المحذوفة
        total_allocated = 0
        for form in self.forms:
            if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE", False):
                total_allocated += form.cleaned_data.get("allocated_amount") or 0

        main = self.instance  # MainProgram الحالي
        total_cap = main.total_donation_amount or 0

        if total_allocated > total_cap:
            raise ValidationError(
                f"إجمالي المبالغ المخصصة للبرامج الفرعية ({total_allocated:,.2f}) "
                f"يتجاوز سقف البرنامج الأساسي ({total_cap:,.2f})."
            )


class PaymentPlanForm(forms.ModelForm):
    class Meta:
        model = PaymentPlan
        fields = ["amount", "duration_months", "is_active"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "duration_months": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "amount": "مبلغ الاشتراك (ريال)",
            "duration_months": "المدة (بالأشهر)",
            "is_active": "نشطة",
        }
