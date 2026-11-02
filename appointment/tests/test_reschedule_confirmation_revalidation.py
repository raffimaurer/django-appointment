from datetime import time, timedelta
from unittest.mock import patch

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, Unavailability
from appointment.tests.base.base_test import BaseTest
from appointment.utils.db_helpers import has_overlapping_unavailability


class HasOverlappingUnavailabilityTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))

    def overlaps(self, start, end, day=None, staff=None):
        return has_overlapping_unavailability(day or self.day, start, end, staff or self.staff_member1)

    def test_half_open_interval_semantics(self):
        self.assertTrue(self.overlaps(time(10), time(11)))
        self.assertTrue(self.overlaps(time(9, 30), time(10, 30)))
        self.assertTrue(self.overlaps(time(10, 15), time(10, 45)))
        self.assertTrue(self.overlaps(time(9), time(12)))
        self.assertFalse(self.overlaps(time(9), time(10)))
        self.assertFalse(self.overlaps(time(11), time(12)))

    def test_scoped_to_staff_member_and_date(self):
        self.assertFalse(self.overlaps(time(10), time(11), staff=self.staff_member2))
        self.assertFalse(self.overlaps(time(10), time(11), day=self.day + timedelta(days=1)))

    def test_missing_staff_member_is_not_a_conflict(self):
        self.assertFalse(has_overlapping_unavailability(self.day, time(10), time(11), None))


class ConfirmRescheduleRevalidationTests(BaseTest):
    """Confirmation must re-check unavailability added after the reschedule was requested."""

    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic rehearsal',
            reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])

    def block(self, start=time(10), end=time(11), day=None):
        return Unavailability.objects.create(staff_member=self.staff_member1, date=day or self.day,
                                             start_time=start, end_time=end)

    @staticmethod
    def snapshot(obj):
        obj.refresh_from_db()
        return {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}

    def test_rejection_preserves_all_fields_and_sends_no_email(self):
        request_before = self.snapshot(self.original)
        pending_before = self.snapshot(self.pending)
        self.block(time(9), time(12))
        mail.outbox = []

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'no longer available', status_code=409)
        self.assertEqual(self.snapshot(self.original), request_before)
        self.assertEqual(self.snapshot(self.pending), pending_before)
        self.assertEqual(mail.outbox, [])

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_block_ending_at_requested_start_allowed(self, notify):
        self.block(time(9), time(10))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_same_staff_block_on_other_date_allowed(self, notify):
        self.block(day=self.day + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.original.refresh_from_db()
        self.assertEqual(self.original.date, self.day)
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_link_usable_again_once_block_removed(self, notify):
        blocker = self.block()
        self.assertEqual(self.client.get(self.url).status_code, 409)
        blocker.delete()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.original.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time), (self.day, time(10)))
        notify.assert_called_once()
