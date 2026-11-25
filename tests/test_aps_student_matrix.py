import base64
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
            'color_rgb': '#123456',
            'tag_ids': [(6, 0, category_tag.ids)],
        })
        cls.level = cls.env['aps.level'].create({
            'name': 'Student Matrix Level',
            'short_name': 'SML',
            'sequence': 5,
        })
        cls.home_subject = cls.env['aps.subject'].create({
            'name': 'Student Matrix Home Subject',
            'category_id': home_category.id,
            'level_id': cls.level.id,
        })
        cls.second_home_subject = cls.env['aps.subject'].create({
            'name': 'Student Matrix Second Home Subject',
            'category_id': home_category.id,
            'level_id': cls.level.id,
        })
        cls.other_subject = cls.env['aps.subject'].create({
            'name': 'Student Matrix Other Subject',
        })
        cls.home_class = cls.env['aps.class'].create({
            'subject_id': cls.home_subject.id,
            'academic_year_id': cls.past_year.id,
        })
        cls.second_home_class = cls.env['aps.class'].create({
            'subject_id': cls.second_home_subject.id,
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
                'class_id': cls.second_home_class.id,
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
            {self.home_subject.id, self.second_home_subject.id, self.other_subject.id},
        )
        subjects_by_id = {subject['id']: subject for subject in data['subjects']}
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['category_id'],
            self.home_subject.category_id.id,
        )
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['category_name'],
            self.home_subject.category_id.name,
        )
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['category_color'],
            '#123456',
        )
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['level_id'],
            self.level.id,
        )
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['level_name'],
            self.level.display_name,
        )
        self.assertEqual(
            subjects_by_id[self.home_subject.id]['level_sequence'],
            5,
        )
        self.assertFalse(subjects_by_id[self.other_subject.id]['level_id'])
        self.assertEqual(
            subjects_by_id[self.other_subject.id]['category_key'],
            'uncategorized',
        )
        self.assertEqual(
            subjects_by_id[self.other_subject.id]['category_name'],
            'Uncategorized',
        )
        self.assertEqual(
            data['category_totals'],
            {str(self.home_subject.category_id.id): 2, 'uncategorized': 1},
        )

    def test_matrix_subject_icons_prefer_subject_then_category_icon(self):
        category_icon = base64.b64encode(b'category-icon')
        subject_icon = base64.b64encode(b'subject-icon')
        self.home_subject.category_id.write({'icon': category_icon})
        self.home_subject.write({'icon': subject_icon})
        self.second_home_subject.write({'icon': False})

        data = self.matrix.get_matrix_data([self.home_class.id], self.past_year.id)
        subjects_by_id = {subject['id']: subject for subject in data['subjects']}

        self.assertEqual(
            subjects_by_id[self.home_subject.id]['icon_url'],
            f'/web/image/aps.subject/{self.home_subject.id}/icon',
        )
        self.assertEqual(
            subjects_by_id[self.second_home_subject.id]['icon_url'],
            f'/web/image/aps.subject.category/{self.home_subject.category_id.id}/icon',
        )
        self.assertFalse(subjects_by_id[self.other_subject.id]['icon_url'])

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
