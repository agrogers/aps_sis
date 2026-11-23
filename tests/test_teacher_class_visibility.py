from odoo.tests.common import Form, TransactionCase


class TestTeacherClassVisibility(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Class Visibility Teacher',
        })
        self.teacher = self.env['aps.teacher'].create({
            'partner_id': self.partner.id,
        })
        current_year = self.env['aps.academic.year'].create({
            'name': 'Class Visibility Current Year',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'is_current': True,
        })
        previous_year = self.env['aps.academic.year'].create({
            'name': 'Class Visibility Previous Year',
            'start_date': '2025-01-01',
            'end_date': '2025-12-31',
        })
        self.current_class = self.env['aps.class'].create({
            'name': 'Class Visibility Current Class',
            'academic_year_id': current_year.id,
            'teacher_ids': [(6, 0, self.partner.ids)],
        })
        self.previous_class = self.env['aps.class'].create({
            'name': 'Class Visibility Previous Class',
            'academic_year_id': previous_year.id,
            'assistant_teacher_ids': [(6, 0, self.partner.ids)],
        })

    def test_toggle_shows_classes_from_all_academic_years(self):
        with Form(self.teacher) as teacher_form:
            self.assertEqual(
                set(teacher_form.class_ids.ids),
                set(self.current_class.ids),
            )

            teacher_form.show_all_classes = True

            self.assertEqual(
                set(teacher_form.class_ids.ids),
                set((self.current_class | self.previous_class).ids),
            )
