from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.views import THANK_YOU_SESSION_KEY


class RescheduleConfirmationBlockedTimeTests(BaseTest):
    """Synthetic regression coverage for issue #2: confirming a pending reschedule into time the staff member
    blocked after the request was submitted."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.ar)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic rehearsal',
            reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])

    def block(self, start=time(10), end=time(11), staff=None, date=None):
        return Unavailability.objects.create(staff_member=staff or self.staff_member1, date=date or self.day,
                                             start_time=start, end_time=end, description='Synthetic block')

    @staticmethod
    def snapshot(obj):
        obj.refresh_from_db()
        return {field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields}

    def assert_rejected_without_side_effects(self, response, notify):
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(self.ar), self.request_before)
        self.assertEqual(self.snapshot(self.pending), self.history_before)
        self.assertEqual(self.snapshot(self.appointment), self.appointment_before)
        notify.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn(THANK_YOU_SESSION_KEY, self.client.session)
        self.assertEqual([m.level_tag for m in get_messages(response.wsgi_request)], [])

    def capture_before(self):
        self.request_before = self.snapshot(self.ar)
        self.history_before = self.snapshot(self.pending)
        self.appointment_before = self.snapshot(self.appointment)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_exact_block_rejected_and_every_field_preserved(self, notify):
        self.capture_before()
        self.block()
        response = self.client.get(self.url)
        self.assert_rejected_without_side_effects(response, notify)
        self.assertContains(response, 'no longer available', status_code=409)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_enclosing_block_rejected(self, notify):
        self.capture_before()
        self.block(time(9), time(12))
        self.assert_rejected_without_side_effects(self.client.get(self.url), notify)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_inside_slot_rejected(self, notify):
        self.capture_before()
        self.block(time(10, 15), time(10, 45))
        self.assert_rejected_without_side_effects(self.client.get(self.url), notify)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_overlapping_start_rejected(self, notify):
        self.capture_before()
        self.block(time(9, 30), time(10, 30))
        self.assert_rejected_without_side_effects(self.client.get(self.url), notify)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_ending_at_slot_start_allowed(self, notify):
        self.block(time(9), time(10))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time), (self.day, time(10)))
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_same_staff_block_on_other_date_allowed(self, notify):
        self.block(date=self.day + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual(self.ar.date, self.day)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_rejected_link_still_works_once_block_removed(self, notify):
        block = self.block()
        self.assertEqual(self.client.get(self.url).status_code, 409)
        block.delete()
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('appointment:default_thank_you', args=[self.appointment.id]),
                             fetch_redirect_response=False)
        self.ar.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time, self.ar.end_time), (self.day, time(10), time(11)))
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_expired_link_with_block_is_not_applied(self, notify):
        self.capture_before()
        self.block()
        with patch('appointment.models.AppointmentRescheduleHistory.still_valid', return_value=False):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(self.ar), self.request_before)
        self.assertEqual(self.snapshot(self.pending), self.history_before)
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_replay_after_confirmation_does_not_move_again(self, notify):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        after_first = self.snapshot(self.ar)
        self.block()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.snapshot(self.ar), after_first)
        notify.assert_called_once()
