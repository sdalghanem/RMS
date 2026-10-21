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
