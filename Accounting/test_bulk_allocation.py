from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from . import tests as existing_tests
from .models import MainProgram, AllocationHistory, FundEntry
from .bulk_allocation import allocation_token


class BulkAllocationTests(TestCase):
    setUpTestData = classmethod(existing_tests.RepairTests.setUpTestData.__func__)

    def setUp(self):
        self.client.force_login(self.users['accountant'])
        self.other = MainProgram.objects.create(name='ثان',total_donation_amount=0)
        self.url = reverse('Accounting:fund_to_main_allocate')
        self.payload = {'mode':'percent','token':allocation_token(self.users['accountant']),
                        'bulk_amount':'100.01',f'share_{self.main.pk}':'50',f'share_{self.other.pk}':'50'}

    def test_rounding_and_replay(self):
        self.assertContains(self.client.get(self.url),'percentage-allocation')
        before=FundEntry.objects.count()
        for _ in range(2):
            self.assertEqual(self.client.post(self.url,self.payload).status_code,302)
        allocations=AllocationHistory.objects.filter(reference__startswith='BULK-').order_by('to_main_program_id')
        self.assertEqual(list(allocations.values_list('amount',flat=True)),[Decimal('50.01'),Decimal('50.00')])
        self.assertEqual(FundEntry.objects.count(),before)

    def test_invalid_amount_rate_and_role(self):
        for update in [{'bulk_amount':'500'},{f'share_{self.main.pk}':'49.99'},{'share_999999':'1'},{'token':'bad'}]:
            self.client.post(self.url,{**self.payload,**update})
        self.client.force_login(self.users['cashier'])
        self.assertEqual(self.client.post(self.url,self.payload).status_code,403)
        self.assertFalse(AllocationHistory.objects.filter(reference__startswith='BULK-').exists())
