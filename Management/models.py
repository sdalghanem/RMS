# Create your models here.
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.core.validators import MinValueValidator, RegexValidator
from datetime import date
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

class Profile(models.Model):
    class Roles(models.TextChoices):
        DONOR = "donor", "Donor"           # متبرع
        ACCOUNTANT = "accountant", "Accountant"  # محاسب
        CASHIER = "cashier", "Cashier"     # أمين صرف/صندوق
        SYSTEM_ADMIN = "system_admin", "System Admin"  # ✅ مدير نظام جديد


    ...

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        db_index=True,
    )

    # رقم الجوال السعودي بصيغة 05xxxxxxxx
    phone = models.CharField(
        max_length=10,
        unique=True,
        validators=[RegexValidator(
            regex=r"^05\d{8}$",
            message="أدخل رقم جوال سعودي بصيغة 05xxxxxxxx"
        )],
        help_text="05xxxxxxxx"
    )

    father_name = models.CharField(
        max_length=50,
        blank=True,
        help_text="اسم الأب (اختياري)"
    )

    grandpa_name = models.CharField(
        max_length=50,
        blank=True,
        help_text="اسم الجد (اختياري)"
    )

    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        default=Roles.DONOR,
        db_index=True
    )

    # الهوية الوطنية السعودية: 10 أرقام
    national_number = models.CharField(
        max_length=10,
        unique=True,
        validators=[RegexValidator(
            regex=r"^\d{10}$",
            message="رقم الهوية يجب أن يتكون من 10 أرقام"
        )],
        help_text="10 أرقام"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["user"]),
        ]
        constraints = [
            # مثال: منع تكرار نفس الهوية مع مستخدم مختلف (unique على الحقل يكفي، لكن نوضح النية)
            models.UniqueConstraint(fields=["national_number"], name="uq_profile_national_number"),
            models.UniqueConstraint(fields=["phone"], name="uq_profile_phone"),
        ]

    def __str__(self):
        return self.user.get_full_name()



class AuditLog(models.Model):
    class Actions(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        LOGIN_FAILED = "login_failed", "Login Failed"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        REQUEST = "request", "Request"
        PASSWORD_CHANGE = "password_change", "Password Change"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=32, choices=Actions.choices, db_index=True)
    entity = models.CharField(max_length=100, db_index=True)
    entity_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # محتوى إضافي (اختياري): طريقة/مسار/بيانات/وصف… بصيغة JSON أو نص
    extra = models.JSONField(null=True, blank=True)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-ts"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["action", "entity"]),
            models.Index(fields=["ts"]),
        ]

    def __str__(self):
        who = self.user and (self.user.get_full_name() or self.user.username) or "anonymous"
        return f"[{self.ts:%Y-%m-%d %H:%M:%S}] {who} -> {self.action} {self.entity}#{self.entity_id or '-'}"


# ... موجوداتك القديمة ...


class Beneficiary(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "ذكر"
        FEMALE = "female", "أنثى"

    class EducationLevel(models.TextChoices):
        CHILD = "child", "طفل"
        KG    = "kg",    "روضة"
        P1 = "p1", "أول ابتدائي"
        P2 = "p2", "ثاني ابتدائي"
        P3 = "p3", "ثالث ابتدائي"
        P4 = "p4", "رابع ابتدائي"
        P5 = "p5", "خامس ابتدائي"
        P6 = "p6", "سادس ابتدائي"
        M1 = "m1", "أول متوسط"
        M2 = "m2", "ثاني متوسط"
        M3 = "m3", "ثالث متوسط"
        H1 = "h1", "أول ثانوي"
        H2 = "h2", "ثاني ثانوي"
        H3 = "h3", "ثالث ثانوي"
       

    class HealthStatus(models.TextChoices):
        HEALTHY = "healthy", "سليم"
        SICK = "sick", "مريض"
       

    class DiseaseType(models.TextChoices):
        NONE = "none", "لا يوجد"
        CHRONIC = "chronic", "مستعصي"
        TEMPORARY = "temporary", "غير مستعصي"

    class HousingType(models.TextChoices):
        OWN = "own", "ملك"
        RENT = "rent", "إيجار"
        FAMILY = "share", "مشترك"

     


    first_name = models.CharField(max_length=50)
    father_name = models.CharField(max_length=50, blank=True)
    grand_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50)

    gender = models.CharField(max_length=10, choices=Gender.choices, db_index=True)
    birth_date = models.DateField(null=True, blank=True)

    education_level = models.CharField(max_length=20, choices=EducationLevel.choices, blank=True)
    health_status = models.CharField(max_length=10, choices=HealthStatus.choices, blank=True)

    disease = models.CharField(max_length=100, blank=True, help_text="اسم المرض (إن وجد)")
    type_disease = models.CharField(max_length=20, choices=DiseaseType.choices, default=DiseaseType.NONE)

    type_housing = models.CharField(max_length=10, choices=HousingType.choices, blank=True)
    housing_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    beneficiary_rank = models.CharField(max_length=20, blank=True , help_text="ترتيب اليتيم")

    number_of_beneficiary_in_family = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)] , help_text="عدد ايتام الأسرة")
    national_number = models.CharField(
        max_length=10,
        unique=True,
        validators=[RegexValidator(regex=r"^\d{10}$", message="رقم الهوية يجب أن يتكون من 10 أرقام")]
    )

    donor = models.ForeignKey(
        "Management.Profile",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        limit_choices_to={"role": "donor"},
        related_name="beneficiaries",
        help_text="المتبرّع (كفيل) المسؤول"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Beneficiary"
        verbose_name_plural = "Beneficiaries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["gender"]),
            models.Index(fields=["donor"]),
        ]

    @property
    def age_years(self):
        if not self.birth_date:
            return None
        today = date.today()
        years = today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )
        return max(0, years)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.national_number}"





class BeneficiarySponsorHistory(models.Model):
    """
    سجل تاريخ انتقالات الكفيل للمستفيد.
    يحتفظ بجميع الكفلاء الذين مر عليهم المستفيد.
    """

    beneficiary = models.ForeignKey(
        "Beneficiary",
        on_delete=models.CASCADE,
        related_name="sponsor_history",
        verbose_name="المستفيد",
    )

    donor = models.ForeignKey(
        "Profile",
        on_delete=models.PROTECT,
        related_name="beneficiary_history",
        limit_choices_to={"role": Profile.Roles.DONOR},
        verbose_name="الكافل",
    )

    start_date = models.DateField(
        verbose_name="بداية الكفالة",
        default=timezone.now,
    )

    end_date = models.DateField(
        verbose_name="نهاية الكفالة",
        null=True,
        blank=True,
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="تم الإسناد بواسطة",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        verbose_name = "سجل كفالة"
        verbose_name_plural = "سجل الكفالات"

    def __str__(self):
        return f"{self.beneficiary} ← {self.donor}"
########   البرامج 




class MainProgram(models.Model):
    name = models.CharField(max_length=150, verbose_name="اسم البرنامج الأساسي")
    description = models.TextField(blank=True, null=True, verbose_name="الوصف")
    is_active = models.BooleanField(
    default=True,
    verbose_name="نشط"
    )
    total_donation_amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="إجمالي مبلغ التبرع"
    )
    remaining_amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="المبلغ المتبقي", default=0
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "برنامج أساسي"
        verbose_name_plural = "البرامج الأساسية"
        ordering = ['-created_at']

    def clean(self):
        # في الإنشاء الأول لا يوجد PK؛ لا تستخدم العلاقات هنا
        if not self.pk:
            return

        # تحقق: مجموع المخصص للفروع لا يتجاوز سقف البرنامج
        allocated_sum = self.sub_programs.aggregate(s=Sum("allocated_amount"))["s"] or 0
        if allocated_sum > (self.total_donation_amount or 0):
            raise ValidationError("مجموع المبالغ المخصصة للبرامج الفرعية يتجاوز سقف البرنامج الأساسي.")

    def __str__(self):
        return self.name



class SubProgram(models.Model):
    main_program = models.ForeignKey(
        MainProgram, on_delete=models.CASCADE, related_name="sub_programs",
        verbose_name="البرنامج الأساسي"
    )
    name = models.CharField(max_length=150, verbose_name="اسم البرنامج الفرعي")
    description = models.TextField(blank=True, null=True, verbose_name="الوصف")
    allocated_amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="المبلغ المخصص"
    )
    spent_amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="المبلغ المصروف", default=0 , blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "برنامج فرعي"
        verbose_name_plural = "البرامج الفرعية"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.main_program.name})"

    def clean(self):
        if (self.spent_amount or 0) > (self.allocated_amount or 0):
            raise ValidationError("المبلغ المصروف لا يمكن أن يتجاوز المبلغ المخصص.")
        
    @property
    def remaining_amount(self):
        return self.allocated_amount - self.spent_amount


class PaymentPlan(models.Model):
    amount = models.DecimalField("مبلغ الاشتراك (ريال)", max_digits=12, decimal_places=2)
    duration_months = models.PositiveSmallIntegerField("المدة (بالأشهر)")
    is_active = models.BooleanField("نشطة", default=True)
    created_at = models.DateTimeField("تاريخ الإضافة", auto_now_add=True)

    class Meta:
        verbose_name = "خطة دفع"
        verbose_name_plural = "إدارة الدفعات"

    def __str__(self):
        return f"{self.amount} ريال / {self.duration_months} شهر"