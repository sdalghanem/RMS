from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from Management.models import Profile, Beneficiary, MainProgram, SubProgram
from Accounting.models import (Invoice, FinancialSponsorshipInvoice, FinancialSponsorshipAllocation,
    BeneficiarySupportEntry, SubProgramDisbursement, FundEntry)
from Accounting.reporting import sponsorship_expenses, association_benefits
from Accounting.report_forms import PeriodForm, AssociationReportForm


@override_settings(TIME_ZONE='Asia/Riyadh')
class ReportsRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for i, role in enumerate(('donor','accountant','system_admin','cashier'), 1):
            user = get_user_model().objects.create_user(username=role, first_name='تجريبي', password='test-only')
            Profile.objects.create(user=user, role=role, phone='050000000'+str(i), national_number='100000000'+str(i))
            cls.users[role] = user
        cls.donor = cls.users['donor'].profile
        cls.b = Beneficiary.objects.create(first_name='أحمد', father_name='علي', last_name='تجريبي',
            gender='male', national_number='2000000001', education_level='p1')
        cls.main = MainProgram.objects.create(name='تعليم تجريبي', total_donation_amount=0)
        cls.sub = SubProgram.objects.create(main_program=cls.main, name='دعم دراسي', allocated_amount=0)
        cls.start, cls.end = date(2026,1,1), date(2026,12,31)

    def invoice(self, amount=5000, start=None, end=None, beneficiary=None, donor=None, legacy_overlap=False):
        inv = Invoice.objects.create(number='TEST-'+str(Invoice.objects.count()+1), date=self.start,
            invoice_type='financial_sponsorship', created_by=self.users['cashier'])
        fi = FinancialSponsorshipInvoice.objects.create(invoice=inv, sponsor=donor or self.donor,
            custom_amount=amount, start_date=start or self.start, end_date=end or self.end)
        # Only a test fixture: simulate historical overlaps which current creation forbids.
        if legacy_overlap:
            with patch.object(FinancialSponsorshipAllocation, 'validate_period'):
                FinancialSponsorshipAllocation.objects.create(sponsorship_invoice=fi, beneficiary=beneficiary or self.b, amount=amount)
        else:
            FinancialSponsorshipAllocation.objects.create(sponsorship_invoice=fi, beneficiary=beneficiary or self.b, amount=amount)
        return fi

    def support(self, amount, when='2026-11-05T09:00:00+00:00', beneficiary=None, sub=None, reversed=False):
        disb = None
        if reversed:
            disb = SubProgramDisbursement.objects.create(sub_program=sub or self.sub,
                voucher_number='REV-'+str(SubProgramDisbursement.objects.count()),
                created_by=self.users['accountant'], is_reversed=True)
        entry = BeneficiarySupportEntry.objects.create(beneficiary=beneficiary or self.b,
            sub_program=sub or self.sub, main_program=(sub or self.sub).main_program,
            amount=amount, disbursement=disb)
        # Test database only: auto_now_add cannot represent historical fixture dates.
        BeneficiarySupportEntry.objects.filter(pk=entry.pk).update(created_at=datetime.fromisoformat(when))
        return entry

    def sponsor(self, start=None, end=None):
        return sponsorship_expenses(self.donor, start or self.start, end or self.end)

    def test_zero_spending_is_not_partially_used(self):
        self.invoice()
        result = self.sponsor()
        self.assertEqual(result['spent'], 0)
        self.assertEqual(result['rows'][0]['expense_status'], 'لا توجد مصروفات ضمن الفترة')

    def test_amount_below_equal_and_above_is_never_capped(self):
        self.invoice()
        for increment, expected in ((3000,3000),(2000,5000),(3000,8000)):
            self.support(increment)
            result = self.sponsor()
            self.assertEqual(result['spent'], expected)
            self.assertEqual(result['difference'], 5000-expected)

    def test_overlap_counts_expense_once_and_marks_shared(self):
        self.invoice()
        self.invoice(2000, start=date(2026,6,1), legacy_overlap=True)
        self.support(8000)
        result = self.sponsor()
        self.assertEqual(result['spent'], 8000)
        self.assertEqual(result['amount'], 7000)
        self.assertEqual(result['sponsorship_count'], 2)
        self.assertTrue(result['rows'][0]['overlap'])
        self.assertEqual(result['rows'][0]['shared_spent'], 8000)

    def test_expired_invoice_excludes_later_spend_association_includes_it(self):
        self.invoice(end=date(2026,6,30))
        self.support(100)
        self.assertEqual(self.sponsor()['spent'], 0)
        self.assertEqual(association_benefits(self.start,self.end,donor=self.donor)['spent'],100)

    def test_renewed_successive_invoices_keep_original_dates(self):
        first = self.invoice(end=date(2026,6,30))
        second = self.invoice(start=date(2026,7,1))
        self.support(100, '2026-03-01T09:00:00+00:00')
        self.support(200)
        result = self.sponsor()
        self.assertEqual(result['spent'],300)
        self.assertFalse(result['rows'][0]['overlap'])
        self.assertEqual(result['rows'][0]['invoices'][0]['end'], first.end_date)
        self.assertEqual(result['rows'][0]['invoices'][1]['start'], second.start_date)

    def test_multiple_donors_do_not_multiply_association_expenses(self):
        self.invoice()
        user = get_user_model().objects.create_user(username='donor2')
        donor = Profile.objects.create(user=user,role='donor',phone='0500000009',national_number='1000000009')
        self.invoice(donor=donor,legacy_overlap=True)
        self.support(125)
        self.assertEqual(association_benefits(self.start,self.end)['spent'],125)
        self.assertEqual(association_benefits(self.start,self.end,donor=self.donor)['participation_count'],1)

    def test_multiple_beneficiaries_and_programs(self):
        other = Beneficiary.objects.create(first_name='ثان',last_name='تجريبي',national_number='2000000002',gender='male')
        sub = SubProgram.objects.create(main_program=self.main,name='غذاء',allocated_amount=0)
        self.invoice()
        self.invoice(beneficiary=other)
        self.support(100)
        self.support(200,sub=sub)
        self.support(300,beneficiary=other)
        result = association_benefits(self.start,self.end)
        self.assertEqual((result['beneficiary_count'],result['participation_count'],result['spent']),(2,3,600))
        self.assertEqual(association_benefits(self.start,self.end,sub_program=sub)['spent'],200)
        self.assertEqual(self.sponsor()['spent'],600)

    def test_reversed_spending_is_excluded_from_both_reports(self):
        self.invoice()
        self.support(100)
        self.support(200,reversed=True)
        self.assertEqual(self.sponsor()['spent'],100)
        self.assertEqual(association_benefits(self.start,self.end)['spent'],100)

    def test_local_midnight_and_inclusive_end_date(self):
        self.invoice(start=date(2026,11,5),end=date(2026,11,6))
        self.support(1,'2026-11-04T20:59:59+00:00')
        self.support(2,'2026-11-04T21:00:00+00:00')
        self.support(3,'2026-11-05T20:59:59+00:00')
        self.support(4,'2026-11-05T21:00:00+00:00')
        self.assertEqual(self.sponsor(date(2026,11,5),date(2026,11,5))['spent'],5)

    def test_report_clips_calculation_not_original_dates(self):
        self.invoice()
        self.support(100,'2026-02-01T10:00:00+00:00')
        self.support(200)
        result = self.sponsor(date(2026,10,1),self.end)
        self.assertEqual(result['spent'],200)
        item = result['rows'][0]['invoices'][0]
        self.assertEqual(item['start'],self.start)
        self.assertEqual(item['from'],date(2026,10,1))

    def test_period_forms(self):
        for data, expected in [({'report_type':'annual','year':2026},(self.start,self.end)),
            ({'report_type':'quarterly','year':2026,'quarter':4},(date(2026,10,1),self.end)),
            ({'report_type':'half','year':2026,'half':2},(date(2026,7,1),self.end)),
            ({'report_type':'custom','from_date':'2026-11-05','to_date':'2026-11-05'},(date(2026,11,5),date(2026,11,5)))]:
            form = PeriodForm(data)
            self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual((form.cleaned_data['start'],form.cleaned_data['end']),expected)

    def test_invalid_period_filters(self):
        for data in ({'report_type':'evil'},{'report_type':'annual','year':'x'},
            {'report_type':'quarterly','quarter':5},{'report_type':'quarterly'},
            {'report_type':'half','half':3},{'report_type':'custom'},
            {'report_type':'custom','from_date':'2026-11-06','to_date':'2026-11-05'},
            {'report_type':'custom','from_date':'bad','to_date':'2026-11-05'}):
            self.assertFalse(PeriodForm(data).is_valid())

    def test_inconsistent_program_filter(self):
        other = MainProgram.objects.create(name='آخر',total_donation_amount=0)
        form = AssociationReportForm({'report_type':'annual','main_program':other.pk,'sub_program':self.sub.pk})
        self.assertFalse(form.is_valid())

    def test_permissions_and_no_donor_id_bypass(self):
        sponsor_url = reverse('Accounting:sponsorship_report_print')
        assoc_url = reverse('Accounting:association_report_print')
        self.assertEqual(self.client.get(sponsor_url).status_code,302)
        for role in self.users:
            self.client.force_login(self.users[role])
            response = self.client.get(sponsor_url,{'donor':self.donor.pk,'year':2026})
            self.assertEqual(response.status_code,403 if role == 'donor' else 200)
            response = self.client.get(assoc_url,{'year':2026})
            self.assertEqual(response.status_code,200 if role in ('accountant','system_admin') else 403)
        self.client.force_login(self.users['donor'])
        self.assertEqual(self.client.get(sponsor_url,{'donor':9999}).status_code,403)

    def test_invalid_object_filter_returns_form_error(self):
        self.client.force_login(self.users['accountant'])
        for key in ('beneficiary','donor','main_program','sub_program'):
            response = self.client.get(reverse('Accounting:association_report_print'),{key:'999999'})
            self.assertEqual(response.status_code,400)

    def test_legacy_period_links(self):
        self.client.force_login(self.users['accountant'])
        for kind in ('year','quarter'):
            response = self.client.get(reverse('Accounting:sponsorship_report_print'),
                {'donor':self.donor.pk,'report_type':kind,'quarter':4,'year':2026})
            self.assertEqual(response.status_code,200)

    def test_print_templates_are_separate_private_and_complete(self):
        self.invoice()
        self.support(8000)
        self.client.force_login(self.users['accountant'])
        first = self.client.get(reverse('Accounting:sponsorship_report_print'),{'donor':self.donor.pk,'year':2026})
        second = self.client.get(reverse('Accounting:association_report_print'),{'year':2026})
        self.assertTemplateUsed(first,'Accounting/sponsorship_report_print.html')
        self.assertTemplateUsed(second,'Accounting/association_report_print.html')
        self.assertContains(first,'8000.00')
        self.assertContains(first,'-3000.00')
        self.assertNotContains(second,'مبلغ الكفالات المخصص')
        for response in (first,second):
            self.assertContains(response,'<thead>')
            self.assertContains(response,'reports.css')
            self.assertContains(response,'5 نوفمبر 2026')
            self.assertNotContains(response,self.b.national_number)
            self.assertNotContains(response,self.donor.phone)

    def test_status_uses_original_period(self):
        self.invoice()
        with patch('Accounting.reporting.timezone.localdate',return_value=date(2026,11,5)):
            self.assertEqual(self.sponsor()['rows'][0]['invoices'][0]['status'],'سارية')
        with patch('Accounting.reporting.timezone.localdate',return_value=date(2027,1,1)):
            self.assertEqual(self.sponsor()['rows'][0]['invoices'][0]['status'],'منتهية')

    def test_calculations_are_read_only(self):
        self.invoice()
        self.support(100)
        before = list(BeneficiarySupportEntry.objects.values())
        with CaptureQueriesContext(connection) as queries:
            self.sponsor()
            association_benefits(self.start,self.end)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        self.assertEqual(before,list(BeneficiarySupportEntry.objects.values()))
        self.assertEqual(FundEntry.objects.count(),0)


    @patch('Accounting.reporting.timezone.localdate',return_value=date(2026,11,16))
    def test_current_report_policy(self,clock):
        from Management.models import BeneficiarySponsorHistory as History
        other=self.users['accountant'].profile
        other.role='donor';other.save()
        def history(b,p,s,e):
            History.objects.create(beneficiary=b,donor=p,start_date=s,end_date=e)
        def person(n):
            return Beneficiary.objects.create(first_name='Test'+str(n),father_name='Father',last_name='Family',
                gender='male',national_number=str(2200000000+n),education_level='p1')
        extra,expired=person(2),person(3)
        history(self.b,self.donor,date(2026,1,5),date(2026,1,31))
        self.invoice(100,start=date(2026,8,1),end=date(2026,11,16))
        self.invoice(100,start=date(2026,9,1),end=date(2026,12,1),legacy_overlap=True)
        history(extra,self.donor,date(2026,11,16),None)
        history(expired,self.donor,date(2026,1,1),date(2026,11,15))
        history(self.b,other,date(2026,10,1),None)
        for amt,when in [(9,'2026-01-04T20:59:59+00:00'),(120,'2026-01-04T21:00:00+00:00'),(300,'2026-04-01T00:00:00+00:00'),(15,'2026-11-01T00:00:00+00:00')]:
            self.support(amt,when)
        self.support(55,reversed=True);self.support(70,beneficiary=expired)
        page=reverse('Accounting:sponsorship_reports');url=reverse('Accounting:sponsorship_report_print')
        self.client.force_login(self.users['donor'])
        self.assertEqual(self.client.get(page).status_code,200)
        self.assertEqual(self.client.get(page,{'donor':other.pk}).status_code,403)
        self.assertEqual(self.client.get(url,{'beneficiary':expired.pk}).status_code,403)
        self.assertEqual(self.client.get(url,{'donor':other.pk}).status_code,403)
        result=self.client.get(url,{'year':2026})
        self.assertEqual((result.context['spent'],result.context['beneficiary_count'],result.context['participation_count']),(435,2,3))
        self.assertNotContains(result,expired.first_name)
        custom=self.client.get(url,{'report_type':'custom','from_date':'2026-04-01','to_date':'2026-04-01'})
        self.assertEqual(custom.context['spent'],300)
        self.client.force_login(self.users['accountant'])
        self.assertEqual(self.client.get(url,{'year':2026}).context['spent'],15)
        History.objects.filter(donor=other).update(end_date=date(2026,11,15))
        self.assertEqual(self.client.get(page).status_code,403)
        self.assertEqual(self.client.get(url).status_code,403)
