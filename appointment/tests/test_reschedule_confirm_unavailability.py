"""Regression tests for INC-2: a still-valid reschedule confirmation must re-check staff unavailability."""
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import Appointment, AppointmentRequest, AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.views import THANK_YOU_SESSION_KEY


@patch('appointment.views.notify_admin_about_reschedule')
class ConfirmRescheduleUnavailabilityTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.ar)
        self.pending = self.make_pending(self.staff_member1)
        mail.outbox = []

    def make_pending(self, staff_member):
        AppointmentRescheduleHistory.objects.filter(appointment_request=self.ar).delete()
        pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=staff_member, reason_for_rescheduling='Synthetic rehearsal', reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[pending.id_request])
        return pending

    def block(self, start, end, staff=None, date=None):
        return Unavailability.objects.create(staff_member=staff or self.staff_member1, date=date or self.day,
                                             start_time=start, end_time=end, description='Synthetic block')

    def snapshot(self):
        return (list(AppointmentRequest.objects.filter(pk=self.ar.pk).values()),
                list(AppointmentRescheduleHistory.objects.filter(pk=self.pending.pk).values()),
                list(Appointment.objects.filter(pk=self.appointment.pk).values()))

    def assert_rejected_without_side_effects(self, notify, before):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        notify.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertNotIn(THANK_YOU_SESSION_KEY, self.client.session)
        self.assertEqual([m.level_tag for m in get_messages(response.wsgi_request)], [])
        return response

    def assert_confirmed(self, notify):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.ar.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time, self.ar.end_time),
                         (self.day, time(10), time(11)))
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()

    def test_rejection_preserves_records_and_sends_nothing(self, notify):
        self.block(time(10), time(11))
        response = self.assert_rejected_without_side_effects(notify, self.snapshot())
        self.assertIn('no longer available', response.content.decode())

    def test_block_enclosing_slot_rejected(self, notify):
        self.block(time(9, 30), time(11, 30))
        self.assert_rejected_without_side_effects(notify, self.snapshot())

    def test_block_inside_slot_rejected(self, notify):
        self.block(time(10, 15), time(10, 45))
        self.assert_rejected_without_side_effects(notify, self.snapshot())

    def test_block_overlapping_start_rejected(self, notify):
        self.block(time(9, 30), time(10, 1))
        self.assert_rejected_without_side_effects(notify, self.snapshot())

    def test_block_ending_at_start_allowed(self, notify):
        self.block(time(9), time(10))
        self.assert_confirmed(notify)

    def test_block_same_staff_other_date_allowed(self, notify):
        self.block(time(10), time(11), date=self.day + timedelta(days=1))
        self.assert_confirmed(notify)

    def test_block_for_new_staff_member_rejected(self, notify):
        self.pending = self.make_pending(self.staff_member2)
        self.block(time(10), time(11), staff=self.staff_member2)
        self.assert_rejected_without_side_effects(notify, self.snapshot())

    def test_block_for_previous_staff_member_does_not_reject_move_to_new_staff(self, notify):
        self.pending = self.make_pending(self.staff_member2)
        self.block(time(10), time(11), staff=self.staff_member1)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.ar.refresh_from_db()
        self.assertEqual(self.ar.staff_member, self.staff_member2)

    def test_rejected_link_replay_stays_rejected(self, notify):
        self.block(time(10), time(11))
        before = self.snapshot()
        self.assert_rejected_without_side_effects(notify, before)
        self.assert_rejected_without_side_effects(notify, before)

    def test_link_confirms_after_block_removed_within_window(self, notify):
        block = self.block(time(10), time(11))
        self.assert_rejected_without_side_effects(notify, self.snapshot())
        block.delete()
        self.assert_confirmed(notify)

    def test_expired_link_with_block_reports_expiry_without_mutation(self, notify):
        self.block(time(10), time(11))
        before = self.snapshot()
        with patch('appointment.models.AppointmentRescheduleHistory.still_valid', return_value=False):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(), before)
        notify.assert_not_called()

    def test_confirmed_link_replay_after_new_block_not_reapplied(self, notify):
        self.assert_confirmed(notify)
        self.block(time(10), time(11))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.ar.refresh_from_db()
        self.assertEqual((self.ar.date, self.ar.start_time), (self.day, time(10)))
        notify.assert_called_once()
