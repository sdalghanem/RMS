from decimal import Decimal
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db import transaction

from .models import (
    FundEntry,
    BeneficiarySupportEntry,
    SubProgramDisbursement,
    AllocationHistory,
    MainProgram,
    SubProgram,
)


def get_fund_balance() -> Decimal:
    """
    الرصيد الحقيقي للصندوق.

    لا يتأثر بالتخصيصات الداخلية.
    يتغير فقط من خلال FundEntry.
    """

    return FundEntry.objects.aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]


def get_total_main_allocated() -> Decimal:
    """
    إجمالي المبالغ المخصصة للبرامج الرئيسية.
    """

    return MainProgram.objects.aggregate(
        total=Coalesce(
            Sum("total_donation_amount"),
            Decimal("0.00"),
        )
    )["total"]


def get_available_for_allocation() -> Decimal:
    """
    المبلغ المتاح حاليًا لإعادة التخصيص من الصندوق.

    الرصيد الحقيقي للصندوق لا يتغير عند التخصيصات الداخلية.

    المتاح للتخصيص =
        رصيد الصندوق الحقيقي
        - إجمالي التخصيصات الحالية للبرامج الرئيسية
    """

    fund_balance = get_fund_balance()

    allocated = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.FUND_TO_MAIN,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    released = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.MAIN_TO_FUND,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    allocated = allocated or Decimal("0.00")
    released = released or Decimal("0.00")

    current_allocated = allocated - released

    available = fund_balance - current_allocated

    return max(
        available,
        Decimal("0.00"),
    )

def get_main_program_balance(main_program) -> Decimal:
    """
    الرصيد المتاح داخل البرنامج الرئيسي
    للتوزيع على البرامج الفرعية أو إعادة التخصيص.

    الرصيد =
    إجمالي تخصيص البرنامج الرئيسي
    - المبالغ المحولة إلى البرامج الفرعية
    + المبالغ المحررة من البرامج الفرعية إلى البرنامج الرئيسي.
    """

    allocated = main_program.total_donation_amount or Decimal("0.00")

    transferred_to_sub = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.MAIN_TO_SUB,
        from_main_program=main_program,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    returned_from_sub = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.SUB_TO_MAIN,
        to_main_program=main_program,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    balance = (
        allocated
        - transferred_to_sub
        + returned_from_sub
    )

    return max(
        balance,
        Decimal("0.00"),
    )
def get_sub_program_balance(sub_program) -> Decimal:
    """
    الرصيد المتاح داخل البرنامج الفرعي للصرف.

    الرصيد =
    المبالغ المحولة من البرنامج الرئيسي
    - المبالغ المحررة من الفرعي إلى الرئيسي
    - المصروف الفعلي للمستفيدين.
    """

    transferred_to_sub = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.MAIN_TO_SUB,
        to_sub_program=sub_program,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    returned_to_main = AllocationHistory.objects.filter(
        action=AllocationHistory.Action.SUB_TO_MAIN,
        from_sub_program=sub_program,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    spent = BeneficiarySupportEntry.objects.filter(
        sub_program=sub_program,
        disbursement__is_reversed=False,
    ).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
        )
    )["total"]

    balance = (
        transferred_to_sub
        - returned_to_main
        - spent
    )

    return max(
        balance,
        Decimal("0.00"),
    )

# تخصيص من صندوق الجمعية لبرنامج رئيسي 
def allocate_to_main_program(
    *,
    main_program,
    amount,
    user,
    note="",
    reference="",
):
    """
    تخصيص مبلغ من الرصيد المتاح للصندوق
    إلى برنامج رئيسي.

    التخصيص الداخلي لا يخصم من FundEntry.
    """

    amount = Decimal(amount)

    if amount <= 0:
        raise ValueError("يجب أن يكون المبلغ أكبر من صفر.")

    available = get_available_for_allocation()

    if amount > available:
        raise ValueError(
            f"المبلغ يتجاوز المتاح للتخصيص ({available:,.2f} ر.س)."
        )

    with transaction.atomic():

        main_program.total_donation_amount += amount
        main_program.save(
            update_fields=["total_donation_amount"]
        )

        history = AllocationHistory.objects.create(
            action=AllocationHistory.Action.FUND_TO_MAIN,
            to_main_program=main_program,
            amount=amount,
            reference=reference,
            note=note,
            created_by=user,
        )

    return history

def allocate_to_sub_program(
    *,
    main_program,
    sub_program,
    amount,
    user,
    note="",
    reference="",
):
    """
    تخصيص مبلغ من البرنامج الرئيسي إلى برنامج فرعي.

    لا يؤثر على رصيد الصندوق.
    """

    amount = Decimal(amount)

    if amount <= 0:
        raise ValueError("يجب أن يكون المبلغ أكبر من صفر.")

    if sub_program.main_program_id != main_program.id:
        raise ValueError(
            "البرنامج الفرعي لا يتبع البرنامج الرئيسي المحدد."
        )

    available = get_main_program_balance(main_program)

    if amount > available:
        raise ValueError(
            f"المبلغ يتجاوز المتاح في البرنامج الرئيسي "
            f"({available:,.2f} ر.س)."
        )

    with transaction.atomic():

        sub_program.allocated_amount += amount
        sub_program.save(
            update_fields=["allocated_amount"]
        )

        history = AllocationHistory.objects.create(
            action=AllocationHistory.Action.MAIN_TO_SUB,
            from_main_program=main_program,
            to_sub_program=sub_program,
            amount=amount,
            reference=reference,
            note=note,
            created_by=user,
        )

    return history

def release_from_sub_program(
    *,
    sub_program,
    amount,
    user,
    note="",
    reference="",
):
    """
    تحرير مبلغ من البرنامج الفرعي وإعادته إلى البرنامج الرئيسي.

    لا يؤثر على رصيد الصندوق.
    """

    amount = Decimal(amount)

    if amount <= 0:
        raise ValueError("يجب أن يكون المبلغ أكبر من صفر.")

    available = get_sub_program_balance(sub_program)

    if amount > available:
        raise ValueError(
            f"المبلغ يتجاوز المتاح في البرنامج الفرعي "
            f"({available:,.2f} ر.س)."
        )

    main_program = sub_program.main_program

    with transaction.atomic():

        sub_program.allocated_amount -= amount
        sub_program.save(
            update_fields=["allocated_amount"]
        )

        history = AllocationHistory.objects.create(
            action=AllocationHistory.Action.SUB_TO_MAIN,
            from_sub_program=sub_program,
            to_main_program=main_program,
            amount=amount,
            reference=reference,
            note=note,
            created_by=user,
        )

    return history


def release_from_main_program(
    *,
    main_program,
    amount,
    user,
    note="",
    reference="",
):
    """
    فك تخصيص مبلغ من البرنامج الرئيسي وإعادته
    إلى الرصيد المتاح للتخصيص.

    لا يؤثر على FundEntry.
    """

    amount = Decimal(amount)

    if amount <= 0:
        raise ValueError("يجب أن يكون المبلغ أكبر من صفر.")

    available = get_main_program_balance(main_program)

    if amount > available:
        raise ValueError(
            f"لا يمكن تحرير المبلغ. "
            f"المتاح للتحرير من البرنامج الرئيسي "
            f"هو ({available:,.2f} ر.س)."
        )

    with transaction.atomic():

        main_program.total_donation_amount -= amount

        main_program.save(
            update_fields=["total_donation_amount"]
        )

        history = AllocationHistory.objects.create(
            action=AllocationHistory.Action.MAIN_TO_FUND,
            from_main_program=main_program,
            amount=amount,
            reference=reference,
            note=note,
            created_by=user,
        )

    return history


#إعادة تخصيص من برنامج رئيسي إلى برنامج رئيسي آخر
def reallocate_main_to_main(
    *,
    from_main_program,
    to_main_program,
    amount,
    user,
    note="",
    reference="",
):
    """
    نقل مبلغ متاح من برنامج رئيسي إلى برنامج رئيسي آخر.

    لا يؤثر على رصيد الصندوق.
    """

    amount = Decimal(amount)

    if amount <= 0:
        raise ValueError("يجب أن يكون المبلغ أكبر من صفر.")

    if from_main_program.id == to_main_program.id:
        raise ValueError(
            "لا يمكن تحويل المبلغ إلى نفس البرنامج."
        )

    available = get_main_program_balance(from_main_program)

    if amount > available:
        raise ValueError(
            f"المبلغ يتجاوز المتاح في البرنامج الرئيسي "
            f"({available:,.2f} ر.س)."
        )

    with transaction.atomic():

        from_main_program.total_donation_amount -= amount
        from_main_program.save(
            update_fields=["total_donation_amount"]
        )

        to_main_program.total_donation_amount += amount
        to_main_program.save(
            update_fields=["total_donation_amount"]
        )

        history = AllocationHistory.objects.create(
            action=AllocationHistory.Action.MAIN_TO_MAIN,
            from_main_program=from_main_program,
            to_main_program=to_main_program,
            amount=amount,
            reference=reference,
            note=note,
            created_by=user,
        )

    return history
# ========= أوامر الصرف =========
def validate_subprogram_disbursement(
    *,
    sub_program,
    beneficiaries,
    voucher_number,
):
    """
    التحقق من أمر الصرف.

    الصرف يتم من الرصيد المتاح للبرنامج الفرعي،
    والصندوق ينقص فقط عند تنفيذ الصرف الفعلي.
    """

    if not voucher_number:
        raise ValueError("رقم سند الصرف مطلوب.")

    if SubProgramDisbursement.objects.filter(
        voucher_number=voucher_number
    ).exists():
        raise ValueError("رقم سند الصرف مستخدم مسبقاً.")

    if not beneficiaries:
        raise ValueError(
            "يجب اختيار مستفيد واحد على الأقل."
        )

    total_amount = Decimal("0.00")

    for item in beneficiaries:

        amount = Decimal(item["amount"])

        if amount <= 0:
            raise ValueError(
                "جميع مبالغ الصرف يجب أن تكون أكبر من صفر."
            )

        total_amount += amount

    if total_amount <= 0:
        raise ValueError(
            "إجمالي مبلغ الصرف يجب أن يكون أكبر من صفر."
        )

    available_balance = get_sub_program_balance(
        sub_program
    )

    if total_amount > available_balance:
        raise ValueError(
            f"رصيد البرنامج الفرعي غير كافٍ. "
            f"المتاح ({available_balance:,.2f} ر.س)."
        )

    return total_amount


def create_disbursement(
    *,
    sub_program,
    voucher_number,
    note,
    user,
):
    return SubProgramDisbursement.objects.create(
        sub_program=sub_program,
        source_type=SubProgramDisbursement.SourceTypes.SUB_PROGRAM,
        voucher_number=voucher_number,
        notes=note,
        created_by=user,
    )


def create_support_entries(
    *,
    disbursement,
    sub_program,
    beneficiaries,
    voucher_number,
    note,
    user,
):
    entries = []

    for item in beneficiaries:

        beneficiary = item["beneficiary"]
        amount = Decimal(item["amount"])

        entry = BeneficiarySupportEntry.objects.create(
            beneficiary=beneficiary,
            main_program=sub_program.main_program,
            sub_program=sub_program,
            disbursement=disbursement,
            voucher_number=voucher_number,
            amount=amount,
            note=note,
            created_by=user,
        )

        entries.append(entry)

    return entries


def create_fund_entry(
    *,
    sub_program,
    total_amount,
    voucher_number,
    user,
):
    """
    هذه هي النقطة الوحيدة التي تنقص الصندوق.
    """

    return FundEntry.objects.create(
        invoice=None,
        beneficiary=None,
        main_program=sub_program.main_program,
        sub_program=sub_program,
        type=FundEntry.Types.PROGRAM_EXPENSE,
        amount=-Decimal(total_amount),
        voucher_number=voucher_number,
        description=(
            f"صرف من البرنامج الفرعي "
            f"{sub_program.name}"
        ),
        created_by=user,
    )


def spend_from_sub_program(
    *,
    sub_program,
    beneficiaries,
    voucher_number,
    user,
    note="",
):
    """
    تنفيذ الصرف بالكامل داخل Transaction واحدة.
    """

    total_amount = validate_subprogram_disbursement(
        sub_program=sub_program,
        beneficiaries=beneficiaries,
        voucher_number=voucher_number,
    )

    with transaction.atomic():

        disbursement = create_disbursement(
            sub_program=sub_program,
            voucher_number=voucher_number,
            note=note,
            user=user,
        )

        create_support_entries(
            disbursement=disbursement,
            sub_program=sub_program,
            beneficiaries=beneficiaries,
            voucher_number=voucher_number,
            note=note,
            user=user,
        )

        # زيادة المصروف على البرنامج الفرعي
        sub_program.spent_amount += total_amount
        sub_program.save(
            update_fields=["spent_amount"]
        )

        # نقص الصندوق الحقيقي
        create_fund_entry(
            sub_program=sub_program,
            total_amount=total_amount,
            voucher_number=voucher_number,
            user=user,
        )

    return disbursement


def create_disbursement(
    *,
    sub_program,
    voucher_number,
    note,
    user,
):
    """
    إنشاء رأس أمر الصرف.
    """

    return SubProgramDisbursement.objects.create(
        sub_program=sub_program,
        source_type=SubProgramDisbursement.SourceTypes.SUB_PROGRAM,
        voucher_number=voucher_number,
        notes=note,
        created_by=user,
    )
def create_support_entries(
    *,
    disbursement,
    sub_program,
    beneficiaries,
    voucher_number,
    note,
    user,
):
    """
    إنشاء تفاصيل الصرف للمستفيدين.
    """

    entries = []

    for item in beneficiaries:

        beneficiary = item["beneficiary"]
        amount = Decimal(item["amount"])

        entry = BeneficiarySupportEntry.objects.create(
            beneficiary=beneficiary,
            main_program=sub_program.main_program,
            sub_program=sub_program,
            disbursement=disbursement,
            voucher_number=voucher_number,
            amount=amount,
            note=note,
            created_by=user,
        )

        entries.append(entry)

    return entries
def create_fund_entry(
    *,
    sub_program,
    total_amount,
    voucher_number,
    user,
):
    """
    إنشاء الحركة المالية الخاصة بأمر الصرف.
    """

    return FundEntry.objects.create(
        invoice=None,
        beneficiary=None,
        main_program=sub_program.main_program,
        sub_program=sub_program,
        type=FundEntry.Types.PROGRAM_EXPENSE,
        amount=-Decimal(total_amount),
        voucher_number=voucher_number,
        description=f"صرف من البرنامج الفرعي {sub_program.name}",
        created_by=user,
    )

def spend_from_sub_program(
    *,
    sub_program,
    beneficiaries,
    voucher_number,
    user,
    note="",
):

    total_amount = validate_subprogram_disbursement(
        sub_program=sub_program,
        beneficiaries=beneficiaries,
        voucher_number=voucher_number,
    )

    with transaction.atomic():

        disbursement = create_disbursement(
            sub_program=sub_program,
            voucher_number=voucher_number,
            note=note,
            user=user,
        )

        create_support_entries(
            disbursement=disbursement,
            sub_program=sub_program,
            beneficiaries=beneficiaries,
            voucher_number=voucher_number,
            note=note,
            user=user,
        )

        create_fund_entry(
            sub_program=sub_program,
            total_amount=total_amount,
            voucher_number=voucher_number,
            user=user,
        )

    return disbursement

# عكس عملية الصرف 
def reverse_subprogram_disbursement(
    *,
    disbursement,
    user,
    reason="",
):
    """
    عكس أمر صرف سابق بالكامل.

    - لا يحذف السند الأصلي.
    - لا يحذف تفاصيل الصرف.
    - يعتمد على BeneficiarySupportEntry كمصدر فعلي لقيمة الصرف.
    - ينشئ حركة مالية عكسية لإرجاع المبلغ للصندوق.
    - يعلّم السند بأنه معكوس.
    """

    if disbursement.is_reversed:
        raise ValueError(
            "لا يمكن عكس أمر الصرف لأنه معكوس مسبقًا."
        )

    with transaction.atomic():

        disbursement = (
            SubProgramDisbursement.objects
            .select_for_update()
            .select_related("sub_program")
            .get(pk=disbursement.pk)
        )

        if disbursement.is_reversed:
            raise ValueError(
                "لا يمكن عكس أمر الصرف لأنه معكوس مسبقًا."
            )

        # ==========================================
        # حساب قيمة السند من المصروف الفعلي
        # ==========================================

        total_amount = (
            BeneficiarySupportEntry.objects
            .filter(
                disbursement=disbursement,
            )
            .aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )

        if total_amount <= 0:
            raise ValueError(
                "لا يمكن عكس أمر الصرف لأن تفاصيل الصرف غير موجودة."
            )

        sub_program = (
            SubProgram.objects
            .select_for_update()
            .get(
                pk=disbursement.sub_program_id
            )
        )

        # ==========================================
        # إنشاء حركة مالية عكسية
        # ==========================================

        FundEntry.objects.create(
            invoice=None,
            beneficiary=None,
            main_program=sub_program.main_program,
            sub_program=sub_program,
            type=FundEntry.Types.PROGRAM_EXPENSE,
            amount=total_amount,
            voucher_number=f"REV-{disbursement.voucher_number}",
            description=(
                f"عكس صرف السند "
                f"{disbursement.voucher_number}"
                + (
                    f" - {reason}"
                    if reason
                    else ""
                )
            ),
            created_by=user,
        )

        # ==========================================
        # تعليم السند بأنه معكوس
        # ==========================================

        disbursement.is_reversed = True

        if reason:
            disbursement.notes = (
                f"{disbursement.notes or ''}\n"
                f"سبب العكس: {reason}"
            ).strip()

        disbursement.save(
            update_fields=[
                "is_reversed",
                "notes",
            ]
        )

    return disbursement