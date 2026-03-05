from odoo.tests.common import TransactionCase


class TestAPSResourceSubmissionAutoScore(TransactionCase):
    """Tests for the auto_score field and parent score calculation."""

    def setUp(self):
        super().setUp()
        # Create a student partner
        self.student = self.env['res.partner'].create({
            'name': 'Test Student',
            'is_student': True,
        })

        # Create parent resource with marks = sum of children (5+6+3=14)
        self.parent_resource = self.env['aps.resources'].create({
            'name': 'Q1',
            'marks': 14.0,
        })

        # Create three child resources
        self.child_resource_a = self.env['aps.resources'].create({
            'name': 'Q1a',
            'marks': 5.0,
            'parent_ids': [(6, 0, [self.parent_resource.id])],
            'primary_parent_id': self.parent_resource.id,
        })
        self.child_resource_b = self.env['aps.resources'].create({
            'name': 'Q1b',
            'marks': 6.0,
            'parent_ids': [(6, 0, [self.parent_resource.id])],
            'primary_parent_id': self.parent_resource.id,
        })
        self.child_resource_c = self.env['aps.resources'].create({
            'name': 'Q1c',
            'marks': 3.0,
            'parent_ids': [(6, 0, [self.parent_resource.id])],
            'primary_parent_id': self.parent_resource.id,
        })

        # Create tasks (parent + children) for the student
        self.parent_task = self.env['aps.resource.task'].create({
            'resource_id': self.parent_resource.id,
            'student_id': self.student.id,
        })
        self.child_task_a = self.env['aps.resource.task'].create({
            'resource_id': self.child_resource_a.id,
            'student_id': self.student.id,
        })
        self.child_task_b = self.env['aps.resource.task'].create({
            'resource_id': self.child_resource_b.id,
            'student_id': self.student.id,
        })
        self.child_task_c = self.env['aps.resource.task'].create({
            'resource_id': self.child_resource_c.id,
            'student_id': self.student.id,
        })

        # Create submissions with a shared label so parent can be found
        self.parent_submission = self.env['aps.resource.submission'].create({
            'task_id': self.parent_task.id,
            'submission_name': 'Q1',
            'submission_label': 'Exam2025',
            'auto_score': True,
        })
        self.child_sub_a = self.env['aps.resource.submission'].create({
            'task_id': self.child_task_a.id,
            'submission_name': 'Q1a',
            'submission_label': 'Exam2025',
            'submission_order': 1,
        })
        self.child_sub_b = self.env['aps.resource.submission'].create({
            'task_id': self.child_task_b.id,
            'submission_name': 'Q1b',
            'submission_label': 'Exam2025',
            'submission_order': 2,
        })
        self.child_sub_c = self.env['aps.resource.submission'].create({
            'task_id': self.child_task_c.id,
            'submission_name': 'Q1c',
            'submission_label': 'Exam2025',
            'submission_order': 3,
        })

    def test_auto_score_defaults_to_true(self):
        """New submissions should have auto_score=True by default."""
        sub = self.env['aps.resource.submission'].create({
            'task_id': self.parent_task.id,
            'submission_name': 'New',
        })
        self.assertTrue(sub.auto_score)

    def test_setting_score_sets_auto_score_false(self):
        """Writing a score without explicitly passing auto_score should set auto_score=False."""
        self.child_sub_a.write({'score': 3.0})
        self.assertFalse(self.child_sub_a.auto_score)

    def test_setting_answer_sets_auto_score_false(self):
        """Writing an answer without explicitly passing auto_score should set auto_score=False."""
        self.child_sub_a.write({'answer': '<p>My answer</p>'})
        self.assertFalse(self.child_sub_a.auto_score)

    def test_auto_score_explicit_true_is_preserved(self):
        """Writing score with auto_score=True explicitly should keep auto_score=True."""
        self.child_sub_a.write({'score': 3.0, 'auto_score': True})
        self.assertTrue(self.child_sub_a.auto_score)

    def test_parent_score_updated_when_child_score_changes(self):
        """When a child score is set, the parent submission (with auto_score=True) should be updated."""
        self.child_sub_a.write({'score': 2.0, 'auto_score': False})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        # Re-read parent to get updated values
        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)

    def test_parent_answer_updated_with_summary(self):
        """Parent answer should contain a summary of child scores when auto_score=True."""
        self.child_sub_a.write({'score': 2.0, 'auto_score': False})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        self.parent_submission.invalidate_recordset()
        answer = self.parent_submission.answer or ''
        self.assertIn('Q1a', answer)
        self.assertIn('Q1b', answer)
        self.assertIn('Q1c', answer)
        self.assertIn('TOTAL', answer)
        self.assertIn('9/14', answer)

    def test_parent_not_updated_when_auto_score_false(self):
        """Parent score should NOT be updated when parent.auto_score=False."""
        self.parent_submission.write({'auto_score': False})
        original_score = self.parent_submission.score

        self.child_sub_a.write({'score': 2.0})

        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, original_score)

    def test_reset_auto_score_to_true_triggers_recalculation(self):
        """When auto_score is reset from False to True, parent score should be recalculated."""
        # Manually set children's scores
        self.child_sub_a.write({'score': 2.0, 'auto_score': False})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        # Disable auto_score on parent, then re-enable
        self.parent_submission.write({'auto_score': False, 'score': 0.0})
        self.parent_submission.write({'auto_score': True})

        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)

    def test_all_parents_updated_when_child_has_multiple_parents(self):
        """When a child resource belongs to multiple parents, all parent submissions
        with auto_score=True should be updated when the child score changes."""
        # Create a second parent resource that also contains child_resource_a
        parent_resource_2 = self.env['aps.resources'].create({
            'name': 'Q2',
            'marks': 10.0,
        })

        # Add the second parent to child_resource_a
        self.child_resource_a.write({
            'parent_ids': [(4, parent_resource_2.id)],
        })

        # Create task and submission for the second parent
        parent_task_2 = self.env['aps.resource.task'].create({
            'resource_id': parent_resource_2.id,
            'student_id': self.student.id,
        })
        parent_submission_2 = self.env['aps.resource.submission'].create({
            'task_id': parent_task_2.id,
            'submission_name': 'Q2',
            'submission_label': 'Exam2025',
            'auto_score': True,
        })

        # Set scores on all children of original parent
        self.child_sub_b.write({'score': 4.0, 'auto_score': False})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})
        # Updating child_resource_a's score should trigger both parents
        self.child_sub_a.write({'score': 2.0, 'auto_score': False})

        # Original parent_submission should be updated (sum of a+b+c = 9)
        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)

        # Second parent_submission_2 should also be updated (only child_a contributes = 2)
        parent_submission_2.invalidate_recordset()
        self.assertEqual(parent_submission_2.score, 2.0)

    def test_fmt_num_integer(self):
        """_fmt_num should return integer string for whole numbers."""
        Submission = self.env['aps.resource.submission']
        self.assertEqual(Submission._fmt_num(5.0), '5')
        self.assertEqual(Submission._fmt_num(14.0), '14')

    def test_fmt_num_decimal(self):
        """_fmt_num should return two decimal places for non-integer values."""
        Submission = self.env['aps.resource.submission']
        self.assertEqual(Submission._fmt_num(5.5), '5.50')
        self.assertEqual(Submission._fmt_num(3.14), '3.14')
