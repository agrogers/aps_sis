import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSSubmitMarkWizard(models.TransientModel):
    """Wizard that allows a student (or teacher on behalf of a student) to record
    the score they achieved on a past-paper question resource.

    * For students: ``student_id`` is auto-populated from the logged-in user's
      partner and cannot be changed.
    * For teachers: ``student_id`` is an editable dropdown.

    Workflow
    --------
    1. Select student (teachers only) → subject → resource.
    2. Enter score and optional confidence rating.
    3. Click *Submit* (or *Submit and Add Another*).

    If the resource already exists in the system a task is found-or-created for
    the (student, resource) pair and a new submission is recorded.

    If the resource does NOT exist yet (the checkbox is ticked), a *To-Do*
    activity is scheduled for every APS Manager so they can create the resource
    and assign the mark manually.
    """

    _name = 'aps.submit.mark.wizard'
    _description = 'APEX Submit Mark Wizard'

    # ── Identity helpers ──────────────────────────────────────────────────────

    is_teacher = fields.Boolean(compute='_compute_is_teacher', store=False)

    @api.depends()
    def _compute_is_teacher(self):
        is_teacher = self.env.user.has_group('aps_sis.group_aps_teacher')
        for rec in self:
            rec.is_teacher = is_teacher

    # ── Core wizard fields ────────────────────────────────────────────────────

    student_id = fields.Many2one(
        'res.partner',
        string='Student',
        domain=[('is_student', '=', True)],
        help='The student who achieved this mark.',
    )

    available_subject_ids = fields.Many2many(
        'op.subject',
        compute='_compute_available_subject_ids',
        string='Available Subjects',
        help='Subjects the selected student is currently enrolled in.',
    )

    subject_id = fields.Many2one(
        'op.subject',
        string='Subject',
        help='Subject the resource belongs to.',
    )

    resource_id = fields.Many2one(
        'aps.resources',
        string='Resource',
        help='The past-paper question resource the student completed.',
    )

    resource_does_not_exist = fields.Boolean(
        string='Resource does not yet exist',
        default=False,
        help='Tick if the resource has not been created in APEX yet. '
             'An activity will be sent to the APS Manager to create it.',
    )

    resource_name = fields.Char(
        string='Resource Name',
        help='Name of the resource if it does not yet exist in the system.',
    )

    score = fields.Float(
        string='Mark',
        digits=(16, 2),
        help='Score the student achieved on this resource.',
    )

    out_of_marks = fields.Float(
        string='Out of',
        digits=(16, 1),
        compute='_compute_out_of_marks',
        store=False,
        help='Maximum marks for the selected resource (for reference only).',
    )

    confidence_rating = fields.Selection(
        selection=[
            ('1', '1 – Very Low'),
            ('2', '2 – Low'),
            ('3', '3 – Moderate'),
            ('4', '4 – High'),
            ('5', '5 – Very High'),
        ],
        string='Confidence Rating',
        default=False,
        help='How confident the student felt about this resource (optional, 1–5 scale).',
    )

    # ── Computed helpers ──────────────────────────────────────────────────────

    @api.depends('student_id')
    def _compute_available_subject_ids(self):
        """Collect subjects from the student's currently-running course enrolments."""
        for rec in self:
            if not rec.student_id:
                rec.available_subject_ids = [(5, 0, 0)]
                continue
            student_record = self.env['op.student'].sudo().search(
                [('partner_id', '=', rec.student_id.id)], limit=1
            )
            if student_record:
                running_courses = student_record.course_detail_ids.filtered(
                    lambda c: c.state == 'running'
                )
                subject_ids = running_courses.mapped('subject_ids').ids
            else:
                subject_ids = []
            rec.available_subject_ids = [(6, 0, subject_ids)]

    @api.depends('resource_id')
    def _compute_out_of_marks(self):
        for rec in self:
            rec.out_of_marks = rec.resource_id.marks if rec.resource_id else 0.0

    # ── Onchange helpers ──────────────────────────────────────────────────────

    @api.onchange('student_id')
    def _onchange_student_id(self):
        """Reset subject and resource when the student changes."""
        self.subject_id = False
        self.resource_id = False

    @api.onchange('subject_id')
    def _onchange_subject_id(self):
        """Reset resource when the subject changes."""
        self.resource_id = False

    @api.onchange('resource_does_not_exist')
    def _onchange_resource_does_not_exist(self):
        if self.resource_does_not_exist:
            self.resource_id = False

    # ── Default get ───────────────────────────────────────────────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # For student users, pre-fill with their own partner record
        if not self.env.user.has_group('aps_sis.group_aps_teacher'):
            partner = self.env.user.partner_id
            if partner.is_student:
                res['student_id'] = partner.id
        return res

    # ── Submission logic ──────────────────────────────────────────────────────

    def _validate(self):
        """Raise a UserError if required data is missing."""
        if not self.student_id:
            raise UserError(_('Please select a student.'))
        if not self.subject_id:
            raise UserError(_('Please select a subject.'))
        if self.resource_does_not_exist:
            if not self.resource_name:
                raise UserError(
                    _('Please enter the name of the resource that does not yet exist.')
                )
        else:
            if not self.resource_id:
                raise UserError(_('Please select a resource.'))

    def _create_submission(self):
        """Core logic: create task+submission or schedule a manager activity."""
        self.ensure_one()
        self._validate()

        if self.resource_does_not_exist:
            self._notify_manager_resource_missing()
            return

        Task = self.env['aps.resource.task']
        Submission = self.env['aps.resource.submission']

        # Find or create the task for this (student, resource) pair
        task = Task.search([
            ('resource_id', '=', self.resource_id.id),
            ('student_id', '=', self.student_id.id),
        ], limit=1)
        if not task:
            task = Task.create({
                'resource_id': self.resource_id.id,
                'student_id': self.student_id.id,
            })

        today = fields.Date.today()
        # confidence_rating in the wizard is a Selection string ('1'-'5') or False;
        # the submission model stores it as an Integer (0 = not set, 1-5 = rated).
        _confidence_map = {'1': 1, '2': 2, '3': 3, '4': 4, '5': 5}
        confidence = _confidence_map.get(self.confidence_rating, 0)

        Submission.create({
            'task_id': task.id,
            'date_assigned': today,
            'date_submitted': today,
            'state': 'submitted',
            'score': self.score if self.score else 0.0,
            'out_of_marks': self.resource_id.marks or 0.0,
            'confidence_rating': confidence,
            'subjects': [(6, 0, self.subject_id.ids)],
            'submission_active': True,
            'submission_name': self.resource_id.display_name or self.resource_id.name,
            'points_scale': self.resource_id.points_scale or 1,
            'auto_score': False,
        })

    def _notify_manager_resource_missing(self):
        """Schedule a To-Do activity for each APS Manager user."""
        manager_group = self.env.ref('aps_sis.group_aps_manager', raise_if_not_found=False)
        manager_users = manager_group.users if manager_group else self.env['res.users']

        if not manager_users:
            _logger.warning(
                'APSSubmitMarkWizard: no APS Manager users found – '
                'cannot schedule resource-missing activity.'
            )
            return

        # We attach the activity to the first resource we can find (aps.resources has
        # mail.activity.mixin).  Fall back to just logging if none exist yet.
        anchor = self.env['aps.resources'].search([], limit=1)
        if not anchor:
            _logger.warning(
                'APSSubmitMarkWizard: no aps.resources records found – '
                'cannot attach activity.  Data: student=%s subject=%s resource_name=%s score=%s',
                self.student_id.display_name,
                self.subject_id.name,
                self.resource_name,
                self.score,
            )
            return

        confidence_label = dict(self._fields['confidence_rating'].selection).get(
            self.confidence_rating, _('Not set')
        )

        note = _(
            '<p>A student submitted a mark for a resource that does not yet exist in APEX.</p>'
            '<ul>'
            '<li><strong>Student:</strong> %(student)s</li>'
            '<li><strong>Subject:</strong> %(subject)s</li>'
            '<li><strong>Resource name:</strong> %(resource_name)s</li>'
            '<li><strong>Score:</strong> %(score)s</li>'
            '<li><strong>Confidence rating:</strong> %(confidence)s</li>'
            '</ul>'
            '<p>Please create the resource and assign the mark.</p>'
        ) % {
            'student': self.student_id.display_name,
            'subject': self.subject_id.name,
            'resource_name': self.resource_name,
            'score': self.score,
            'confidence': confidence_label,
        }

        for manager_user in manager_users:
            anchor.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager_user.id,
                summary=_('Create resource and assign mark: %(name)s (%(student)s)') % {
                    'name': self.resource_name,
                    'student': self.student_id.display_name,
                },
                note=note,
                date_deadline=fields.Date.today(),
            )

    # ── Action buttons ────────────────────────────────────────────────────────

    def action_submit(self):
        """Submit the mark and close the dialog."""
        self._create_submission()
        return {'type': 'ir.actions.act_window_close'}

    def action_submit_and_another(self):
        """Submit the mark and reopen the wizard to enter another one."""
        self._create_submission()

        # Reopen the same dialog, preserving student + subject for convenience
        ctx = dict(self.env.context)
        ctx.update({
            'default_student_id': self.student_id.id,
            'default_subject_id': self.subject_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aps.submit.mark.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': ctx,
        }
