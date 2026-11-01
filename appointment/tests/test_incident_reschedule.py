from datetime import time, timedelta
from unittest.mock import patch
from django.urls import reverse
from django.utils import timezone
from appointment.models import AppointmentRescheduleHistory, Unavailability, WorkingHours
from appointment.services import get_available_slots_for_staff
from appointment.tests.base.base_test import BaseTest

class RescheduleIncidentTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.original)
        self.pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day,
            start_time=time(10), end_time=time(11), staff_member=self.staff_member1,
            reschedule_status='pending')
        self.url = reverse('appointment:confirm_reschedule', args=[self.pending.id_request])
        self.before = (self.original.date, self.original.start_time, self.original.end_time,
                       self.original.staff_member_id)
        WorkingHours.objects.create(staff_member=self.staff_member1,
            day_of_week=(self.day.weekday() + 1) % 7, start_time=time(9), end_time=time(17))

    def block(self, start=time(10), end=time(11), staff=None):
        return Unavailability.objects.create(staff_member=staff or self.staff_member1,
            date=self.day, start_time=start, end_time=end, description='Synthetic staff meeting')

    def test_slot_listing_hides_new_block(self):
        self.pending.delete()
        before = get_available_slots_for_staff(self.day, self.staff_member1,
            (self.day.weekday() + 1) % 7, service=self.service1)
        self.assertIn(time(10), [slot.time() for slot in before])
        self.block()
        slots = get_available_slots_for_staff(self.day, self.staff_member1,
            (self.day.weekday() + 1) % 7, service=self.service1)
        self.assertNotIn(time(10), [slot.time() for slot in slots])

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_confirmation_rejects_new_block_without_mutation(self, notify):
        self.block()
        response = self.client.get(self.url)
        self.original.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time, self.original.end_time,
                          self.original.staff_member_id), self.before,
                         'INCIDENT: confirmation moved appointment into newly blocked time')
        self.assertNotEqual(self.pending.reschedule_status, 'confirmed')
        self.assertIn(response.status_code, (400, 409))
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_unblocked_confirmation_still_works(self, notify):
        response = self.client.get(self.url)
        self.original.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.original.date, self.day)
        self.assertEqual(self.original.start_time, time(10))
        self.assertEqual(self.pending.reschedule_status, 'confirmed')
        notify.assert_called_once()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_partial_overlap_rejected(self, notify):
        self.block(time(10, 30), time(11, 30))
        response = self.client.get(self.url)
        self.original.refresh_from_db()
        self.assertEqual(self.original.date, self.before[0])
        self.assertIn(response.status_code, (400, 409))
        notify.assert_not_called()

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_adjacent_block_allowed(self, notify):
        self.block(time(11), time(12))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.original.refresh_from_db()
        self.assertEqual(self.original.date, self.day)

    @patch('appointment.views.notify_admin_about_reschedule')
    def test_other_staff_block_allowed(self, notify):
        self.block(staff=self.staff_member2)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.original.refresh_from_db()
        self.assertEqual(self.original.date, self.day)

    @patch('appointment.views.notify_admin_about_reschedule')
    @patch('appointment.views.send_reschedule_confirmation_email')
    def test_real_submit_then_block_then_confirm(self, send_email, notify):
        self.pending.delete()
        response = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
            'appointment_request_id': self.original.id_request,
            'date': self.day.isoformat(), 'start_time': '10:00', 'end_time': '11:00',
            'service': self.service1.id, 'staff_member': self.staff_member1.id,
            'reason_for_rescheduling': 'Synthetic incident rehearsal'})
        self.assertEqual(response.status_code, 200)
        send_email.assert_called_once()
        pending = AppointmentRescheduleHistory.objects.get(appointment_request=self.original)
        self.assertTrue(pending.still_valid())
        self.block()
        response = self.client.get(reverse('appointment:confirm_reschedule', args=[pending.id_request]))
        self.original.refresh_from_db()
        self.assertEqual(self.original.date, self.before[0])
        self.assertIn(response.status_code, (400, 409))
        notify.assert_not_called()
