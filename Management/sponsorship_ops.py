from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Beneficiary, BeneficiarySponsorHistory
from Accounting.models import FinancialSponsorshipInvoice, FinancialSponsorshipAllocation


@transaction.atomic
def attach_sponsorship(sponsorship_id, beneficiary_id, user, allow_future=False, allow_past=False, renewal_from=None):
    receipt = FinancialSponsorshipInvoice.objects.select_for_update().get(pk=sponsorship_id)
    beneficiary = Beneficiary.objects.select_for_update().get(pk=beneficiary_id)
    today = timezone.localdate()
    if (not allow_past and receipt.end_date < today) or receipt.end_date <= receipt.start_date or (not allow_future and receipt.start_date > today):
        raise ValidationError("السند غير ساري أو تواريخه غير صحيحة. عدّل تواريخه أولاً.")
    if FinancialSponsorshipAllocation.objects.filter(sponsorship_invoice=receipt).exists():
        raise ValidationError("هذا السند ملحق بمستفيد بالفعل؛ لا يمكن إلحاقه مرة أخرى.")
    allocation = FinancialSponsorshipAllocation(sponsorship_invoice=receipt, beneficiary=beneficiary, amount=receipt.total_amount)
    allocation._renewal_from = renewal_from
    allocation.save()
    BeneficiarySponsorHistory.objects.create(beneficiary=beneficiary, donor=receipt.sponsor, start_date=receipt.start_date, end_date=receipt.end_date, assigned_by=user)
    return allocation


@transaction.atomic
def reassign_sponsorship(pk, new_id, expected_assignment, actor):
    from django.db.models import Q
    from Accounting.models import BeneficiarySupportEntry
    from .models import AuditLog, MainProgram

    # Use the same first lock as the disbursement and reversal services.
    list(MainProgram.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    receipt = FinancialSponsorshipInvoice.objects.select_for_update().get(pk=pk)
    allocation = FinancialSponsorshipAllocation.objects.select_for_update().filter(sponsorship_invoice=receipt).first()
    if not allocation or not allocation.created_at:
        raise ValidationError("تعذر إثبات تاريخ إسناد السند إلى المستفيد.")
    old_id = allocation.beneficiary_id
    assigned_at = allocation.created_at
    if expected_assignment != (allocation.pk, old_id, assigned_at.isoformat()):
        raise ValidationError("تغيّر الإسناد منذ فتح النموذج. أعد فتحه للتحقق.")
    beneficiaries = {b.pk:b for b in Beneficiary.objects.select_for_update().filter(
        pk__in=[old_id,new_id]).order_by("pk")}
    if old_id == new_id or new_id not in beneficiaries:
        raise ValidationError("اختر مستفيدًا آخر مسجلًا.")
    now = timezone.now()
    if assigned_at >= now:
        raise ValidationError("تعذر التحقق من ترتيب توقيت الإسناد.")
    active_support = BeneficiarySupportEntry.objects.filter(
        beneficiary_id=old_id, created_at__gte=assigned_at).filter(
        Q(disbursement__isnull=True) | Q(disbursement__is_reversed=False))
    if active_support.exists():
        raise ValidationError("تعذر تغيير المستفيد لوجود مصروف عند توقيت الإسناد أو بعده.")
    start, end = receipt.start_date, receipt.end_date
    if not start or not end or end <= start:
        raise ValidationError("فترة السند غير موثقة.")
    histories = BeneficiarySponsorHistory.objects.select_for_update()
    candidates = list(histories.filter(beneficiary_id=old_id, donor_id=receipt.sponsor_id,
        start_date=start, end_date=end).order_by("pk")[:2])
    others = FinancialSponsorshipAllocation.objects.exclude(pk=allocation.pk)
    if len(candidates) != 1 or others.filter(beneficiary_id=old_id,
            sponsorship_invoice__sponsor_id=receipt.sponsor_id,
            sponsorship_invoice__start_date=start,sponsorship_invoice__end_date=end).exists():
        raise ValidationError("تعذر تحديد سجل الإسناد التاريخي الخاص بهذا السند وحده.")
    if histories.filter(beneficiary_id=new_id,start_date__lte=end).filter(
            Q(end_date__gte=start)|Q(end_date__isnull=True)).exists():
        raise ValidationError("للمستفيد البديل فترة كفالة تتداخل مع السند.")
    allocation.beneficiary_id = new_id
    allocation.created_at = now
    allocation.save(update_fields=["beneficiary","created_at"])
    history = candidates[0]
    history.beneficiary_id = new_id
    history.save(update_fields=["beneficiary"])
    # Allocation and period queries drive status. Maintain any current donor pointer.
    today=timezone.localdate()
    for person in beneficiaries.values():
        if person.pk==old_id and person.donor_id!=receipt.sponsor_id:
            continue
        if person.pk==new_id and not start<=today<=end:
            continue
        donors=set(FinancialSponsorshipAllocation.objects.filter(beneficiary=person,
            sponsorship_invoice__start_date__lte=today,sponsorship_invoice__end_date__gte=today
        ).values_list("sponsorship_invoice__sponsor_id",flat=True))
        donors.update(histories.filter(beneficiary=person,start_date__lte=today).filter(
            Q(end_date__gte=today)|Q(end_date__isnull=True)).values_list("donor_id",flat=True))
        if len(donors)>1 or (person.pk==new_id and person.donor_id not in (None,receipt.sponsor_id)):
            raise ValidationError("تعذر تحديد الكافل الحالي دون المساس بإسناد آخر.")
        donor_id=next(iter(donors),None)
        if person.donor_id!=donor_id:
            person.donor_id=donor_id
            person.save(update_fields=["donor"])
    AuditLog.objects.create(user=actor,action=AuditLog.Actions.UPDATE,entity="sponsorship_reassignment",
        entity_id=str(receipt.pk),extra={"invoice_number":str(receipt.invoice.number),"allocation":allocation.pk,
        "history":history.pk,"old_beneficiary":old_id,"new_beneficiary":new_id,
        "previous_assignment":assigned_at.isoformat(),"assigned_at":now.isoformat()})


@transaction.atomic
def update_sponsorship_dates(pk, start, end):
    if not start or not end or end <= start:
        raise ValidationError("تاريخ النهاية يجب ألا يسبق البداية.")
    receipt = FinancialSponsorshipInvoice.objects.select_for_update().get(pk=pk)
    # History records remain immutable assignment snapshots, not invoice-date aliases.
    receipt.start_date, receipt.end_date = start, end
    receipt.save(update_fields=["start_date", "end_date"])
    return receipt


@transaction.atomic
def create_sponsorship(form, user, *, sponsor=None, beneficiary=None, record_income=True, allow_past=False, renewal_from=None):
    from Accounting.models import Invoice, FundEntry
    from Management.utils.audit import log_activity, AuditLog
    data = form.cleaned_data
    invoice = Invoice.objects.create(number=data["number"], date=data.get("date") or timezone.localdate(),
        invoice_type=Invoice.Types.FINANCIAL_SPONSORSHIP, receipt_kind=Invoice.ReceiptKinds.RECEIPT,
        payment_method=data.get("payment_method"), notes=data.get("notes") or "", created_by=user)
    sponsorship = form.save(commit=False)
    sponsorship.invoice = invoice
    if sponsor is not None:
        sponsorship.sponsor = sponsor
    if not sponsorship.is_custom_plan and sponsorship.payment_plan:
        sponsorship.custom_amount = sponsorship.payment_plan.amount
        sponsorship.custom_duration_months = sponsorship.payment_plan.duration_months
    sponsorship.save()
    if beneficiary is not None:
        attach_sponsorship(sponsorship.pk, beneficiary.pk, user, allow_future=True, allow_past=allow_past, renewal_from=renewal_from)
    if record_income:
        FundEntry.objects.create(invoice=invoice, type=FundEntry.Types.SPONSORSHIP_INCOME,
            amount=sponsorship.total_amount, voucher_number=invoice.number,
            description=f"دخل كفالة مالية من السند رقم {invoice.number}", created_by=user)
    log_activity(user=user, action=AuditLog.Actions.CREATE,
        entity=f"إنشاء سند كفالة مالية رقم {invoice.number}", entity_id=invoice.pk,
        extra={"invoice_number": invoice.number, "beneficiary_assigned": beneficiary is not None})
    return sponsorship


def can_renew_sponsorship(sponsorship):
    from datetime import timedelta
    today = timezone.localdate()
    return sponsorship.start_date <= today and sponsorship.end_date <= today + timedelta(days=30)
