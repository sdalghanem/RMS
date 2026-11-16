from datetime import timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from Accounting import test_reports as fixtures
from Accounting.models import (BeneficiarySupportEntry, FinancialSponsorshipAllocation as Allocation,
                              FundEntry, Invoice, SubProgramDisbursement)
from Management.models import AuditLog, Beneficiary, BeneficiarySponsorHistory as History
from Management.sponsorship_ops import reassign_sponsorship


class AssignmentFixture:
    invoice = fixtures.ReportsRegressionTests.invoice
    support = fixtures.ReportsRegressionTests.support

    def setUp(self):
        fixtures.ReportsRegressionTests.setUpTestData.__func__(self)
        self.receipt=self.invoice()
        # Some clocks have coarser resolution than an assignment transaction.
        Allocation.objects.filter(sponsorship_invoice=self.receipt).update(created_at=timezone.now()-timedelta(seconds=2))
        self.alloc=Allocation.objects.get(sponsorship_invoice=self.receipt)
        self.history=History.objects.create(beneficiary=self.b,donor=self.donor,
            start_date=self.start,end_date=self.end)
        self.new=Beneficiary.objects.create(first_name='بديل',last_name='تجريبي',gender='male',
            education_level='p1',national_number='3000000001')
        self.actor=self.users['accountant']
        self.version=(self.alloc.pk,self.b.pk,self.alloc.created_at.isoformat())
        self.url=reverse('Management:sponsorship_reassign',args=[self.receipt.pk])

    def move(self):
        reassign_sponsorship(self.receipt.pk,self.new.pk,self.version,self.actor)

    def financial_snapshot(self):
        return [list(m.objects.order_by('pk').values()) for m in
                (Invoice,FundEntry,BeneficiarySupportEntry,SubProgramDisbursement,type(self.receipt))]


class AssignmentTests(AssignmentFixture,TestCase):
    def test_no_spending_and_audit(self):
        before=self.financial_snapshot()
        self.move()
        self.alloc.refresh_from_db()
        self.history.refresh_from_db()
        self.assertEqual((self.alloc.beneficiary_id,self.history.beneficiary_id),(self.new.pk,self.new.pk))
        self.assertEqual(self.financial_snapshot(),before)
        log=AuditLog.objects.get(entity='sponsorship_reassignment')
        self.assertEqual((log.user_id,log.extra['old_beneficiary'],log.extra['new_beneficiary']),
                         (self.actor.pk,self.b.pk,self.new.pk))
        with self.assertRaises(ValidationError):self.move()

    def test_before_and_reversed_allowed(self):
        self.support(19,(self.alloc.created_at-timedelta(seconds=1)).isoformat())
        self.support(31,(self.alloc.created_at+timedelta(seconds=1)).isoformat(),reversed=True)
        before=self.financial_snapshot()
        self.move()
        self.assertEqual(before,self.financial_snapshot())

    def test_equal_or_after_denied(self):
        entry=self.support(20,self.alloc.created_at.isoformat())
        for delta in (0,1):
            BeneficiarySupportEntry.objects.filter(pk=entry.pk).update(created_at=self.alloc.created_at+timedelta(seconds=delta))
            with self.assertRaisesMessage(ValidationError,'مصروف'):self.move()
        self.assertEqual(Allocation.objects.get(pk=self.alloc.pk).beneficiary_id,self.b.pk)

    def test_unrelated_history_and_second_invoice_preserved(self):
        earlier=self.start-timedelta(days=90)
        other=self.invoice(start=earlier,end=self.start-timedelta(days=1))
        h=History.objects.create(beneficiary=self.b,donor=self.donor,start_date=other.start_date,end_date=other.end_date)
        previous=History.objects.create(beneficiary=self.new,donor=self.donor,start_date=earlier,end_date=other.end_date)
        self.move()
        for record,person in [(other.allocation,self.b),(h,self.b),(previous,self.new)]:
            record.refresh_from_db()
            self.assertEqual(record.beneficiary_id,person.pk)

    def test_target_conflict(self):
        History.objects.create(beneficiary=self.new,donor=self.donor,start_date=self.start,end_date=None)
        with self.assertRaisesMessage(ValidationError,'تتداخل'):self.move()

    def test_missing_or_ambiguous_evidence(self):
        duplicate=History.objects.create(beneficiary=self.b,donor=self.donor,start_date=self.start,end_date=self.end)
        with self.assertRaisesMessage(ValidationError,'التاريخي'):self.move()
        duplicate.delete()
        self.history.delete()
        with self.assertRaisesMessage(ValidationError,'التاريخي'):self.move()
        self.alloc.delete()
        with self.assertRaisesMessage(ValidationError,'تاريخ إسناد'):self.move()

    def test_authorized_workflow_only(self):
        for role in ('cashier','donor'):
            self.client.force_login(self.users[role])
            for method in [self.client.get,self.client.post]:
                self.assertEqual(method(self.url).status_code,403)
        for role in ('system_admin','accountant'):
            self.client.force_login(self.users[role])
            page=self.client.get(self.url)
            self.assertContains(page,self.receipt.invoice.number)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.beneficiary_id,self.b.pk)
        payload={'version':page.context['version'],'confirmed':'yes','replacement':self.new.pk}
        for change in ({'confirmed':''},{'replacement':self.b.pk},{'replacement':999999},{'version':'bad'}):
            self.client.post(self.url,{**payload,**change})
            self.alloc.refresh_from_db()
            self.assertEqual(self.alloc.beneficiary_id,self.b.pk)
        self.assertEqual(self.client.post(self.url,payload).status_code,302)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.beneficiary_id,self.new.pk)


class AssignmentRaceTests(AssignmentFixture,TransactionTestCase):
    def test_overlapping_submissions(self):
        written,release=Event(),Event()
        original=Allocation.save
        outcomes=[]
        def hold(instance,*args,**kwargs):
            original(instance,*args,**kwargs)
            written.set()
            if not release.wait(10):raise RuntimeError('Thread timeout')
        def submit():
            close_old_connections()
            try:
                self.move()
                outcomes.append('ok')
            except (OperationalError,ValidationError):
                outcomes.append('blocked')
            finally:close_old_connections()
        with patch.object(Allocation,'save',hold):
            worker=Thread(target=submit)
            worker.start()
            try:
                self.assertTrue(written.wait(10))
                second=Thread(target=submit)
                second.start()
                second.join(1)
            finally:
                release.set()
                worker.join(10)
            second.join(10)
        self.assertCountEqual(outcomes,['ok','blocked'])
        self.assertEqual(AuditLog.objects.filter(entity='sponsorship_reassignment').count(),1)
