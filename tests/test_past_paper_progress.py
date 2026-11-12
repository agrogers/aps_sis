from types import SimpleNamespace

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestPastPaperProgress(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['aps.subject.category'].create({
            'name': 'Past Paper Progress Category',
        })
        cls.other_category = cls.env['aps.subject.category'].create({
            'name': 'Other Past Paper Progress Category',
        })
        cls.subject = cls.env['aps.subject'].create({
            'name': 'Past Paper Progress Subject',
            'category_id': cls.category.id,
        })
        cls.other_subject = cls.env['aps.subject'].create({
            'name': 'Other Past Paper Progress Subject',
            'category_id': cls.other_category.id,
        })

        cls.academic_year = cls.env['aps.academic.year'].search(
            [('is_current', '=', True)],
            limit=1,
        )
        if not cls.academic_year:
            cls.academic_year = cls.env['aps.academic.year'].create({
                'name': 'Past Paper Progress Current Year',
                'short_name': 'PPPCY',
                'start_date': '2026-01-01',
                'end_date': '2026-12-31',
                'is_current': True,
            })
        cls.subject_class = cls.env['aps.class'].create({
            'name': 'Past Paper Progress Class',
            'subject_id': cls.subject.id,
            'academic_year_id': cls.academic_year.id,
        })
        cls.other_subject_class = cls.env['aps.class'].create({
            'name': 'Other Past Paper Progress Class',
            'subject_id': cls.other_subject.id,
            'academic_year_id': cls.academic_year.id,
        })

        cls.student_partner = cls.env['res.partner'].create({
            'name': 'Past Paper Progress Student',
            'is_student': True,
        })
        cls.other_student_partner = cls.env['res.partner'].create({
            'name': 'Other Past Paper Progress Student',
            'is_student': True,
        })
        cls.student = cls._get_student(cls.student_partner)
        cls.other_student = cls._get_student(cls.other_student_partner)
        cls.env['aps.student.class'].create([
            {
                'student_id': cls.student.id,
                'class_id': cls.subject_class.id,
                'state': 'enrolled',
            },
            {
                'student_id': cls.other_student.id,
                'class_id': cls.other_subject_class.id,
                'state': 'enrolled',
            },
        ])

        cls.paper_type = cls._get_resource_type('Past Paper')
        cls.question_type = cls._get_resource_type('Question (Past Paper)')
        cls.paper = cls.env['aps.resources'].create({
            'name': 'Progress Test Past Paper',
            'type_id': cls.paper_type.id,
            'subjects': [(6, 0, cls.subject.ids)],
        })
        cls.question_one = cls.env['aps.resources'].create({
            'name': 'Question One',
            'type_id': cls.question_type.id,
            'subjects': [(6, 0, cls.subject.ids)],
            'parent_ids': [(4, cls.paper.id)],
            'has_question': 'yes',
            'question': '<p>Question one</p>',
            'marks': 10,
        })
        cls.question_two = cls.env['aps.resources'].create({
            'name': 'Question Two',
            'type_id': cls.question_type.id,
            'subjects': [(6, 0, cls.subject.ids)],
            'parent_ids': [(4, cls.paper.id)],
            'has_question': 'yes',
            'question': '<p>Question two</p>',
            'marks': 10,
        })

        cls.student_user = cls._get_user(
            cls.student_partner,
            'aps_sis.group_aps_student',
            'past-paper-progress-student',
        )
        cls.teacher_partner = cls.env['res.partner'].create({
            'name': 'Past Paper Progress Teacher',
            'is_teacher': True,
        })
        cls.subject_class.write({
            'teacher_ids': [(4, cls.teacher_partner.id)],
        })
        cls.teacher_user = cls._get_user(
            cls.teacher_partner,
            'aps_sis.group_aps_teacher',
            'past-paper-progress-teacher',
        )

    @classmethod
    def _get_student(cls, partner):
        student = cls.env['aps.student'].search(
            [('partner_id', '=', partner.id)],
            limit=1,
        )
        return student or cls.env['aps.student'].create({
            'partner_id': partner.id,
        })

    @classmethod
    def _get_resource_type(cls, name):
        resource_type = cls.env['aps.resource.types'].search(
            [('name', '=', name)],
            limit=1,
        )
        return resource_type or cls.env['aps.resource.types'].create({
            'name': name,
        })

    @classmethod
    def _get_user(cls, partner, group_xml_id, login):
        groups = [
            cls.env.ref('base.group_user').id,
            cls.env.ref(group_xml_id).id,
        ]
        return cls.env['res.users'].with_context(
            no_reset_password=True
        ).create({
            'name': partner.name,
            'login': login,
            'partner_id': partner.id,
            'groups_id': [(6, 0, groups)],
        })

    def _create_submission(self, resource, student, label, score, state='complete'):
        task = self.env['aps.resource.task'].search([
            ('resource_id', '=', resource.id),
            ('student_id', '=', student.id),
        ], limit=1)
        if not task:
            task = self.env['aps.resource.task'].create({
                'resource_id': resource.id,
                'student_id': student.id,
            })
        return self.env['aps.resource.submission'].create({
            'task_id': task.id,
            'submission_label': label,
            'submission_name': label,
            'state': state,
            'score': score,
            'out_of_marks': 10,
        })

    def _create_paper_attempt(self, label, questions):
        root_submission = self._create_submission(
            self.paper,
            self.student_partner,
            label,
            8,
        )
        question_submissions = self.env['aps.resource.submission']
        for question in questions:
            question_submission = self._create_submission(
                question,
                self.student_partner,
                label,
                8,
            )
            question_submission.parent_submission_id = root_submission
            question_submissions |= question_submission
        return root_submission, question_submissions

    def test_question_tooltip_name_keeps_every_segment_after_paper_name(self):
        paper = SimpleNamespace(
            name='4BI1-1BR-2019.05',
            display_name='4BI1-1BR-2019.05',
        )
        question = SimpleNamespace(
            name='a.iii',
            display_name=(
                'Biology 🢒 Exams 🢒 Paper 1 🢒 '
                '4BI1-1BR-2019.05 🢒 Q7 🢒 a.iii'
            ),
        )

        tooltip_name = self.env['aps.resources']._get_past_paper_question_name(
            paper,
            question,
        )

        self.assertEqual(tooltip_name, 'Q7 🢒 a.iii')

    def test_questions_follow_parent_then_child_resource_sequence(self):
        paper = self.env['aps.resources'].create({
            'name': 'Ordered Past Paper',
            'type_id': self.paper_type.id,
            'subjects': [(6, 0, self.subject.ids)],
        })
        section_type = self._get_resource_type('Past Paper Section')
        first_section = self.env['aps.resources'].create({
            'name': 'First Section',
            'type_id': section_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, paper.id)],
            'sequence': 10,
        })
        second_section = self.env['aps.resources'].create({
            'name': 'Second Section',
            'type_id': section_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, paper.id)],
            'sequence': 20,
        })
        first_question = self.env['aps.resources'].create({
            'name': 'Q1',
            'type_id': self.question_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, first_section.id)],
            'sequence': 30,
        })
        second_question = self.env['aps.resources'].create({
            'name': 'Q2',
            'type_id': self.question_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, first_section.id)],
            'sequence': 40,
        })
        third_question = self.env['aps.resources'].create({
            'name': 'Q3',
            'type_id': self.question_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, second_section.id)],
            'sequence': 1,
        })

        descendants = paper._get_all_descendant_resources()
        ordered_questions = self.env[
            'aps.resources'
        ]._get_past_paper_questions_in_resource_order(paper, descendants)

        self.assertEqual(
            [question.id for question in ordered_questions],
            [first_question.id, second_question.id, third_question.id],
        )

    def test_student_data_is_limited_to_self_and_enrolled_categories(self):
        self._create_submission(
            self.question_one,
            self.student_partner,
            'Practice A',
            8,
        )
        self._create_submission(
            self.question_two,
            self.other_student_partner,
            'Other Student Attempt',
            5,
        )

        data = self.env['aps.resources'].with_user(
            self.student_user
        ).get_past_paper_progress_data()

        self.assertEqual(data['student_id'], self.student_partner.id)
        self.assertEqual(
            [category['id'] for category in data['categories']],
            [self.category.id],
        )
        self.assertEqual([paper['id'] for paper in data['papers']], [self.paper.id])
        self.assertEqual(data['papers'][0]['name'], self.paper.name)
        self.assertEqual(data['papers'][0]['attempted_question_count'], 1)
        self.assertEqual(data['papers'][0]['completed_paper_attempts'], 0)
        self.assertEqual(data['papers'][0]['questions'][0]['attempts'], 1)
        self.assertEqual(data['papers'][0]['questions'][0]['number'], 1)
        self.assertTrue(data['papers'][0]['has_attempts'])
        self.assertFalse(data['papers'][0]['history'])

        with self.assertRaises(AccessError):
            self.env['aps.resources'].with_user(
                self.student_user
            ).action_assign_past_paper(
                self.paper.id,
                self.other_student_partner.id,
            )

    def test_completed_paper_attempts_count_full_question_sets(self):
        for attempt in range(3):
            label = f'Full paper attempt {attempt + 1}'
            for question in (self.question_one, self.question_two):
                self._create_submission(
                    question,
                    self.student_partner,
                    label,
                    8,
                )

        data = self.env['aps.resources'].with_user(
            self.student_user
        ).get_past_paper_progress_data()

        self.assertEqual(
            data['papers'][0]['completed_paper_attempts'],
            3,
        )

    def test_partial_paper_attempts_are_shown_alongside_completed_attempts(self):
        self._create_paper_attempt(
            'Full paper attempt',
            (self.question_one, self.question_two),
        )
        self._create_paper_attempt(
            'Partial paper attempt',
            (self.question_one,),
        )

        data = self.env['aps.resources'].with_user(
            self.student_user
        ).get_past_paper_progress_data()

        self.assertEqual(
            data['papers'][0]['completed_paper_attempts'],
            1,
        )
        self.assertEqual(
            data['papers'][0]['partial_paper_attempts'],
            1,
        )

    def test_paper_history_lists_each_root_and_its_question_submissions(self):
        first_root, first_question_submissions = self._create_paper_attempt(
            'Paper attempt',
            (self.question_one, self.question_two),
        )
        second_root, second_question_submissions = self._create_paper_attempt(
            'Paper attempt',
            (self.question_one, self.question_two),
        )
        question_only_submission = self._create_submission(
            self.question_one,
            self.student_partner,
            'Question-only attempt',
            8,
        )

        data = self.env['aps.resources'].with_user(
            self.student_user
        ).get_past_paper_progress_data()
        history = data['papers'][0]['history']
        history_by_submission_id = {
            attempt['submission_id']: attempt for attempt in history
        }

        self.assertEqual(len(history), 2)
        self.assertEqual(
            set(history_by_submission_id[first_root.id]['submission_ids']),
            {first_root.id} | set(first_question_submissions.ids),
        )
        self.assertEqual(
            set(history_by_submission_id[second_root.id]['submission_ids']),
            {second_root.id} | set(second_question_submissions.ids),
        )
        self.assertNotIn(
            question_only_submission.id,
            set().union(*(
                set(attempt['submission_ids']) for attempt in history
            )),
        )

    def test_teacher_categories_follow_selected_student_enrolment(self):
        other_paper = self.env['aps.resources'].create({
            'name': 'Other Progress Past Paper',
            'type_id': self.paper_type.id,
            'subjects': [(6, 0, self.other_subject.ids)],
        })
        resource_model = self.env['aps.resources'].with_user(self.teacher_user)
        data = resource_model.get_past_paper_progress_data()

        self.assertEqual(
            {student['id'] for student in data['students']},
            {self.student_partner.id, self.other_student_partner.id},
        )
        self.assertFalse(data['categories'])
        self.assertFalse(data['papers'])

        selected_student_data = resource_model.get_past_paper_progress_data(
            False,
            self.student_partner.id,
        )
        self.assertEqual(
            [category['id'] for category in selected_student_data['categories']],
            [self.category.id],
        )
        self.assertEqual(
            [paper['id'] for paper in selected_student_data['papers']],
            [self.paper.id],
        )

        other_student_data = resource_model.get_past_paper_progress_data(
            False,
            self.other_student_partner.id,
        )
        self.assertEqual(
            [category['id'] for category in other_student_data['categories']],
            [self.other_category.id],
        )
        self.assertEqual(
            [paper['id'] for paper in other_student_data['papers']],
            [other_paper.id],
        )

    def test_assign_paper_creates_a_fresh_labelled_paper_and_question_set(self):
        resource_model = self.env['aps.resources'].with_user(self.teacher_user)
        first_action = resource_model.action_assign_past_paper(
            self.paper.id,
            self.student_partner.id,
            self.category.id,
        )
        second_action = resource_model.action_assign_past_paper(
            self.paper.id,
            self.student_partner.id,
            self.category.id,
        )

        self.assertEqual(first_action['res_model'], 'aps.resource.submission')
        self.assertEqual(second_action['res_model'], 'aps.resource.submission')
        self.assertEqual(
            [view[1] for view in first_action['views']],
            ['list'],
        )
        self.assertEqual(
            [view[1] for view in second_action['views']],
            ['list'],
        )
        paper_submissions = self.env['aps.resource.submission'].search([
            ('task_id.resource_id', '=', self.paper.id),
            ('task_id.student_id', '=', self.student_partner.id),
        ])
        self.assertEqual(len(paper_submissions), 2)
        self.assertEqual(len(set(paper_submissions.mapped('submission_label'))), 2)

        question_submissions = self.env['aps.resource.submission'].search([
            ('task_id.resource_id', 'in', [
                self.question_one.id,
                self.question_two.id,
            ]),
            ('task_id.student_id', '=', self.student_partner.id),
        ])
        self.assertEqual(len(question_submissions), 4)
        self.assertFalse(any(
            (paper_submissions | question_submissions).mapped('date_due')
        ))
        self.assertEqual(
            set(first_action['domain'][0][2]),
            set(paper_submissions.sorted('id')[:1].ids)
            | set(question_submissions.sorted('id')[:2].ids),
        )

    def test_assign_question_creates_only_that_question_submission(self):
        nested_question = self.env['aps.resources'].create({
            'name': 'Nested Question',
            'type_id': self.question_type.id,
            'subjects': [(6, 0, self.subject.ids)],
            'parent_ids': [(4, self.question_one.id)],
            'has_question': 'yes',
            'question': '<p>Nested question</p>',
            'marks': 5,
        })
        resource_model = self.env['aps.resources'].with_user(self.teacher_user)
        action = resource_model.action_assign_past_paper_question(
            self.paper.id,
            self.question_one.id,
            self.student_partner.id,
            self.category.id,
        )

        self.assertEqual(action['res_model'], 'aps.resource.submission')
        submissions = self.env['aps.resource.submission'].search([
            ('task_id.student_id', '=', self.student_partner.id),
        ])
        self.assertEqual(
            submissions.mapped('task_id.resource_id'),
            self.question_one,
        )
        self.assertFalse(self.env['aps.resource.submission'].search([
            ('task_id.resource_id', '=', nested_question.id),
            ('task_id.student_id', '=', self.student_partner.id),
        ]))

    def test_question_assignment_uses_label_distinct_from_paper_submission(self):
        base_label = (
            f'{self.paper.display_name or self.paper.name} '
            f'({fields.Date.today()})'
        )
        paper_submission = self._create_submission(
            self.paper,
            self.student_partner,
            base_label,
            8,
        )

        self.env['aps.resources'].with_user(
            self.teacher_user
        ).action_assign_past_paper_question(
            self.paper.id,
            self.question_one.id,
            self.student_partner.id,
            self.category.id,
        )

        question_submission = self.env['aps.resource.submission'].search([
            ('task_id.resource_id', '=', self.question_one.id),
            ('task_id.student_id', '=', self.student_partner.id),
        ], order='id desc', limit=1)
        self.assertNotEqual(
            question_submission.submission_label,
            paper_submission.submission_label,
        )
        self.assertFalse(question_submission.parent_submission_id)
