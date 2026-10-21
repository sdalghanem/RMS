from collections import Counter
from datetime import date, datetime
from zipfile import BadZipFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.core.exceptions import ValidationError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from Accounting.models import FinancialSponsorshipInvoice, FinancialSponsorshipAllocation
from Management.forms import SponsorshipDatesForm
from Management.sponsorship_ops import update_sponsorship_dates


class Command(BaseCommand):
    help = "Validate receipt dates from Excel; defaults to dry run."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--number-column", default="number")
        parser.add_argument("--start-column", default="start_date")
        parser.add_argument("--end-column", default="end_date")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true")
        mode.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            workbook = load_workbook(options["file"], read_only=True, data_only=True)
            try:
                rows = list(workbook.active.iter_rows(values_only=True))
            finally:
                workbook.close()
        except (OSError, ValueError, BadZipFile, InvalidFileException) as exc:
            raise CommandError("Cannot read Excel file.") from exc
        columns = [options[key] for key in ("number_column", "start_column", "end_column")]
        header = [str(v).strip() if v is not None else "" for v in (rows[0] if rows else [])]
        if len(set(columns)) != 3 or any(header.count(name) != 1 for name in columns):
            raise CommandError("Required columns are missing or duplicated.")
        indexes = [header.index(name) for name in columns]
        items = []
        for row in rows[1:]:
            if not any(v is not None for v in row):
                continue
            values = [row[i] if i < len(row) else None for i in indexes]
            number = str(values[0]).strip() if values[0] is not None else ""
            dates = [v.date() if isinstance(v, datetime) else v for v in values[1:]]
            items.append((number, dates))
        counts = Counter(number for number, _ in items)
        rejected, matched = 0, []
        for number, dates in items:
            # Numeric Excel cells without a date format are not accepted as dates.
            if any(not isinstance(v, (str, date)) for v in dates):
                rejected += 1
                continue
            form = SponsorshipDatesForm({"start_date": dates[0], "end_date": dates[1]})
            if not number or counts[number] != 1 or not form.is_valid():
                rejected += 1
                continue
            receipt = FinancialSponsorshipInvoice.objects.filter(invoice__number=number).first()
            if receipt is None:
                rejected += 1
                continue
            allocation = FinancialSponsorshipAllocation.objects.filter(sponsorship_invoice=receipt).first()
            if allocation:
                try:
                    FinancialSponsorshipAllocation.validate_period(allocation.beneficiary_id,
                        form.cleaned_data["start_date"], form.cleaned_data["end_date"], exclude_receipt=receipt.pk)
                except ValidationError:
                    rejected += 1
                    continue
            matched.append((receipt.pk, receipt.start_date, receipt.end_date, form.cleaned_data))
        self.stdout.write(f"matched={len(matched)} updated=0 rejected={rejected}")
        if rejected:
            raise CommandError("Validation failed; no dates were changed.")
        if not options["apply"]:
            self.stdout.write("DRY RUN: no changes.")
            return
        with transaction.atomic():
            for pk, old_start, old_end, dates in sorted(matched):
                receipt = FinancialSponsorshipInvoice.objects.select_for_update().get(pk=pk)
                if (receipt.start_date, receipt.end_date) != (old_start, old_end):
                    raise CommandError("Receipt changed during validation; all updates rolled back.")
                update_sponsorship_dates(pk, dates["start_date"], dates["end_date"])
        self.stdout.write(f"matched={len(matched)} updated={len(matched)} rejected=0")
