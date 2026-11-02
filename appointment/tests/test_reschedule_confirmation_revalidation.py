from datetime import time, timedelta
from unittest.mock import patch

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.utils.db_helpers import has_overlapping_unavailability


class RescheduleConfirmationRevalidationTests(BaseTest):
    """Confirmation must re-check current staff unavailability before mutating data (INC-2, synthetic data)."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reschedule_status='pending',
            reason_for_rescheduling='Synthetic rehearsal')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])

    def block(self, start, end, date=None):
        return Unavailability.objects.create(staff_member=self.staff_member1, date=date or self.day,
                                             start_time=start, end_time=end, description='Synthetic block')

    def pending_snapshot(self):
        self.pending.refresh_from_db()
        return (self.pending.date, self.pending.start_time, self.pending.end_time,
                self.pending.staff_member_id, self.pending.reschedule_status, self.pending.reason_for_rescheduling)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_rejection_preserves_pending_history_and_sends_no_mail(self, notify):
        before = self.pending_snapshot()
        self.block(time(10), time(11))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.pending_snapshot(), before)
        self.assertEqual(len(mail.outbox), 0)
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_link_confirms_after_block_is_removed(self, notify):
        blocker = self.block(time(10), time(11))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        blocker.delete()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.original.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time), (self.day, time(10)))
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_containing_and_contained_blocks_rejected(self, notify):
        for start, end in ((time(9), time(12)), (time(10, 15), time(10, 45)), (time(9, 30), time(10, 30))):
            with self.subTest(start=start, end=end):
                blocker = self.block(start, end)
                self.assertEqual(self.client.get(self.url).status_code, 409)
                blocker.delete()
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_ending_at_start_allowed(self, notify):
        self.block(time(9), time(10))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_same_staff_block_on_other_date_allowed(self, notify):
        self.block(time(10), time(11), date=self.day + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_helper_uses_half_open_intervals(self):
        self.block(time(10), time(11))
        sm = self.staff_member1
        self.assertTrue(has_overlapping_unavailability(self.day, time(10, 59), time(11, 30), sm))
        self.assertFalse(has_overlapping_unavailability(self.day, time(11), time(12), sm))
        self.assertFalse(has_overlapping_unavailability(self.day, time(9), time(10), sm))
        self.assertFalse(has_overlapping_unavailability(self.day, time(10), time(11), self.staff_member2))
