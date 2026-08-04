from odoo import fields
from odoo.tests.common import TransactionCase


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
        subject = self.env['aps.subject'].create({
            'name': 'Algebra',
            'category_id': category.id,
        })

        self.class_a = self.env['aps.class'].create({
            'subject_id': subject.id,
            'identifier': 'A',
            'academic_year_id': self.current_year.id,
        })
        self.class_b = self.env['aps.class'].create({
            'subject_id': subject.id,
            'identifier': 'B',
            'academic_year_id': self.current_year.id,
        })
        self.class_no_submission = self.env['aps.class'].create({
            'subject_id': subject.id,
            'identifier': 'C',
            'academic_year_id': self.current_year.id,
        })
        self.class_old = self.env['aps.class'].create({
            'subject_id': subject.id,
            'identifier': 'D',
            'academic_year_id': self.old_year.id,
        })

        self.partner_a = self.env['res.partner'].create({'name': 'Student A', 'is_student': True})
        self.partner_b = self.env['res.partner'].create({'name': 'Student B', 'is_student': True})
        self.partner_c = self.env['res.partner'].create({'name': 'Student C', 'is_student': True})
        self.partner_d = self.env['res.partner'].create({'name': 'Student D', 'is_student': True})

        self.student_a = self.env['aps.student'].create({'partner_id': self.partner_a.id})
        self.student_b = self.env['aps.student'].create({'partner_id': self.partner_b.id})
        self.student_c = self.env['aps.student'].create({'partner_id': self.partner_c.id})
        self.student_d = self.env['aps.student'].create({'partner_id': self.partner_d.id})

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

        resource = self.env['aps.resources'].create({'name': 'Dashboard Filter Resource'})

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
