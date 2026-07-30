from django.conf import settings
from decimal import Decimal
from django.db.models import Sum
from django.core.exceptions import ValidationError
from Management.models import (
    Profile,
    PaymentPlan,
    Beneficiary,
    MainProgram,
    SubProgram,
)
from django.db import models, transaction
import uuid
from django.db import models
from django.db.models.functions import Coalesce
from Management.models import Profile, PaymentPlan  # عدّل المسار لو عندك مختلف

class FundEntry(models.Model):
    """
    دفتر حركات رصيد الجمعية (صندوق عام):
    - دخل من تبرعات عامة أو كفالات
    - صرف على البرامج (رئيسي/فرعي)
    - تحويل لرصيد مستفيد
    """

    class Types(models.TextChoices):
        GENERAL_DONATION_INCOME = "general_donation_income", "دخل تبرع عام"
        SPONSORSHIP_INCOME = "sponsorship_income", "دخل كفالة مالية"
        PROGRAM_EXPENSE = "program_expense", "صرف على برنامج"
        TRANSFER_TO_BENEFICIARY = "transfer_to_beneficiary", "تحويل لرصيد مستفيد"
        ADJUSTMENT = "adjustment", "تعديل رصيد"

    voucher_number = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="رقم السند"
    )

    invoice = models.ForeignKey(
        "Invoice",
        verbose_name="السند المرتبط",
        related_name="fund_entries",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    beneficiary = models.ForeignKey(
        Beneficiary,
        verbose_name="المستفيد (إن وجد)",
        related_name="fund_entries",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    main_program = models.ForeignKey(
        MainProgram,
        verbose_name="البرنامج الرئيسي (إن وجد)",
        related_name="fund_entries",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    sub_program = models.ForeignKey(
        SubProgram,
        verbose_name="البرنامج الفرعي (إن وجد)",
        related_name="fund_entries",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    type = models.CharField(
        "نوع الحركة",
        max_length=40,
        choices=Types.choices,
    )

    amount = models.DecimalField(
        "المبلغ",
        max_digits=12,
        decimal_places=2,
        help_text="موجب للدخل، سالب للصرف.",
    )

    description = models.CharField(
        "وصف الحركة",
        max_length=255,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="تم تسجيلها بواسطة",
        related_name="fund_entries",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        "تاريخ الحركة",
        auto_now_add=True
    )

    class Meta:
        verbose_name = "حركة رصيد الجمعية"
        verbose_name_plural = "حركات رصيد الجمعية"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        parts = [self.get_type_display()]

        if self.main_program:
            parts.append(self.main_program.name)

        if self.sub_program:
            parts.append(self.sub_program.name)

        if self.beneficiary:
            parts.append(str(self.beneficiary))

        return f"{' | '.join(parts)} | {self.amount:,.2f} ر.س"

    @classmethod
    def total_balance(cls) -> Decimal:
        agg = cls.objects.aggregate(total=Sum("amount"))
        return agg["total"] or Decimal("0.00")

    @classmethod
    def general_donation_balance(cls) -> Decimal:
        agg = cls.objects.filter(
            type=cls.Types.GENERAL_DONATION_INCOME
        ).aggregate(total=Sum("amount"))
        return agg["total"] or Decimal("0.00")################################################################################################################################

class Invoice(models.Model):
    """
    الفاتورة الأساسية (سند قبض/صرف) لأي نوع (تبرع عام / كفالة مالية)
    """

    class Types(models.TextChoices):
        GENERAL_DONATION = "general_donation", "تبرع عام"
        FINANCIAL_SPONSORSHIP = "financial_sponsorship", "كفالة مالية"

    class ReceiptKinds(models.TextChoices):
        RECEIPT = "receipt", "سند قبض"
        PAYMENT = "payment", "سند صرف"

    class PaymentMethods(models.TextChoices):
        CASH = "cash", "نقدًا"
        BANK_TRANSFER = "bank_transfer", "تحويل بنكي"
        BANK_CARD = "bank_card", "بطاقة بنكية"

    number = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        help_text="اكتب رقم السند يدوياً"
    )

    date = models.DateField("تاريخ السند")

    invoice_type = models.CharField(
        "نوع الفاتورة",
        max_length=32,
        choices=Types.choices,
    )

    receipt_kind = models.CharField(
        "نوع السند",
        max_length=16,
        choices=ReceiptKinds.choices,
        default=ReceiptKinds.RECEIPT,
    )

    payment_method = models.CharField(
        "وسيلة القبض",
        max_length=20,
        choices=PaymentMethods.choices,
        blank=True,
        null=True,
    )

    notes = models.TextField("ملاحظات", blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="تم الإنشاء بواسطة",
        related_name="created_invoices",
        on_delete=models.PROTECT,
    )

    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("تاريخ آخر تحديث", auto_now=True)

    class Meta:
        verbose_name = "فاتورة / سند"
        verbose_name_plural = "الفواتير / السندات"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.number} | {self.get_invoice_type_display()}"

class GeneralDonationInvoice(models.Model):
    """
    تفاصيل التبرع العام المرتبطة بالفاتورة.
    كل سجل هنا مرتبط بـ Invoice نوعها GENERAL_DONATION
    """
    invoice = models.OneToOneField(
        Invoice,
        verbose_name="الفاتورة",
        related_name="general_donation",
        on_delete=models.CASCADE,
        limit_choices_to={"invoice_type": Invoice.Types.GENERAL_DONATION},
    )

    # بيانات التحويل (إن وجدت)
    bank_from = models.CharField(
        "البنك المحوّل منه",
        max_length=100,
        blank=True,
    )
    from_account_number = models.CharField(
        "رقم الحساب المحوّل منه",
        max_length=50,
        blank=True,
    )
    to_account_number = models.CharField(
        "الحساب المحوّل عليه",
        max_length=50,
        blank=True,
    )

    # 🔹 مبلغ التبرع
    amount = models.DecimalField(
        "المبلغ",
        max_digits=12,
        decimal_places=2,
    )
    amount_in_words = models.CharField(
        "المبلغ كتابة",
        max_length=255,
        blank=True,
        help_text="يتم توليدها أو كتابتها يدويًا في النموذج.",
    )

    # 🔹 بيانات المتبرع (كافل محتمل)
    supporter_name = models.CharField(
        "اسم الداعم",
        max_length=150,
        blank=True,
    )
    supporter_phone = models.CharField(
        "جوال الداعم",
        max_length=20,
        blank=True,
    )
    supporter_national_number = models.CharField(
        "هوية الداعم",
        max_length=20,
        blank=True,
        help_text="يمكن استخدامها لاحقًا لربط الداعم ككافل في النظام.",
    )

    class Meta:
        verbose_name = "تفاصيل تبرع عام"
        verbose_name_plural = "تفاصيل التبرعات العامة"

  
    @classmethod
    def generate_next_number(cls, prefix="INV-"):
        """
        توليد رقم سند جديد متسلسل بالشكل:
        INV-0001, INV-0002, ...
        ويمكن تغيير البادئة prefix حسب نوع السند، مثل: GDN- للكفالة المالية أو GNR- للتبرع العام.
        """
        last_invoice = (
            cls.objects.filter(number__startswith=prefix)
            .order_by("-id")
            .first()
        )
        if not last_invoice:
            return f"{prefix}0001"

        last_number = last_invoice.number.replace(prefix, "")
        try:
            last_int = int(last_number)
        except ValueError:
            # لو الرقم السابق ما كان رقم صافي، نبدأ من 1 من جديد للبريفكس هذا
            return f"{prefix}0001"

        new_int = last_int + 1
        return f"{prefix}{new_int:04d}"
    def __str__(self):
        supporter = self.supporter_name or "متبرع غير مسجل"
        return f"{self.invoice.number} | {supporter} | {self.amount:,.2f} ر.س"


class FinancialSponsorshipInvoice(models.Model):
    """
    تفاصيل الكفالة المالية المرتبطة بالفاتورة.
    كل سجل هنا مرتبط بـ Invoice نوعها FINANCIAL_SPONSORSHIP
    """

    invoice = models.OneToOneField(
        "Invoice",  # نرجع لإسم الكلاس كسلسلة عشان يعرفه حتى لو معرف بعده
        verbose_name="الفاتورة",
        related_name="financial_sponsorship",
        on_delete=models.CASCADE,
        limit_choices_to={"invoice_type": "financial_sponsorship"},
    )

    sponsor = models.ForeignKey(
        Profile,
        verbose_name="الكافل",
        on_delete=models.PROTECT,
        related_name="sponsorship_invoices",
        limit_choices_to={"role": Profile.Roles.DONOR},
        help_text="يجب أن يكون نوعه DONOR في النظام.",
    )

    payment_plan = models.ForeignKey(
        PaymentPlan,
        verbose_name="نوع الكفالة (خطة الدفع)",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text="يتم تعريفها من مدير النظام في جدول خطط الدفعات.",
    )

    # خطة مخصّصة أو نسخة من مبلغ/مدة الخطة (نحن نملؤها في الفيو)
    is_custom_plan = models.BooleanField(
        "خطة مخصّصة (أخرى)",
        default=False,
        help_text="إذا كانت الخطة 'أخرى' يسمح بإدخال مبلغ ومدة يدويًا.",
    )

    # هنا نخزن *المبلغ الفعلي* للسند سواء من الخطة أو مخصص
    custom_amount = models.DecimalField(
        "مبلغ الكفالة (فعلي)",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )

    # وهنا نخزن *مدة الكفالة الفعلية* بالأشهر
    custom_duration_months = models.PositiveIntegerField(
        "مدة الكفالة بالأشهر (فعلية)",
        blank=True,
        null=True,
    )

    start_date = models.DateField("تاريخ بداية الكفالة")
    end_date = models.DateField("تاريخ نهاية الكفالة")

        # 🔹 تفاصيل التحويل البنكي (اختيارية – تظهر فقط عند اختيار تحويل بنكي)
    bank_from = models.CharField(
        "البنك المحوّل منه",
        max_length=100,
        blank=True,
    )
    from_account_number = models.CharField(
        "رقم الحساب المحوّل منه",
        max_length=50,
        blank=True,
    )
    to_account_number = models.CharField(
        "الحساب المحوّل عليه",
        max_length=50,
        blank=True,
    )

    class Meta:
        verbose_name = "تفاصيل كفالة مالية"
        verbose_name_plural = "تفاصيل الكفالات المالية"


    # 🔢 المبلغ الإجمالي للكفالة (يُستخدم في التخصيص)
    @property
    def total_amount(self) -> Decimal:
        """
        المبلغ الفعلي للكفالة:
        - نستخدم custom_amount لأنه يتم تعبئته من الفيو
          سواء كانت الخطة جاهزة أو مخصّصة.
        - كاحتياط، لو كان None نحاول نقرأ من مبلغ الخطة (payment_plan.amount).
        """
        if self.custom_amount is not None:
            return self.custom_amount

        if self.payment_plan and hasattr(self.payment_plan, "amount"):
            return self.payment_plan.amount

        return Decimal("0.00")

    # 💰 إجمالي ما تم تخصيصه كمبالغ للمستفيدين
    @property
    def allocated_amount(self) -> Decimal:
        from django.db.models import Sum
        agg = self.allocations.aggregate(total=Sum("amount"))
        return agg["total"] or Decimal("0.00")

    # 💸 المتبقي من مبلغ الكفالة الذي يمكن تخصيصه
    @property
    def remaining_amount(self) -> Decimal:
        return self.total_amount - self.allocated_amount

    def __str__(self):
        sponsor = (
            self.sponsor.full_name
            if self.sponsor and getattr(self.sponsor, "full_name", None)
            else str(self.sponsor)
        )

        amount = self.total_amount

        return (
            f"{self.invoice.number} | "
            f"{sponsor} | "
            f"{amount:,.2f} ر.س"
        )
##############################################################################################
class FinancialSponsorshipAllocation(models.Model):
    """
    تخصيص جزء من مبلغ الكفالة لمستفيد معيّن.
    """

    sponsorship_invoice = models.ForeignKey(
        FinancialSponsorshipInvoice,
        verbose_name="سند الكفالة المالية",
        related_name="allocations",
        on_delete=models.CASCADE,
    )

    beneficiary = models.ForeignKey(
        Beneficiary,
        verbose_name="المستفيد",
        related_name="sponsorship_allocations",
        on_delete=models.PROTECT,
    )

    amount = models.DecimalField(
        "المبلغ المخصص",
        max_digits=12,
        decimal_places=2,
    )

    notes = models.CharField(
        "ملاحظات",
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField("تاريخ التخصيص", auto_now_add=True)

    class Meta:
        verbose_name = "تخصيص كفالة مالية"
        verbose_name_plural = "تخصيصات الكفالات المالية"

    def __str__(self):
        return f"{self.amount} ر.س للمستفيد {self.beneficiary}"

    def clean(self):
        super().clean()

        if not self.sponsorship_invoice_id:
            return

        if self.amount is None or self.amount <= 0:
            raise ValidationError("المبلغ المخصص يجب أن يكون أكبر من صفر.")

        # 1) تحقق من سقف الكفالة نفسها
        existing_total = (
            self.sponsorship_invoice.allocations
            .exclude(pk=self.pk)
            .aggregate(total=Sum("amount"))
            .get("total") or Decimal("0.00")
        )

        new_total = existing_total + self.amount

        if new_total > self.sponsorship_invoice.total_amount:
            raise ValidationError(
                f"إجمالي التخصيصات ({new_total}) يتجاوز مبلغ الكفالة ({self.sponsorship_invoice.total_amount})."
            )

        # 2) ✅ التحقق المحاسبي الأهم: الصندوق المتاح
        available_fund = FundReservation.available_fund()

        if self.amount > available_fund:
            raise ValidationError(
                f"لا يمكن تخصيص {self.amount} ر.س — المتاح في الصندوق {available_fund} ر.س فقط."
            )


    def save(self, *args, **kwargs):
        # نضمن تشغيل clean بعد ما يكون sponsorship_invoice متعيّن في الفيو
        self.full_clean()
        super().save(*args, **kwargs)

        # بعد الحفظ، ننشئ/نحدّث حركة رصيد للمستفيد مرتبطة بهذا التخصيص
        BeneficiaryBalanceEntry.objects.update_or_create(
            allocation=self,
            defaults={
                "beneficiary": self.beneficiary,
                "amount": self.amount,  # دائماً موجبة هنا (رصيد لصالح المستفيد)
                "type": BeneficiaryBalanceEntry.Types.SPONSORSHIP_ALLOCATION,
                "program": None,  # ربطه ببرنامج عند الصرف لاحقاً
                "description": f"رصيد كفالة من السند {self.sponsorship_invoice.invoice.number}",
                "created_by": self.sponsorship_invoice.invoice.created_by,
            },
        )



class BeneficiaryBalanceEntry(models.Model):
    """
    حركة رصيد للمستفيد:
    - رصيد دائن من تخصيص كفالة مالية (Credit)
    - لاحقًا: حركات صرف (Debit) تحت برامج معينة
    """

    class Types(models.TextChoices):
        SPONSORSHIP_ALLOCATION = "sponsorship_allocation", "رصيد كفالة"
        ADJUSTMENT = "adjustment", "تعديل رصيد"
        EXPENSE = "expense", "صرف تحت برنامج"

    beneficiary = models.ForeignKey(
        "Management.Beneficiary",
        verbose_name="المستفيد",
        related_name="balance_entries",
        on_delete=models.PROTECT,
    )

    amount = models.DecimalField(
        "المبلغ",
        max_digits=12,
        decimal_places=2,
        help_text="موجب = زيادة في رصيد المستفيد، سالب = تخفيض/صرف.",
    )

    type = models.CharField(
        "نوع الحركة",
        max_length=32,
        choices=Types.choices,
    )

    # لو كانت الحركة ناتجة عن تخصيص كفالة مالية
    allocation = models.OneToOneField(
        FinancialSponsorshipAllocation,
        verbose_name="تخصيص الكفالة",
        related_name="balance_entry",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    # مستقبلاً عند الصرف من رصيد المستفيد على برنامج فرعي معيّن
    program = models.ForeignKey(
        SubProgram,
        verbose_name="البرنامج الفرعي",
        related_name="beneficiary_balance_entries",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    description = models.CharField(
        "وصف الحركة",
        max_length=255,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="تم تسجيلها بواسطة",
        related_name="beneficiary_balance_entries",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField("تاريخ إنشاء الحركة", auto_now_add=True)

    class Meta:
        verbose_name = "حركة رصيد مستفيد"
        verbose_name_plural = "حركات أرصدة المستفيدين"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        parts = [
            str(self.beneficiary),
            self.get_type_display(),
        ]

        if self.program:
            parts.append(self.program.name)

        parts.append(f"{self.amount:,.2f} ر.س")

        return " | ".join(parts)
##########################################################################################################################

# ====== NEW MODELS FOR ACCOUNTANT (Policy B) ======

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F

class FundToMainProgramAllocation(models.Model):
    """
    تخصيص (داخلي) من الصندوق العام إلى برنامج رئيسي (Budget/Reservation).
    ملاحظة:
    - هذا ليس خصماً فعلياً من الصندوق البنكي.
    - الخصم الفعلي من الصندوق يُسجل فقط في FundEntry عند الصرف الحقيقي.
    """

    main_program = models.ForeignKey(
        MainProgram, on_delete=models.PROTECT,
        related_name="fund_allocations",
        verbose_name="البرنامج الرئيسي"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تخصيص من الصندوق لبرنامج رئيسي"
        verbose_name_plural = "تخصيصات الصندوق للبرامج الرئيسية"
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError("المبلغ يجب أن يكون أكبر من صفر.")
        # ❌ لا تفحص FundEntry.total_balance هنا
        # ✅ فحص المتاح بعد الحجوزات يتم في الفيو قبل إنشاء الحجز

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)

            # ✅ رفع ميزانية البرنامج الرئيسي (محفظة داخلية)
            MainProgram.objects.filter(pk=self.main_program_id).update(
                total_donation_amount=F("total_donation_amount") + self.amount
            )
            # تحديث الكائن الحالي (اختياري لتفادي قيم قديمة بالذاكرة)
            self.main_program.refresh_from_db(fields=["total_donation_amount"])

    def __str__(self):
        return (
            f"{self.main_program.name} | "
            f"{self.amount:,.2f} ر.س"
        )
class MainToSubProgramAllocation(models.Model):
    """
    تحويل رصيد من برنامج رئيسي إلى برنامج فرعي (محفظة داخلية).
    لا يلمس الصندوق العام إطلاقاً (لا ينشئ FundEntry).
    """
    main_program = models.ForeignKey(
        MainProgram, on_delete=models.PROTECT,
        related_name="sub_allocations",
        verbose_name="البرنامج الرئيسي"
    )
    sub_program = models.ForeignKey(
        SubProgram, on_delete=models.PROTECT,
        related_name="main_allocations",
        verbose_name="البرنامج الفرعي"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "تحويل رئيسي إلى فرعي"
        verbose_name_plural = "تحويلات رئيسي إلى فرعي"
    @property
    def remaining_main_balance(self):
        return self.main_program.remaining_balance
    def clean(self):
        super().clean()

        if not self.main_program_id or not self.sub_program_id:
            return

        if self.amount is None or self.amount <= 0:
            raise ValidationError("أدخل مبلغ صحيح أكبر من صفر.")

        # ✅ لازم الفرعي تابع لنفس الرئيسي
        if self.sub_program.main_program_id != self.main_program_id:
            raise ValidationError("البرنامج الفرعي المختار لا يتبع البرنامج الرئيسي المحدد.")

        # ✅ تحقق سقف الرئيسي (Budget) = total_donation_amount - مجموع تخصيصات الفروع الأخرى
        other_allocs = (
            SubProgram.objects
            .filter(main_program_id=self.main_program_id)
            .exclude(pk=self.sub_program_id)
            .aggregate(t=Sum("allocated_amount"))["t"] or Decimal("0.00")
        )
        available_main = (self.main_program.total_donation_amount or Decimal("0.00")) - other_allocs
        if self.amount > available_main:
            raise ValidationError("رصيد البرنامج الرئيسي المتاح لا يكفي للتحويل.")

    def save(self, *args, **kwargs):
        self.full_clean()

        with transaction.atomic():
            # ✅ delta-safe: لو تعديل على سجل قديم ما يتضاعف الرصيد
            delta = self.amount
            if self.pk:
                old = MainToSubProgramAllocation.objects.select_for_update().get(pk=self.pk)
                # لو تغير الفرعي (نادر) نعكس القديم من الفرعي السابق ثم نضيف للجديد
                if old.sub_program_id != self.sub_program_id:
                    old_sp = SubProgram.objects.select_for_update().get(pk=old.sub_program_id)
                    old_sp.allocated_amount = (old_sp.allocated_amount or Decimal("0.00")) - (old.amount or Decimal("0.00"))
                    if old_sp.allocated_amount < 0:
                        old_sp.allocated_amount = Decimal("0.00")
                    old_sp.save(update_fields=["allocated_amount"])
                    delta = self.amount
                else:
                    delta = (self.amount or Decimal("0.00")) - (old.amount or Decimal("0.00"))

            super().save(*args, **kwargs)

            sp = SubProgram.objects.select_for_update().get(pk=self.sub_program_id)
            sp.allocated_amount = (sp.allocated_amount or Decimal("0.00")) + (delta or Decimal("0.00"))
            if sp.allocated_amount < 0:
                sp.allocated_amount = Decimal("0.00")
            sp.save(update_fields=["allocated_amount"])

    def __str__(self):
        return (
            f"{self.main_program.name}"
            f" → "
            f"{self.sub_program.name}"
            f" | "
            f"{self.amount:,.2f} ر.س"
        )
class SubProgramDisbursement(models.Model):
    """
    أمر صرف من برنامج فرعي لمستفيد واحد أو أكثر (سياسة B).

    ملاحظة محاسبية:
    - محافظ (الفرعي/المستفيد) = قيود داخلية (Budget Wallet)
    - FundEntry = حركة الصندوق العام الفعلية فقط (Cash Movement)
    - ممنوع ربط الصرف بـ FundReservation هنا (لا خصم ولا تحرير).
    """

    class SourceTypes(models.TextChoices):
        SUB_PROGRAM = "sub_program", "من رصيد البرنامج الفرعي"
        BENEFICIARY = "beneficiary", "من رصيد المستفيد"

    sub_program = models.ForeignKey("Management.SubProgram", on_delete=models.PROTECT)
    source_type = models.CharField(
        max_length=20,
        choices=SourceTypes.choices,
        default=SourceTypes.SUB_PROGRAM,
        verbose_name="مصدر الصرف",
    )
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    voucher_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        verbose_name="رقم السند"
    )

    class Meta:
        verbose_name = "أمر صرف برنامج فرعي"
        verbose_name_plural = "أوامر صرف البرامج الفرعية"
        ordering = ["-created_at", "-id"]

    
    @property
    def total_amount(self):
        return self.lines.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    def execute(self):
        """
        التنفيذ الصحيح (خيار A):
        - SUB_PROGRAM:
            * خصم داخلي من ميزانية الفرعي (spent_amount)
            * تسجيل حركة الصندوق (FundEntry)
            * تسجيل “دعم” للمستفيدين في BeneficiarySupportEntry (للتقارير) ✅
            * لا يلمس محفظة المستفيد (BeneficiaryBalanceEntry) ❌
        - BENEFICIARY:
            * خصم داخلي من محفظة المستفيد (BeneficiaryBalanceEntry)
            * تسجيل حركة الصندوق (FundEntry)
        """
        from decimal import Decimal
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from django.db.models import Sum
        from .models import FundEntry, BeneficiaryBalanceEntry, BeneficiarySupportEntry

        with transaction.atomic():
            sp = self.sub_program
            total = self.total_amount

            if total <= 0:
                raise ValidationError("يجب إضافة مستفيدين ومبالغ قبل التنفيذ.")

            # ====== مصدر الصرف: محفظة البرنامج الفرعي ======
            if self.source_type == self.SourceTypes.SUB_PROGRAM:
                if sp.remaining_amount < total:
                    raise ValidationError("رصيد البرنامج الفرعي لا يكفي لهذا الصرف.")

                lines = list(self.lines.select_related("beneficiary").all())
                if not lines:
                    raise ValidationError("لا يوجد مستفيدين داخل أمر الصرف.")

                # (1) خصم داخلي من محفظة الفرعي
                sp.spent_amount = (sp.spent_amount or Decimal("0.00")) + total
                sp.save(update_fields=["spent_amount"])

                # (2) حركة فعلية في الصندوق العام
                FundEntry.objects.create(
                    invoice=None,
                    beneficiary=None,
                    main_program=sp.main_program,
                    sub_program=sp,
                    type=FundEntry.Types.PROGRAM_EXPENSE,
                    amount=-total,
                    voucher_number=self.voucher_number,
                    description=f"صرف فعلي لمستفيدين تحت برنامج {sp.name} (مصدر: محفظة الفرعي)",
                    created_by=self.created_by,
                )

                # (3) ✅ تسجيل دعم للمستفيدين (تقارير فقط)
                for ln in lines:
                    if (ln.amount or Decimal("0.00")) <= 0:
                        raise ValidationError("مبلغ الصرف لكل مستفيد يجب أن يكون أكبر من صفر.")

                    BeneficiarySupportEntry.objects.create(
                        beneficiary=ln.beneficiary,
                        sub_program=sp,
                        main_program=sp.main_program,
                        amount=ln.amount,
                        voucher_number=self.voucher_number,
                        disbursement=self,
                        note=(self.notes or "").strip(),
                        created_by=self.created_by,
                    )

                return  # انتهى SUB_PROGRAM ✅

            # ====== مصدر الصرف: محفظة المستفيد ======
            lines = list(self.lines.select_related("beneficiary").all())
            if len(lines) != 1:
                raise ValidationError("الصرف من رصيد المستفيد متاح لمستفيد واحد فقط في الأمر.")

            line = lines[0]
            bene = line.beneficiary
            amount = line.amount or Decimal("0.00")

            if amount <= 0:
                raise ValidationError("مبلغ الصرف يجب أن يكون أكبر من صفر.")

            bene_balance = (
                BeneficiaryBalanceEntry.objects
                .filter(beneficiary=bene)
                .aggregate(t=Sum("amount"))["t"]
                or Decimal("0.00")
            )

            if amount > bene_balance:
                raise ValidationError("رصيد المستفيد لا يكفي لهذا الصرف.")

            # (1) خصم داخلي من محفظة المستفيد
            BeneficiaryBalanceEntry.objects.create(
                beneficiary=bene,
                amount=-amount,
                type=BeneficiaryBalanceEntry.Types.EXPENSE,
                program=sp,
                description=f"صرف من محفظة المستفيد على برنامج {sp.name} - سند {self.voucher_number}",
                created_by=self.created_by,
            )

            # (2) حركة فعلية في الصندوق العام
            FundEntry.objects.create(
                invoice=None,
                beneficiary=bene,
                main_program=sp.main_program,
                sub_program=sp,
                type=FundEntry.Types.PROGRAM_EXPENSE,
                amount=-amount,
                voucher_number=self.voucher_number,
                description=f"صرف فعلي للمستفيد {bene} تحت برنامج {sp.name} (مصدر: محفظة المستفيد)",
                created_by=self.created_by,
            )
    def __str__(self):
        return (
            f"{self.voucher_number} | "
            f"{self.sub_program.name} | "
            f"{self.get_source_type_display()} | "
            f"{self.total_amount:,.2f} ر.س"
        )   

class SubProgramDisbursementLine(models.Model):
    disbursement = models.ForeignKey(
        SubProgramDisbursement, related_name="lines",
        on_delete=models.CASCADE
    )
    beneficiary = models.ForeignKey("Management.Beneficiary", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "تفاصيل صرف مستفيد"
        verbose_name_plural = "تفاصيل صرف المستفيدين"

    def clean(self):
        if self.amount <= 0:
            raise ValidationError("مبلغ الصرف يجب أن يكون أكبر من صفر.")
    def __str__(self):
        return (
            f"{self.beneficiary} | "
            f"{self.amount:,.2f} ر.س"
        )


class FundReservation(models.Model):
    """
    حجز داخلي من رصيد الصندوق العام
    (لا يمثل حركة بنكية فعلية)
    """

    class Sources(models.TextChoices):
        BENEFICIARY = "beneficiary", "محفظة مستفيد"
        MAIN_PROGRAM = "main_program", "ميزانية برنامج رئيسي"
        SUB_PROGRAM = "sub_program", "ميزانية برنامج فرعي"

    source_type = models.CharField(
        max_length=20,
        choices=Sources.choices,
    )

    beneficiary = models.ForeignKey(
        Beneficiary,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="fund_reservations",
    )

    main_program = models.ForeignKey(
        MainProgram,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="fund_reservations",
    )

    sub_program = models.ForeignKey(
        SubProgram,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="fund_reservations",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="موجب = حجز، سالب = تحرير حجز",
    )

    reference = models.CharField(
        max_length=50,
        blank=True,
        help_text="رقم السند / مرجع العملية",
    )

    note = models.CharField(
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    @classmethod
    def total_reserved(cls) -> Decimal:
        return cls.objects.aggregate(
            t=Coalesce(Sum("amount"), Decimal("0.00"))
        )["t"]

    @classmethod
    def available_fund(cls) -> Decimal:
        """
        المتاح في الصندوق = إجمالي حركات الصندوق (FundEntry) - إجمالي المحجوزات (FundReservation)
        """
        from .models import FundEntry  # لتجنب circular import

        fund_total = FundEntry.objects.aggregate(
            t=Coalesce(Sum("amount"), Decimal("0.00"))
        )["t"]

        reserved = cls.total_reserved()
        available = fund_total - reserved
        return available if available > 0 else Decimal("0.00")

    def __str__(self):
        if self.main_program:
            target = self.main_program.name
        elif self.sub_program:
            target = self.sub_program.name
        elif self.beneficiary:
            target = str(self.beneficiary)
        else:
            target = "الصندوق العام"

        return (
            f"{self.get_source_type_display()} | "
            f"{target} | "
            f"{self.amount:,.2f} ر.س"
        )
##################################################################################################################################


class BeneficiarySupportEntry(models.Model):
    """
    دفتر “دعم/استفادة” للمستفيدين من محافظ البرامج (ليس دين).
    - يُستخدم للعرض والتقارير للمحاسب.
    - لا يؤثر على محفظة المستفيد (BeneficiaryBalanceEntry).
    """

    beneficiary = models.ForeignKey(
        "Management.Beneficiary",
        on_delete=models.PROTECT,
        related_name="support_entries",
        verbose_name="المستفيد",
    )

    sub_program = models.ForeignKey(
        "Management.SubProgram",
        on_delete=models.PROTECT,
        related_name="support_entries",
        verbose_name="البرنامج الفرعي",
    )

    main_program = models.ForeignKey(
        "Management.MainProgram",
        on_delete=models.PROTECT,
        related_name="support_entries",
        verbose_name="البرنامج الرئيسي",
        null=True, blank=True,
    )

    amount = models.DecimalField(
        "مبلغ الدعم",
        max_digits=12,
        decimal_places=2,
        help_text="موجب فقط (قيمة ما استفاد به المستفيد من محفظة برنامج).",
    )

    voucher_number = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="رقم سند الصرف",
    )

    disbursement = models.ForeignKey(
        "Accounting.SubProgramDisbursement",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="support_entries",
        verbose_name="أمر الصرف",
    )

    note = models.CharField("ملاحظة", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="beneficiary_support_entries",
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "دعم مستفيد من برنامج"
        verbose_name_plural = "دعم المستفيدين من البرامج"

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError("مبلغ الدعم يجب أن يكون أكبر من صفر.")

    def __str__(self):
        return (
            f"{self.beneficiary} | "
            f"{self.sub_program.name} | "
            f"{self.amount:,.2f} ر.س"
        )
    

class SponsorshipReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    donor = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="sponsorship_reports",
    )

    generated_by = models.ForeignKey(
            Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    from_date = models.DateField()

    to_date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    pdf_file = models.FileField(
        upload_to="reports/sponsorship/",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        donor = (
            self.donor.full_name
            if getattr(self.donor, "full_name", None)
            else str(self.donor)
        )

        return (
            f"{donor} | "
            f"{self.from_date} → {self.to_date}"
        )