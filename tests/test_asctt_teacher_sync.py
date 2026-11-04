from datetime import timedelta

from odoo import fields
from odoo.tests import Form, TransactionCase


class TestASCTTTeacherSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.today()
        cls.start_date = today - timedelta(days=30)
        cls.end_date = today + timedelta(days=30)
        cls.academic_year = cls.env['aps.academic.year'].create({
            'name': 'aSc Teacher Sync Test Year',
            'short_name': 'ATSTY',
            'start_date': cls.start_date,
            'end_date': cls.end_date,
        })
        cls.category = cls.env['aps.subject.category'].create({
            'name': 'aSc Teacher Sync Category',
        })
        cls.level = cls.env['aps.level'].create({
            'name': 'aSc Teacher Sync Level',
        })
        cls.subject = cls.env['aps.subject'].create({
            'name': 'aSc Teacher Sync Subject',
            'category_id': cls.category.id,
            'level_id': cls.level.id,
        })
        cls.aps_class = cls.env['aps.class'].create({
            'subject_id': cls.subject.id,
            'identifier': 'SYNC',
            'academic_year_id': cls.academic_year.id,
        })
        student_partner = cls.env['res.partner'].create({
            'name': 'aSc Teacher Sync Student',
            'is_student': True,
        })
        student = cls.env['aps.student'].create({
            'partner_id': student_partner.id,
        })
        cls.env['aps.student.class'].create({
            'student_id': student.id,
            'class_id': cls.aps_class.id,
            'start_date': cls.start_date,
            'end_date': cls.end_date,
        })
        cls.env['asctt.grade'].create({
            'grade': 7,
            'name': 'aSc Teacher Sync Grade',
            'aps_level_id': cls.level.id,
        })
        cls.asctt_class = cls.env['asctt.class'].create({
            'name': 'aSc Teacher Sync Class',
            'grade': '7',
        })
        cls.asctt_subject = cls.env['asctt.subject'].create({
            'name': 'aSc Teacher Sync Subject',
            'aps_subject_category_id': cls.category.id,
        })
        cls.teacher_a = cls._create_teacher('aSc Sync Teacher A')
        cls.teacher_b = cls._create_teacher('aSc Sync Teacher B')
        cls.teacher_c = cls._create_teacher('aSc Sync Teacher C')

    @classmethod
    def _create_teacher(cls, name):
        partner = cls.env['res.partner'].create({
            'name': name,
            'is_teacher': True,
        })
        aps_teacher = cls.env['aps.teacher'].create({
            'partner_id': partner.id,
        })
        return cls.env['asctt.teacher'].create({
            'name': name,
            'aps_teacher_id': aps_teacher.id,
        })

    def test_sync_aggregates_lesson_roles_with_teacher_priority(self):
        self.env['asctt.lesson'].create({
            'subject_id': self.asctt_subject.id,
            'class_ids': [(6, 0, self.asctt_class.ids)],
            'teacher_ids': [(6, 0, (self.teacher_a | self.teacher_b).ids)],
            'teacher_order': '%s,%s' % (self.teacher_a.id, self.teacher_b.id),
        })
        self.env['asctt.lesson'].create({
            'subject_id': self.asctt_subject.id,
            'class_ids': [(6, 0, self.asctt_class.ids)],
            'teacher_ids': [(6, 0, (self.teacher_b | self.teacher_c).ids)],
            'teacher_order': '%s,%s' % (self.teacher_b.id, self.teacher_c.id),
        })
        self.aps_class.write({
            'teacher_ids': [(6, 0, self.teacher_a.aps_teacher_id.partner_id.ids)],
            'assistant_teacher_ids': [
                (6, 0, self.teacher_b.aps_teacher_id.partner_id.ids)
            ],
        })

        wizard_model = self.env['asctt.teacher.sync.wizard'].with_context(
            default_start_date=self.start_date,
            default_end_date=self.end_date,
        )
        wizard = Form(wizard_model).save()

        self.assertEqual(wizard.start_date, self.start_date)
        self.assertEqual(wizard.end_date, self.end_date)
        self.assertFalse(wizard.issue_names)
        self.assertFalse(wizard.synced_class_names)
        self.assertEqual(len(wizard.line_ids), 1)
        line = wizard.line_ids
        self.assertEqual(line.aps_class_id, self.aps_class)
        expected_teachers = (
            self.teacher_a.aps_teacher_id.partner_id
            | self.teacher_b.aps_teacher_id.partner_id
        )
        expected_assistants = self.teacher_c.aps_teacher_id.partner_id
        self.assertEqual(set(line.source_teacher_ids.ids), set(expected_teachers.ids))
        self.assertEqual(
            set(line.source_assistant_teacher_ids.ids),
            set(expected_assistants.ids),
        )
        self.assertTrue(line.selected)

        line.write({
            'source_teacher_ids': [(5, 0, 0)],
            'source_assistant_teacher_ids': [(5, 0, 0)],
        })
        wizard.action_apply()

        self.assertEqual(set(self.aps_class.teacher_ids.ids), set(expected_teachers.ids))
        self.assertEqual(
            set(self.aps_class.assistant_teacher_ids.ids),
            set(expected_assistants.ids),
        )
        synced_defaults = wizard_model.default_get([
            'line_ids',
            'issue_names',
            'synced_class_names',
        ])
        self.assertFalse(synced_defaults['line_ids'])
        self.assertIn(self.aps_class.display_name, synced_defaults['synced_class_names'])

    def test_dashboard_sync_action_uses_saved_import_date_range(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_param(
            'asctt.import.wizard.apply_from_date',
            fields.Date.to_string(self.start_date),
        )
        parameters.set_param('asctt.import.wizard.apply_to_term_id', '')

        import_wizard_model = self.env['asctt.import.wizard']
        import_wizard = import_wizard_model.new(
            import_wizard_model.default_get([
                'apply_from_date',
                'apply_to_term_id',
            ])
        )
        start_date, end_date = import_wizard._get_effective_date_range()

        action = self.env['asctt.dashboard'].action_open_teacher_sync()

        self.assertEqual(
            action['context']['default_start_date'],
            fields.Date.to_string(start_date),
        )
        self.assertEqual(
            action['context']['default_end_date'],
            fields.Date.to_string(end_date),
        )
