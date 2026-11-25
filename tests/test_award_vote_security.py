from odoo.tests.common import TransactionCase


class TestAwardVoteSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.restricted_user = Users.create({
            'name': 'Restricted Vote Manager',
            'login': 'test_restricted_vote_manager',
            'groups_id': [(6, 0, [cls.env.ref('aps_sis.group_awards_user').id])],
        })
        cls.general_user = Users.create({
            'name': 'General Vote Manager',
            'login': 'test_general_vote_manager',
            'groups_id': [(6, 0, [cls.env.ref('aps_sis.group_awards_manager').id])],
        })
        cls.other_voter = cls.env['res.partner'].create({'name': 'Other Voter'})

        tag = cls.env['aps.subject.category.tag'].search([('name', '=', 'Home Class')], limit=1)
        if not tag:
            tag = cls.env['aps.subject.category.tag'].create({'name': 'Home Class'})
        category = cls.env['aps.subject.category'].create({
            'name': 'Vote Security Home Category',
            'tag_ids': [(4, tag.id)],
        })
        home_subject = cls.env['aps.subject'].create({
            'name': 'Vote Security Home Subject',
            'category_id': category.id,
        })
        other_subject = cls.env['aps.subject'].create({'name': 'Vote Security Other Subject'})
        partner_id = cls.restricted_user.partner_id.id
        teacher_class = cls.env['aps.class'].create({
            'name': 'Vote Security Teacher Class',
            'subject_id': home_subject.id,
            'teacher_ids': [(4, partner_id)],
        })
        assistant_class = cls.env['aps.class'].create({
            'name': 'Vote Security Assistant Class',
            'subject_id': home_subject.id,
            'assistant_teacher_ids': [(4, partner_id)],
        })
        other_home_class = cls.env['aps.class'].create({
            'name': 'Vote Security Other Home Class',
            'subject_id': home_subject.id,
        })
        other_subject_class = cls.env['aps.class'].create({
            'name': 'Vote Security Other Subject Class',
            'subject_id': other_subject.id,
            'teacher_ids': [(4, partner_id)],
        })

        students = cls.env['aps.student']
        for name in ('Teacher', 'Assistant', 'Other', 'Split', 'Withdrawn'):
            partner = cls.env['res.partner'].create({'name': 'Vote Security ' + name})
            students |= cls.env['aps.student'].create({'partner_id': partner.id})
        teacher_student, assistant_student, other_student, split_student, withdrawn_student = students
        cls.env['aps.student.class'].create([
            {'student_id': teacher_student.id, 'class_id': teacher_class.id, 'start_date': False, 'end_date': False},
            {'student_id': assistant_student.id, 'class_id': assistant_class.id, 'start_date': False, 'end_date': False},
            {'student_id': other_student.id, 'class_id': other_home_class.id, 'start_date': False, 'end_date': False},
            {'student_id': split_student.id, 'class_id': other_home_class.id, 'start_date': False, 'end_date': False},
            {'student_id': split_student.id, 'class_id': other_subject_class.id, 'start_date': False, 'end_date': False},
            {'student_id': withdrawn_student.id, 'class_id': teacher_class.id, 'state': 'withdrawn', 'start_date': False, 'end_date': False},
        ])

        restricted_set = cls.env['aps.award.voting.set'].create({
            'name': 'Restricted Vote Set',
            'vote_set_restricted_managers': [(4, partner_id)],
        })
        general_set = cls.env['aps.award.voting.set'].create({
            'name': 'General Vote Set',
            'vote_set_managers': [(4, cls.general_user.partner_id.id)],
        })
        rounds = cls.env['aps.award.vote.round'].create([
            {
                'name': name,
                'datetime_start': '2026-01-01 00:00:00',
                'datetime_end': '2026-01-02 00:00:00',
                'voting_set_ids': [(4, voting_set.id)],
            }
            for name, voting_set in (('Restricted Round', restricted_set), ('General Round', general_set))
        ])
        restricted_round, general_round = rounds
        cls.votes = cls.env['aps.award.vote'].create([
            {
                'vote_round_id': restricted_round.id,
                'voter_partner_id': cls.restricted_user.partner_id.id,
            },
            *[
                {
                    'vote_round_id': restricted_round.id,
                    'voter_partner_id': cls.other_voter.id,
                    'recipient_partner_id': student.partner_id.id,
                }
                for student in students
            ],
            {
                'vote_round_id': general_round.id,
                'voter_partner_id': cls.other_voter.id,
                'recipient_partner_id': teacher_student.partner_id.id,
            },
        ])

    def test_restricted_manager_sees_only_own_and_pastoral_votes(self):
        visible = self.env['aps.award.vote'].with_user(self.restricted_user).search([
            ('id', 'in', self.votes.ids),
        ])
        self.assertEqual(set(visible.ids), set(self.votes[:3].ids))

    def test_awards_manager_is_also_subject_to_global_rule(self):
        visible = self.env['aps.award.vote'].with_user(self.general_user).search([
            ('id', 'in', self.votes.ids),
        ])
        self.assertEqual(visible, self.votes[-1].with_user(self.general_user))

    def test_restricted_manager_with_teacher_group(self):
        self.restricted_user.write({
            'groups_id': [(4, self.env.ref('aps_sis.group_aps_teacher').id)],
        })
        visible = self.env['aps.award.vote'].with_user(self.restricted_user).search([
            ('id', 'in', self.votes.ids),
        ])
        self.assertEqual(set(visible.ids), set(self.votes[:3].ids))
