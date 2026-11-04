"""INC-2 bounded related-risk probes (synthetic data only).

Not part of normal test discovery (lives outside appointment/ and uses a probe_*.py name). Each probe records the
*observed* behaviour and prints REPRODUCED / NOT REPRODUCED; probes do not assert the desired behaviour.

Run: DJANGO_SETTINGS_MODULE=appointments.demo_settings python manage.py test demo/evidence/INC-2 \
         --pattern="probe_*.py" -v 2
"""
from datetime import time, timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from appointment.models import Appointment, AppointmentRescheduleHistory, DayOff, Unavailability
from appointment.tests.base.base_test import BaseTest


def report(name, reproduced, detail):
    print(f"\nPROBE {name}: {'REPRODUCED' if reproduced else 'NOT REPRODUCED'} - {detail}")


@patch('appointment.views.notify_admin_about_reschedule')
class RelatedRiskProbes(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.ar = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.ar)

    def pending(self, staff=None):
        return AppointmentRescheduleHistory.objects.create(
            appointment_request=self.ar, date=self.day, start_time=time(10), end_time=time(11),
            staff_member=staff or self.staff_member1, reschedule_status='pending')

    def confirm(self, pending):
        response = self.client.get(reverse('appointment:confirm_reschedule', args=[pending.id_request]))
        self.ar.refresh_from_db()
        return response.status_code, self.ar.date == self.day

    def test_probe_day_off_added_after_request(self, notify):
        p = self.pending()
        DayOff.objects.create(staff_member=self.staff_member1, start_date=self.day, end_date=self.day)
        status, moved = self.confirm(p)
        report('day_off_after_request', moved, f'status={status} moved_into_day_off={moved}')

    def test_probe_other_booking_overlaps(self, notify):
        p = self.pending()
        other = self.create_appt_request_for_sm1(date_=self.day, start_time=time(10), end_time=time(11))
        Appointment.objects.create(client=self.users['client2'], appointment_request=other)
        status, moved = self.confirm(p)
        report('other_booking_overlap', moved, f'status={status} moved_onto_existing_booking={moved}')

    @patch('appointment.views.send_reschedule_confirmation_email')
    def test_probe_submit_into_already_blocked_hour(self, send_confirmation, notify):
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        response = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
            'appointment_request_id': self.ar.id_request, 'date': self.day.isoformat(),
            'start_time': '10:00', 'end_time': '11:00', 'service': self.service1.id,
            'staff_member': self.staff_member1.id, 'reason_for_rescheduling': 'Synthetic probe'})
        created = AppointmentRescheduleHistory.objects.filter(appointment_request=self.ar).exists()
        link_sent = send_confirmation.called
        report('submit_into_blocked_hour', created and link_sent,
               f'status={response.status_code} pending_created={created} confirmation_link_sent={link_sent}')

    def test_probe_pending_without_staff_member_skips_check(self, notify):
        p = self.pending()
        AppointmentRescheduleHistory.objects.filter(pk=p.pk).update(staff_member=None)
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        status, moved = self.confirm(p)
        self.ar.refresh_from_db()
        report('pending_staff_member_null', moved,
               f'status={status} moved={moved} staff_member_cleared={self.ar.staff_member_id is None}')

    def test_probe_rejected_request_consumes_reschedule_limit(self, notify):
        self.service1.reschedule_limit = 1
        self.service1.allow_rescheduling = True
        self.service1.save()
        p = self.pending()
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day,
                                      start_time=time(10), end_time=time(11))
        status, _ = self.confirm(p)
        from appointment.utils.db_helpers import can_appointment_be_rescheduled
        retry_flag = 'True' if can_appointment_be_rescheduled(self.ar) else 'False'
        report('rejected_request_counts_toward_limit', status == 409 and retry_flag == 'False',
               f'confirm_status={status} can_reschedule_again_within_5_min={retry_flag}')
