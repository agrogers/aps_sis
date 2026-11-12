import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


_PAST_PAPER_TYPE = 'Past Paper'
_PAST_PAPER_QUESTION_TYPE = 'Question (Past Paper)'


class APSResource(models.Model):
    _inherit = 'aps.resources'

    @api.model
    def _get_past_paper_question_name(self, paper, question):
        display_name = question.display_name or question.name or ''
        separator = ' 🢒 '
        name_parts = [part.strip() for part in display_name.split(separator)]
        paper_name = paper.name or ''
        paper_index = next(
            (
                index
                for index in range(len(name_parts) - 1, -1, -1)
                if name_parts[index] == paper_name
            ),
            None,
        )
        if paper_index is not None and paper_index < len(name_parts) - 1:
            return separator.join(name_parts[paper_index + 1:])

        paper_display_name = paper.display_name or paper_name
        prefix = f'{paper_display_name}{separator}'
        if paper_display_name and display_name.startswith(prefix):
            suffix = display_name[len(prefix):].strip()
            if suffix:
                return suffix
        return display_name.strip() or question.name or ''

    @api.model
    def _get_past_paper_questions_in_resource_order(self, paper, descendants):
        ordered_questions = []
        visited = {paper.id}

        def visit(resource):
            children = (resource.child_ids & descendants).sorted(
                key=lambda child: (child.sequence or 0, child.id)
            )
            for child in children:
                if child.id in visited:
                    continue
                visited.add(child.id)
                if (
                    child.type_id
                    and (child.type_id.name or '').strip().casefold()
                    == _PAST_PAPER_QUESTION_TYPE.casefold()
                ):
                    ordered_questions.append(child)
                visit(child)

        visit(paper)
        return ordered_questions

    @api.model
    def _get_past_paper_submission_views(self, role):
        if role == 'student':
            return [
                [
                    self.env.ref(
                        'aps_sis.view_aps_resource_submission_list_for_students'
                    ).id,
                    'list',
                ],
                [
                    self.env.ref(
                        'aps_sis.view_aps_resource_submission_form_for_students'
                    ).id,
                    'form',
                ],
            ]
        return [
            [self.env.ref('aps_sis.view_aps_resource_submission_list').id, 'list'],
            [self.env.ref('aps_sis.view_aps_resource_submission_form').id, 'form'],
        ]

    @api.model
    def _get_past_paper_progress_scope(self, category_id=False, student_id=False):
        user = self.env.user
        if user.has_group('aps_sis.group_aps_teacher'):
            role = 'teacher'
            enrolled_subjects = self.env['aps.subject']
        elif (
            user.has_group('aps_sis.group_aps_student')
            and user.partner_id.is_student
        ):
            role = 'student'
            student = self.env['aps.student'].search(
                [('partner_id', '=', user.partner_id.id)],
                limit=1,
            )
            enrolled_subjects = student.enrollment_ids.filtered(
                lambda enrollment: enrollment.state == 'enrolled'
            ).mapped('class_id.subject_id')
        else:
            raise AccessError(_('You are not allowed to view Past Paper progress.'))

        papers = self.search([('type_id.name', '=', _PAST_PAPER_TYPE)])
        if role == 'student':
            papers = papers.filtered(
                lambda paper: bool(paper.subjects & enrolled_subjects)
            )
            students = self.env['res.partner']
            applicable_subjects = papers.mapped('subjects') & enrolled_subjects
            categories = applicable_subjects.mapped('category_id').sorted('name')
        else:
            subject_ids = papers.mapped('subjects').ids
            enrollments = self.env['aps.student.class'].search([
                ('state', '=', 'enrolled'),
                ('class_id.subject_id', 'in', subject_ids),
            ])
            students = enrollments.mapped('student_id.partner_id').filtered(
                lambda partner: partner.is_student
            )
            if student_id:
                try:
                    student_id = int(student_id)
                except (TypeError, ValueError):
                    raise UserError(_('Select a valid student.'))
                selected_student = self.env['res.partner'].browse(
                    student_id
                ).exists()
                if not selected_student or selected_student not in students:
                    raise AccessError(
                        _('The selected student is not currently enrolled in a Past Paper subject.')
                    )
                student_record = self.env['aps.student'].search(
                    [('partner_id', '=', selected_student.id)],
                    limit=1,
                )
                enrolled_subjects = student_record.enrollment_ids.filtered(
                    lambda enrollment: enrollment.state == 'enrolled'
                ).mapped('class_id.subject_id')
                papers = papers.filtered(
                    lambda paper: bool(paper.subjects & enrolled_subjects)
                )
                applicable_subjects = papers.mapped('subjects') & enrolled_subjects
                categories = applicable_subjects.mapped('category_id').sorted('name')
            else:
                papers = self.browse()
                categories = self.env['aps.subject.category']
                category_id = False

        if category_id:
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                raise UserError(_('Select a valid subject category.'))
            category = self.env['aps.subject.category'].browse(category_id).exists()
            if not category or category not in categories:
                if role == 'student':
                    raise AccessError(_('You are not enrolled in this Past Paper category.'))
                raise UserError(_('The selected category has no Past Papers.'))
            papers = papers.filtered(
                lambda paper: category in (
                    paper.subjects & enrolled_subjects
                ).mapped('category_id')
            )

        return role, papers, categories, students

    @api.model
    def get_past_paper_progress_data(self, category_id=False, student_id=False):
        role, papers, categories, students = self._get_past_paper_progress_scope(
            category_id,
            student_id,
        )
        selected_category_id = int(category_id) if category_id else False
        if role == 'student':
            student = self.env.user.partner_id
        elif student_id:
            try:
                student_id = int(student_id)
            except (TypeError, ValueError):
                raise UserError(_('Select a valid student.'))
            student = self.env['res.partner'].browse(student_id).exists()
            if not student or student not in students:
                raise AccessError(_('The selected student is not enrolled in this category.'))
        else:
            student = self.env['res.partner']

        if not student:
            return {
                'role': role,
                'categories': [
                    {'id': category.id, 'name': category.display_name}
                    for category in categories
                ],
                'students': [
                    {'id': partner.id, 'name': partner.display_name}
                    for partner in students.sorted(
                        key=lambda partner: (partner.display_name or '').casefold()
                    )
                ],
                'student_id': False,
                'papers': [],
                'submission_views': self._get_past_paper_submission_views(role),
            }

        descendants_by_paper = {}
        questions_by_paper = {}
        related_resource_ids = set()
        for paper in papers:
            descendants = paper._get_all_descendant_resources()
            questions = self._get_past_paper_questions_in_resource_order(
                paper,
                descendants,
            )
            descendants_by_paper[paper.id] = descendants
            questions_by_paper[paper.id] = questions
            related_resource_ids.update((paper | descendants).ids)

        task_map = {}
        if related_resource_ids:
            tasks = self.env['aps.resource.task'].search([
                ('resource_id', 'in', list(related_resource_ids)),
                ('student_id', '=', student.id),
            ])
            task_map = {task.resource_id.id: task for task in tasks}

        submissions_by_resource = {}
        if related_resource_ids:
            submissions = self.env['aps.resource.submission'].search([
                ('task_id.resource_id', 'in', list(related_resource_ids)),
                ('task_id.student_id', '=', student.id),
            ], order='id desc')
            for submission in submissions:
                submissions_by_resource.setdefault(
                    submission.resource_id.id,
                    self.env['aps.resource.submission'],
                )
                submissions_by_resource[submission.resource_id.id] |= submission

        paper_data = []
        for paper in papers.sorted(key=lambda resource: (resource.sequence, resource.name or '')):
            questions = questions_by_paper[paper.id]
            question_data = []
            minimum_attempts = min(
                (task_map.get(question.id).submission_count or 0
                 if task_map.get(question.id) else 0)
                for question in questions
            ) if questions else 0
            any_attempts = any(
                (task_map[question.id].submission_count or 0) > 0
                for question in questions
                if question.id in task_map
            )

            for question in questions:
                question_index = len(question_data) + 1
                task = task_map.get(question.id)
                question_descendants = question._get_all_descendant_resources()
                question_name = self._get_past_paper_question_name(paper, question)
                question_number_match = re.search(
                    r'\bQ\s*(\d+)',
                    question_name,
                    re.IGNORECASE,
                )
                question_data.append({
                    'id': question.id,
                    'name': question_name,
                    'number': (
                        int(question_number_match.group(1))
                        if question_number_match
                        else question_index
                    ),
                    'description': question.description or '',
                    'out_of': question.marks or 0.0,
                    'attempts': task.submission_count if task else 0,
                    'weighted_result': task.weighted_result if task else False,
                    'has_children': bool(question.child_ids),
                    'related_resource_ids': (question | question_descendants).ids,
                })

            paper_subjects = paper.subjects
            if selected_category_id:
                category_subjects = paper_subjects.filtered(
                    lambda subject: subject.category_id.id == selected_category_id
                )
                if category_subjects:
                    paper_subjects = category_subjects
            paper_subject = paper_subjects.sorted('name')[:1]
            subject_icon_url = False
            if paper_subject and paper_subject.icon:
                subject_icon_url = (
                    f'/web/image/aps.subject/{paper_subject.id}/icon'
                )
            elif paper_subject and paper_subject.category_id.icon:
                subject_icon_url = (
                    '/web/image/aps.subject.category/'
                    f'{paper_subject.category_id.id}/icon'
                )

            paper_resource_ids = set(
                (paper | descendants_by_paper[paper.id]).ids
            )
            related_submissions = self.env['aps.resource.submission']
            for resource_id in paper_resource_ids:
                related_submissions |= submissions_by_resource.get(
                    resource_id,
                    self.env['aps.resource.submission'],
                )
            submissions_by_parent_id = {}
            for submission in related_submissions:
                parent_id = submission.parent_submission_id.id
                if parent_id:
                    submissions_by_parent_id.setdefault(
                        parent_id,
                        self.env['aps.resource.submission'],
                    )
                    submissions_by_parent_id[parent_id] |= submission

            paper_question_ids = {question.id for question in questions}
            history = []
            root_submissions = related_submissions.filtered(
                lambda submission: submission.resource_id == paper
            )
            for root_submission in root_submissions:
                visited_submission_ids = {root_submission.id}
                submission_stack = [root_submission]
                descendant_submissions = self.env['aps.resource.submission']
                while submission_stack:
                    parent_submission = submission_stack.pop()
                    children = submissions_by_parent_id.get(
                        parent_submission.id,
                        self.env['aps.resource.submission'],
                    )
                    for child_submission in children:
                        if child_submission.id in visited_submission_ids:
                            continue
                        visited_submission_ids.add(child_submission.id)
                        submission_stack.append(child_submission)
                        descendant_submissions |= child_submission

                question_submissions = descendant_submissions.filtered(
                    lambda submission: (
                        submission.resource_id.id in paper_question_ids
                    )
                )
                completed_question_ids = {
                    submission.resource_id.id
                    for submission in question_submissions
                    if submission.state in ('submitted', 'complete')
                }
                label = root_submission.submission_label or (
                    _('Unlabelled submission #%s') % root_submission.id
                )
                history.append({
                    'submission_id': root_submission.id,
                    'label': label,
                    'result': (
                        root_submission.result_percent
                        if root_submission.score != -0.01
                        else False
                    ),
                    'completed_questions': len(completed_question_ids),
                    'total_questions': len(questions),
                    'submission_ids': sorted(
                        [root_submission.id] + question_submissions.ids
                    ),
                })
            history.sort(
                key=lambda item: item['submission_id'],
                reverse=True,
            )
            partial_attempts = sum(
                1 for attempt in history
                if 0 < attempt['completed_questions'] < attempt['total_questions']
            )

            paper_task = task_map.get(paper.id)
            paper_data.append({
                'id': paper.id,
                'name': paper.name or paper.display_name or '',
                'thumbnail_url': (
                    f'/web/image/aps.resources/{paper.id}/thumbnail'
                    if paper.thumbnail else False
                ),
                'subject_icon_url': subject_icon_url,
                'subject_name': (
                    paper_subject.name if paper_subject else ''
                ),
                'weighted_result': (
                    paper_task.weighted_result if paper_task else False
                ),
                'completed_paper_attempts': minimum_attempts,
                'partial_paper_attempts': partial_attempts,
                'has_attempts': any_attempts,
                'question_count': len(questions),
                'attempted_question_count': sum(
                    1 for question in question_data if question['attempts'] > 0
                ),
                'questions': question_data,
                'related_resource_ids': sorted(paper_resource_ids),
                'history': history,
            })

        return {
            'role': role,
            'categories': [
                {'id': category.id, 'name': category.display_name}
                for category in categories
            ],
            'students': [
                {'id': partner.id, 'name': partner.display_name}
                for partner in students.sorted(
                    key=lambda partner: (partner.display_name or '').casefold()
                )
            ],
            'student_id': student.id,
            'papers': paper_data,
            'submission_views': self._get_past_paper_submission_views(role),
        }

    @api.model
    def action_assign_past_paper(self, paper_id, student_id=False, category_id=False):
        return self._assign_past_paper_resource(
            paper_id,
            student_id,
            category_id,
        )

    @api.model
    def action_assign_past_paper_question(
        self,
        paper_id,
        question_id,
        student_id=False,
        category_id=False,
    ):
        if question_id is False or question_id is None:
            raise UserError(_('Select a valid Past Paper question.'))
        return self._assign_past_paper_resource(
            paper_id,
            student_id,
            category_id,
            question_id=question_id,
        )

    def _assign_past_paper_resource(
        self,
        paper_id,
        student_id=False,
        category_id=False,
        question_id=False,
    ):
        role, papers, _categories, students = self._get_past_paper_progress_scope(
            category_id,
            student_id,
        )
        if role == 'teacher' and not student_id:
            raise UserError(_('Select a student before assigning this Past Paper.'))
        try:
            paper_id = int(paper_id)
        except (TypeError, ValueError):
            raise UserError(_('Select a valid Past Paper.'))
        paper = self.browse(paper_id).exists()
        if not paper or paper not in papers:
            raise AccessError(_('You are not allowed to assign this Past Paper.'))
        assignment_resource = paper
        if question_id is not False and question_id is not None:
            try:
                question_id = int(question_id)
            except (TypeError, ValueError):
                raise UserError(_('Select a valid Past Paper question.'))
            question = self.browse(question_id).exists()
            question_type = (
                question.type_id.name.strip().casefold()
                if question and question.type_id.name
                else ''
            )
            if (
                not question
                or question not in paper._get_all_descendant_resources()
                or question_type != _PAST_PAPER_QUESTION_TYPE.casefold()
            ):
                raise AccessError(
                    _('You are not allowed to assign this Past Paper question.')
                )
            assignment_resource = question

        if role == 'student':
            if student_id:
                try:
                    requested_student_id = int(student_id)
                except (TypeError, ValueError):
                    raise UserError(_('Select a valid student.'))
                if requested_student_id != self.env.user.partner_id.id:
                    raise AccessError(
                        _('Students can only start their own Past Papers.')
                    )
            student = self.env.user.partner_id
        else:
            if not student_id:
                raise UserError(_('Select a student before assigning this Past Paper.'))
            try:
                student_id = int(student_id)
            except (TypeError, ValueError):
                raise UserError(_('Select a student before assigning this Past Paper.'))
            student = self.env['res.partner'].browse(student_id).exists()
            if not student or student not in students:
                raise AccessError(_('The selected student is not enrolled in this category.'))

        today = fields.Date.today()
        base_label = f'{paper.display_name or paper.name} ({today})'
        all_resources = paper | paper._get_all_descendant_resources()
        submission_model = self.env['aps.resource.submission']
        existing_labels = set(submission_model.sudo().search([
            ('task_id.resource_id', 'in', all_resources.ids),
            ('task_id.student_id', '=', student.id),
        ]).mapped('submission_label'))
        label = base_label
        suffix = 2
        while label in existing_labels:
            label = f'{base_label} #{suffix}'
            suffix += 1

        classes = self.env['aps.class'].search([
            ('academic_year_id.is_current', '=', True),
            ('subject_id', 'in', paper.subjects.ids),
        ])
        wizard_model = self.env['aps.assign.students.wizard']
        if role == 'student':
            wizard_model = wizard_model.sudo()
        wizard_model = wizard_model.with_context(
            default_resource_id=assignment_resource.id
        )
        wizard_values = wizard_model.default_get([
            'resource_id',
            'date_assigned',
            'date_due',
            'time_assigned',
            'custom_submission_name',
            'submission_label',
            'assigned_by',
            'url',
            'allow_subject_editing',
            'has_question',
            'question',
            'has_answer',
            'answer',
            'has_default_answer',
            'default_answer',
            'points_scale',
            'permit_resubmission',
            'exam_condition',
            'class_ids',
        ])
        wizard_values.update({
            'resource_id': assignment_resource.id,
            'class_ids': [(6, 0, classes.ids)],
            'student_ids': [(6, 0, [student.id])],
            'student_line_ids': [(0, 0, {'student_id': student.id})],
            'notify_student': False,
            'submission_label': label,
        })
        wizard = wizard_model.new(wizard_values)
        wizard._onchange_resource_id()
        wizard._onchange_has_question()
        wizard.class_ids = [(6, 0, classes.ids)]
        wizard.student_ids = [(6, 0, [student.id])]
        wizard.student_line_ids = (
            [(5, 0, 0)] + wizard._build_student_lines(student)
        )

        root_line = wizard.affected_resource_line_ids.filtered(
            lambda line: line.resource_id == assignment_resource
        )
        if not root_line:
            raise UserError(_('The assignment could not be prepared.'))
        for line in wizard.affected_resource_line_ids:
            is_past_paper_question = (
                line.resource_id.type_id
                and (line.resource_id.type_id.name or '').strip().casefold()
                == _PAST_PAPER_QUESTION_TYPE.casefold()
            )
            if question_id:
                line.selected = line.resource_id == assignment_resource
            elif line.resource_id == assignment_resource or is_past_paper_question:
                line.selected = True

        wizard.action_assign_students()
        created_submissions = submission_model.search([
            ('task_id.resource_id', 'in', all_resources.ids),
            ('task_id.student_id', '=', student.id),
            ('submission_label', '=', label),
        ], order='submission_order, id')
        if not created_submissions:
            raise UserError(_('No submissions were created for this resource.'))

        first_question = created_submissions.filtered(
            lambda submission: submission.resource_id.type_id
            and (submission.resource_id.type_id.name or '').strip().casefold()
            == _PAST_PAPER_QUESTION_TYPE.casefold()
        )[:1]
        submission_to_open = first_question or created_submissions.filtered(
            lambda submission: submission.resource_id == assignment_resource
        )[:1]
        if not submission_to_open:
            raise UserError(_('The assignment has no submission to open.'))

        return (
            submission_to_open.action_open_submission_student_view()
            if role == 'student'
            else submission_to_open.action_open_submission()
        )
