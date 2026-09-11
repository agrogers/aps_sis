from datetime import date, timedelta

from odoo.tests.common import TransactionCase


class TestWeeklySubmissionResult(TransactionCase):
    """Focused regression tests for weekly-result scope helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result_model = cls.env["aps.weekly.submission.result"]

    def test_student_domain_uses_exact_match_for_one_student(self):
        self.assertEqual(
            self.result_model._weekly_student_domain({42}),
            [("student_id", "=", 42)],
        )

    def test_student_domain_uses_membership_for_multiple_students(self):
        self.assertEqual(
            self.result_model._weekly_student_domain({42, 43}),
            [("student_id", "in", [42, 43])],
        )

    def test_submission_domain_contains_shared_visibility_filters(self):
        start = date(2026, 1, 1)
        end = start + timedelta(days=6)
        domain = self.result_model._weekly_submission_domain({42, 43}, start, end, {7})
        self.assertIn(("student_id", "in", [42, 43]), domain)
        self.assertIn(("state", "in", ("submitted", "complete")), domain)
        self.assertIn(("is_course_explorer", "=", False), domain)
        self.assertIn(("date_submitted", ">=", start), domain)
        self.assertIn(("date_submitted", "<=", end), domain)
        self.assertIn(("subjects", "in", [7]), domain)
        self.assertIn(("resource_id.subjects", "in", [7]), domain)

    def test_rebuild_cleanup_overlaps_partial_start_week(self):
        start = date(2026, 1, 7)
        end = date(2026, 1, 14)
        existing_domain = [("student_id", "=", 42)]
        if start:
            existing_domain.append(("week_end", ">=", start))
        if end:
            existing_domain.append(("week_start", "<=", end))
        self.assertEqual(
            existing_domain,
            [
                ("student_id", "=", 42),
                ("week_end", ">=", start),
                ("week_start", "<=", end),
            ],
        )