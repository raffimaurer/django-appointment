"""INC-8 deleted-appointment probes (evidence only, not part of the normal suite).

Each probe prints the observed state as an ``OBSERVED`` line, then asserts the desired behaviour. A failing
assertion is the evidence for a defect. Run it explicitly (see README.md). ``manage.py test appointment`` does
not discover this file. Synthetic data only; no confirmation IDs are printed.
"""
from datetime import time, timedelta
from unittest.mock import patch

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory
from appointment.tests.base.base_test import BaseTest


@patch('appointment.views.send_reschedule_confirmation_email')
@patch('appointment.views.notify_admin_about_reschedule')
class DeletedAppointmentProbe(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.original)
        self.client = Client(raise_request_exception=False)

    def pending(self, staff=None):
        return AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=staff or self.staff_member1, reason_for_rescheduling='Synthetic probe',
            reschedule_status='pending')

    def confirm(self, history):
        return self.client.get(reverse('appointment:confirm_reschedule', args=[history.id_request]))

    def test_issue_confirm_after_appointment_deleted(self, notify, send_email):
        history = self.pending()
        self.appointment.delete()
        response = self.confirm(history)
        self.original.refresh_from_db()
        history.refresh_from_db()
        moved = (self.original.date, self.original.start_time) == (self.day, time(10))
        print(f"\nOBSERVED issue: status={response.status_code} request_moved={moved} "
              f"history_status={history.reschedule_status} notify_calls={notify.call_count}")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(moved)
        self.assertEqual(history.reschedule_status, 'pending')

    def test_related_submit_after_appointment_deleted(self, notify, send_email):
        self.appointment.delete()
        before = AppointmentRescheduleHistory.objects.count()
        response = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
            'appointment_request_id': self.original.id_request, 'date': self.day.isoformat(),
            'start_time': '10:00', 'end_time': '11:00', 'staff_member': self.staff_member1.id,
            'service': self.service1.id, 'reason_for_rescheduling': 'Synthetic probe'})
        created = AppointmentRescheduleHistory.objects.count() - before
        print(f"\nOBSERVED submit: status={response.status_code} histories_created={created} "
              f"emails_sent={send_email.call_count}")
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(created, 0)

    def test_related_confirm_after_target_staff_deleted(self, notify, send_email):
        other_staff = self.staff_member2
        history = self.pending(staff=other_staff)
        other_staff.delete()
        response = self.confirm(history)
        self.original.refresh_from_db()
        history.refresh_from_db()
        print(f"\nOBSERVED staff-deleted: status={response.status_code} "
              f"request_staff_is_none={self.original.staff_member_id is None} "
              f"history_status={history.reschedule_status} notify_calls={notify.call_count}")
        self.assertIsNotNone(self.original.staff_member_id)
