import re

from odoo import api, fields, models
from .aps_assign_mixin import APSAssignMixin


class APSAssignDetails(APSAssignMixin, models.Model):
    _name = 'aps.assign.details'
    _description = 'APEX Recurring Assignment Details'
    _order = 'next_assignment_date, id desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    active = fields.Boolean(default=True)

    resource_id = fields.Many2one('aps.resources', string='Top Level Resource', required=True)
    assigned_by = fields.Many2one('op.faculty', string='Assigned By')

    custom_submission_name = fields.Char(string='Custom Submission Name')
    submission_label = fields.Char(string='Submission Label')

    date_due_offset_days = fields.Integer(
        string='Due Date Offset (Days)',
        default=0,
        help='Number of days added to assignment date to compute due date for recurring runs.',
    )
    time_assigned = fields.Float(string='Time Assigned')

    recurring_days = fields.Integer(
        string='Recurring (Days)',
        required=True,
        default=0,
        help='Days between assignment runs. A value greater than 0 enables recurring scheduling.',
    )
    next_assignment_date = fields.Date(string='Next Assignment Date', required=True)
    last_assigned_date = fields.Date(string='Last Assigned Date')

    allow_subject_editing = fields.Boolean(string='Allow Subject Editing', default=False)
    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
    ], string='Has Question', default='no', required=True)
    question = fields.Html(string='Question')
    has_answer = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('yes_notes', 'Yes (Notes)'),
        ('use_parent', 'Use Parent'),
    ], string='Has Answer', default='no', required=True)
    answer = fields.Html(string='Answer')
    has_default_answer = fields.Boolean(string='Use Default Answer', default=False)
    default_answer = fields.Html(string='Default Answer')

    subjects = fields.Many2many('op.subject', string='Subjects')
    points_scale = fields.Integer(string='Points Scale', default=1)
    notify_student = fields.Boolean(string='Notify Student', default=True)

    assign_student_ids = fields.One2many(
        'aps.assign.students',
        'assign_detail_id',
        string='Students',
    )
    assign_resource_ids = fields.One2many(
        'aps.assign.resources',
        'assign_detail_id',
        string='Resources',
        order='sequence',
    )

    def _assign_students_field_name(self):
        return 'assign_student_ids'

    def _assign_resources_field_name(self):
        return 'assign_resource_ids'

    @api.onchange('subjects')
    def _onchange_subjects(self):
        self._onchange_subjects_shared()

    @api.onchange('resource_id')
    def _onchange_resource_id(self):
        self._onchange_resource_id_shared()

    @api.depends('resource_id', 'next_assignment_date', 'recurring_days')
    def _compute_name(self):
        for rec in self:
            resource_name = rec.resource_id.display_name if rec.resource_id else 'Recurring Assignment'
            if rec.next_assignment_date:
                rec.name = f'{resource_name} - every {rec.recurring_days} day(s) - next {rec.next_assignment_date}'
            else:
                rec.name = f'{resource_name} - every {rec.recurring_days} day(s)'

    @api.model
    def _format_submission_label(self, label, assigned_date):
        base = (label or '').strip()
        if not base:
            return False
        base = re.sub(r'\s*\(\d{4}-\d{2}-\d{2}\)\s*$', '', base).strip()
        if assigned_date:
            return f'{base} ({assigned_date})'
        return base

    def _create_assignment_for_date(self, assignment_date):
        self.ensure_one()
        if not assignment_date:
            return

        due_date = fields.Date.add(assignment_date, days=self.date_due_offset_days or 0)
        label_source = self.submission_label or self.custom_submission_name or self.resource_id.display_name
        submission_label = self._format_submission_label(label_source, assignment_date)

        line_commands = []
        for line in self.assign_resource_ids.sorted('sequence'):
            line_commands.append((0, 0, {
                'resource_id': line.resource_id.id,
                'parent_resource_id': self.resource_id.id,
                'selected': True,
                'sequence': line.sequence,
            }))

        wizard_vals = {
            'resource_id': self.resource_id.id,
            'date_assigned': assignment_date,
            'time_assigned': self.time_assigned,
            'date_due': due_date,
            'student_ids': [(6, 0, self.assign_student_ids.mapped('student_id').ids)],
            'assigned_by': self.assigned_by.id if self.assigned_by else False,
            'custom_submission_name': self.custom_submission_name,
            'submission_label': submission_label,
            'affected_resource_line_ids': line_commands,
            'allow_subject_editing': self.allow_subject_editing,
            'has_question': self.has_question,
            'question': self.question,
            'has_answer': self.has_answer,
            'answer': self.answer,
            'has_default_answer': self.has_default_answer,
            'default_answer': self.default_answer,
            'subjects': [(6, 0, self.subjects.ids)],
            'points_scale': self.points_scale,
            'notify_student': self.notify_student,
            'recurring_days': self.recurring_days,
        }

        wizard = self.env['aps.assign.students.wizard'].with_context(skip_recurring_save=True).create(wizard_vals)
        wizard.action_assign_students()
        self.last_assigned_date = assignment_date

    @api.model
    def run_daily_recurring_assignments(self):
        today = fields.Date.today()
        schedules = self.search([
            ('active', '=', True),
            ('next_assignment_date', '!=', False),
            ('next_assignment_date', '<=', today),
        ])

        for schedule in schedules:
            run_date = schedule.next_assignment_date
            while run_date and run_date <= today:
                schedule._create_assignment_for_date(run_date)
                run_date = fields.Date.add(run_date, days=schedule.recurring_days)
            schedule.next_assignment_date = run_date


class APSAssignStudents(models.Model):
    _name = 'aps.assign.students'
    _description = 'APEX Recurring Assignment Students'

    assign_detail_id = fields.Many2one('aps.assign.details', required=True, ondelete='cascade')
    student_id = fields.Many2one('res.partner', string='Student', required=True)


class APSAssignResources(models.Model):
    _name = 'aps.assign.resources'
    _description = 'APEX Recurring Assignment Resources'
    _order = 'sequence, id'

    assign_detail_id = fields.Many2one('aps.assign.details', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    resource_id = fields.Many2one('aps.resources', string='Resource', required=True)
