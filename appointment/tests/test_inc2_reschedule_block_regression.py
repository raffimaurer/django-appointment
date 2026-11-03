"""Regression coverage for INC-2: a still-valid reschedule confirmation must re-check
staff unavailability at commit time. Synthetic data only."""
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability, WorkingHours
from appointment.tests.base.base_test import BaseTest
from appointment.views import THANK_YOU_SESSION_KEY


class ConfirmRescheduleBlockedTimeTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.ar)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reschedule_status='pending',
            reason_for_rescheduling='Synthetic rehearsal')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])
        WorkingHours.objects.create(staff_member=self.staff_member1,
                                    day_of_week=(self.day.weekday() + 1) % 7, start_time=time(9),
                                    end_time=time(17))
        self.ar_before = self.ar_snapshot()
        self.pending_before = self.pending_snapshot()

    def ar_snapshot(self):
        self.ar.refresh_from_db()
        return self.ar.date, self.ar.start_time, self.ar.end_time, self.ar.staff_member_id

    def pending_snapshot(self):
        self.pending.refresh_from_db()
        p = self.pending
        return (p.date, p.start_time, p.end_time, p.staff_member_id, p.reschedule_status,
                p.reason_for_rescheduling)

    def block(self, start=time(10), end=time(11), staff=None, date_=None):
        return Unavailability.objects.create(staff_member=staff or self.staff_member1, date=date_ or self.day,
                                             start_time=start, end_time=end, description='Synthetic block')

    def assert_rejected_without_side_effects(self, response):
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'no longer available', status_code=409)
        self.assertEqual(self.ar_snapshot(), self.ar_before)
        self.assertEqual(self.pending_snapshot(), self.pending_before)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn(str(self.appointment.id), self.client.session.get(THANK_YOU_SESSION_KEY, {}))
        self.assertEqual([m for m in get_messages(response.wsgi_request) if m.level_tag == 'success'], [])

    def assert_confirmed(self, response, start=time(10)):
        self.assertEqual(response.status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time), (self.day, start))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        self.assertIn(str(self.appointment.id), self.client.session.get(THANK_YOU_SESSION_KEY, {}))

    def test_exact_block_rejected_without_side_effects(self):
        self.block()
        self.assert_rejected_without_side_effects(self.client.get(self.url))

    def test_block_containing_slot_rejected(self):
        self.block(time(9), time(12))
        self.assert_rejected_without_side_effects(self.client.get(self.url))

    def test_block_inside_slot_rejected(self):
        self.block(time(10, 15), time(10, 45))
        self.assert_rejected_without_side_effects(self.client.get(self.url))

    def test_block_overlapping_start_rejected(self):
        self.block(time(9, 30), time(10, 30))
        self.assert_rejected_without_side_effects(self.client.get(self.url))

    def test_unblocked_confirmation_sends_notification(self):
        # Positive control: proves the no-email assertion above is meaningful.
        self.assert_confirmed(self.client.get(self.url))
        self.assertGreater(len(mail.outbox), 0)

    def test_adjacent_block_before_allowed(self):
        self.block(time(9), time(10))
        self.assert_confirmed(self.client.get(self.url))

    def test_same_staff_other_date_block_allowed(self):
        self.block(date_=self.day + timedelta(days=1))
        self.assert_confirmed(self.client.get(self.url))

    def test_block_on_original_slot_does_not_reject(self):
        self.block(self.ar_before[1], self.ar_before[2], date_=self.ar_before[0])
        self.assert_confirmed(self.client.get(self.url))

    def test_rejected_link_confirms_after_block_removed(self):
        unavailability = self.block()
        self.assert_rejected_without_side_effects(self.client.get(self.url))
        unavailability.delete()
        self.assert_confirmed(self.client.get(self.url))

    def test_expired_link_with_block_not_applied(self):
        self.block()
        AppointmentRescheduleHistory.objects.filter(pk=self.pending.pk).update(
            created_at=timezone.now() - timedelta(minutes=6))
        self.pending_before = self.pending_snapshot()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.ar_snapshot(), self.ar_before)
        self.assertEqual(self.pending_snapshot(), self.pending_before)
        self.assertEqual(len(mail.outbox), 0)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_confirmed_link_replay_after_block_not_applied(self, notify):
        self.assert_confirmed(self.client.get(self.url))
        self.block()
        ar_after_first, pending_after_first = self.ar_snapshot(), self.pending_snapshot()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.ar_snapshot(), ar_after_first)
        self.assertEqual(self.pending_snapshot(), pending_after_first)
        notify.assert_called_once()
