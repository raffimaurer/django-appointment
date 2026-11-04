"""Synthetic related-risk probes for issue #2 (outside normal test discovery).

Each probe prints OBSERVED behaviour; probes do not assert a desired outcome and are not regression tests.
Run from the repository root:
    DJANGO_SETTINGS_MODULE=appointments.demo_settings .venv/bin/python demo/evidence/INC-2/related_risk_probes.py
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
from appointment.tests.base.base_test import BaseTest  # noqa: E402


class RelatedRiskProbes(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.ar)
        WorkingHours.objects.create(staff_member=self.staff_member1, day_of_week=(self.day.weekday() + 1) % 7,
                                    start_time=time(9), end_time=time(17))

    def pending(self, **kwargs):
        values = dict(appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
                      staff_member=self.staff_member1, reschedule_status='pending')
        values.update(kwargs)
        return AppointmentRescheduleHistory.objects.create(**values)

    def confirm(self, history):
        with patch('appointment.views.notify_admin_about_reschedule') as notify:
            response = self.client.get(reverse('appointment:confirm_reschedule', args=[history.id_request]))
        self.ar.refresh_from_db()
        moved = (self.ar.date, self.ar.start_time) == (self.day, time(10))
        return f"status={response.status_code} moved_into_target={moved} notified={notify.called}"

    def report(self, name, outcome):
        print(f"PROBE {name}: {outcome}")

    def test_p1_day_off_added_after_request(self):
        history = self.pending()
        DayOff.objects.create(staff_member=self.staff_member1, start_date=self.day, end_date=self.day,
                              description='Synthetic leave')
        self.report('confirm-after-day-off', self.confirm(history))

    def test_p2_other_appointment_booked_in_target_slot(self):
        history = self.pending()
        other = self.create_appt_request_for_sm1(date_=self.day, start_time=time(10), end_time=time(11))
        self.create_appt_for_sm2(appointment_request=other)
        self.report('confirm-into-other-booking', self.confirm(history))

    def test_p3_working_hours_removed_after_request(self):
        history = self.pending()
        WorkingHours.objects.filter(staff_member=self.staff_member1).delete()
        self.report('confirm-after-working-hours-removed', self.confirm(history))

    def test_p4_submit_into_already_blocked_hour(self):
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day, start_time=time(10),
                                      end_time=time(11), description='Synthetic block')
        with patch('appointment.views.send_reschedule_confirmation_email') as send_email:
            response = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
                'appointment_request_id': self.ar.id_request, 'date': self.day.isoformat(),
                'start_time': '10:00', 'end_time': '11:00', 'service': self.service1.id,
                'staff_member': self.staff_member1.id, 'reason_for_rescheduling': 'Synthetic probe'})
        created = AppointmentRescheduleHistory.objects.filter(appointment_request=self.ar).exists()
        self.report('submit-into-blocked-hour',
                    f"status={response.status_code} pending_created={created} email_sent={send_email.called}")

    def test_p5_reschedule_page_after_rejected_confirmation(self):
        self.service1.reschedule_limit = 1
        self.service1.allow_rescheduling = True
        self.service1.save()
        history = self.pending()
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day, start_time=time(10),
                                      end_time=time(11), description='Synthetic block')
        first = self.confirm(history)
        response = self.client.get(reverse('appointment:prepare_reschedule_appointment', args=[self.ar.id_request]))
        self.report('reschedule-page-after-rejection', f"confirm[{first}] then reschedule_page={response.status_code}")

    def test_p6_pending_with_null_staff_member(self):
        history = self.pending(staff_member=None)
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day, start_time=time(10),
                                      end_time=time(11), description='Synthetic block')
        try:
            outcome = self.confirm(history)
        except Exception as exc:  # observed, not expected
            outcome = f"exception={type(exc).__name__}"
        self.report('confirm-with-null-staff-member', outcome)


if __name__ == '__main__':
    runner = get_runner(settings)(verbosity=0)
    runner.setup_test_environment()
    old_config = runner.setup_databases()
    try:
        result = unittest.TextTestRunner(verbosity=1).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(RelatedRiskProbes))
    finally:
        runner.teardown_databases(old_config)
        runner.teardown_test_environment()
    sys.exit(0 if result.wasSuccessful() else 1)
