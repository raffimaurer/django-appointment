"""INC-2 related-risk probes (synthetic data). Not part of the normal test suite.

Run from the repo root:
    DJANGO_SETTINGS_MODULE=appointments.demo_settings .venv/bin/python demo/evidence/INC-2/probe_related_risks.py

Each probe prints OBSERVED behaviour rather than asserting, so the output records what the code
does today. "RISK" means the probe showed a commit into time that the offer stage would hide.
"""
import os
import sys
import unittest
from datetime import time, timedelta
from unittest.mock import patch

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'appointments.demo_settings')
import django  # noqa: E402

django.setup()

from django.test.utils import get_runner  # noqa: E402
from django.conf import settings  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from appointment.models import AppointmentRescheduleHistory, DayOff, Unavailability, WorkingHours  # noqa: E402
from appointment.services import get_available_slots_for_staff  # noqa: E402
from appointment.tests.base.base_test import BaseTest  # noqa: E402


def report(name, risk, detail):
    print(f"PROBE {name}: {'RISK' if risk else 'ok'} - {detail}")


class RelatedRiskProbes(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.wd = (self.day.weekday() + 1) % 7
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.ar)
        self.wh = WorkingHours.objects.create(staff_member=self.staff_member1, day_of_week=self.wd,
                                              start_time=time(9), end_time=time(17))

    def pending(self):
        p = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reschedule_status='pending')
        return reverse('appointment:confirm_reschedule', args=[p.id_request])

    def moved(self):
        self.ar.refresh_from_db()
        return self.ar.date == self.day and self.ar.start_time == time(10)

    @patch('appointment.views.send_reschedule_confirmation_email')
    def test_p1_submit_into_already_blocked_time(self, send_email):
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        r = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
            'appointment_request_id': self.ar.id_request, 'date': self.day.isoformat(),
            'start_time': '10:00', 'end_time': '11:00', 'service': self.service1.id,
            'staff_member': self.staff_member1.id, 'reason_for_rescheduling': 'probe'})
        created = AppointmentRescheduleHistory.objects.filter(appointment_request=self.ar).exists()
        report('P1 reschedule submit into already-blocked hour', created,
               f"status={r.status_code} pending_created={created} email_sent={send_email.called} "
               "(confirmation is now rejected by the INC-2 fix, but the hold and email still happen)")

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_p2_confirm_after_day_off_added(self, notify):
        url = self.pending()
        DayOff.objects.create(staff_member=self.staff_member1, start_date=self.day, end_date=self.day)
        r = self.client.get(url)
        report('P2 confirm after DayOff added', self.moved(), f"status={r.status_code} moved={self.moved()}")

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_p3_confirm_into_other_booking(self, notify):
        url = self.pending()
        other = self.create_appt_request_for_sm1(date_=self.day, start_time=time(10), end_time=time(11))
        self.create_appointment_(user=self.users['client2'], appointment_request=other)
        r = self.client.get(url)
        report('P3 confirm into slot booked by another client', self.moved(),
               f"status={r.status_code} moved={self.moved()}")

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_p4_confirm_after_working_hours_removed(self, notify):
        url = self.pending()
        self.wh.delete()
        r = self.client.get(url)
        report('P4 confirm after working hours removed for that weekday', self.moved(),
               f"status={r.status_code} moved={self.moved()}")

    def test_p5_listing_adjacent_to_block(self):
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        offered = get_available_slots_for_staff(self.day, self.staff_member1, self.wd, service=self.service1)
        slots = [s.time() for s in offered]
        report('P5 slot listing offers 11:00 right after a 10:00-11:00 block', time(11) not in slots,
               f"09:00 offered={time(9) in slots} 11:00 offered={time(11) in slots}")

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_p6_rejected_confirmation_still_consumes_reschedule_limit(self, notify):
        # Devin Review finding BUG_..._0002 on 09e5310.
        self.service1.allow_rescheduling = True
        self.service1.reschedule_limit = 1
        self.service1.save()
        url = self.pending()
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        confirm = self.client.get(url)
        page = self.client.get(reverse('appointment:prepare_reschedule_appointment', args=[self.ar.id_request]))
        report('P6 after a rejected confirmation, reschedule page is locked (limit=1)', page.status_code == 403,
               f"confirm_status={confirm.status_code} reschedule_page_status={page.status_code} "
               "(pending row is preserved, so it counts toward the 5-minute limit)")


if __name__ == '__main__':
    runner = get_runner(settings)(verbosity=1)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RelatedRiskProbes)
    runner.setup_test_environment()
    old = runner.setup_databases()
    try:
        result = runner.run_suite(suite)
    finally:
        runner.teardown_databases(old)
        runner.teardown_test_environment()
    sys.exit(0 if result.wasSuccessful() else 1)
