from datetime import time, timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability, WorkingHours
from appointment.tests.base.base_test import BaseTest
from appointment.utils.db_helpers import has_overlapping_unavailability


class HasOverlappingUnavailabilityTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))

    def overlaps(self, start, end, staff=None, date=None):
        return has_overlapping_unavailability(date or self.day, start, end, staff or self.staff_member1)

    def test_overlapping_intervals(self):
        self.assertTrue(self.overlaps(time(10), time(11)))
        self.assertTrue(self.overlaps(time(9, 30), time(10, 30)))
        self.assertTrue(self.overlaps(time(10, 30), time(11, 30)))
        self.assertTrue(self.overlaps(time(10, 15), time(10, 45)))
        self.assertTrue(self.overlaps(time(9), time(12)))

    def test_touching_boundaries_do_not_overlap(self):
        self.assertFalse(self.overlaps(time(9), time(10)))
        self.assertFalse(self.overlaps(time(11), time(12)))

    def test_scoped_to_staff_and_date(self):
        self.assertFalse(self.overlaps(time(10), time(11), staff=self.staff_member2))
        self.assertFalse(self.overlaps(time(10), time(11), date=self.day + timedelta(days=1)))


class ConfirmRescheduleRevalidationTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.ar)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic', reschedule_status='pending')
        WorkingHours.objects.create(staff_member=self.staff_member1, day_of_week=(self.day.weekday() + 1) % 7,
                                    start_time=time(9), end_time=time(17))
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])

    def block(self, start, end, date=None):
        Unavailability.objects.create(staff_member=self.staff_member1, date=date or self.day,
                                      start_time=start, end_time=end)

    def snapshot(self):
        self.ar.refresh_from_db()
        self.pending.refresh_from_db()
        return ((self.ar.date, self.ar.start_time, self.ar.end_time, self.ar.staff_member_id),
                (self.pending.date, self.pending.start_time, self.pending.end_time, self.pending.staff_member_id,
                 self.pending.reschedule_status, self.pending.reason_for_rescheduling))

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_rejection_preserves_request_and_pending_history(self, notify):
        before = self.snapshot()
        self.block(time(9), time(12))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'no longer available', status_code=409)
        self.assertEqual(self.snapshot(), before)
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_contained_within_requested_time_rejected(self, notify):
        self.block(time(10, 15), time(10, 45))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_ending_at_requested_start_allowed(self, notify):
        self.block(time(9), time(10))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time), (self.day, time(10)))
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_on_other_date_allowed(self, notify):
        self.block(time(10), time(11), date=self.day + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual(self.ar.date, self.day)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_rejected_link_can_be_confirmed_once_block_removed(self, notify):
        self.block(time(10), time(11))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        Unavailability.objects.all().delete()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()
