import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from PIL import Image


class TestDashboardDataFilters(TransactionCase):

    def setUp(self):
        super().setUp()

        self.current_year = self.env['aps.academic.year'].create({
            'name': 'AY Current',
            'short_name': 'AYC',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'is_current': True,
        })
        self.old_year = self.env['aps.academic.year'].create({
            'name': 'AY Old',
            'short_name': 'AYO',
            'start_date': '2025-01-01',
            'end_date': '2025-12-31',
            'is_current': False,
        })

        category = self.env['aps.subject.category'].create({'name': 'Math'})
        self.category = category
        self.subject = self.env['aps.subject'].create({
            'name': 'Algebra',
            'category_id': category.id,
        })

        self.class_a = self.env['aps.class'].create({
            'name': 'Class A',
            'subject_id': self.subject.id,
            'identifier': 'A',
            'academic_year_id': self.current_year.id,
        })
        self.class_b = self.env['aps.class'].create({
            'name': 'Class B',
            'subject_id': self.subject.id,
            'identifier': 'B',
            'academic_year_id': self.current_year.id,
        })
        self.class_no_submission = self.env['aps.class'].create({
            'name': 'Class C',
            'subject_id': self.subject.id,
            'identifier': 'C',
            'academic_year_id': self.current_year.id,
        })
        self.class_old = self.env['aps.class'].create({
            'name': 'Class D',
            'subject_id': self.subject.id,
            'identifier': 'D',
            'academic_year_id': self.old_year.id,
        })

        self.partner_a = self.env['res.partner'].create({'name': 'Student A', 'is_student': True})
        self.partner_b = self.env['res.partner'].create({'name': 'Student B', 'is_student': True})
        self.partner_c = self.env['res.partner'].create({'name': 'Student C', 'is_student': True})
        self.partner_d = self.env['res.partner'].create({'name': 'Student D', 'is_student': True})

        self.student_a = self.env['aps.student'].search(
            [('partner_id', '=', self.partner_a.id)], limit=1
        )
        self.student_b = self.env['aps.student'].search(
            [('partner_id', '=', self.partner_b.id)], limit=1
        )
        self.student_c = self.env['aps.student'].search(
            [('partner_id', '=', self.partner_c.id)], limit=1
        )
        self.student_d = self.env['aps.student'].search(
            [('partner_id', '=', self.partner_d.id)], limit=1
        )

        self.env['aps.student.class'].create({
            'student_id': self.student_a.id,
            'class_id': self.class_a.id,
            'state': 'enrolled',
        })
        self.env['aps.student.class'].create({
            'student_id': self.student_b.id,
            'class_id': self.class_b.id,
            'state': 'enrolled',
        })
        self.env['aps.student.class'].create({
            'student_id': self.student_c.id,
            'class_id': self.class_a.id,
            'state': 'withdrawn',
        })
        self.env['aps.student.class'].create({
            'student_id': self.student_d.id,
            'class_id': self.class_no_submission.id,
            'state': 'enrolled',
        })
        self.env['aps.student.class'].create({
            'student_id': self.student_c.id,
            'class_id': self.class_old.id,
            'state': 'enrolled',
        })

        resource = self.env['aps.resources'].create({
            'name': 'Dashboard Filter Resource',
            'subjects': [(6, 0, self.subject.ids)],
        })

        task_a = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': self.partner_a.id,
        })
        task_b = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': self.partner_b.id,
        })
        task_c = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': self.partner_c.id,
        })

        self.env['aps.resource.submission'].create({
            'task_id': task_a.id,
            'submission_name': 'Sub A',
            'date_assigned': fields.Date.today(),
        })
        self.env['aps.resource.submission'].create({
            'task_id': task_b.id,
            'submission_name': 'Sub B',
            'date_assigned': fields.Date.today(),
        })
        self.env['aps.resource.submission'].create({
            'task_id': task_c.id,
            'submission_name': 'Sub C',
            'date_assigned': fields.Date.today(),
        })

        # Ensure computed active flags are updated for test lookups.
        self.env['aps.resource.submission'].search([])._compute_submission_active()

    def test_leaderboard_avatar_maps_include_saved_user_avatar(self):
        image_buffer = io.BytesIO()
        Image.new('RGB', (24, 16), (35, 125, 90)).save(image_buffer, format='PNG')
        avatar_binary = base64.b64encode(image_buffer.getvalue()).decode('ascii')
        self.partner_a.image_1920 = avatar_binary

        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': self.partner_a.name,
            'login': f'dashboard_avatar_test_{self.partner_a.id}',
            'partner_id': self.partner_a.id,
        })
        user.write({'avatar_image': avatar_binary})

        avatar_map, avatar_image_map, image_map = (
            self.env['aps.resource.submission']._get_avatar_and_image_maps([self.partner_a.id])
        )

        self.assertNotIn(self.partner_a.id, avatar_map)
        self.assertEqual(avatar_image_map[self.partner_a.id]['user_id'], user.id)
        self.assertTrue(avatar_image_map[self.partner_a.id]['write_date'])
        self.assertTrue(image_map[self.partner_a.id])

    def test_get_dashboard_classes_for_filters_current_year_with_submissions(self):
        classes = self.env['aps.resource.submission'].get_dashboard_classes_for_filters()
        class_ids = {item['id'] for item in classes}

        self.assertIn(self.class_a.id, class_ids)
        self.assertIn(self.class_b.id, class_ids)
        self.assertNotIn(self.class_no_submission.id, class_ids)
        self.assertNotIn(self.class_old.id, class_ids)

    def test_get_dashboard_students_for_filters_all_classes(self):
        students = self.env['aps.resource.submission'].get_dashboard_students_for_filters()
        student_ids = {item['id'] for item in students}

        self.assertIn(self.partner_a.id, student_ids)
        self.assertIn(self.partner_b.id, student_ids)
        self.assertNotIn(self.partner_c.id, student_ids)
        self.assertNotIn(self.partner_d.id, student_ids)

    def test_get_dashboard_students_for_filters_class_scoped(self):
        students_a = self.env['aps.resource.submission'].get_dashboard_students_for_filters(self.class_a.id)
        students_b = self.env['aps.resource.submission'].get_dashboard_students_for_filters(self.class_b.id)
        students_none = self.env['aps.resource.submission'].get_dashboard_students_for_filters(self.class_no_submission.id)

        self.assertEqual({item['id'] for item in students_a}, {self.partner_a.id})
        self.assertEqual({item['id'] for item in students_b}, {self.partner_b.id})
        self.assertEqual(students_none, [])

    def test_teacher_dashboard_students_match_category_and_period(self):
        partner_e = self.env['res.partner'].create({
            'name': 'Student E',
            'is_student': True,
        })
        student_e = self.env['aps.student'].search(
            [('partner_id', '=', partner_e.id)], limit=1
        )
        self.env['aps.student.class'].create({
            'student_id': student_e.id,
            'class_id': self.class_a.id,
            'state': 'enrolled',
        })
        resource = self.env['aps.resources'].search(
            [('name', '=', 'Dashboard Filter Resource')], limit=1
        )
        old_task = self.env['aps.resource.task'].create({
            'resource_id': resource.id,
            'student_id': partner_e.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': old_task.id,
            'submission_name': 'Old Submission',
            'date_assigned': fields.Date.today() - timedelta(days=60),
        })

        other_category = self.env['aps.subject.category'].create({
            'name': 'Dashboard Filter Other Category',
        })
        other_subject = self.env['aps.subject'].create({
            'name': 'Dashboard Filter Other Subject',
            'category_id': other_category.id,
        })
        other_resource = self.env['aps.resources'].create({
            'name': 'Dashboard Filter Other Resource',
            'subjects': [(6, 0, other_subject.ids)],
        })
        partner_f = self.env['res.partner'].create({
            'name': 'Student F',
            'is_student': True,
        })
        student_f = self.env['aps.student'].search(
            [('partner_id', '=', partner_f.id)], limit=1
        )
        self.env['aps.student.class'].create({
            'student_id': student_f.id,
            'class_id': self.class_a.id,
            'state': 'enrolled',
        })
        other_task = self.env['aps.resource.task'].create({
            'resource_id': other_resource.id,
            'student_id': partner_f.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': other_task.id,
            'submission_name': 'Other Category Submission',
            'date_assigned': fields.Date.today(),
        })

        recent_students = self.env['aps.resources'].get_teacher_dashboard_students(
            category_id=self.category.id,
            days=1,
        )
        all_time_students = self.env['aps.resources'].get_teacher_dashboard_students(
            category_id=self.category.id,
            days=-1,
        )
        all_time_students_without_category = (
            self.env['aps.resources'].get_teacher_dashboard_students(days=-1)
        )

        self.assertEqual(
            {student['id'] for student in recent_students},
            {self.partner_a.id, self.partner_b.id},
        )
        self.assertIn(partner_e.id, {student['id'] for student in all_time_students})
        self.assertNotIn(partner_f.id, {student['id'] for student in recent_students})
        self.assertNotIn(partner_f.id, {student['id'] for student in all_time_students})
        self.assertIn(
            partner_f.id,
            {student['id'] for student in all_time_students_without_category},
        )

    def test_teacher_dashboard_class_filter_excludes_other_subject_resources(self):
        other_category = self.env['aps.subject.category'].create({
            'name': 'Dashboard Class Filter Other Category',
        })
        other_subject = self.env['aps.subject'].create({
            'name': 'Dashboard Class Filter Other Subject',
            'category_id': other_category.id,
        })
        other_resource = self.env['aps.resources'].create({
            'name': 'Dashboard Class Filter Other Resource',
            'subjects': [(6, 0, other_subject.ids)],
        })
        partner_f = self.env['res.partner'].create({
            'name': 'Dashboard Class Filter Student',
            'is_student': True,
        })
        student_f = self.env['aps.student'].search(
            [('partner_id', '=', partner_f.id)], limit=1
        )
        self.env['aps.student.class'].create({
            'student_id': student_f.id,
            'class_id': self.class_a.id,
            'state': 'enrolled',
        })
        other_task = self.env['aps.resource.task'].create({
            'resource_id': other_resource.id,
            'student_id': partner_f.id,
        })
        self.env['aps.resource.submission'].create({
            'task_id': other_task.id,
            'submission_name': 'Biology Revision Quiz',
            'submission_label': 'Biology Revision Quiz',
            'date_assigned': fields.Date.today(),
        })

        class_students = self.env['aps.resources'].get_teacher_dashboard_students(
            days=1,
            class_id=self.class_a.id,
        )
        data = self.env['aps.resources'].get_teacher_dashboard_data(
            days=1,
            class_id=self.class_a.id,
        )
        resource_submissions = (
            self.env['aps.resources'].get_dashboard_submissions_for_resource(
                other_resource.id,
                days=1,
                class_id=self.class_a.id,
            )
        )

        self.assertEqual(
            {student['id'] for student in class_students},
            {self.partner_a.id},
        )
        self.assertNotIn(
            other_resource.id,
            {resource['id'] for resource in data['task_resources']},
        )
        self.assertNotIn(
            'Biology Revision Quiz',
            {group['label'] for group in data['submission_groups']},
        )
        self.assertFalse(resource_submissions)


class TestStudentDashboard(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner_a = self.env['res.partner'].create({'name': 'Dashboard Student A', 'is_student': True})
        self.partner_b = self.env['res.partner'].create({'name': 'Dashboard Student B', 'is_student': True})
        self.partner_d = self.env['res.partner'].create({'name': 'Dashboard Student Without Work', 'is_student': True})
        self.subject = self.env['aps.subject'].create({'name': 'Dashboard Mathematics'})
        resource = self.env['aps.resources'].create({
            'name': 'Student Dashboard Resource',
            'subjects': [(6, 0, self.subject.ids)],
        })
        for partner in [self.partner_a, self.partner_b]:
            task = self.env['aps.resource.task'].create({
                'resource_id': resource.id,
                'student_id': partner.id,
            })
            submission = self.env['aps.resource.submission'].create({
                'task_id': task.id,
                'submission_name': 'Dashboard Work',
                'date_assigned': fields.Date.today(),
            })
            submission._compute_submission_active()

    def _student_dashboard_user(self, partner):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': partner.name,
            'login': f'dashboard_student_test_{partner.id}',
            'partner_id': partner.id,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('aps_sis.group_aps_student').id,
            ])],
        })

    def test_student_dashboard_forces_own_submissions_and_hides_teacher_data(self):
        student_user = self._student_dashboard_user(self.partner_a)
        resources = self.env['aps.resources'].with_user(student_user)
        own_submissions = self.env['aps.resource.submission'].search([
            ('student_id', '=', self.partner_a.id),
        ])
        resource = own_submissions[:1].resource_id
        image_buffer = io.BytesIO()
        Image.new('RGB', (24, 24), (35, 125, 90)).save(image_buffer, format='PNG')
        self.subject.icon = base64.b64encode(image_buffer.getvalue())

        data = resources.get_teacher_dashboard_data(
            days=-1, student_id=self.partner_b.id, class_id=999,
        )

        self.assertTrue(data['is_student'])
        self.assertEqual(data['selected_student_id'], self.partner_a.id)
        self.assertFalse(data['selected_class_id'])
        for key in ['classes', 'students', 'subject_resources', 'favourite_resources', 'task_resources', 'dashboard_metrics']:
            self.assertFalse(data[key], key)
        self.assertEqual(
            {submission_id for group in data['submission_groups'] for submission_id in group['submission_ids']},
            set(own_submissions.ids),
        )
        group = data['submission_groups'][0]
        self.assertEqual(group['student_submission_id'], own_submissions[:1].id)
        self.assertEqual(group['student_state'], own_submissions[:1].state)
        self.assertTrue(group['subject_icons'])
        self.assertEqual(group['subject_name'], self.subject.display_name)

        submissions = resources.sudo().get_dashboard_submissions_for_resource(
            resource.id, days=-1, student_id=self.partner_b.id, class_id=999,
        )
        self.assertEqual({submission['id'] for submission in submissions}, set(own_submissions.ids))

    def test_student_dashboard_without_submissions_does_not_fall_back_to_all_students(self):
        student_user = self._student_dashboard_user(self.partner_d)
        data = self.env['aps.resources'].with_user(student_user).sudo().get_teacher_dashboard_data(
            days=-1, student_id=self.partner_a.id,
        )
        self.assertEqual(data['selected_student_id'], self.partner_d.id)
        self.assertFalse(data['submission_groups'])

    def test_student_dashboard_hides_future_assignments(self):
        student_user = self._student_dashboard_user(self.partner_a)
        own_submission = self.env['aps.resource.submission'].search([
            ('student_id', '=', self.partner_a.id),
        ], limit=1)
        own_submission.date_assigned = fields.Date.today() + timedelta(days=2)
        own_submission._compute_submission_active()
        data = self.env['aps.resources'].with_user(student_user).sudo().get_teacher_dashboard_data(days=-1)
        self.assertFalse(data['submission_groups'])
