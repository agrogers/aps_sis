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
        self.assertEqual(data['papers'][0]['questions'][0]['attempts'], 1)
        self.assertTrue(data['papers'][0]['has_attempts'])
        self.assertEqual(data['papers'][0]['history'][0]['completed_questions'], 1)

        with self.assertRaises(AccessError):
            self.env['aps.resources'].with_user(
                self.student_user
            ).action_assign_past_paper(
                self.paper.id,
                self.other_student_partner.id,
            )

    def test_teacher_students_follow_selected_category(self):
        data = self.env['aps.resources'].with_user(
            self.teacher_user
        ).get_past_paper_progress_data(self.category.id)

        self.assertEqual(
            [student['id'] for student in data['students']],
            [self.student_partner.id],
        )
        self.assertFalse(data['papers'])

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
