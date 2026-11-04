from odoo import fields, models


class ASCTTClass(models.Model):
    _name = 'asctt.class'
    _description = 'aSc Timetable Class'
    _order = 'name'

    asc_id = fields.Char(string='aSc ID', size=64, index=True)
    name = fields.Char(string='Name', required=True)
    short = fields.Char(string='Short', size=20)
    classroom_ids = fields.Many2many(
        'asctt.classroom',
        relation='asctt_class_classroom_rel',
        column1='class_id',
        column2='classroom_id',
        string='Classrooms',
    )
    teacher_id = fields.Many2one(
        'asctt.teacher',
        string='Home Room Teacher',
        ondelete='set null',
    )
    grade = fields.Char(string='Grade', size=20)

    aps_class_identifier = fields.Char(
        string='APEX Class Identifier',
        size=64,
        help='Optional identifier used to document the corresponding APEX class.',
    )

    def _get_aps_class_for_subject(self, subject_category, start_date, end_date):
        """Resolve the first enrolled APEX class matching this grade and subject category."""
        self.ensure_one()
        if not subject_category or not self.grade or not start_date or not end_date:
            return self.env['aps.class']
        try:
            grade_number = int(self.grade)
        except (TypeError, ValueError):
            return self.env['aps.class']

        grade = self.env['asctt.grade'].search(
            [('grade', '=', grade_number)],
            limit=1,
        )
        if not grade.aps_level_id:
            return self.env['aps.class']

        return self.env['aps.class'].search([
            ('subject_id.category_id', '=', subject_category.id),
            ('subject_id.level_id', '=', grade.aps_level_id.id),
            ('enrollment_ids.start_date', '<=', end_date),
            '|',
            ('enrollment_ids.end_date', '=', False),
            ('enrollment_ids.end_date', '>=', start_date),
        ], order='id', limit=1)
