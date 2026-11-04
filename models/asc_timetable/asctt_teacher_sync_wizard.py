from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ASCTTTeacherSyncWizard(models.TransientModel):
    _name = 'asctt.teacher.sync.wizard'
    _description = 'Sync aSc Class Teachers'

    start_date = fields.Date(string='From', readonly=True)
    end_date = fields.Date(string='To', readonly=True)
    line_ids = fields.One2many(
        'asctt.teacher.sync.wizard.line',
        'wizard_id',
        string='Class Teacher Differences',
    )
    issue_names = fields.Text(
        string='Items with Issues',
        readonly=True,
    )
    synced_class_names = fields.Text(
        string='Already Synced Classes',
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        context = self.env.context
        academic_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        start_date = (
            fields.Date.to_date(context.get('default_start_date'))
            or (academic_year.start_date if academic_year else fields.Date.today())
        )
        end_date = (
            fields.Date.to_date(context.get('default_end_date'))
            or (academic_year.end_date if academic_year else start_date)
        )
        if 'start_date' in fields_list:
            values['start_date'] = start_date
        if 'end_date' in fields_list:
            values['end_date'] = end_date
        if (
            'line_ids' in fields_list
            or 'issue_names' in fields_list
            or 'synced_class_names' in fields_list
        ):
            line_values, issues, synced_classes, _sync_assignments = (
                self._get_sync_line_values(start_date, end_date)
            )
            if 'line_ids' in fields_list:
                values['line_ids'] = [(0, 0, line) for line in line_values]
            if 'issue_names' in fields_list:
                values['issue_names'] = '\n'.join(issues)
            if 'synced_class_names' in fields_list:
                values['synced_class_names'] = '\n'.join(synced_classes)
        return values

    @api.model
    def action_open(self, default_context=None):
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Sync Class Teachers'),
            'res_model': self._name,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'aps_sis.asctt_teacher_sync_wizard_view_form'
            ).id,
            'target': 'new',
        }
        if default_context:
            action['context'] = default_context
        return action

    @api.model
    def _get_sync_line_values(self, start_date, end_date):
        """Build one comparison row for each APEX class resolved from aSc lessons."""
        assignments = {}
        issues = set()
        synced_classes = []
        lessons = self.env['asctt.lesson'].search([
            ('class_ids', '!=', False),
        ])

        for lesson in lessons:
            subject_category = (
                lesson.subject_id.aps_subject_category_id
                if lesson.subject_id else False
            )
            if not subject_category:
                for asctt_class in lesson.class_ids:
                    subject_name = lesson.subject_id.display_name if lesson.subject_id else _('Unknown subject')
                    issues.add(
                        _('%(class)s / %(subject)s (no APEX subject category)')
                        % {
                            'class': asctt_class.display_name,
                            'subject': subject_name,
                        }
                    )
                continue

            for asctt_class in lesson.class_ids:
                aps_class = asctt_class._get_aps_class_for_subject(
                    subject_category,
                    start_date,
                    end_date,
                )
                if not aps_class:
                    issues.add(
                        _('%(class)s / %(subject)s (no matching APEX class)')
                        % {
                            'class': asctt_class.display_name,
                            'subject': lesson.subject_id.display_name,
                        }
                    )
                    continue
                assignment = assignments.setdefault(aps_class.id, {
                    'aps_class': aps_class,
                    'asctt_classes': set(),
                    'subjects': set(),
                    'teacher_ids': set(),
                    'assistant_teacher_ids': set(),
                    'unmapped_teacher_names': set(),
                    'issues': set(),
                })
                assignment['asctt_classes'].add(asctt_class.display_name)
                assignment['subjects'].add(lesson.subject_id.display_name)
                if not lesson.teacher_ids:
                    issue = (
                        _('%(class)s / %(subject)s (no teachers assigned in aSc)')
                        % {
                            'class': asctt_class.display_name,
                            'subject': lesson.subject_id.display_name,
                        }
                    )
                    assignment['issues'].add(issue)
                    issues.add(issue)
                    continue

                teachers_by_id = {
                    teacher.id: teacher for teacher in lesson.teacher_ids
                }
                ordered_teacher_ids = []
                for value in (lesson.teacher_order or '').split(','):
                    try:
                        teacher_id = int(value.strip())
                    except (TypeError, ValueError):
                        continue
                    if teacher_id in teachers_by_id and teacher_id not in ordered_teacher_ids:
                        ordered_teacher_ids.append(teacher_id)
                ordered_teacher_ids.extend(
                    teacher_id
                    for teacher_id in sorted(teachers_by_id)
                    if teacher_id not in ordered_teacher_ids
                )

                for index, teacher_id in enumerate(ordered_teacher_ids):
                    teacher = teachers_by_id[teacher_id]
                    partner = (
                        teacher.aps_teacher_id.partner_id
                        if teacher.aps_teacher_id else False
                    )
                    if not partner:
                        assignment['unmapped_teacher_names'].add(
                            teacher.display_name
                        )
                    elif index == 0:
                        assignment['teacher_ids'].add(partner.id)
                    else:
                        assignment['assistant_teacher_ids'].add(partner.id)

        line_values = []
        sync_assignments = {}
        Partner = self.env['res.partner']
        for assignment in assignments.values():
            teacher_ids = assignment['teacher_ids']
            assistant_teacher_ids = (
                assignment['assistant_teacher_ids'] - teacher_ids
            )
            aps_class = assignment['aps_class']
            unmapped_names = sorted(assignment['unmapped_teacher_names'])
            if unmapped_names:
                issue = (
                    _('%(apex_class)s — unmapped aSc teachers: %(teachers)s')
                    % {
                        'apex_class': aps_class.display_name,
                        'teachers': ', '.join(unmapped_names),
                    }
                )
                assignment['issues'].add(issue)
                issues.add(issue)
            sync_assignments[aps_class.id] = {
                'teacher_ids': sorted(teacher_ids),
                'assistant_teacher_ids': sorted(assistant_teacher_ids),
                'issues': sorted(assignment['issues']),
            }
            has_differences = (
                teacher_ids != set(aps_class.teacher_ids.ids)
                or assistant_teacher_ids
                != set(aps_class.assistant_teacher_ids.ids)
            )
            if not has_differences and not assignment['issues']:
                synced_classes.append(
                    _('%(apex_class)s — aSc classes: %(asctt_classes)s')
                    % {
                        'apex_class': aps_class.display_name,
                        'asctt_classes': ', '.join(
                            sorted(assignment['asctt_classes'])
                        ),
                    }
                )
                continue
            if not has_differences:
                continue

            teachers = Partner.browse(sorted(teacher_ids))
            assistant_teachers = Partner.browse(sorted(assistant_teacher_ids))
            current_teachers = aps_class.teacher_ids
            current_assistant_teachers = aps_class.assistant_teacher_ids
            line_values.append({
                'selected': not assignment['issues'],
                'aps_class_id': aps_class.id,
                'asctt_class_names': ', '.join(sorted(assignment['asctt_classes'])),
                'source_subject_names': ', '.join(sorted(assignment['subjects'])),
                'source_teacher_ids': [(6, 0, teachers.ids)],
                'source_assistant_teacher_ids': [(6, 0, assistant_teachers.ids)],
                'current_teacher_names': ', '.join(current_teachers.mapped('name')),
                'current_assistant_teacher_names': ', '.join(
                    current_assistant_teachers.mapped('name')
                ),
                'source_teacher_names': ', '.join(teachers.mapped('name')),
                'source_assistant_teacher_names': ', '.join(
                    assistant_teachers.mapped('name')
                ),
                'unmapped_teacher_names': ', '.join(unmapped_names),
            })

        return line_values, sorted(issues), sorted(synced_classes), sync_assignments

    def action_apply(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('Select at least one class to sync.'))

        _line_values, _issues, _synced_classes, sync_assignments = (
            self._get_sync_line_values(self.start_date, self.end_date)
        )
        blocked_lines = []
        for line in selected_lines:
            assignment = sync_assignments.get(line.aps_class_id.id)
            if not assignment:
                class_name = (
                    line.aps_class_id.display_name
                    or line.asctt_class_names
                    or _('Sync line %s') % line.id
                )
                blocked_lines.append(
                    _('%s: no longer matches an aSc class') % class_name
                )
            elif assignment['issues']:
                blocked_lines.append(
                    '%s: %s' % (
                        line.aps_class_id.display_name,
                        ', '.join(assignment['issues']),
                    )
                )
        if blocked_lines:
            details = '\n'.join(
                blocked_lines
            )
            raise UserError(_(
                'Resolve these aSc class or teacher issues before syncing:\n%s'
            ) % details)

        updated_count = 0
        for line in selected_lines:
            assignment = sync_assignments[line.aps_class_id.id]
            teacher_ids = assignment['teacher_ids']
            assistant_teacher_ids = assignment['assistant_teacher_ids']
            aps_class = line.aps_class_id.exists()
            if not aps_class:
                raise UserError(_('An APEX class selected for syncing no longer exists.'))
            aps_class.write({
                'teacher_ids': [(6, 0, teacher_ids)],
                'assistant_teacher_ids': [
                    (6, 0, assistant_teacher_ids)
                ],
            })
            aps_class.invalidate_recordset([
                'teacher_ids',
                'assistant_teacher_ids',
            ])
            if (
                set(aps_class.teacher_ids.ids) != set(teacher_ids)
                or set(aps_class.assistant_teacher_ids.ids)
                != set(assistant_teacher_ids)
            ):
                raise UserError(
                    _('Could not verify teacher assignments for %s after writing.')
                    % aps_class.display_name
                )
            updated_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Class Teachers Synced'),
                'message': _('Updated and verified teacher assignments for %d class(es).')
                % updated_count,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ASCTTTeacherSyncWizardLine(models.TransientModel):
    _name = 'asctt.teacher.sync.wizard.line'
    _description = 'aSc Class Teacher Sync Line'

    wizard_id = fields.Many2one(
        'asctt.teacher.sync.wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Sync', default=True)
    aps_class_id = fields.Many2one(
        'aps.class',
        string='APEX Class',
        readonly=True,
    )
    asctt_class_names = fields.Char(string='aSc Classes', readonly=True)
    source_subject_names = fields.Char(string='aSc Subjects', readonly=True)
    current_teacher_names = fields.Char(string='APEX Teachers', readonly=True)
    current_assistant_teacher_names = fields.Char(
        string='APEX Assistant Teachers',
        readonly=True,
    )
    source_teacher_names = fields.Char(string='aSc Teachers', readonly=True)
    source_assistant_teacher_names = fields.Char(
        string='aSc Assistant Teachers',
        readonly=True,
    )
    unmapped_teacher_names = fields.Char(
        string='Unmapped aSc Teachers',
        readonly=True,
    )
    source_teacher_ids = fields.Many2many(
        'res.partner',
        'asctt_teacher_sync_line_teacher_rel',
        'line_id',
        'partner_id',
        string='Teachers to Set',
    )
    source_assistant_teacher_ids = fields.Many2many(
        'res.partner',
        'asctt_teacher_sync_line_assistant_rel',
        'line_id',
        'partner_id',
        string='Assistant Teachers to Set',
    )
