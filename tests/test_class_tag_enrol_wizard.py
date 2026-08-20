from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestClassTagEnrolWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.today()
        cls.academic_year = cls.env['aps.academic.year'].create({
            'name': 'Tag Enrolment Test Year',
            'short_name': 'TETY',
            'start_date': today - timedelta(days=365),
            'end_date': today + timedelta(days=365),
            'is_current': False,
        })
        subject_category = cls.env['aps.subject.category'].create({'name': 'Test Category'})
        subject = cls.env['aps.subject'].create({
            'name': 'Test Subject',
            'category_id': subject_category.id,
        })
        cls.tag = cls.env['aps.class.tag'].create({'name': 'Test Tag'})
        cls.test_class = cls.env['aps.class'].create({
            'subject_id': subject.id,
            'identifier': 'TAG',
            'academic_year_id': cls.academic_year.id,
            'tag_ids': [(6, 0, cls.tag.ids)],
        })

    def _create_student(self, name, category=False):
        partner = self.env['res.partner'].create({
            'name': name,
            'is_student': True,
            'category_id': [(6, 0, category.ids)] if category else False,
        })
        return self.env['aps.student'].create({'partner_id': partner.id})

    def _create_enrollment(self, student, start_date):
        return self.env['aps.student.class'].create({
            'student_id': student.id,
            'class_id': self.test_class.id,
            'start_date': start_date,
            'end_date': self.academic_year.end_date,
            'state': 'enrolled',
        })

    def _create_wizard(self, **values):
        return self.env['aps.class.tag.enrol.wizard'].create({
            'academic_year_id': self.academic_year.id,
            'tag_ids': [(6, 0, self.tag.ids)],
            **values,
        })

    def test_also_remove_students_defaults_true(self):
        wizard = self._create_wizard()
        self.assertTrue(wizard.also_remove_students)

    def test_removal_deletes_under_30_and_withdraws_at_30_days(self):
        today = fields.Date.today()
        category = self.env['res.partner.category'].create({'name': self.tag.name})
        matching_student = self._create_student('Matching Student', category)
        short_student = self._create_student('Short Enrolment Student')
        long_student = self._create_student('Long Enrolment Student')

        self._create_enrollment(matching_student, today - timedelta(days=10))
        short_enrollment = self._create_enrollment(
            short_student,
            today - timedelta(days=29),
        )
        long_enrollment = self._create_enrollment(
            long_student,
            today - timedelta(days=30),
        )

        self._create_wizard().action_execute()

        self.assertFalse(short_enrollment.exists())
        self.assertEqual(long_enrollment.state, 'withdrawn')
        self.assertEqual(long_enrollment.end_date, today)
        self.assertEqual(
            self.env['aps.student.class'].search_count([
                ('student_id', '=', matching_student.id),
                ('class_id', '=', self.test_class.id),
            ]),
            1,
        )

    def test_unchecked_removal_preserves_non_matching_enrollment(self):
        today = fields.Date.today()
        non_matching_student = self._create_student('Non-Matching Student')
        enrollment = self._create_enrollment(
            non_matching_student,
            today - timedelta(days=10),
        )

        self._create_wizard(also_remove_students=False).action_execute()

        self.assertTrue(enrollment.exists())
        self.assertEqual(enrollment.state, 'enrolled')
