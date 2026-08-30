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
from django.utils import timezone

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
    تفاصيل الكفالة المالية المرتبطة بالسند.

    القاعدة:
    - كل سند كفالة مالي مرتبط بكافل واحد.
    - كل سند كفالة مالي يمكن إلحاقه بمستفيد واحد فقط.
    - مبلغ السند هو المبلغ الكامل المخصص لذلك المستفيد.
    """

    invoice = models.OneToOneField(
        "Invoice",
        verbose_name="الفاتورة",
        related_name="financial_sponsorship",
        on_delete=models.CASCADE,
        limit_choices_to={
            "invoice_type": "financial_sponsorship"
        },
    )

    sponsor = models.ForeignKey(
        Profile,
        verbose_name="الكافل",
        on_delete=models.PROTECT,
        related_name="sponsorship_invoices",
        limit_choices_to={
            "role": Profile.Roles.DONOR
        },
        help_text="يجب أن يكون نوع الكافل DONOR في النظام.",
    )

    payment_plan = models.ForeignKey(
        PaymentPlan,
        verbose_name="نوع الكفالة (خطة الدفع)",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        help_text="يتم تعريفها من مدير النظام في جدول خطط الدفعات.",
    )

    is_custom_plan = models.BooleanField(
        "خطة مخصّصة (أخرى)",
        default=False,
        help_text=(
            "إذا كانت الخطة أخرى يسمح بإدخال "
            "مبلغ ومدة يدويًا."
        ),
    )

    custom_amount = models.DecimalField(
        "مبلغ الكفالة (فعلي)",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )

    custom_duration_months = models.PositiveIntegerField(
        "مدة الكفالة بالأشهر (فعلية)",
        blank=True,
        null=True,
    )

    start_date = models.DateField(
        "تاريخ بداية الكفالة"
    )

    end_date = models.DateField(
        "تاريخ نهاية الكفالة"
    )

    # ---------------------------------------------------------
    # تفاصيل التحويل البنكي
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # المبلغ الفعلي للسند
    # ---------------------------------------------------------

    @property
    def total_amount(self) -> Decimal:
        """
        المبلغ الفعلي لسند الكفالة.

        يتم استخدام custom_amount لأنه يمثل
        المبلغ النهائي الفعلي للسند.
        """

        if self.custom_amount is not None:
            return self.custom_amount

        if self.payment_plan and hasattr(
            self.payment_plan,
            "amount",
        ):
            return self.payment_plan.amount

        return Decimal("0.00")

    # ---------------------------------------------------------
    # التخصيص
    # ---------------------------------------------------------

    @property
    def allocated_amount(self) -> Decimal:
        """
        المبلغ المخصص للمستفيد.

        السند الآن يمكن أن يكون له تخصيص واحد فقط.
        """

        if hasattr(self, "allocation"):
            return self.allocation.amount or Decimal("0.00")

        return Decimal("0.00")

    # ---------------------------------------------------------
    # المتبقي
    # ---------------------------------------------------------

    @property
    def remaining_amount(self) -> Decimal:
        """
        المبلغ المتبقي من السند قبل إلحاقه بمستفيد.
        """

        remaining = (
            self.total_amount - self.allocated_amount
        )

        return max(
            remaining,
            Decimal("0.00"),
        )

    # ---------------------------------------------------------
    # هل السند مرتبط بمستفيد؟
    # ---------------------------------------------------------

    @property
    def is_allocated(self) -> bool:
        """
        True إذا تم إلحاق السند بمستفيد.
        """

        return hasattr(self, "allocation")

    # ---------------------------------------------------------
    # المستفيد المرتبط بالسند
    # ---------------------------------------------------------

    @property
    def beneficiary(self):
        """
        يعيد المستفيد المرتبط بالسند، إن وجد.
        """

        if hasattr(self, "allocation"):
            return self.allocation.beneficiary

        return None

    # ---------------------------------------------------------
    # هل السند ساري اليوم؟
    # ---------------------------------------------------------

    def is_active(self, today=None) -> bool:
        """
        يتحقق من أن السند ساري في التاريخ المحدد.
        إذا لم يتم تمرير تاريخ يستخدم تاريخ اليوم.
        """


        if today is None:
            today = timezone.localdate()

        return (
            self.start_date <= today
            and self.end_date >= today
        )

    # ---------------------------------------------------------
    # حالة السند
    # ---------------------------------------------------------

    @property
    def status(self):
        """
        حالة سند الكفالة:
        - لم تبدأ بعد
        - سارية
        - منتهية
        """


        today = timezone.localdate()

        if today < self.start_date:
            return "لم تبدأ بعد"

        if today > self.end_date:
            return "منتهية"

        return "سارية"

    def __str__(self):
        sponsor = (
            self.sponsor.full_name
            if self.sponsor
            and getattr(
                self.sponsor,
                "full_name",
                None,
            )
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
    تخصيص سند كفالة مالية لمستفيد واحد فقط.

    كل سند كفالة مالية يمكن ربطه بمستفيد واحد فقط.
    """

    sponsorship_invoice = models.OneToOneField(
        FinancialSponsorshipInvoice,
        verbose_name="سند الكفالة المالية",
        related_name="allocation",
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

    created_at = models.DateTimeField(
        "تاريخ التخصيص",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "تخصيص كفالة مالية"
        verbose_name_plural = "تخصيصات الكفالات المالية"

    def __str__(self):
        return (
            f"{self.amount} ر.س "
            f"للمستفيد {self.beneficiary}"
        )

    def clean(self):
        super().clean()

        if not self.sponsorship_invoice_id:
            return

        # ---------------------------------------------------------
        # 1) التحقق من المبلغ
        # ---------------------------------------------------------

        if self.amount is None or self.amount <= 0:
            raise ValidationError(
                "المبلغ المخصص يجب أن يكون أكبر من صفر."
            )

        # ---------------------------------------------------------
        # 2) السند الواحد = مستفيد واحد
        # ---------------------------------------------------------
        #
        # OneToOneField يضمن ذلك على مستوى قاعدة البيانات،
        # لكن نتحقق أيضًا هنا برسالة واضحة للمستخدم.
        #

        existing_allocation = (
            FinancialSponsorshipAllocation.objects
            .filter(
                sponsorship_invoice=self.sponsorship_invoice
            )
            .exclude(pk=self.pk)
            .first()
        )

        if existing_allocation:
            raise ValidationError(
                "سند الكفالة هذا مرتبط بالفعل بمستفيد آخر."
            )

        # ---------------------------------------------------------
        # 3) التحقق من أن مبلغ التخصيص لا يتجاوز مبلغ السند
        # ---------------------------------------------------------

        if self.amount > self.sponsorship_invoice.total_amount:
            raise ValidationError(
                f"المبلغ المخصص ({self.amount} ر.س) "
                f"يتجاوز مبلغ الكفالة "
                f"({self.sponsorship_invoice.total_amount} ر.س)."
            )

      
    def save(self, *args, **kwargs):
        """
        التحقق قبل الحفظ ثم إنشاء/تحديث رصيد المستفيد
        المرتبط بتخصيص الكفالة.
        """

        self.full_clean()

        super().save(*args, **kwargs)



    
class SubProgramDisbursement(models.Model):
    """
    رأس أمر صرف من برنامج فرعي أو من رصيد مستفيد.
    يحتوي على بيانات الأمر فقط، أما تنفيذ العمليات المحاسبية
    فيتم من خلال Accounting.services.
    """

    class SourceTypes(models.TextChoices):
        SUB_PROGRAM = "sub_program", "من رصيد البرنامج الفرعي"
        BENEFICIARY = "beneficiary", "من رصيد المستفيد"

    sub_program = models.ForeignKey(
        "Management.SubProgram",
        on_delete=models.PROTECT,
        related_name="disbursements",
        verbose_name="البرنامج الفرعي",
    )

    source_type = models.CharField(
        max_length=20,
        choices=SourceTypes.choices,
        default=SourceTypes.SUB_PROGRAM,
        verbose_name="مصدر الصرف",
    )

    voucher_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        verbose_name="رقم سند الصرف",
    )
    is_reversed = models.BooleanField(
        default=False,
        verbose_name="تم عكس العملية"
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="ملاحظات",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sub_program_disbursements",
        verbose_name="أنشئ بواسطة",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاريخ الإنشاء",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "أمر صرف برنامج فرعي"
        verbose_name_plural = "أوامر صرف البرامج الفرعية"

    @property
    def total_amount(self):
        return (
            self.support_entries.aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )

    def __str__(self):
        return (
            f"{self.voucher_number} | "
            f"{self.sub_program.name} | "
            f"{self.get_source_type_display()} | "
            f"{self.total_amount:,.2f} ر.س"
        )
 
#################################################################################################


class BeneficiarySupportEntry(models.Model):
    """
    دفتر “دعم/استفادة” للمستفيدين من محافظ البرامج (ليس دين).
    - يُستخدم للعرض والتقارير للمحاسب.
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
    




        #########################################################################
class AllocationHistory(models.Model):

    class Action(models.TextChoices):
        FUND_TO_MAIN = "fund_to_main", "الصندوق > البرنامج الرئيسي"
        MAIN_TO_MAIN = "main_to_main", "برنامج رئيسي > برنامج رئيسي"
        MAIN_TO_SUB = "main_to_sub", "البرنامج الرئيسي > الفرعي"
        SUB_TO_MAIN = "sub_to_main", "البرنامج الفرعي > الرئيسي"
        MAIN_TO_FUND = "main_to_fund", "البرنامج الرئيسي > الصندوق"

    action = models.CharField(
        "نوع العملية",
        max_length=30,
        choices=Action.choices,
    )

    from_main_program = models.ForeignKey(
        MainProgram,
        verbose_name="من البرنامج الرئيسي",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="allocation_history_from",
    )

    to_main_program = models.ForeignKey(
        MainProgram,
        verbose_name="إلى البرنامج الرئيسي",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="allocation_history_to",
    )

    from_sub_program = models.ForeignKey(
        SubProgram,
        verbose_name="من البرنامج الفرعي",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="allocation_history_from",
    )

    to_sub_program = models.ForeignKey(
        SubProgram,
        verbose_name="إلى البرنامج الفرعي",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="allocation_history_to",
    )

    amount = models.DecimalField(
        "المبلغ",
        max_digits=12,
        decimal_places=2,
    )

    reference = models.CharField(
        "المرجع",
        max_length=50,
        blank=True,
    )

    note = models.CharField(
        "ملاحظات",
        max_length=255,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="تمت بواسطة",
        on_delete=models.PROTECT,
        related_name="allocation_history",
    )

    created_at = models.DateTimeField(
        "تاريخ العملية",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "سجل تخصيص"
        verbose_name_plural = "سجل التخصيصات"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return (
            f"{self.get_action_display()} | "
            f"{self.amount:,.2f} ر.س"
        )