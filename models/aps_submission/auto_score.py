from odoo import models, api

from .constants import sentinel_zero


class APSResourceSubmission(models.Model):
    _inherit = 'aps.resource.submission'

    # region - Auto Score / Auto Answer

    @staticmethod
    def _fmt_num(n):
        """Format a number, removing unnecessary decimal places."""
        if n == int(n):
            return str(int(n))
        return f"{n:.2f}"

    def _recalculate_score_from_children(self):
        """For records with auto_score=True, recalculate score and answer summary
        from child resource submissions for the same student and submission label.

        The parent score is only updated when *every* contributing child has at
        least one submission in the 'submitted' or 'complete' state for the same
        student and label.  When a child resource has multiple submissions with the
        same label the one with the highest score is used so that duplicate entries
        do not distort the total.
        """
        for record in self:
            if not record.auto_score:
                continue

            child_resources = record.resource_id.child_ids if record.resource_id else False
            if not child_resources:
                continue

            # Only include children that contribute to the parent score
            contributing_children = child_resources.filtered(lambda r: r.score_contributes_to_parent)
            if not contributing_children:
                continue

            base_domain = [
                ('resource_id', 'in', contributing_children.ids),
                ('student_id', '=', record.student_id.id),
            ]
            if record.submission_label:
                base_domain.append(('submission_label', '=', record.submission_label))

            # Guard: every contributing child must have at least one submitted or
            # completed submission (same student, same label) before we update the
            # parent.  If any child is missing one we skip this parent entirely.
            submitted_resource_ids = set(
                self.search(base_domain + [('state', 'in', ('submitted', 'complete'))]).mapped('resource_id.id')
            )
            if not all(c.id in submitted_resource_ids for c in contributing_children):
                continue

            child_submissions = self.search(base_domain).sorted(
                lambda s: (s.submission_order or 999, s.submission_name or '')
            )

            if not child_submissions:
                continue

            # Deduplicate: for each contributing child resource keep only the
            # submission with the best (highest) score.  This handles the edge
            # case where a child resource has two submissions sharing the same
            # label and resource ID.
            best_per_resource = {}
            for sub in child_submissions:
                rid = sub.resource_id.id
                sub_score = sub.score if sub.score != sentinel_zero else 0.0
                existing = best_per_resource.get(rid)
                if existing is None:
                    best_per_resource[rid] = sub
                else:
                    existing_score = existing.score if existing.score != sentinel_zero else 0.0
                    if sub_score > existing_score:
                        best_per_resource[rid] = sub

            deduplicated = sorted(
                best_per_resource.values(),
                key=lambda s: (s.submission_order or 999, s.submission_name or ''),
            )

            total_score = 0.0
            total_out_of = 0.0
            lines = []

            for child_sub in deduplicated:
                score = child_sub.score if child_sub.score != sentinel_zero else 0.0
                out_of = child_sub.out_of_marks or 0.0
                name = child_sub.submission_name or child_sub.display_name or '?'
                lines.append(
                    f"{name}) Score: {self._fmt_num(score)}/{self._fmt_num(out_of)}"
                )
                total_score += score
                total_out_of += out_of

            new_score = total_score if total_out_of > 0 else sentinel_zero

            if not lines:
                continue

            total_line = f"TOTAL: {self._fmt_num(total_score)}/{self._fmt_num(total_out_of)}"
            all_lines = lines + [total_line]
            summary_html = '<p>' + '</p><p>'.join(all_lines) + '</p>'

            # Pass auto_score=True explicitly so write() does not flip the flag back to False
            record.write({
                'score': new_score,
                'answer': summary_html,
                'auto_score': True,
            })

    def _check_and_update_parent_score(self):
        """After a score update on this record, find the corresponding parent submissions
        for all parent resources and trigger a score recalculation if the parent has
        auto_score enabled."""
        for record in self:
            if not record.resource_id or not record.resource_id.parent_ids:
                continue

            for parent_resource in record.resource_id.parent_ids:
                # Find the parent task for the same student
                parent_task = self.env['aps.resource.task'].search([
                    ('resource_id', '=', parent_resource.id),
                    ('student_id', '=', record.student_id.id),
                ], limit=1)

                if not parent_task:
                    continue

                # Find the parent submission, preferring one with a matching label
                parent_domain = [('task_id', '=', parent_task.id)]
                if record.submission_label:
                    parent_domain.append(('submission_label', '=', record.submission_label))

                parent_submission = self.search(parent_domain, order='create_date desc', limit=1)

                if not parent_submission:
                    continue

                if parent_submission.auto_score:
                    parent_submission._recalculate_score_from_children()

    # endregion - Auto Score / Auto Answer
