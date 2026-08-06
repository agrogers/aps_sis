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
    class_id = fields.Many2one(
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
            ('waiting', 'Waiting'),
            ('enrolled', 'Enrolled'),
            ('withdrawn', 'Withdrawn'),
            ('finished', 'Finished'),
        ],
        string='Status',
        default='enrolled',
        required=True,
    )
    notes = fields.Text(string='Notes', help='Internal notes, e.g. reason for withdrawal.')
    subject_icon = fields.Image(
        related='class_id.subject_id.icon',
        string='Subject Icon',
        readonly=True,
    )
    image_128 = fields.Image(
        related='student_id.image_128',
        string='Photo',
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='student_id.partner_id',
        string='Student Name',
        readonly=True,
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

    @api.depends('student_id', 'class_id')
    def _compute_display_name(self):
        for rec in self:
            student = rec.student_id.display_name or ''
            cls = rec.class_id.display_name or ''
            rec.display_name = f"{student} / {cls}" if student and cls else student or cls

    _sql_constraints = [
        ('student_class_uniq', 'unique(student_id, class_id)', 'This student is already enrolled in this class!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.today()
        for vals in vals_list:
            if vals.get('state') not in ('finished', 'withdrawn'):
                start = vals.get('start_date')
                end = vals.get('end_date')
                if start and end:
                    if today < start:
                        vals['state'] = 'waiting'
                    elif today < end:
                        vals['state'] = 'enrolled'
        records = super().create(vals_list)
        records.mapped('student_id')._recompute_home_class()
        return records

    def write(self, vals):
        # If state is being set to withdrawn (e.g. via the clickable statusbar),
        # set end_date to today (overriding any future date already on the record).
        if vals.get('state') == 'withdrawn':
            vals['end_date'] = fields.Date.today()
        result = super().write(vals)
        if any(f in vals for f in ('class_id', 'state', 'student_id')):
            self.mapped('student_id')._recompute_home_class()
        # If end_date is set to a future date on a withdrawn record, re-enrol
        if 'end_date' in vals:
            today = fields.Date.today()
            for rec in self:
                if rec.state == 'withdrawn' and rec.end_date and rec.end_date > today:
                    rec.state = 'enrolled'
        return result

    @api.model
    def cron_reconcile_enrollment_states(self):
        """Cron method: auto-transition states based on today's date.

        - start_date in the future  -> waiting
        - today within [start, end] -> enrolled
        - Otherwise (end passed, no manual status) -> finished
        Withdrawn and manually finished records are left untouched.
        """
        today = fields.Date.today()
        auto_states = self.search([
            ('state', 'in', ('waiting', 'enrolled', 'finished')),
        ])
        for rec in auto_states:
            if rec.state == 'withdrawn':
                continue
            if not rec.start_date or not rec.end_date:
                continue
            if today < rec.start_date:
                new_state = 'waiting'
            elif rec.start_date <= today <= rec.end_date:
                new_state = 'enrolled'
            else:
                new_state = 'finished'
            if rec.state != new_state:
                rec.state = new_state
        return True

    def unlink(self):
        students = self.mapped('student_id')
        result = super().unlink()
        students._recompute_home_class()
        return result
