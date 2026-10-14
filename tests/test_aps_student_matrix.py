from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAPSStudentMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.today()
        cls.past_year = cls.env['aps.academic.year'].create({
            'name': 'Student Matrix Past Year',
            'short_name': 'SMPY',
            'start_date': today - timedelta(days=730),
            'end_date': today - timedelta(days=365),
        })
        category_tag = cls.env['aps.subject.category.tag'].create({
            'name': 'Home Class',
        })
        home_category = cls.env['aps.subject.category'].create({
            'name': 'Student Matrix Home Category',
            'tag_ids': [(6, 0, category_tag.ids)],
        })
        cls.home_subject = cls.env['aps.subject'].create({
            'name': 'Student Matrix Home Subject',
            'category_id': home_category.id,
        })
        cls.other_subject = cls.env['aps.subject'].create({
            'name': 'Student Matrix Other Subject',
        })
        cls.home_class = cls.env['aps.class'].create({
            'subject_id': cls.home_subject.id,
            'academic_year_id': cls.past_year.id,
        })
        cls.other_class = cls.env['aps.class'].create({
            'subject_id': cls.other_subject.id,
            'academic_year_id': cls.past_year.id,
        })
        partner = cls.env['res.partner'].create({
            'name': 'Student Matrix Past Student',
            'is_student': True,
        })
        cls.student = cls.env['aps.student'].create({'partner_id': partner.id})
        cls.env['aps.student.class'].create([
            {
                'student_id': cls.student.id,
                'class_id': cls.home_class.id,
                'start_date': cls.past_year.start_date,
                'end_date': cls.past_year.end_date,
                'state': 'finished',
            },
            {
                'student_id': cls.student.id,
                'class_id': cls.other_class.id,
                'start_date': cls.past_year.start_date,
                'end_date': cls.past_year.end_date,
                'state': 'finished',
            },
        ])
        cls.matrix = cls.env['aps.student.matrix']

    def test_past_year_classes_and_matrix_include_finished_enrollments(self):
        classes = self.matrix.get_home_classes(self.past_year.id)

        self.assertIn(
            {'id': self.home_class.id, 'name': self.home_class.display_name},
            classes,
        )

        data = self.matrix.get_matrix_data([self.home_class.id], self.past_year.id)
        self.assertEqual([student['id'] for student in data['students']], [self.student.id])
        self.assertEqual(
            {subject['id'] for subject in data['subjects']},
            {self.home_subject.id, self.other_subject.id},
        )

    def test_current_year_classes_still_exclude_finished_enrollments(self):
        today = fields.Date.today()
        current_year = self.env['aps.academic.year'].create({
            'name': 'Student Matrix Current Year',
            'short_name': 'SMCY',
            'start_date': today - timedelta(days=1),
            'end_date': today + timedelta(days=365),
            'is_current': True,
        })
        current_class = self.env['aps.class'].create({
            'subject_id': self.home_subject.id,
            'academic_year_id': current_year.id,
        })
        self.env['aps.student.class'].create({
            'student_id': self.student.id,
            'class_id': current_class.id,
            'start_date': current_year.start_date,
            'end_date': current_year.end_date,
            'state': 'finished',
        })

        self.assertNotIn(
            current_class.id,
            {class_info['id'] for class_info in self.matrix.get_home_classes(current_year.id)},
        )
        data = self.matrix.get_matrix_data([current_class.id], current_year.id)
        self.assertFalse(data['students'])
