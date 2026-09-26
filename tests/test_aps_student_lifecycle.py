from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAPSStudentLifecycle(TransactionCase):

    def _create_student(self, **values):
        partner = self.env['res.partner'].create({
            'name': 'Lifecycle Test Student',
            'is_student': True,
        })
        return self.env['aps.student'].create({
            'partner_id': partner.id,
            **values,
        })

    def test_defaults_and_optional_start_date(self):
        student = self._create_student()

        self.assertEqual(student.enrolment_status.code, 'enrolled')
        self.assertTrue(student.enrolment_status.description)
        self.assertGreaterEqual(student.enrolment_status.color, 0)
        self.assertFalse(student.start_date)

    def test_admissions_references_can_be_set(self):
        grade = self.env['aps.level'].create({'name': 'Lifecycle Test Level'})
        leaving_reason = self.env['aps.student.leaving.reason'].create({
            'name': 'Lifecycle Test Reason',
        })
        entry_source = self.env['aps.student.entry.source'].create({
            'name': 'Lifecycle Test Source',
        })

        student = self._create_student(
            entry_grade_id=grade.id,
            leaving_reason_id=leaving_reason.id,
            entry_source_id=entry_source.id,
        )

        self.assertEqual(student.entry_grade_id, grade)
        self.assertEqual(student.leaving_reason_id, leaving_reason)
        self.assertEqual(student.entry_source_id, entry_source)

    def test_end_date_cannot_precede_start_date(self):
        start_date = fields.Date.today()
        student = self._create_student(start_date=start_date)

        with self.assertRaises(ValidationError):
            student.write({'end_date': start_date - timedelta(days=1)})