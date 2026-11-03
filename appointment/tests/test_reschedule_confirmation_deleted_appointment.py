from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.views import THANK_YOU_SESSION_KEY


class ConfirmRescheduleDeletedAppointmentTests(BaseTest):
    """INC-8: opening a reschedule link whose Appointment was deleted must not touch the surviving records."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(14), end_time=time(15),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic rehearsal',
            reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])
        mail.outbox = []

    @staticmethod
    def snapshot(obj):
        obj.refresh_from_db()
        return {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}

    def assert_rejected_without_side_effects(self, response, status, text, request_before, pending_before, notify):
        self.assertEqual(response.status_code, status)
        self.assertContains(response, text, status_code=status)
        self.assertEqual(self.snapshot(self.original), request_before)
        self.assertEqual(self.snapshot(self.pending), pending_before)
        notify.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertNotIn(THANK_YOU_SESSION_KEY, self.client.session)
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [])

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_deleted_appointment_rejected_without_changes(self, notify):
        self.appointment.delete()
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assert_rejected_without_side_effects(response, 404, 'no longer exists', request_before,
                                                  pending_before, notify)
        self.assertEqual(pending_before['reschedule_status'], 'pending')

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_reopening_link_after_deletion_still_rejected(self, notify):
        self.appointment.delete()
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        self.client.get(self.url)
        response = self.client.get(self.url)

        self.assert_rejected_without_side_effects(response, 404, 'no longer exists', request_before,
                                                  pending_before, notify)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_deleted_appointment_with_expired_link_reports_expiry(self, notify):
        self.appointment.delete()
        AppointmentRescheduleHistory.objects.filter(pk=self.pending.pk).update(
            created_at=timezone.now() - timedelta(seconds=301))
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assert_rejected_without_side_effects(response, 404, 'no longer valid', request_before,
                                                  pending_before, notify)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_deleted_appointment_with_blocked_time_rejected(self, notify):
        self.appointment.delete()
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(14), end_time=time(15))
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assertIn(response.status_code, (404, 409))
        self.assertEqual(self.snapshot(self.original), request_before)
        self.assertEqual(self.snapshot(self.pending), pending_before)
        notify.assert_not_called()
        self.assertNotIn(THANK_YOU_SESSION_KEY, self.client.session)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_existing_appointment_still_confirms(self, notify):
        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('appointment:default_thank_you', args=[self.appointment.id]),
                             fetch_redirect_response=False)
        self.original.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time, self.original.end_time),
                         (self.day, time(14), time(15)))
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        self.assertEqual(self.pending.date, self.day - timedelta(days=1))
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[2], self.users['client1'].get_full_name())
        self.assertEqual(self.client.session[THANK_YOU_SESSION_KEY], {str(self.appointment.id): True})

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_replay_after_confirmation_rejected(self, notify):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        request_after, pending_after = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(self.original), request_after)
        self.assertEqual(self.snapshot(self.pending), pending_after)
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_failed_history_write_rolls_back_request_move(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        with patch.object(AppointmentRescheduleHistory, 'save', side_effect=DatabaseError('synthetic failure')):
            with self.assertRaises(DatabaseError):
                self.client.get(self.url)

        self.assertEqual(self.snapshot(self.original), request_before)
        self.assertEqual(self.snapshot(self.pending), pending_before)
        notify.assert_not_called()
