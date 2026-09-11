from collections import defaultdict
from datetime import date, timedelta

from odoo import api, fields, models


# Keep special display behaviour isolated until resource types have a dedicated field.
SPECIAL_RESOURCE_TYPES = {
    "progress": "progress",
}


class APSWeeklySubmissionResult(models.Model):
    _name = "aps.weekly.submission.result"
    _description = "Weekly Submission Result"
    _rec_name = "display_name"
    _order = "week_start, subject_id, type_id"

    student_id = fields.Many2one("res.partner", required=True, index=True, ondelete="cascade")
    subject_id = fields.Many2one("aps.subject", required=True, index=True, ondelete="cascade")
    type_id = fields.Many2one("aps.resource.types", required=True, index=True, ondelete="cascade")
    week_start = fields.Date(required=True, index=True)
    week_end = fields.Date(required=True)
    academic_week_id = fields.Many2one("aps.academic.week", index=True, ondelete="set null")
    submission_count = fields.Integer(default=0)
    score_total = fields.Float(default=0.0)
    out_of_marks_total = fields.Float(default=0.0)
    weighted_percent = fields.Float(default=0.0)
    display_mode = fields.Selection(
        [("marks", "Marks"), ("progress", "Progress")],
        default="marks",
        required=True,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        (
            "weekly_submission_result_unique",
            "unique(student_id, subject_id, type_id, week_start)",
            "A weekly submission result already exists for this student, subject, type, and week.",
        ),
    ]

    @api.depends("student_id", "subject_id", "type_id", "week_start")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s / %s / %s / %s" % (
                record.student_id.display_name,
                record.subject_id.display_name,
                record.type_id.display_name,
                record.week_start or "",
            )

    @classmethod
    def _mode_for_type_name(cls, name):
        return SPECIAL_RESOURCE_TYPES.get((name or "").strip().lower(), "marks")

    @staticmethod
    def _week_start(value):
        return value - timedelta(days=value.weekday())

    @staticmethod
    def _weighted_percent(records, mode="marks"):
        """Return a bounded percentage from the source submission records.

        Submission scores are marks, not percentages.  The denominator must
        therefore be the sum of positive maximum marks.  Bounding the result
        also prevents malformed source marks from producing values such as
        1,000% in the dashboard.
        """
        if not records:
            return 0.0
        if mode == "progress":
            # Progress resources store their percentage in the submission
            # result, while ``progress`` is the workflow/course-explorer
            # progress field and is commonly zero for scored submissions.
            value = sum(max(record.result_percent, 0.0) for record in records) / len(records)
        else:
            marks_total = sum(max(record.out_of_marks, 0.0) for record in records)
            if not marks_total:
                return 0.0
            value = sum(max(record.score, 0.0) for record in records) / marks_total * 100.0
        return min(100.0, max(0.0, value))

    @api.model
    def rebuild_for_student(self, student_partner_id, date_start=False, date_end=False):
        """Rebuild current weekly facts from submitted/finalised submissions."""
        domain = [
            ("student_id", "=", student_partner_id),
            ("state", "in", ("submitted", "complete")),
            ("is_course_explorer", "=", False),
            ("date_submitted", "!=", False),
        ]
        if date_start:
            domain.append(("date_submitted", ">=", date_start))
        if date_end:
            domain.append(("date_submitted", "<=", date_end))

        submissions = self.env["aps.resource.submission"].search(domain)
        grouped = defaultdict(list)
        for submission in submissions:
            subjects = submission.subjects or submission.resource_id.subjects
            if not subjects or not submission.type_id:
                continue
            week_start = self._week_start(submission.date_submitted)
            for subject in subjects:
                grouped[(subject.id, submission.type_id.id, week_start)].append(submission)

        existing_domain = [("student_id", "=", student_partner_id)]
        if date_start:
            existing_domain.append(("week_start", ">=", date_start))
        if date_end:
            existing_domain.append(("week_start", "<=", date_end))
        existing = self.search(existing_domain)
        seen = set()

        for (subject_id, type_id, week_start), records in grouped.items():
            type_record = records[0].type_id
            mode = self._mode_for_type_name(type_record.name)
            score_total = sum(max(record.score, 0.0) for record in records)
            marks_total = sum(max(record.out_of_marks, 0.0) for record in records)
            progress_total = sum(max(record.result_percent, 0.0) for record in records)
            percent = self._weighted_percent(records, mode)
            key = (student_partner_id, subject_id, type_id, week_start)
            seen.add(key)
            values = {
                "student_id": student_partner_id,
                "subject_id": subject_id,
                "type_id": type_id,
                "week_start": week_start,
                "week_end": week_start + timedelta(days=6),
                "submission_count": len(records),
                "score_total": score_total if mode == "marks" else progress_total,
                "out_of_marks_total": marks_total if mode == "marks" else 0.0,
                "weighted_percent": percent,
                "display_mode": mode,
            }
            academic_week = self.env["aps.academic.week"].search([
                ("date_start", "<=", week_start + timedelta(days=6)),
                ("date_stop", ">=", week_start),
            ], limit=1)
            values["academic_week_id"] = academic_week.id or False
            row = self.search(
                [
                    ("student_id", "=", student_partner_id),
                    ("subject_id", "=", subject_id),
                    ("type_id", "=", type_id),
                    ("week_start", "=", week_start),
                ],
                limit=1,
            )
            if row:
                row.write(values)
            else:
                self.create(values)

        for row in existing:
            key = (row.student_id.id, row.subject_id.id, row.type_id.id, row.week_start)
            if key not in seen:
                row.unlink()
        return True

    @api.model
    def get_grid_data(self, student_partner_id=False, date_start=False, date_end=False, type_ids=None, academic_term_id=False):
        user = self.env.user
        is_teacher = user.has_group("aps_sis.group_aps_teacher")
        if not is_teacher:
            student_partner_id = user.partner_id.id
        elif not student_partner_id:
            student_partner_id = user.partner_id.id

        if date_start:
            date_start = fields.Date.to_date(date_start)
        if date_end:
            date_end = fields.Date.to_date(date_end)
        if not date_start:
            date_start = date.today() - timedelta(days=date.today().weekday() + 28)
        if not date_end:
            date_end = date.today()
        # The weekly result model is a materialized cache. Students can read
        # their rows, but must not need write ACLs merely to refresh the cache
        # when opening the dashboard.
        self.sudo().rebuild_for_student(student_partner_id, date_start, date_end)

        submissions = self.env["aps.resource.submission"].search([
            ("student_id", "=", student_partner_id),
            ("state", "in", ("submitted", "complete")),
            ("date_submitted", ">=", date_start),
            ("date_submitted", "<=", date_end),
        ])
        submission_subjects = {
            submission.id: (submission.subjects or submission.resource_id.subjects)
            for submission in submissions
        }
        available_types = submissions.mapped("type_id")
        requested_type_ids = type_ids
        type_ids = [int(value) for value in (type_ids or [])]
        rows = {}
        all_results = self.search([
            ("student_id", "=", student_partner_id),
            ("week_start", ">=", date_start - timedelta(days=date_start.weekday())),
            ("week_start", "<=", date_end),
        ])
        if not available_types and requested_type_ids is None:
            available_types = all_results.mapped("type_id")
        selected_types = (
            available_types
            if requested_type_ids is None
            else available_types.filtered(lambda record: record.id in type_ids)
        )
        for result in all_results.filtered(lambda record: record.type_id in selected_types):
            key = (result.subject_id.id, result.type_id.id)
            rows.setdefault(key, {
                "key": "%s-%s" % key,
                "subject_id": result.subject_id.id,
                "subject_name": result.subject_id.name,
                "subject_icon_url": "/web/image/aps.subject/%s/icon" % result.subject_id.id if result.subject_id.icon else False,
                "type_id": result.type_id.id,
                "type_name": result.type_id.name,
                "type_description": result.type_id.description or "",
                "type_icon_url": "/web/image/aps.resource.types/%s/icon" % result.type_id.id if result.type_id.icon else False,
                "cells": [],
            })
            rows[key]["cells"].append({
                "key": result.id,
                "week_start": fields.Date.to_string(result.week_start),
                "submission_count": result.submission_count,
                "percent_label": round(result.weighted_percent, 1),
                "show_percent": bool(result.out_of_marks_total or result.display_mode == "progress"),
                "is_progress": result.display_mode == "progress",
                "show_marks": bool(result.out_of_marks_total and result.display_mode == "marks"),
                "marks_label": round(result.out_of_marks_total, 1),
                "tooltip": "%s submissions" % result.submission_count,
                "is_non_school": not bool(result.academic_week_id),
                "academic_week_name": result.academic_week_id.short_name if result.academic_week_id else False,
                "submission_domain": [
                    ("student_id", "=", student_partner_id),
                    ("type_id", "=", result.type_id.id),
                    "|",
                    ("subjects", "in", [result.subject_id.id]),
                    ("resource_id.subjects", "in", [result.subject_id.id]),
                    ("date_submitted", ">=", result.week_start),
                    ("date_submitted", "<=", result.week_end),
                ],
            })
        weeks = []
        cursor = date_start - timedelta(days=date_start.weekday())
        while cursor <= date_end:
            academic_week = self.env["aps.academic.week"].search([
                ("date_start", "<=", cursor + timedelta(days=6)),
                ("date_stop", ">=", cursor),
            ], limit=1)
            weeks.append({
                "start": fields.Date.to_string(cursor),
                "label": cursor.strftime("%d %b"),
                "academic_week_name": academic_week.short_name if academic_week else False,
                "is_non_school": not bool(academic_week),
            })
            cursor += timedelta(days=7)
        for row_key, row in rows.items():
            cells = {cell["week_start"]: cell for cell in row["cells"]}
            row["cells"] = [cells.get(week["start"], {
                "key": "%s-%s" % (row["key"], week["start"]),
                "week_start": week["start"],
                "submission_count": 0,
                "show_percent": False,
                "show_marks": False,
                "is_non_school": week["is_non_school"],
            }) for week in weeks]
            subject_id, type_id = row_key
            row_submissions = submissions.filtered(lambda submission: (
                subject_id in submission_subjects[submission.id].ids
                and submission.type_id.id == type_id
            ))
            total_count = len(row_submissions)
            marks_total = sum(max(record.out_of_marks, 0.0) for record in row_submissions)
            mode = self._mode_for_type_name(row["type_name"])
            row["total"] = {
                "submission_count": total_count,
                "percent_label": round(self._weighted_percent(row_submissions, mode), 1),
                "show_percent": bool(marks_total or mode == "progress"),
                "is_progress": mode == "progress",
                "show_marks": bool(marks_total and mode == "marks"),
                "marks_label": round(marks_total, 1),
                "submission_domain": [
                    ("student_id", "=", student_partner_id),
                    ("state", "in", ("submitted", "complete")),
                    ("date_submitted", ">=", date_start),
                    ("date_submitted", "<=", date_end),
                    ("type_id", "=", type_id),
                    "|",
                    ("subjects", "in", [subject_id]),
                    ("resource_id.subjects", "in", [subject_id]),
                ],
                "tooltip": "%s submissions" % total_count,
            }
        students = []
        if is_teacher:
            period_submissions = self.env["aps.resource.submission"].search([
                ("state", "in", ("submitted", "complete")),
                ("date_submitted", ">=", date_start),
                ("date_submitted", "<=", date_end),
                ("student_id.is_student", "=", True),
            ])
            student_partners = period_submissions.mapped("student_id").sorted(
                key=lambda partner: partner.display_name.lower()
            )
            students = [
                {"id": partner.id, "name": partner.display_name}
                for partner in student_partners
            ]
        terms = self.env["aps.academic.term"].search([], order="start_date desc")
        return {
            "studentId": student_partner_id,
            "students": students,
            "terms": [{"id": term.id, "name": term.display_name, "start": fields.Date.to_string(term.start_date), "end": fields.Date.to_string(term.end_date)} for term in terms],
            "academicTermId": int(academic_term_id) if academic_term_id else False,
            "types": [{"id": record.id, "name": record.name} for record in available_types],
            "selectedTypeIds": None if requested_type_ids is None else type_ids,
            "startDate": fields.Date.to_string(date_start),
            "endDate": fields.Date.to_string(date_end),
            "weeks": weeks,
            "rows": list(rows.values()),
        }
