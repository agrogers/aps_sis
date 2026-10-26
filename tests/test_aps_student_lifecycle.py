import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from PIL import Image


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

    def test_avatar_images_are_stored_independently_of_avatar_records_and_photos(self):
        def image_binary(color):
            image_buffer = io.BytesIO()
            Image.new('RGB', (24, 16), color).save(image_buffer, format='PNG')
            return base64.b64encode(image_buffer.getvalue()).decode('ascii')

        avatar_binary = image_binary((35, 125, 90))
        updated_avatar_binary = image_binary((125, 35, 90))
        photo_binary = image_binary((90, 125, 35))
        avatar = self.env['aps.avatar'].create({
            'name': 'Stored Avatar Test',
            'image': avatar_binary,
        })
        user = self.env.user
        user.write({
            'image_1920': photo_binary,
            'avatar_id': avatar.id,
            'avatar_image': avatar_binary,
        })
        student = self._create_student()
        student.partner_id.image_1920 = photo_binary
        student.write({
            'avatar_id': avatar.id,
            'avatar_image': avatar_binary,
        })

        avatar.image = updated_avatar_binary

        self.assertFalse(self.env['res.users']._fields['avatar_image'].related)
        self.assertFalse(self.env['aps.student']._fields['avatar_image'].related)
        self.assertEqual(user.avatar_image, avatar_binary)
        self.assertEqual(student.avatar_image, avatar_binary)
        self.assertEqual(user.avatar_id, avatar)
        self.assertEqual(student.avatar_id, avatar)
        self.assertEqual(user.image_1920, photo_binary)
        self.assertEqual(student.partner_id.image_1920, photo_binary)

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