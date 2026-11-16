"""Read-only report calculations; expenses are benefits, not invoice funding."""
from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.db.models import Q, Sum
from django.utils import timezone
from .models import BeneficiarySupportEntry, FinancialSponsorshipAllocation

ZERO = Decimal('0.00')

def beneficiary_name(beneficiary):
    return ' '.join(filter(None, (beneficiary.first_name, beneficiary.father_name,
                                 beneficiary.grand_name, beneficiary.last_name)))

def support_entries(start, end):
    # Half-open local datetime bounds also work without MySQL timezone tables.
    tz = timezone.get_current_timezone()
    lower = timezone.make_aware(datetime.combine(start, time.min), tz)
    upper = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    return (BeneficiarySupportEntry.objects.filter(created_at__gte=lower, created_at__lt=upper)
            .filter(Q(disbursement__is_reversed=False) | Q(disbursement__isnull=True))
            .select_related('beneficiary', 'main_program', 'sub_program__main_program')
            .order_by('beneficiary_id', 'created_at', 'pk'))

def participation(entry):
    return {'id': entry.pk, 'date': timezone.localtime(entry.created_at).date(),
            'main': entry.main_program or entry.sub_program.main_program,
            'sub': entry.sub_program, 'amount': entry.amount}

def sponsorship_expenses(donor, start, end):
    allocations = (FinancialSponsorshipAllocation.objects
        .filter(sponsorship_invoice__sponsor=donor,
                sponsorship_invoice__start_date__lte=end,
                sponsorship_invoice__end_date__gte=start)
        .select_related('beneficiary', 'sponsorship_invoice__invoice')
        .order_by('beneficiary_id', 'sponsorship_invoice__start_date', 'pk'))
    rows = OrderedDict()
    invalid = []
    today = timezone.localdate()
    for allocation in allocations:
        invoice = allocation.sponsorship_invoice
        if not invoice.start_date or not invoice.end_date or invoice.end_date <= invoice.start_date:
            invalid.append(invoice.invoice.number)
            continue
        row = rows.setdefault(allocation.beneficiary_id, {
            'name': beneficiary_name(allocation.beneficiary), 'beneficiary_id': allocation.beneficiary_id,
            'invoices': [], 'participations': [], 'amount': ZERO, 'spent': ZERO,
            'shared_spent': ZERO, 'overlap': False})
        status = 'منتهية' if today > invoice.end_date else ('لم تبدأ بعد' if today < invoice.start_date else 'سارية')
        item = {'id': invoice.pk, 'number': invoice.invoice.number,
                'start': invoice.start_date, 'end': invoice.end_date,
                'from': max(start, invoice.start_date), 'to': min(end, invoice.end_date),
                'amount': allocation.amount, 'status': status, 'spent': ZERO}
        row['overlap'] |= any(item['from'] <= old['to'] and old['from'] <= item['to'] for old in row['invoices'])
        row['invoices'].append(item)
        row['amount'] += allocation.amount
    for entry in support_entries(start, end).filter(beneficiary_id__in=rows):
        row = rows[entry.beneficiary_id]
        item = participation(entry)
        matches = [i for i in row['invoices'] if i['from'] <= item['date'] <= i['to']]
        if not matches:
            continue
        item['shared'] = len(matches) > 1
        if len(matches) == 1:
            matches[0]['spent'] += entry.amount
        row['participations'].append(item)
        row['spent'] += entry.amount
        if item['shared']:
            row['shared_spent'] += entry.amount
    for row in rows.values():
        row['difference'] = row['amount'] - row['spent']
        for invoice in row['invoices']:
            invoice['difference'] = invoice['amount'] - invoice['spent']
        row['expense_status'] = ('لا توجد مصروفات ضمن الفترة' if not row['participations']
                                 else 'توجد مصروفات برامج ضمن الفترة')
    rows = list(rows.values())
    amount = sum((r['amount'] for r in rows), ZERO)
    spent = sum((r['spent'] for r in rows), ZERO)
    return {'rows': rows, 'donor': donor, 'amount': amount, 'spent': spent,
            'difference': amount - spent, 'beneficiary_count': len(rows),
            'sponsorship_count': sum(len(r['invoices']) for r in rows),
            'participation_count': sum(len(r['participations']) for r in rows),
            'invalid_invoices': invalid}

def association_benefits(start, end, *, beneficiary=None, main_program=None, sub_program=None, donor=None):
    entries = support_entries(start, end)
    if beneficiary:
        entries = entries.filter(beneficiary=beneficiary)
    if main_program:
        entries = entries.filter(Q(main_program=main_program) |
            Q(main_program__isnull=True, sub_program__main_program=main_program))
    if sub_program:
        entries = entries.filter(sub_program=sub_program)
    if donor:
        # Membership is all recorded financial allocations, independent of their dates.
        members = FinancialSponsorshipAllocation.objects.filter(
            sponsorship_invoice__sponsor=donor).values('beneficiary_id')
        entries = entries.filter(beneficiary_id__in=members)
    rows = OrderedDict()
    for entry in entries:
        row = rows.setdefault(entry.beneficiary_id, {'name': beneficiary_name(entry.beneficiary),
            'beneficiary_id': entry.beneficiary_id, 'participations': [], 'spent': ZERO})
        row['participations'].append(participation(entry))
        row['spent'] += entry.amount
    rows = list(rows.values())
    return {'rows': rows, 'spent': sum((r['spent'] for r in rows), ZERO),
            'beneficiary_count': len(rows), 'participation_count': sum(len(r['participations']) for r in rows)}


def current_sponsor_scope(donor):
    """Earliest verified date per currently eligible beneficiary."""
    from zoneinfo import ZoneInfo
    from Management.models import BeneficiarySponsorHistory
    today = timezone.localdate(timezone=ZoneInfo("Asia/Riyadh"))
    periods = FinancialSponsorshipAllocation.objects.filter(
        sponsorship_invoice__sponsor=donor).values_list(
        'beneficiary_id','sponsorship_invoice__start_date','sponsorship_invoice__end_date')
    history = BeneficiarySponsorHistory.objects.filter(donor=donor).values_list(
        'beneficiary_id','start_date','end_date')
    earliest, active, invoiced = {}, set(), set()
    for source, records in [('invoice',periods), ('history',history)]:
        for beneficiary, start, end in records:
            if source == 'invoice':
                invoiced.add(beneficiary)
            if not start or (end and end <= start):
                continue
            earliest[beneficiary] = min(earliest.get(beneficiary,start),start)
            # History snapshots survive invoice period corrections.
            if source == 'history' and beneficiary in invoiced:
                continue
            if start <= today and (end is None or today <= end):
                active.add(beneficiary)
    return {key:earliest[key] for key in active}

def current_sponsor_expenses(donor,start,end):
    from Management.models import Beneficiary
    from zoneinfo import ZoneInfo
    scope=current_sponsor_scope(donor)
    rows={b.pk:dict(name=beneficiary_name(b),first=scope[b.pk],participations=[],spent=ZERO)
          for b in Beneficiary.objects.filter(pk__in=scope).order_by('pk')}
    with timezone.override(ZoneInfo('Asia/Riyadh')):
        for entry in support_entries(start,end).filter(beneficiary_id__in=scope):
            item=participation(entry)
            row=rows[entry.beneficiary_id]
            if item['date'] >= row['first']:
                row['participations'].append(item)
                row['spent']+=entry.amount
    allocated = FinancialSponsorshipAllocation.objects.filter(sponsorship_invoice__sponsor=donor,
        beneficiary_id__in=scope,sponsorship_invoice__start_date__lte=end,
        sponsorship_invoice__end_date__gte=start).aggregate(total=Sum('amount'))['total'] or ZERO
    spent=sum((r['spent'] for r in rows.values()),ZERO)
    return dict(donor=donor,rows=list(rows.values()),spent=spent,amount=allocated,difference=allocated-spent,
                beneficiary_count=len(rows),participation_count=sum(len(r['participations']) for r in rows.values()))
