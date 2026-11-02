"""INC-2 bounded related-risk probes (synthetic data only).

Not part of normal test discovery (lives outside ``appointment/`` and does not match ``test*.py``).
Each probe prints an OBSERVED line and never asserts, so it records behaviour rather than gating CI.
Run (from repo root, Python 3.12, demo-requirements.lock):

    DJANGO_SETTINGS_MODULE=appointments.demo_settings .venv/bin/python manage.py test \
        demo/evidence/INC-2 --pattern="probe_*.py" -v 2
"""
from datetime import time, timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from appointment.models import AppointmentRescheduleHistory, DayOff, Unavailability
from appointment.tests.base.base_test import BaseTest


class RelatedRiskProbes(BaseTest):
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=7)
        self.original = self.create_appt_request_for_sm1(date_=self.day - timedelta(days=1))
        self.create_appt_for_sm1(appointment_request=self.original)

    def pending(self, start=time(10), end=time(11)):
        return AppointmentRescheduleHistory.objects.create(
            appointment_request=self.original, date=self.day, start_time=start, end_time=end,
            staff_member=self.staff_member1, reschedule_status='pending')

    def confirm(self, arh):
        with patch('appointment.views.notify_admin_about_reschedule') as notify:
            status = self.client.get(reverse('appointment:confirm_reschedule', args=[arh.id_request])).status_code
        self.original.refresh_from_db()
        moved = (self.original.date, self.original.start_time) == (self.day, arh.start_time)
        return status, moved, notify.called

    def report(self, name, status, moved, notified):
        verdict = 'REPRODUCED' if moved else 'NOT REPRODUCED'
        print(f"\nOBSERVED {name}: status={status} moved={moved} notified={notified} -> {verdict}")

    def test_probe_day_off_added_after_request(self):
        arh = self.pending()
        DayOff.objects.create(staff_member=self.staff_member1, start_date=self.day, end_date=self.day,
                              description='Synthetic day off')
        self.report('R1 day-off added before confirmation', *self.confirm(arh))

    def test_probe_other_booking_added_after_request(self):
        arh = self.pending()
        other = self.create_appointment_request_(service=self.service1, staff_member=self.staff_member1,
                                                 date_=self.day, start_time=time(10), end_time=time(11))
        self.create_appointment_(user=self.users['client2'], appointment_request=other)
        self.report('R2 overlapping appointment booked before confirmation', *self.confirm(arh))

    def test_probe_submit_into_already_blocked_hour(self):
        Unavailability.objects.create(staff_member=self.staff_member1, date=self.day, start_time=time(10),
                                      end_time=time(11), description='Synthetic block')
        with patch('appointment.views.send_reschedule_confirmation_email') as send_email:
            status = self.client.post(reverse('appointment:reschedule_appointment_submit'), {
                'appointment_request_id': self.original.id_request, 'date': self.day.isoformat(),
                'start_time': '10:00', 'end_time': '11:00', 'service': self.service1.id,
                'staff_member': self.staff_member1.id, 'reason_for_rescheduling': 'Synthetic'}).status_code
        created = AppointmentRescheduleHistory.objects.filter(appointment_request=self.original).exists()
        verdict = 'REPRODUCED' if created and send_email.called else 'NOT REPRODUCED'
        print(f"\nOBSERVED R3 submit into already-blocked hour: status={status} pending_created={created} "
              f"email_sent={send_email.called} -> {verdict}")
