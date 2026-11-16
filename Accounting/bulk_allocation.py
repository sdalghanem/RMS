import re
from decimal import Decimal
from uuid import uuid4

from django.core import signing
from django.db import transaction

from .models import AllocationHistory, MainProgram
from .services import allocate_to_main_program, get_available_for_allocation


def allocation_token(user):
    return signing.dumps([user.pk, uuid4().hex], salt="bulk-fund")


def hundredths(value):
    if not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", value):
        raise ValueError("أدخل قيمة موجبة بدقتين عشريتين كحد أقصى.")
    return int(Decimal(value) * 100)


@transaction.atomic
def allocate_percentages(data, user):
    try:
        owner, key = signing.loads(data.get("token", ""), salt="bulk-fund")
    except signing.BadSignature:
        raise ValueError("تعذر التحقق من النموذج. حدّث الصفحة.")
    if owner != user.pk:
        raise ValueError("هذا النموذج يخص مستخدمًا آخر.")
    reference = "BULK-" + key
    programs = {p.pk: p for p in MainProgram.objects.select_for_update().order_by("pk")}
    if AllocationHistory.objects.select_for_update().filter(reference=reference).exists():
        return False
    total = hundredths(data.get("bulk_amount", ""))
    shares = {}
    for field in data:
        if not field.startswith("share_") or not data[field]:
            continue
        if len(data.getlist(field)) != 1:
            raise ValueError("تكررت نسبة البرنامج.")
        ratio = hundredths(data[field])
        if not ratio:
            continue
        pid = int(field[6:]) if re.fullmatch(r"[1-9][0-9]{0,18}", field[6:]) else None
        if pid not in programs or not programs[pid].is_active:
            raise ValueError("اختر برنامجًا نشطًا.")
        shares[pid] = ratio
    if sum(shares.values()) != 10000 or total <= 0:
        raise ValueError("أدخل مبلغًا أكبر من صفر ونسبًا مجموعها 100٪.")
    if Decimal(total)/100 > get_available_for_allocation():
        raise ValueError("المبلغ يتجاوز المتاح للتخصيص.")
    parts = {pid: total * ratio // 10000 for pid, ratio in shares.items()}
    ranked = sorted(shares, key=lambda pid: (-(total * shares[pid] % 10000), pid))
    for pid in ranked[:total - sum(parts.values())]:
        parts[pid] += 1
    if not all(parts.values()):
        raise ValueError("حصة أحد البرامج أقل من هللة. عدّل المبلغ أو النسب.")
    for pid, cents in sorted(parts.items()):
        allocate_to_main_program(main_program=programs[pid], amount=Decimal(cents)/100,
                                 user=user, reference=reference)
    return True
