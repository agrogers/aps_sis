import base64
import io
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from PIL import Image


class TestTeacherWorkloadProfile(TransactionCase):

    def setUp(self):
        super().setUp()
        partner = self.env['res.partner'].create({'name': 'Workload Profile Teacher'})
        self.teacher = self.env['aps.teacher'].create({
            'partner_id': partner.id,
            'max_load': 180,
        })
        department = self.env['hr.department'].create({
            'name': 'Workload Profile Department',
            'company_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Workload Profile Employee',
            'department_id': department.id,
            'company_id': self.env.company.id,
        })
        self.teacher.emp_id = employee
        self.workload_model = self.env['asctt.teacher.workload']
        category = self.env['aps.subject.category'].create({
            'name': 'Workload Icon Category',
            'color_rgb': '#3478c8',
        })
        image_buffer = io.BytesIO()
        Image.new('RGB', (2, 2), color='teal').save(image_buffer, format='PNG')
        category.icon = base64.b64encode(image_buffer.getvalue())
        self.timetable_subject = self.env['asctt.subject'].create({
            'name': 'Math',
            'aps_subject_category_id': category.id,
        })

    def _profile_for_rows(self, rows):
        with patch.object(type(self.workload_model), 'read_group', return_value=rows):
            return self.teacher.get_timetable_workload_profile()

    def test_profile_groups_lead_assistant_and_supervision_minutes(self):
        self.assertTrue(self.timetable_subject.aps_subject_category_id.icon)
        profile = self._profile_for_rows([
            {
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': False,
                'weighted_minutes': 120.0,
            },
            {
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': True,
                'weighted_minutes': 45.0,
            },
            {
                'subject_id': False,
                'subject_name': 'Supervision',
                'is_assistant': True,
                'weighted_minutes': 30.0,
            },
        ])

        self.assertEqual(profile['teacher_name'], 'Workload Profile Teacher')
        self.assertEqual(profile['department_name'], 'Workload Profile Department')
        self.assertEqual(profile['subjects'], [
            {
                'name': 'Math',
                'icon_url': f'/web/image/aps.subject.category/{self.timetable_subject.aps_subject_category_id.id}/icon',
                'category_color': '#3478c8',
                'lead_minutes': 120.0,
                'assistant_minutes': 45.0,
            },
            {
                'name': 'Supervision',
                'icon_url': '',
                'category_color': '',
                'lead_minutes': 0.0,
                'assistant_minutes': 30.0,
            },
        ])
        self.assertEqual(profile['lead_total'], 120.0)
        self.assertEqual(profile['assistant_total'], 75.0)
        self.assertEqual(profile['total_minutes'], 195.0)
        self.assertEqual(profile['max_load'], 180)
        self.assertEqual(profile['remaining_minutes'], 60)
        self.assertEqual(profile['over_limit_minutes'], 15.0)

    def test_profile_handles_no_workload_rows(self):
        profile = self._profile_for_rows([])

        self.assertEqual(profile['subjects'], [])
        self.assertEqual(profile['total_minutes'], 0)
        self.assertEqual(profile['remaining_minutes'], 180)
        self.assertEqual(profile['over_limit_minutes'], 0)

    def test_open_profile_returns_client_action_for_teacher(self):
        action = self.teacher.action_open_workload_profile()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'aps_teacher_workload_profile')
        self.assertEqual(action['params'], {'teacher_id': self.teacher.id})
