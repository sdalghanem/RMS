from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from Management.models import Profile, Beneficiary, BeneficiarySponsorHistory, MainProgram, SubProgram, PaymentPlan
from Management.middleware import AuditMiddleware
from Donation.views import _sponsored_supports
from .models import FundEntry, Invoice, FinancialSponsorshipInvoice, FinancialSponsorshipAllocation, SubProgramDisbursement, BeneficiarySupportEntry
from . import services, views


class RepairTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for i, role in enumerate(("donor", "accountant", "cashier", "system_admin"), 1):
            user = get_user_model().objects.create_user(username=role, email=role+"@example.invalid", password="test12345")
            Profile.objects.create(user=user, role=role, phone="050000000"+str(i), national_number="100000000"+str(i))
            cls.users[role] = user
        cls.main = MainProgram.objects.create(name="Main", total_donation_amount=0)
        cls.sub = SubProgram.objects.create(main_program=cls.main, name="Sub", allocated_amount=0)
        cls.beneficiary = Beneficiary.objects.create(first_name="Test", last_name="Child", gender="male", national_number="2000000001", education_level="p1")
        cls.today = timezone.localdate()
        cls.history = BeneficiarySponsorHistory.objects.create(beneficiary=cls.beneficiary, donor=cls.users["donor"].profile, start_date=cls.today-timedelta(days=10), end_date=cls.today+timedelta(days=10))
        cls.invoice = Invoice.objects.create(number="TEST-1", date=cls.today, invoice_type="financial_sponsorship", created_by=cls.users["cashier"])
        cls.sponsorship = FinancialSponsorshipInvoice.objects.create(invoice=cls.invoice, sponsor=cls.users["donor"].profile, custom_amount=1000, start_date=cls.history.start_date, end_date=cls.history.end_date)
        FundEntry.objects.create(invoice=cls.invoice, type="sponsorship_income", amount=1000)
        services.allocate_to_main_program(main_program=cls.main, amount=600, user=cls.users["accountant"])
        services.allocate_to_sub_program(main_program=cls.main, sub_program=cls.sub, amount=400, user=cls.users["accountant"])

    def login(self, role="accountant"):
        self.client.force_login(self.users[role])

    def spend(self, amount="100", number="SPEND-1"):
        return services.spend_from_sub_program(sub_program=self.sub, beneficiaries=[{"beneficiary": self.beneficiary, "amount": amount}], voucher_number=number, user=self.users["accountant"])

    def test_private_reports_reject_anonymous_and_donor(self):
        paths=["/accounting/reports/sponsorship/", "/accounting/reports/sponsorship/print/", "/accounting/cashier/"]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code,302)
        self.login("donor")
        for path in paths:
            self.assertEqual(self.client.get(path).status_code,403)

    def test_donor_cannot_manage_programs_or_plans(self):
        self.login("donor")
        for path in ("/programs/", "/programs/new/", "/programs/sub/new/", "/payment-plans/", "/payment-plans/new/"):
            self.assertEqual(self.client.get(path).status_code,403,path)
        self.assertEqual(self.client.post("/programs/new/", {"name":"Illegal"}).status_code,403)
        self.assertEqual(self.client.post("/payment-plans/new/", {"amount":"1", "duration_months":1}).status_code,403)

    def test_admin_can_create_plan(self):
        self.login("system_admin")
        response=self.client.post("/payment-plans/new/", {"amount":"150", "duration_months":1, "is_active":"on"})
        self.assertEqual(response.status_code,302)
        self.assertTrue(PaymentPlan.objects.filter(amount=150).exists())

    def test_program_write_requires_permission_and_toggle_post(self):
        self.login("system_admin")
        self.assertEqual(self.client.post("/programs/new/", {"name":"Allowed"}).status_code,403)
        self.users["system_admin"].user_permissions.add(*Permission.objects.filter(codename__in=["add_mainprogram", "change_mainprogram"], content_type__app_label="Management"))
        self.assertEqual(self.client.post("/programs/new/", {"name":"Allowed"}).status_code,302)
        path=reverse("Management:program_toggle",args=[self.main.pk])
        self.assertEqual(self.client.get(path).status_code,405)
        self.assertEqual(self.client.post(path).status_code,302)
        self.main.refresh_from_db()
        self.assertFalse(self.main.is_active)
        csrf_client=Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.users["system_admin"])
        self.assertEqual(csrf_client.post(path).status_code,403)

    def test_donor_sees_history_membership_without_legacy_donor(self):
        self.login("donor")
        self.assertIsNone(self.beneficiary.donor_id)
        response=self.client.get("/donation/beneficiaries/")
        self.assertEqual(response.status_code,200)
        self.assertIn(self.beneficiary,list(response.context["beneficiaries"]))
        self.assertEqual(self.client.get(reverse("Donation:beneficiary_detail",args=[self.beneficiary.pk])).status_code,200)

    def test_donor_cannot_read_unrelated_beneficiary(self):
        other=Beneficiary.objects.create(first_name="Other",last_name="Child",gender="female",national_number="2000000002",donor=self.users["donor"].profile)
        self.login("donor")
        self.assertEqual(self.client.get(reverse("Donation:beneficiary_detail",args=[other.pk])).status_code,404)

    def test_single_allocation_invoice_and_ownership(self):
        FinancialSponsorshipAllocation.objects.create(sponsorship_invoice=self.sponsorship,beneficiary=self.beneficiary,amount=1000)
        self.login("donor")
        response=self.client.get(reverse("Donation:invoice_detail",args=[self.sponsorship.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context["allocations"]),1)
        self.sponsorship.sponsor=self.users["cashier"].profile
        self.sponsorship.save()
        self.assertEqual(self.client.get(reverse("Donation:invoice_detail",args=[self.sponsorship.pk])).status_code,404)

    def test_portal_rejects_staff_and_existing_donor_login_works(self):
        self.login("donor")
        self.assertEqual(self.client.get("/donation/login/").status_code,302)
        self.login("accountant")
        self.assertEqual(self.client.get("/donation/").status_code,403)

    def test_history_overlap_is_not_double_counted_and_reversal_excluded(self):
        disbursement=self.spend()
        BeneficiarySponsorHistory.objects.create(beneficiary=self.beneficiary,donor=self.users["donor"].profile,start_date=self.history.start_date,end_date=self.history.end_date)
        self.assertEqual(_sponsored_supports(self.users["donor"].profile).count(),1)
        self.login("donor")
        self.assertEqual(self.client.get("/donation/profile/").context["total_support"],Decimal("100"))
        services.reverse_subprogram_disbursement(disbursement=disbursement,user=self.users["accountant"])
        self.assertEqual(_sponsored_supports(self.users["donor"].profile).count(),0)
        self.assertEqual(self.client.get("/donation/profile/").context["total_support"],0)

    def test_spend_reverse_and_duplicate_reversal(self):
        disbursement=self.spend()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.spent_amount,100)
        self.assertEqual(services.get_fund_balance(),900)
        services.reverse_subprogram_disbursement(disbursement=disbursement,user=self.users["accountant"])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.spent_amount,0)
        self.assertEqual(services.get_fund_balance(),1000)
        with self.assertRaises(ValueError):
            services.reverse_subprogram_disbursement(disbursement=disbursement,user=self.users["accountant"])
        self.assertEqual(services.get_fund_balance(),1000)

    def test_failed_spend_rolls_back_all_financial_writes(self):
        with patch("Accounting.services.create_fund_entry",side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):self.spend()
        self.assertFalse(SubProgramDisbursement.objects.exists())
        self.assertFalse(BeneficiarySupportEntry.objects.exists())
        self.assertEqual(services.get_fund_balance(),1000)

    def test_spend_rejects_invalid_and_overdrawn_amounts(self):
        for amount in ("0", "-1", "NaN", "Infinity", "0.001", "401"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):self.spend(amount)
        self.assertFalse(SubProgramDisbursement.objects.exists())

    def test_stale_program_is_refreshed_before_allocation(self):
        stale=MainProgram.objects.get(pk=self.main.pk)
        services.allocate_to_main_program(main_program=self.main,amount=100,user=self.users["accountant"])
        services.allocate_to_main_program(main_program=stale,amount=100,user=self.users["accountant"])
        stale.refresh_from_db()
        self.assertEqual(stale.total_donation_amount,800)

    def test_used_unassigned_sponsorship_income_cannot_be_removed(self):
        self.login("cashier")
        self.assertEqual(self.client.post(reverse("Accounting:invoice_delete",args=[self.invoice.pk])).status_code,302)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.client.post(reverse("Accounting:invoice_update",args=[self.invoice.pk]),{"amount":"1"})
        self.sponsorship.refresh_from_db()
        self.assertEqual(self.sponsorship.total_amount,1000)

    def test_disbursement_post_rejects_mismatched_and_duplicate_lists(self):
        self.login()
        for ids,amounts in [([str(self.beneficiary.pk)],[]),([str(self.beneficiary.pk)]*2,["1","1"]),(["999999"],["1"])]:
            self.client.post(reverse("Accounting:subprogram_disburse_create"),{"sub_program":self.sub.pk,"voucher_number":"BAD","beneficiary_ids[]":ids,"amounts[]":amounts})
            self.assertFalse(SubProgramDisbursement.objects.exists())

    def test_inactive_program_rejected_in_service(self):
        MainProgram.objects.filter(pk=self.main.pk).update(is_active=False)
        with self.assertRaises(ValueError):self.spend()
        self.assertFalse(SubProgramDisbursement.objects.exists())

    def test_sponsor_invalid_profile_does_not_update_user(self):
        self.login("cashier")
        response=self.client.post(reverse("Accounting:sponsor_quick_update",args=[self.users["donor"].profile.pk]),{"email":"changed@example.invalid","first_name":"Changed","last_name":"Name","phone":"invalid","national_number":"invalid"})
        self.assertEqual(response.status_code,400)
        self.users["donor"].refresh_from_db()
        self.assertEqual(self.users["donor"].email,"donor@example.invalid")

    def test_general_donation_failure_rolls_back_header(self):
        request=RequestFactory().post("/",{})
        request.user=self.users["cashier"]
        with patch("Accounting.views.GeneralDonationInvoiceForm") as form, patch("Accounting.views.GeneralDonationInvoice.objects.create",side_effect=RuntimeError("failure")):
            form.return_value.is_valid.return_value=True
            form.return_value.cleaned_data={"number":"NEW","date":self.today,"payment_method":"cash","notes":"","bank_from":"","from_account_number":"","to_account_number":"","amount":Decimal("1"),"amount_in_words":"","supporter_name":"test"}
            with self.assertRaises(RuntimeError):views.invoice_create_general(request)
        self.assertFalse(Invoice.objects.filter(number="NEW").exists())

    def test_audit_scrubs_sensitive_request_values(self):
        middleware=AuditMiddleware(lambda request:None)
        data={"new_password1":"secret","national_number":"identity","disease":"health","bank":"account","nested":{"password":"secret"}}
        self.assertEqual(middleware._scrub(data),{key:"***" for key in data})

    @override_settings(ALLOW_MULTIPLE_SPONSORSHIP_INVOICES=False)
    def test_open_ended_history_blocks_second_assignment(self):
        self.history.end_date=None
        self.history.save(update_fields=["end_date"])
        self.login()
        response=self.client.post(reverse("Management:beneficiaries_bulk_assign"), {"sponsorship_invoice":self.sponsorship.pk,"selected_ids":str(self.beneficiary.pk)})
        self.assertEqual(response.status_code,302)
        self.assertFalse(FinancialSponsorshipAllocation.objects.exists())

    def test_no_history_never_exposes_support(self):
        self.spend()
        self.assertEqual(_sponsored_supports(self.users["cashier"].profile).count(),0)

    def test_accountant_retains_invoice_and_sponsorship_access(self):
        self.login("accountant")
        paths=["/accounting/invoices/", reverse("Accounting:invoice_detail",args=[self.invoice.pk]),
               "/accounting/invoices/create/general/", "/accounting/invoices/create/sponsorship/",
               "/sponsorships/", "/accounting/accountant/", "/accounting/allocate/fund-to-main/",
               "/accounting/allocate/main-to-sub/", "/accounting/disbursement/create/"]
        for path in paths:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)

    def test_accountant_can_create_and_assign_sponsorship(self):
        self.login("accountant")
        response=self.client.post("/accounting/invoices/create/sponsorship/",{
            "number":"ACCOUNTANT-NEW","date":self.today,"payment_method":"cash",
            "sponsor":self.users["donor"].profile.pk,"is_custom_plan":"on",
            "custom_amount":"100","custom_duration_months":1,
            "start_date":self.today,"end_date":self.today+timedelta(days=30),
        })
        self.assertEqual(response.status_code,302)
        sponsorship=FinancialSponsorshipInvoice.objects.get(invoice__number="ACCOUNTANT-NEW")
        beneficiary=Beneficiary.objects.create(first_name="New",last_name="Child",gender="male",national_number="2000000099")
        response=self.client.post(reverse("Management:beneficiaries_bulk_assign"),{
            "sponsorship_invoice":sponsorship.pk,"selected_ids":str(beneficiary.pk)})
        self.assertEqual(response.status_code,302)
        self.assertTrue(FinancialSponsorshipAllocation.objects.filter(sponsorship_invoice=sponsorship,beneficiary=beneficiary).exists())

    def test_accountant_can_disburse_and_reverse_through_views(self):
        self.login("accountant")
        response=self.client.post(reverse("Accounting:subprogram_disburse_create"),{
            "sub_program":self.sub.pk,"voucher_number":"ACCOUNTANT-SPEND",
            "beneficiary_ids[]":[str(self.beneficiary.pk)],"amounts[]":["50"]})
        self.assertEqual(response.status_code,302)
        disbursement=SubProgramDisbursement.objects.get(voucher_number="ACCOUNTANT-SPEND")
        self.assertEqual(services.get_fund_balance(),950)
        response=self.client.post(reverse("Accounting:reverse_subprogram_disbursement",args=[disbursement.pk]),{"reason":"test"})
        self.assertEqual(response.status_code,302)
        disbursement.refresh_from_db()
        self.assertTrue(disbursement.is_reversed)
        self.assertEqual(services.get_fund_balance(),1000)


    def new_receipt(self, number="SECOND", **kwargs):
        invoice = Invoice.objects.create(number=number, date=self.today, invoice_type="financial_sponsorship", created_by=self.users["cashier"])
        return FinancialSponsorshipInvoice.objects.create(invoice=invoice, sponsor=self.users["donor"].profile, custom_amount=100, start_date=kwargs.get("start", self.today), end_date=kwargs.get("end", self.today+timedelta(days=30)))

    def child_payload(self):
        return {"number":"INLINE", "date":self.today, "payment_method":"cash", "sponsor":self.users["donor"].profile.pk,
            "is_custom_plan":"on", "custom_amount":"100", "custom_duration_months":1,
            "start_date":self.today,"end_date":self.today+timedelta(days=30), "create_beneficiary":"1",
            "new_beneficiary-first_name":"New", "new_beneficiary-father_name":"Father", "new_beneficiary-grand_name":"Grand",
            "new_beneficiary-last_name":"Family", "new_beneficiary-gender":"male", "new_beneficiary-national_number":"2000000088",
            "new_beneficiary-type_disease":"none", "new_beneficiary-housing_fee":"0", "new_beneficiary-number_of_beneficiary_in_family":"1"}

    def test_receipt_options_and_attachment_preserve_finances(self):
        from Management.forms import BeneficiariesBulkAssignForm
        from Management.sponsorship_ops import attach_sponsorship
        form=BeneficiariesBulkAssignForm()
        self.assertIn(self.sponsorship, form.fields["sponsorship_invoice"].queryset)
        self.assertIn("TEST-1", str(form["sponsorship_invoice"]))
        before=list(FundEntry.objects.values())
        attach_sponsorship(self.sponsorship.pk,self.beneficiary.pk,self.users["accountant"])
        self.assertNotIn(self.sponsorship, BeneficiariesBulkAssignForm().fields["sponsorship_invoice"].queryset)
        self.assertEqual(list(FundEntry.objects.values()),before)
        self.assertTrue(BeneficiarySponsorHistory.objects.filter(pk=self.history.pk).exists())

    def test_multiple_receipts_and_duplicate_protection(self):
        from Management.sponsorship_ops import attach_sponsorship
        from django.core.exceptions import ValidationError
        first=attach_sponsorship(self.sponsorship.pk,self.beneficiary.pk,self.users["accountant"])
        second=self.new_receipt()
        attach_sponsorship(second.pk,self.beneficiary.pk,self.users["accountant"])
        with self.assertRaises(ValidationError):attach_sponsorship(second.pk,self.beneficiary.pk,self.users["accountant"])
        self.assertEqual(FinancialSponsorshipAllocation.objects.count(),2)
        self.assertTrue(FinancialSponsorshipAllocation.objects.filter(pk=first.pk).exists())
        self.spend()
        self.assertEqual(BeneficiarySupportEntry.objects.count(),1)
        self.assertEqual(_sponsored_supports(self.users["donor"].profile).count(),1)
        self.assertEqual(services.get_fund_balance(),900)

    def test_renewal_retains_old_link_without_financial_entry(self):
        from Management.sponsorship_ops import attach_sponsorship
        old=attach_sponsorship(self.sponsorship.pk,self.beneficiary.pk,self.users["accountant"])
        next_receipt=self.new_receipt(start=self.today+timedelta(days=31),end=self.today+timedelta(days=61))
        self.login()
        url=reverse("Management:sponsorship_renew",args=[self.sponsorship.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        before=FundEntry.objects.count()
        self.assertEqual(self.client.post(url,{"sponsorship_invoice":next_receipt.pk}).status_code,302)
        self.assertEqual(self.client.post(url,{"sponsorship_invoice":next_receipt.pk}).status_code,200)
        self.assertEqual(FundEntry.objects.count(),before)
        self.assertTrue(FinancialSponsorshipAllocation.objects.filter(pk=old.pk).exists())
        self.assertEqual(FinancialSponsorshipAllocation.objects.count(),2)

    def test_inline_child_creation_and_duplicate_rollback(self):
        self.login()
        url="/accounting/invoices/create/sponsorship/"
        payload=self.child_payload()
        response=self.client.post(url,payload)
        self.assertEqual(response.status_code,302, getattr(response,"context",None) and response.context["child_form"].errors)
        child=Beneficiary.objects.get(national_number="2000000088")
        self.assertEqual(FinancialSponsorshipAllocation.objects.get(sponsorship_invoice__invoice__number="INLINE").beneficiary_id,child.pk)
        payload["number"]="INLINE-DUP"
        self.assertEqual(self.client.post(url,payload).status_code,200)
        self.assertFalse(Invoice.objects.filter(number="INLINE-DUP").exists())
        self.assertEqual(Beneficiary.objects.filter(national_number="2000000088").count(),1)

    def test_inline_failure_rolls_back_child_and_receipt(self):
        self.login()
        from django.core.exceptions import ValidationError
        with patch("Accounting.views.attach_sponsorship",side_effect=ValidationError("failed")):
            self.assertEqual(self.client.post("/accounting/invoices/create/sponsorship/",self.child_payload()).status_code,200)
        self.assertFalse(Invoice.objects.filter(number="INLINE").exists())
        self.assertFalse(Beneficiary.objects.filter(national_number="2000000088").exists())

    def test_cashier_cannot_create_inline_child(self):
        self.login("cashier")
        self.assertEqual(self.client.post("/accounting/invoices/create/sponsorship/",self.child_payload()).status_code,200)
        self.assertFalse(Invoice.objects.filter(number="INLINE").exists())

    def test_three_part_search_still_matches_family_name(self):
        self.beneficiary.father_name="Father"
        self.beneficiary.grand_name="Grand"
        self.beneficiary.save()
        self.login()
        response=self.client.get(reverse("Accounting:ajax_beneficiary_search"),{"q":"Child"})
        self.assertEqual(response.json()["results"][0]["name"],"Test Father Grand")

    def sponsor_payload(self):
        return {"email":"new@example.invalid","first_name":"New","last_name":"Sponsor","phone":"0512345678","national_number":"1234567890"}

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_sponsor_random_password_not_exposed_and_existing_unchanged(self):
        self.login("cashier")
        old=self.users["donor"].password
        with patch("Accounting.forms.secrets.token_urlsafe",return_value="random-secret-for-test") as random:
            response=self.client.post(reverse("Accounting:sponsor_quick_create"),self.sponsor_payload())
        self.assertEqual(response.status_code,200,response.content)
        random.assert_called_once_with(32)
        user=get_user_model().objects.get(username="new@example.invalid")
        self.assertTrue(user.check_password("random-secret-for-test"))
        self.assertNotContains(response,"random-secret-for-test")
        self.users["donor"].refresh_from_db()
        self.assertEqual(self.users["donor"].password,old)
        self.assertEqual(user.profile.role,"donor")
        self.assertNotContains(self.client.get(reverse("Accounting:sponsor_create_page")), 'name="password1"')

    def test_csv_import_counts_duplicates_and_invalid_rows(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        content="email,first_name,last_name,phone,national_number\nnew@example.invalid,New,Sponsor,0512345678,1234567890\nnew@example.invalid,New,Sponsor,0512345678,1234567890\nbad,New,Sponsor,abc,abc\n"
        self.login("cashier")
        response=self.client.post(reverse("Accounting:sponsors_import"),{"file":SimpleUploadedFile("sponsors.csv",content.encode())})
        self.assertEqual(response.context["summary"],{"added":1,"duplicates":1,"rejected":1})
        self.assertTrue(get_user_model().objects.get(username="new@example.invalid").has_usable_password())
        self.login("donor")
        self.assertEqual(self.client.get(reverse("Accounting:sponsors_import")).status_code,403)

    def test_dates_all_states_preserve_links_history_and_money(self):
        from Management.sponsorship_ops import attach_sponsorship
        allocation=attach_sponsorship(self.sponsorship.pk,self.beneficiary.pk,self.users["accountant"])
        histories=list(BeneficiarySponsorHistory.objects.values())
        funds=list(FundEntry.objects.values())
        self.login()
        url=reverse("Management:sponsorship_edit_dates",args=[self.sponsorship.pk])
        for start,end in ((self.today-timedelta(days=30),self.today-timedelta(days=1)),(self.today,self.today+timedelta(days=50))):
            self.assertEqual(self.client.post(url,{"start_date":start,"end_date":end}).status_code,302)
            self.sponsorship.refresh_from_db()
            self.assertEqual(self.sponsorship.end_date,end)
        self.assertEqual(self.client.post(url,{"start_date":self.today,"end_date":self.today-timedelta(days=1)}).status_code,200)
        self.assertTrue(FinancialSponsorshipAllocation.objects.filter(pk=allocation.pk).exists())
        self.assertEqual(list(BeneficiarySponsorHistory.objects.values()),histories)
        self.assertEqual(list(FundEntry.objects.values()),funds)

    def test_excel_dry_run_apply_and_invalid_atomicity(self):
        import tempfile
        from pathlib import Path
        from io import StringIO
        from openpyxl import Workbook
        from django.core.management import call_command, CommandError
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"dates.xlsx"
            book=Workbook();sheet=book.active
            sheet.append(["receipt","start","end"])
            sheet.append([self.invoice.number,self.today,self.today+timedelta(days=90)])
            book.save(path)
            options={"number_column":"receipt","start_column":"start","end_column":"end","stdout":StringIO()}
            call_command("update_sponsorship_dates",str(path),**options)
            self.sponsorship.refresh_from_db()
            self.assertEqual(self.sponsorship.end_date,self.history.end_date)
            call_command("update_sponsorship_dates",str(path),apply=True,**options)
            self.sponsorship.refresh_from_db()
            self.assertEqual(self.sponsorship.end_date,self.today+timedelta(days=90))
            sheet.append([self.invoice.number,self.today,self.today+timedelta(days=95)])
            sheet.append(["MISSING",self.today,self.today])
            sheet.append(["INVALID",self.today,"bad"])
            book.save(path)
            with self.assertRaises(CommandError):call_command("update_sponsorship_dates",str(path),apply=True,**options)
            self.sponsorship.refresh_from_db()
            self.assertEqual(self.sponsorship.end_date,self.today+timedelta(days=90))


    def test_unavailable_receipts_and_invalid_beneficiary_are_rejected(self):
        from Management.forms import BeneficiariesBulkAssignForm
        expired=self.new_receipt("EXPIRED",start=self.today-timedelta(days=20),end=self.today-timedelta(days=1))
        future=self.new_receipt("FUTURE",start=self.today+timedelta(days=2))
        available=BeneficiariesBulkAssignForm().fields["sponsorship_invoice"].queryset
        self.assertNotIn(expired,available)
        self.assertNotIn(future,available)
        self.login()
        url=reverse("Management:beneficiaries_bulk_assign")
        for data in ({"sponsorship_invoice":expired.pk,"selected_ids":str(self.beneficiary.pk)},
                     {"sponsorship_invoice":self.sponsorship.pk,"selected_ids":"invalid"}):
            response=self.client.post(url,data,follow=True)
            self.assertEqual(response.status_code,200)
            self.assertTrue(list(response.context["messages"]))
        self.assertFalse(FinancialSponsorshipAllocation.objects.exists())

    def test_new_pages_and_date_actions_keep_role_boundaries(self):
        self.login()
        response=self.client.get("/accounting/invoices/create/sponsorship/")
        self.assertContains(response,'name="create_beneficiary"')
        self.assertNotContains(response,'name="password1"')
        self.login("donor")
        for name in ("sponsorship_edit_dates","sponsorship_renew"):
            url=reverse("Management:"+name,args=[self.sponsorship.pk])
            self.assertEqual(self.client.post(url,{"start_date":self.today,"end_date":self.today}).status_code,403)

    def test_excel_mixed_invalid_batch_leaves_valid_receipt_unchanged(self):
        import tempfile
        from pathlib import Path
        from io import StringIO
        from openpyxl import Workbook
        from django.core.management import call_command, CommandError
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"dates.xlsx"
            book=Workbook();sheet=book.active
            sheet.append(["number","start_date","end_date"])
            sheet.append([self.invoice.number,self.today,self.today+timedelta(days=90)])
            sheet.append(["MISSING",self.today,self.today])
            book.save(path)
            with self.assertRaises(CommandError):
                call_command("update_sponsorship_dates",str(path),apply=True,stdout=StringIO())
            self.sponsorship.refresh_from_db()
            self.assertEqual(self.sponsorship.end_date,self.history.end_date)


class DisplayDurationTests(TestCase):
    setUpTestData = classmethod(RepairTests.setUpTestData.__func__)

    def test_calendar_duration_and_invalid_dates_without_queries(self):
        from datetime import date
        cases = [
            (date(2026,8,25), date(2027,1,7), "4 أشهر و13 يومًا"),
            (date(2026,5,10), date(2026,8,10), "3 أشهر"),
            (date(2026,1,1), date(2026,2,1), "شهر واحد"),
            (date(2026,1,1), date(2026,1,16), "15 يومًا"),
            (date(2026,1,1), date(2027,1,1), "12 شهرًا"),
            (date(2026,1,31), date(2026,2,28), "شهر واحد"),
            (date(2026,1,1), date(2026,1,1), "—"),
            (date(2026,2,1), date(2026,1,1), "—"),
            (None, date(2026,1,1), "—"), (date(2026,1,1), None, "—"),
            ("invalid", date(2026,1,1), "—"),
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end), self.assertNumQueries(0):
                obj = FinancialSponsorshipInvoice(start_date=start,end_date=end,custom_duration_months=99)
                self.assertEqual(obj.display_duration, expected)
                self.assertEqual(obj.custom_duration_months,99)

    def test_receipt_584_and_sponsor_pages_preserve_stored_values(self):
        from datetime import date
        self.invoice.number="584"
        self.invoice.save(update_fields=["number"])
        self.sponsorship.start_date=date(2026,8,25)
        self.sponsorship.end_date=date(2027,1,7)
        self.sponsorship.custom_duration_months=None
        self.sponsorship.save()
        self.history.start_date=self.sponsorship.start_date
        self.history.end_date=self.sponsorship.end_date
        self.history.save()
        FinancialSponsorshipAllocation.objects.create(sponsorship_invoice=self.sponsorship,beneficiary=self.beneficiary,amount=1000)
        before=FinancialSponsorshipInvoice.objects.values().get(pk=self.sponsorship.pk)
        funds=list(FundEntry.objects.values())
        self.client.force_login(self.users["cashier"])
        for name, pk in (("Accounting:invoice_detail",self.invoice.pk),("Accounting:sponsor_detail",self.users["donor"].profile.pk)):
            response=self.client.get(reverse(name,args=[pk]))
            self.assertContains(response,"4 أشهر و13 يومًا")
        self.assertEqual(FinancialSponsorshipInvoice.objects.values().get(pk=self.sponsorship.pk),before)
        self.assertEqual(list(FundEntry.objects.values()),funds)

    def test_history_without_financial_receipt_has_placeholder(self):
        self.client.force_login(self.users["cashier"])
        response=self.client.get(reverse("Accounting:sponsor_detail",args=[self.users["donor"].profile.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context["results"][0]["display_duration"],"—")
