from odoo import fields, models, api
from odoo.exceptions import ValidationError


class APSStudentClass(models.Model):
    _name = 'aps.student.class'
    _description = 'Student Class Enrollment'
    _order = 'start_date desc'
    _rec_name = 'student_id'

    student_id = fields.Many2one(
        'aps.student',
        string='Student',
        required=True,
        ondelete='cascade',
    )
    home_class_id = fields.Many2one(
        'aps.class',
        string='Class',
        required=True,
        ondelete='cascade',
    )
    start_date = fields.Date(string='Start Date', default=lambda self: self._default_start_date())
    end_date = fields.Date(string='End Date', default=lambda self: self._default_end_date())

    def _get_current_year(self):
        return self.env['aps.academic.year'].search([('is_current', '=', True)], limit=1)

    def _default_start_date(self):
        year = self._get_current_year()
        return year.start_date if year else False

    def _default_end_date(self):
        year = self._get_current_year()
        return year.end_date if year else False
    active = fields.Boolean(default=True, string='Active')
    state = fields.Selection(
        [
            ('enrolled', 'Enrolled'),
            ('withdrawn', 'Withdrawn'),
            ('finished', 'Finished'),
        ],
        string='Status',
        default='enrolled',
        required=True,
    )

    def action_withdraw(self):
        self.write({
            'state': 'withdrawn',
            'end_date': fields.Date.today(),
        })

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError('End date must be on or after start date.')

    @api.depends('student_id', 'home_class_id')
    def _compute_display_name(self):
        for rec in self:
            student = rec.student_id.display_name or ''
            cls = rec.home_class_id.display_name or ''
            rec.display_name = f"{student} / {cls}" if student and cls else student or cls

    _sql_constraints = [
        ('student_class_uniq', 'unique(student_id, home_class_id)', 'This student is already enrolled in this class!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('student_id')._recompute_home_class()
        return records

    def write(self, vals):
        result = super().write(vals)
        if any(f in vals for f in ('home_class_id', 'state', 'student_id')):
            self.mapped('student_id')._recompute_home_class()
        return result

    def unlink(self):
        students = self.mapped('student_id')
        result = super().unlink()
        students._recompute_home_class()
        return result
