from datetime import time, timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.views import THANK_YOU_SESSION_KEY


@patch('appointment.views.notify_admin_about_reschedule')
class ConfirmRescheduleMissingAppointmentTests(BaseTest):
    """A confirmation must not mutate or notify when its Appointment has been deleted (INC-8)."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic rehearsal',
            reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])
        self.client = Client(raise_request_exception=False)
        mail.outbox = []

    @staticmethod
    def snapshot(obj):
        obj.refresh_from_db()
        return {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}

    def assert_unchanged(self, request_before, pending_before, notify):
        self.assertEqual(self.snapshot(self.original), request_before)
        self.assertEqual(self.snapshot(self.pending), pending_before)
        notify.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertNotIn(THANK_YOU_SESSION_KEY, self.client.session)

    def test_deleted_appointment_rejected_without_side_effects(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)
        self.appointment.delete()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'no longer exists', status_code=404)
        self.assertNotContains(response, 'rescheduled successfully', status_code=404)
        self.assert_unchanged(request_before, pending_before, notify)

    def test_deleted_appointment_rejected_even_when_slot_is_blocked(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)
        self.appointment.delete()
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))

        response = self.client.get(self.url)

        self.assertIn(response.status_code, (404, 409))
        self.assert_unchanged(request_before, pending_before, notify)

    def test_deleted_appointment_link_stays_rejected_on_retry(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)
        self.appointment.delete()

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assert_unchanged(request_before, pending_before, notify)

    def test_normal_confirmation_still_moves_and_notifies_once(self, notify):
        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('appointment:default_thank_you', args=[self.appointment.id]),
                             fetch_redirect_response=False)
        self.original.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time), (self.day, time(10)))
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()
        self.assertEqual(self.client.session[THANK_YOU_SESSION_KEY], {str(self.appointment.id): True})

    def test_replayed_confirmation_rejected_without_second_notification(self, notify):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        request_after, pending_after = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.snapshot(self.original), request_after)
        self.assertEqual(self.snapshot(self.pending), pending_after)
        notify.assert_called_once()

    def test_expired_link_rejected_without_side_effects(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)
        AppointmentRescheduleHistory.objects.filter(pk=self.pending.pk).update(
            created_at=timezone.now() - timedelta(minutes=6))
        pending_before = self.snapshot(self.pending)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'no longer valid', status_code=404)
        self.assert_unchanged(request_before, pending_before, notify)

    def test_unknown_link_rejected_without_side_effects(self, notify):
        request_before, pending_before = self.snapshot(self.original), self.snapshot(self.pending)

        response = self.client.get(reverse('appointment:confirm_reschedule', args=['unknown-synthetic-id']))

        self.assertEqual(response.status_code, 404)
        self.assert_unchanged(request_before, pending_before, notify)
