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
            'max_non_teaching_load': 90,
        })
        self.department = self.env['hr.department'].create({
            'name': 'Workload Profile Department',
            'company_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Workload Profile Employee',
            'department_id': self.department.id,
            'company_id': self.env.company.id,
            'work_contact_id': partner.id,
        })
        self.employee = employee
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
                'aps_teacher_id': (self.teacher.id, self.teacher.display_name),
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': False,
                'weighted_minutes': 120.0,
            },
            {
                'aps_teacher_id': (self.teacher.id, self.teacher.display_name),
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': True,
                'weighted_minutes': 45.0,
            },
            {
                'aps_teacher_id': (self.teacher.id, self.teacher.display_name),
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
        self.assertEqual(profile['max_non_teaching_load'], 90)
        self.assertAlmostEqual(profile['teaching_load_percentage'], 66.67, places=2)
        self.assertAlmostEqual(profile['non_teaching_load_percentage'], 83.33, places=2)
        self.assertEqual(profile['remaining_minutes'], 60)
        self.assertEqual(profile['over_limit_minutes'], 0)

    def test_profile_handles_no_workload_rows(self):
        self.teacher.max_non_teaching_load = 0
        profile = self._profile_for_rows([])

        self.assertEqual(profile['subjects'], [])
        self.assertEqual(profile['total_minutes'], 0)
        self.assertEqual(profile['teaching_load_percentage'], 0)
        self.assertIsNone(profile['non_teaching_load_percentage'])
        self.assertEqual(profile['remaining_minutes'], 180)
        self.assertEqual(profile['over_limit_minutes'], 0)

    def test_profile_finds_department_from_employee_contact(self):
        profile = self._profile_for_rows([])

        self.assertEqual(profile['department_name'], 'Workload Profile Department')

    def test_employee_phone_updates_matching_teacher_contact(self):
        self.employee.write({'mobile_phone': '555-0100'})

        self.assertEqual(self.teacher.partner_id.mobile, '555-0100')

    def test_roles_are_read_from_current_contract(self):
        jobs = self.env['hr.job'].create([
            {
                'name': f'Workload Profile Role {number}',
                'company_id': self.env.company.id,
            }
            for number in range(1, 4)
        ])
        self.employee.job_id = jobs[0]
        contract = self.env['hr.contract'].create({
            'name': 'Workload Profile Contract',
            'employee_id': self.employee.id,
            'wage': 1000,
            'state': 'open',
            'fte1': 0.8,
            'job2_id': jobs[1].id,
            'department2_id': self.department.id,
            'fte2': 0.5,
            'job3_id': jobs[2].id,
            'department3_id': self.department.id,
            'fte3': 0.25,
        })
        self.employee.contract_id = contract

        self.assertEqual(self.teacher.role_job1_id, jobs[0])
        self.assertEqual(self.teacher.role_fte1, 0.8)
        self.assertEqual(self.teacher.role_department1_id, self.department)
        self.assertEqual(self.teacher.role_job2_id, jobs[1])
        self.assertEqual(self.teacher.role_fte2, 0.5)
        self.assertEqual(self.teacher.role_department2_id, self.department)
        self.assertEqual(self.teacher.role_job3_id, jobs[2])
        self.assertEqual(self.teacher.role_fte3, 0.25)
        self.assertEqual(self.teacher.role_department3_id, self.department)

    def test_roles_are_empty_without_a_current_contract(self):
        self.assertFalse(self.teacher.role_job1_id)
        self.assertFalse(self.teacher.role_job2_id)
        self.assertFalse(self.teacher.role_job3_id)

    def test_stored_load_percentages_match_live_timetable_and_maximums(self):
        rows = [
            {
                'aps_teacher_id': (self.teacher.id, self.teacher.display_name),
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': False,
                'weighted_minutes': 120.0,
            },
            {
                'aps_teacher_id': (self.teacher.id, self.teacher.display_name),
                'subject_id': (self.timetable_subject.id, self.timetable_subject.name),
                'subject_name': 'Math',
                'is_assistant': True,
                'weighted_minutes': 75.0,
            },
        ]
        with patch.object(type(self.workload_model), 'read_group', return_value=rows):
            self.teacher.write({
                'teaching_load': 300,
                'non_teaching_load': 5,
            })

            self.assertAlmostEqual(self.teacher.teaching_load_percentage, 66.67, places=2)
            self.assertAlmostEqual(self.teacher.non_teaching_load_percentage, 83.33, places=2)

            profile = self._profile_for_rows(rows)
            self.assertEqual(
                self.teacher.teaching_load_percentage,
                profile['teaching_load_percentage'],
            )
            self.assertEqual(
                self.teacher.non_teaching_load_percentage,
                profile['non_teaching_load_percentage'],
            )

            self.teacher.write({
                'max_load': 0,
                'max_non_teaching_load': 0,
            })
            self.assertEqual(self.teacher.teaching_load_percentage, -0.01)
            self.assertEqual(self.teacher.non_teaching_load_percentage, -0.01)

    def test_open_profile_returns_client_action_for_teacher(self):
        action = self.teacher.action_open_workload_profile()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'aps_teacher_workload_profile')
        self.assertEqual(action['params'], {'teacher_id': self.teacher.id})
