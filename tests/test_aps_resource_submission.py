import json
import re

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.addons.aps_sis.models.submissions.model import sentinel_zero


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
        """When all child scores are set and submitted, the parent submission
        (with auto_score=True) should be updated."""
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})

        # Re-read parent to get updated values
        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)

    def test_parent_answer_updated_with_summary(self):
        """Parent answer should contain a summary of child scores when auto_score=True."""
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})

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
        # Manually set children's scores and mark them as submitted
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})

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

        # Set scores on all children of original parent and mark as submitted
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})
        # Updating child_resource_a's score should trigger both parents
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})

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

    def test_child_excluded_from_parent_score_when_flag_false(self):
        """When a child resource has score_contributes_to_parent=False its score
        should not be included in the parent's auto-calculated score."""
        # Mark child_c as not contributing to parent score
        self.child_resource_c.write({'score_contributes_to_parent': False})

        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        # child_sub_c is scored but should be excluded; its state does not matter
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        self.parent_submission.invalidate_recordset()
        # Only Q1a (2) + Q1b (4) = 6 should count; Q1c (3) is excluded
        self.assertEqual(self.parent_submission.score, 6.0)

    def test_excluded_child_not_in_parent_answer_summary(self):
        """The excluded child's name should not appear in the parent answer summary."""
        self.child_resource_c.write({'score_contributes_to_parent': False})

        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        self.parent_submission.invalidate_recordset()
        answer = self.parent_submission.answer or ''
        self.assertIn('Q1a', answer)
        self.assertIn('Q1b', answer)
        self.assertNotIn('Q1c', answer)

    def test_parent_not_updated_when_not_all_children_submitted(self):
        """Parent score should NOT be updated if some contributing children have
        not yet reached 'submitted' or 'complete' state."""
        # Submit only two of the three contributing children
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        # child_sub_c remains in 'assigned' state
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        self.parent_submission.invalidate_recordset()
        # Parent must NOT be updated because child_c is still 'assigned'
        self.assertEqual(self.parent_submission.score, sentinel_zero)

    def test_parent_updated_when_last_child_submits(self):
        """Parent score should be updated when the final contributing child
        transitions to 'submitted' state (even if scores were already set)."""
        # Set scores on all children but keep them in 'assigned' state first
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        # child_sub_c has its score but is still assigned
        self.child_sub_c.write({'score': 3.0, 'auto_score': False})

        # Parent should not yet be updated
        self.parent_submission.invalidate_recordset()
        self.assertNotEqual(self.parent_submission.score, 9.0)

        # Now submit the last child — this should trigger the parent update
        self.child_sub_c.write({'state': 'submitted'})

        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)

    def test_best_score_used_for_duplicate_child_submissions(self):
        """When a child resource has two submissions sharing the same resource and
        label, only the one with the highest score should contribute to the parent."""
        # Create a second submission for child_resource_a with a higher score
        self.env['aps.resource.submission'].create({
            'task_id': self.child_task_a.id,
            'submission_name': 'Q1a',
            'submission_label': 'Exam2025',
            'submission_order': 1,
            'score': 4.0,
            'auto_score': False,
            'state': 'submitted',
        })

        # Original child_sub_a gets a lower score and is submitted
        self.child_sub_a.write({'score': 1.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})

        self.parent_submission.invalidate_recordset()
        # Best score for Q1a is 4 (from the duplicate), so total = 4 + 4 + 3 = 11
        self.assertEqual(self.parent_submission.score, 11.0)

    def test_toggling_flag_updates_parent_score_immediately(self):
        """Toggling score_contributes_to_parent on a child resource should immediately
        re-trigger the parent submission recalculation."""
        # Set all child scores and submit so they are eligible for parent aggregation.
        self.child_sub_a.write({'score': 2.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_b.write({'score': 4.0, 'auto_score': False, 'state': 'submitted'})
        self.child_sub_c.write({'score': 3.0, 'auto_score': False, 'state': 'submitted'})

        self.parent_submission.invalidate_recordset()
        # All three children contribute: 2+4+3 = 9
        self.assertEqual(self.parent_submission.score, 9.0)

        # Now exclude child_c — parent should recalculate immediately
        self.child_resource_c.write({'score_contributes_to_parent': False})
        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 6.0)

        # Re-enable child_c — parent should include it again
        self.child_resource_c.write({'score_contributes_to_parent': True})
        self.parent_submission.invalidate_recordset()
        self.assertEqual(self.parent_submission.score, 9.0)


class TestAPSResourceSubmissionProgressOrdering(TransactionCase):
    """Regression tests for current-progress selection used by dashboard APIs."""

    def test_same_day_higher_result_wins(self):
        submission_model = self.env['aps.resource.submission']
        existing = {
            'date': fields.Date.to_date('2026-03-24'),
            'result_percent': 45,
        }

        self.assertTrue(
            submission_model._should_replace_progress_result(
                existing,
                fields.Date.to_date('2026-03-24'),
                70,
            )
        )
        self.assertFalse(
            submission_model._should_replace_progress_result(
                existing,
                fields.Date.to_date('2026-03-24'),
                30,
            )
        )

    def test_newer_date_wins_before_result(self):
        submission_model = self.env['aps.resource.submission']
        existing = {
            'date': fields.Date.to_date('2026-03-23'),
            'result_percent': 95,
        }

        self.assertTrue(
            submission_model._should_replace_progress_result(
                existing,
                fields.Date.to_date('2026-03-24'),
                10,
            )
        )

    def test_collapse_progress_points_keeps_highest_same_day_score(self):
        submission_model = self.env['aps.resource.submission']
        points = [
            {
                'date': '2026-03-24',
                'result_percent': 40,
                'subject_id': 11,
                'subject_name': 'Math',
            },
            {
                'date': '2026-03-24',
                'result_percent': 72,
                'subject_id': 11,
                'subject_name': 'Math',
            },
            {
                'date': '2026-03-25',
                'result_percent': 65,
                'subject_id': 11,
                'subject_name': 'Math',
            },
            {
                'date': '2026-03-25',
                'result_percent': 55,
                'subject_id': 11,
                'subject_name': 'Math',
            },
        ]

        collapsed = submission_model._collapse_progress_points_by_date(points)

        self.assertEqual(len(collapsed), 2)
        self.assertEqual(collapsed[0]['date'], '2026-03-24')
        self.assertEqual(collapsed[0]['result_percent'], 72)
        self.assertEqual(collapsed[1]['date'], '2026-03-25')
        self.assertEqual(collapsed[1]['result_percent'], 65)


class TestAPSAITargetedFeedback(TransactionCase):

    def test_build_submission_answer_chunks_preserves_html_block_boundaries(self):
        ai_model = self.env['aps.ai.model']
        answer_html = '<div>Dog</div><div>Cat</div><div>Milk</div>'

        chunk_data = ai_model._build_submission_answer_chunks(answer_html)

        self.assertEqual(chunk_data['chunks'], [
            {'id': 'c1', 'text': 'Dog'},
            {'id': 'c2', 'text': 'Cat'},
            {'id': 'c3', 'text': 'Milk'},
        ])
        self.assertIn('data-chunk-id="c1"', chunk_data['chunked_html'])
        self.assertIn('<div class="aps-ai-answer-chunk" data-chunk-id="c1">Dog</div>', chunk_data['chunked_html'])
        self.assertIn('<div class="aps-ai-answer-chunk" data-chunk-id="c2">Cat</div>', chunk_data['chunked_html'])
        self.assertIn('<div class="aps-ai-answer-chunk" data-chunk-id="c3">Milk</div>', chunk_data['chunked_html'])

    def test_build_submission_answer_chunks_splits_html_block_into_sentences(self):
        ai_model = self.env['aps.ai.model']
        answer_html = '<div>Cat is an animal. Dog is also an animal.</div>'

        chunk_data = ai_model._build_submission_answer_chunks(answer_html)

        self.assertEqual(chunk_data['chunks'], [
            {'id': 'c1', 'text': 'Cat is an animal.'},
            {'id': 'c2', 'text': 'Dog is also an animal.'},
        ])
        self.assertIn('<div><span class="aps-ai-answer-chunk" data-chunk-id="c1">Cat is an animal.</span> <span class="aps-ai-answer-chunk" data-chunk-id="c2">Dog is also an animal.</span></div>', chunk_data['chunked_html'])

    def test_build_submission_answer_chunks_preserves_full_text(self):
        ai_model = self.env['aps.ai.model']
        answer_html = '<p>Photosynthesis occurs in leaves, not in roots. Water is absorbed by root hairs.</p>'

        chunk_data = ai_model._build_submission_answer_chunks(answer_html)

        self.assertGreaterEqual(len(chunk_data['chunks']), 2)
        self.assertEqual(chunk_data['chunks'][0]['id'], 'c1')
        self.assertIn('data-chunk-id="c1"', chunk_data['chunked_html'])

        reconstructed = ' '.join(chunk['text'] for chunk in chunk_data['chunks'])
        normalized_original = re.sub(r'\s+', ' ', ai_model._html_to_text(answer_html)).strip()
        normalized_reconstructed = re.sub(r'\s+', ' ', reconstructed).strip()
        self.assertEqual(normalized_reconstructed, normalized_original)

    def test_extract_targeted_feedback_filters_invalid_chunk_ids(self):
        ai_model = self.env['aps.ai.model']
        chunk_data = {
            'chunks': [
                {'id': 'c1', 'text': 'Photosynthesis occurs in leaves,'},
                {'id': 'c2', 'text': 'not in roots.'},
            ],
            'chunked_html': '<span data-chunk-id="c1">Photosynthesis occurs in leaves,</span><span data-chunk-id="c2">not in roots.</span>',
        }
        parsed = {
            'html': '<h3>Feedback</h3><ul><li>Photosynthesis does not occur in roots.</li></ul>',
            'feedback': [
                {'id': 'f1', 'type': 'concept_error', 'severity': 'major'},
                {'id': 'f2', 'type': 'positive', 'severity': 'minor'},
            ],
            'links': [
                {'feedback_id': 'f1', 'chunk_ids': ['c2', 'c404', 'c2']},
                {'feedback_id': 'f2', 'chunk_ids': ['c999']},
                {'feedback_id': 'f3', 'chunk_ids': ['c1']},
            ],
        }

        targeted = ai_model._extract_targeted_feedback(parsed, json.dumps(parsed), chunk_data)

        self.assertEqual(targeted['feedback_items'][0]['id'], 'f1')
        self.assertEqual(targeted['feedback_links'], [{'feedback_id': 'f1', 'chunk_ids': ['c2']}])
