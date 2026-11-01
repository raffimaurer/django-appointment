from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.utils.db_helpers import staff_unavailability_overlaps

PENDING_FIELDS = ('date', 'start_time', 'end_time', 'staff_member_id', 'reschedule_status', 'id_request',
                  'appointment_request_id', 'reason_for_rescheduling', 'created_at')
REQUEST_FIELDS = ('date', 'start_time', 'end_time', 'staff_member_id', 'service_id')


class StaffUnavailabilityOverlapsTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))

    def overlaps(self, start, end, staff=None, day=None):
        return staff_unavailability_overlaps(staff or self.staff_member1, day or self.day, start, end)

    def test_half_open_boundaries(self):
        cases = [
            (time(9), time(10), False),  # ends exactly at block start
            (time(11), time(12), False),  # starts exactly at block end
            (time(10), time(11), True),  # identical
            (time(9, 30), time(10, 30), True),  # overlaps block start
            (time(10, 30), time(11, 30), True),  # overlaps block end
            (time(10, 15), time(10, 45), True),  # inside block
            (time(9), time(12), True),  # contains block
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end):
                self.assertEqual(self.overlaps(start, end), expected)

    def test_scoped_to_staff_and_date(self):
        self.assertFalse(self.overlaps(time(10), time(11), staff=self.staff_member2))
        self.assertFalse(self.overlaps(time(10), time(11), day=self.day + timedelta(days=1)))


class ConfirmRescheduleUnavailabilityGuardTests(BaseTest):
    """Complements test_incident_reschedule with containment, boundary, date, expiry and replay coverage."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.ar)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reschedule_status='pending', reason_for_rescheduling='Synthetic')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])
        self.ar_before = self.snapshot(self.ar, REQUEST_FIELDS)
        self.pending_before = self.snapshot(self.pending, PENDING_FIELDS)

    @staticmethod
    def snapshot(obj, fields):
        obj.refresh_from_db()
        return {f: getattr(obj, f) for f in fields}

    def block(self, start, end, day=None):
        return Unavailability.objects.create(staff_member=self.staff_member1, date=day or self.day,
                                             start_time=start, end_time=end, description='Synthetic block')

    def assert_unchanged(self):
        self.assertEqual(self.snapshot(self.ar, REQUEST_FIELDS), self.ar_before)
        self.assertEqual(self.snapshot(self.pending, PENDING_FIELDS), self.pending_before)
        self.assertEqual(AppointmentRescheduleHistory.objects.filter(appointment_request=self.ar).count(), 1)

    def assert_moved(self):
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time, self.ar.end_time), (self.day, time(10), time(11)))

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_containing_block_rejected_without_side_effects(self, notify):
        self.block(time(9, 30), time(11, 30))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'no longer available', status_code=409)
        self.assert_unchanged()
        notify.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertFalse(any(m.level_tag == 'success' for m in get_messages(response.wsgi_request)))

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_inside_slot_rejected(self, notify):
        self.block(time(10, 15), time(10, 45))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assert_unchanged()
        notify.assert_not_called()

    def test_rejection_sends_no_email_unmocked(self):
        self.block(time(10), time(11))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(mail.outbox, [])
        self.assert_unchanged()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_adjacent_block_before_allowed(self, notify):
        self.block(time(9), time(10))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assert_moved()
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_on_different_date_allowed(self, notify):
        self.block(time(10), time(11), day=self.day + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assert_moved()
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_expired_link_rejected_without_mutation(self, notify):
        AppointmentRescheduleHistory.objects.filter(pk=self.pending.pk).update(
            created_at=timezone.now() - timedelta(minutes=6))
        self.pending_before = self.snapshot(self.pending, PENDING_FIELDS)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assert_unchanged()
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_replay_after_success_rejected(self, notify):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assert_moved()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assert_moved()
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_replay_after_rejection_stays_rejected_while_blocked(self, notify):
        blocker = self.block(time(10), time(11))
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assert_unchanged()
        notify.assert_not_called()
        # Pending request is untouched, so it can still be confirmed inside its validity window once the block is gone.
        blocker.delete()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assert_moved()
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_rejection_log_omits_confirmation_token(self, notify):
        self.block(time(10), time(11))
        with self.assertLogs('appointment.views', level='WARNING') as logs:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        rejection_logs = [line for line in logs.output if 'rejected' in line]
        self.assertEqual(len(rejection_logs), 1)
        self.assertIn(f"Reschedule {self.pending.pk} rejected", rejection_logs[0])
        for line in logs.output:
            self.assertNotIn(self.pending.id_request, line)
