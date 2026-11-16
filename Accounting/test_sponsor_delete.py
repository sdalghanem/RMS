from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from Management.models import Beneficiary, BeneficiarySponsorHistory, Profile
from .models import FinancialSponsorshipInvoice, GeneralDonationInvoice, Invoice


class SponsorDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for index, role in enumerate(('system_admin', 'cashier', 'accountant', 'donor')):
            user = get_user_model().objects.create_user(username=role, first_name=role)
            Profile.objects.create(user=user, role=role, phone=f'050000000{index}',
                                   national_number=f'100000000{index}')
            cls.users[role] = user
        cls.donor = cls.users['donor'].profile
        cls.child = Beneficiary.objects.create(first_name='Test', last_name='Child',
            national_number='2000000001', education_level='p1',gender='male')
        cls.url = reverse('Accounting:delete_sponsor',args=[cls.donor.pk])
        cls.list_url = reverse('Accounting:sponsors_list')

    def setUp(self):
        self.client.force_login(self.users['system_admin'])

    def preserved(self):
        self.assertTrue(Profile.objects.filter(pk=self.donor.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.donor.user_id).exists())

    def test_unused_sponsor_and_repeat(self):
        self.assertContains(self.client.get(self.list_url,{'q':'donor'}),self.url)
        self.assertRedirects(self.client.post(self.url),self.list_url)
        self.assertFalse(Profile.objects.filter(pk=self.donor.pk).exists())
        self.assertFalse(get_user_model().objects.filter(pk=self.donor.user_id).exists())
        self.assertRedirects(self.client.post(self.url),self.list_url)
        self.assertTrue(Beneficiary.objects.filter(pk=self.child.pk).exists())

    def test_current_assignment(self):
        self.child.donor=self.donor
        self.child.save(update_fields=['donor'])
        self.client.post(self.url)
        self.child.refresh_from_db()
        self.assertEqual(self.child.donor_id,self.donor.pk)
        self.preserved()

    def test_history_even_when_expired(self):
        today=timezone.localdate()
        history=BeneficiarySponsorHistory.objects.create(beneficiary=self.child,donor=self.donor,
            start_date=today-timedelta(days=40),end_date=today-timedelta(days=1))
        self.client.post(self.url)
        history.refresh_from_db()
        self.preserved()

    def test_invoice_without_allocation(self):
        today=timezone.localdate()
        invoice=Invoice.objects.create(number='DELETE-TEST',date=today,
            invoice_type='financial_sponsorship',created_by=self.users['cashier'])
        detail=FinancialSponsorshipInvoice.objects.create(invoice=invoice,sponsor=self.donor,
            custom_amount=100,start_date=today,end_date=today+timedelta(days=30))
        self.client.post(self.url)
        detail.refresh_from_db()
        self.preserved()

    def test_donation_identity(self):
        invoice=Invoice.objects.create(number='G-TEST',date=timezone.localdate(),
            invoice_type='general_donation',created_by=self.users['cashier'])
        detail=GeneralDonationInvoice.objects.create(invoice=invoice,amount=10,
            supporter_national_number=self.donor.national_number)
        self.client.post(self.url)
        detail.refresh_from_db()
        self.preserved()

    def test_access_get_csrf_and_list(self):
        self.assertEqual(self.client.get(self.url).status_code,405)
        csrf=Client(enforce_csrf_checks=True)
        csrf.force_login(self.users['system_admin'])
        self.assertEqual(csrf.post(self.url).status_code,403)
        for role in ('cashier','accountant','donor'):
            self.client.force_login(self.users[role])
            self.assertEqual(self.client.post(self.url).status_code,403)
            if role=='cashier':
                self.assertNotContains(self.client.get(self.list_url),self.url)
        self.preserved()

    def test_integrity_error_rolls_back_profile(self):
        with patch.object(get_user_model(),'delete',side_effect=ProtectedError('protected',[])):
            self.assertRedirects(self.client.post(self.url),self.list_url)
        self.preserved()
