"""INC-2 sibling-defect probe (evidence only, not part of the normal suite).

Each probe changes one mutable availability input after a reschedule request is pending, then follows the
confirmation link. The assertions describe the desired behaviour (reject with 409, leave the appointment where it
was), so on the PR head the three sibling probes FAIL, which is the evidence. The control probe must pass.

Run it explicitly (see README.md in this directory). ``manage.py test appointment`` does not discover this file.
"""
from datetime import time, timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, DayOff, WorkingHours
from appointment.tests.base.base_test import BaseTest
from appointment.utils.db_helpers import get_weekday_num_from_date


@patch('appointment.views.notify_admin_about_reschedule')
class SiblingAvailabilityProbe(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic probe', reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])

    def confirm_and_report(self):
        response = self.client.get(self.url)
        self.original.refresh_from_db()
        moved = (self.original.date, self.original.start_time) == (self.day, time(10))
        print(f"\n[probe] {self._testMethodName}: HTTP {response.status_code}, appointment moved={moved}")
        return response, moved

    def assert_rejected(self):
        response, moved = self.confirm_and_report()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(moved)

    def test_control_no_change_confirms(self, _notify):
        response, moved = self.confirm_and_report()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(moved)

    def test_day_off_added_after_request(self, _notify):
        DayOff.objects.create(staff_member=self.staff_member1, start_date=self.day, end_date=self.day)
        self.assert_rejected()

    def test_overlapping_appointment_added_after_request(self, _notify):
        other = self.create_appt_request_for_sm1(date_=self.day, start_time=time(10), end_time=time(11))
        self.create_appt_for_sm2(appointment_request=other)
        self.assert_rejected()

    def test_working_hours_changed_after_request(self, _notify):
        WorkingHours.objects.create(staff_member=self.staff_member1, day_of_week=get_weekday_num_from_date(self.day),
                                    start_time=time(13), end_time=time(17))
        self.staff_member1.work_on_saturday = self.staff_member1.work_on_sunday = True
        self.staff_member1.save()
        self.assert_rejected()
