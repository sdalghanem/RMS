from decimal import Decimal
from django.test import TestCase, SimpleTestCase
from django.contrib.auth import get_user_model
from django.template import Template,Context
from django.urls import reverse
from Management.models import Profile

class InterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users={}
        for i,role in enumerate(('system_admin','accountant','cashier','donor'),1):
            user=get_user_model().objects.create_user(username=role+'@example.invalid',email=role+'@example.invalid',password='V2-Test-Only-2026!')
            Profile.objects.create(user=user,role=role,phone='050000000'+str(i),national_number='900000000'+str(i))
            cls.users[role]=user

    def test_four_roles_login_logout(self):
        for role,user in self.users.items():
            with self.subTest(role=role):
                response=self.client.post('/login/',{'username':user.username,'password':'V2-Test-Only-2026!'})
                self.assertEqual(response.status_code,302)
                self.assertIn('_auth_user_id',self.client.session)
                self.assertEqual(self.client.get(response.url).status_code,200)
                self.client.get('/logout/')
                self.assertNotIn('_auth_user_id',self.client.session)

    def test_login_next_preserves_return_url_and_permissions(self):
        from urllib.parse import urlencode
        target='/sponsorships/?status=expiring&q=DEMO'
        for role in ('system_admin','accountant','cashier','donor'):
            with self.subTest(role=role):
                self.client.logout()
                response=self.client.post('/login/?'+urlencode({'next':target}), {
                    'username':self.users[role].username,'password':'V2-Test-Only-2026!'})
                self.assertEqual(response.status_code,302)
                self.assertEqual(response.url,target)
                self.assertEqual(self.client.get(target).status_code,403 if role=='donor' else 200)
        for target in ('https://example.invalid/','//example.invalid/','javascript:alert(1)'):
            with self.subTest(target=target):
                self.client.logout()
                response=self.client.post('/login/',{'username':self.users['accountant'].username,
                    'password':'V2-Test-Only-2026!','next':target})
                self.assertRedirects(response,'/accounting/accountant/',fetch_redirect_response=False)
        self.client.logout()
        response=self.client.post('/login/',{'username':self.users['cashier'].username,
            'password':'V2-Test-Only-2026!','next':'/sponsorships/'})
        self.assertRedirects(response,'/sponsorships/')

    def test_role_navigation_pages(self):
        paths={
            'accountant':['/accounting/accountant/','/accounting/ledger/','/accounting/program-balances/','/accounting/reservations/','/accounting/disbursement/create/','/accounting/allocate/fund-to-main/','/accounting/allocate/main-to-sub/'],
            'cashier':['/accounting/cashier/','/accounting/invoices/','/accounting/invoices/create/general/','/accounting/invoices/create/sponsorship/','/accounting/sponsors/'],
            'system_admin':['/dashboard/','/beneficiaries/','/programs/','/payment-plans/'],
            'donor':['/donation/','/donation/beneficiaries/','/donation/invoices/','/donation/profile/']}
        for role,urls in paths.items():
            self.client.force_login(self.users[role])
            for url in urls:
                with self.subTest(role=role,url=url):self.assertEqual(self.client.get(url).status_code,200)

    def test_authorization_remains_server_enforced(self):
        self.client.force_login(self.users['donor'])
        for url in ['/accounting/ledger/','/accounting/disbursement/create/','/beneficiaries/','/programs/']:
            self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.users['cashier'])
        self.assertEqual(self.client.post('/accounting/disbursement/create/',{}).status_code,403)
