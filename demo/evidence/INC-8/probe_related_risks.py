"""INC-8 related-risk probe (evidence only, not part of the normal suite).

Each probe removes a related record while a reschedule is pending (or before the reschedule is submitted) and
prints what the affected view did to the surviving rows. Assertions describe the desired behaviour, so a FAIL or
ERROR here is evidence of a defect, not a regression. Run explicitly (see README.md); `manage.py test appointment`
does not discover this file.
"""
from datetime import time, timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRequest, AppointmentRescheduleHistory
from appointment.tests.base.base_test import BaseTest


@patch('appointment.views.send_reschedule_confirmation_email')
@patch('appointment.views.notify_admin_about_reschedule')
class RelatedRiskProbe(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.appointment = self.create_appt_for_sm1(appointment_request=self.original)

    def make_pending(self):
        pending = AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=time(14), end_time=time(15),
            staff_member=self.staff_member1, reason_for_rescheduling='Synthetic probe', reschedule_status='pending')
        return pending, reverse('appointment:confirm_reschedule', args=[pending.id_request])

    def report(self, label, status):
        self.original.refresh_from_db()
        rows = list(AppointmentRescheduleHistory.objects.filter(appointment_request=self.original)
                    .values_list('reschedule_status', flat=True))
        print(f"\n[probe] {label}: {status}; request staff={self.original.staff_member_id} "
              f"date={self.original.date} start={self.original.start_time}; histories={rows}")
        return rows

    def get_status(self, method, url, data=None):
        try:
            return getattr(self.client, method)(url, data or {}).status_code
        except Exception as exc:  # noqa: BLE001 - the probe records the unhandled error type
            return f"unhandled {type(exc).__name__}"

    def test_confirm_after_appointment_deleted_issue_8(self, notify, send_email):
        pending, url = self.make_pending()
        self.appointment.delete()
        status = self.get_status('get', url)
        rows = self.report('issue #8: confirm after appointment deleted', status)
        self.original.refresh_from_db()
        self.assertEqual((self.original.date, self.original.start_time), (self.day - timedelta(days=1), time(9)))
        self.assertEqual(rows, ['pending'])
        self.assertEqual(status, 404)
        notify.assert_not_called()

    def test_submit_after_appointment_deleted(self, notify, send_email):
        self.appointment.delete()
        status = self.get_status('post', reverse('appointment:reschedule_appointment_submit'), {
            'appointment_request_id': self.original.id_request, 'date': self.day.isoformat(),
            'start_time': '14:00', 'end_time': '15:00', 'staff_member': self.staff_member1.id,
            'service': self.service1.id, 'reason_for_rescheduling': 'Synthetic probe'})
        rows = self.report('submit after appointment deleted', status)
        self.assertEqual(rows, [], 'a pending reschedule row was created for a deleted appointment')
        self.assertNotIsInstance(status, str)

    def test_confirm_after_client_user_deleted(self, notify, send_email):
        pending, url = self.make_pending()
        before = (self.original.date, self.original.start_time)
        self.users['client1'].delete()
        status = self.get_status('get', url)
        rows = self.report('confirm after client user deleted', status)
        self.assertNotIsInstance(status, str)
        if status != 302:
            self.original.refresh_from_db()
            self.assertEqual((self.original.date, self.original.start_time), before)
            self.assertEqual(rows, ['pending'])

    def test_confirm_after_target_staff_member_deleted(self, notify, send_email):
        pending, url = self.make_pending()
        self.staff_member1.delete()
        status = self.get_status('get', url)
        self.report('confirm after target staff member deleted', status)
        self.assertTrue(AppointmentRequest.objects.filter(pk=self.original.pk).exists())
        self.original.refresh_from_db()
        self.assertNotEqual(status, 302, 'confirmation succeeded with no staff member')
