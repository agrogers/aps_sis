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
    def _weekly_academic_week_map(self, date_start, date_end):
        """Load overlapping academic weeks once for a requested date range."""
        weeks = self.env["aps.academic.week"].search([
            ("date_start", "<=", date_end),
            ("date_stop", ">=", date_start),
        ], order="date_start, id")
        week_map = {}
        cursor = self._week_start(date_start)
        last_week = self._week_start(date_end)
        while cursor <= last_week:
            week_end = cursor + timedelta(days=6)
            week_map[cursor] = next(
                (
                    academic_week
                    for academic_week in weeks
                    if academic_week.date_start <= week_end
                    and academic_week.date_stop >= cursor
                ),
                self.env["aps.academic.week"],
            )
            cursor += timedelta(days=7)
        return week_map

    @api.model
    def rebuild_for_student(self, student_partner_id, date_start=False, date_end=False):
        """Rebuild current weekly facts from submitted/finalised submissions."""
        if date_start:
            date_start = self._week_start(fields.Date.to_date(date_start))
        if date_end:
            date_end = fields.Date.to_date(date_end)
            date_end += timedelta(days=6 - date_end.weekday())
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
            existing_domain.append(("week_end", ">=", date_start))
        if date_end:
            existing_domain.append(("week_start", "<=", date_end))
        existing = self.search(existing_domain)
        existing_by_key = {
            (row.subject_id.id, row.type_id.id, row.week_start): row
            for row in existing
        }
        if grouped:
            grouped_start = min(key[2] for key in grouped)
            grouped_end = max(key[2] for key in grouped)
        else:
            grouped_start = grouped_end = date.today()
        academic_week_map = self._weekly_academic_week_map(
            date_start or grouped_start,
            date_end or grouped_end,
        ) if grouped or (date_start and date_end) else {}
        seen = set()
        values_to_create = []
        values_to_write = []

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
            academic_week = academic_week_map.get(week_start)
            values["academic_week_id"] = academic_week.id or False
            row = existing_by_key.get((subject_id, type_id, week_start))
            if row:
                values_to_write.append((row, values))
            else:
                values_to_create.append(values)

        for row, values in values_to_write:
            row.write(values)
        if values_to_create:
            self.create(values_to_create)

        rows_to_remove = existing.filtered(
            lambda row: (
                row.student_id.id,
                row.subject_id.id,
                row.type_id.id,
                row.week_start,
            ) not in {
                key for key in seen
            }
        )
        if rows_to_remove:
            rows_to_remove.unlink()
        return True

    @api.model
    def _weekly_class_enrollment_map(self, class_ids, date_start, date_end):
        if not class_ids:
            return defaultdict(set)
        enrollments = self.env["aps.student.class"].search([
            ("class_id", "in", list(class_ids)),
            ("state", "=", "enrolled"),
            "|", ("start_date", "=", False), ("start_date", "<=", date_end),
            "|", ("end_date", "=", False), ("end_date", ">=", date_start),
        ])
        enrollment_map = defaultdict(set)
        for enrollment in enrollments:
            if enrollment.partner_id:
                enrollment_map[enrollment.class_id.id].add(enrollment.partner_id.id)
        return enrollment_map

    @api.model
    def _weekly_class_options_and_enrollments(self, date_start, date_end):
        """Return visible classes and one bulk-loaded enrollment map."""
        Class = self.env["aps.class"]
        Submission = self.env["aps.resource.submission"]
        user = self.env.user
        if user.has_group("aps_sis.group_aps_teacher"):
            class_domain = [
                "|",
                ("teacher_ids", "in", user.partner_id.id),
                ("assistant_teacher_ids", "in", user.partner_id.id),
            ]
        else:
            student = self.env["aps.student"].search(
                [("partner_id", "=", user.partner_id.id)], limit=1
            )
            class_domain = [("enrollment_ids.student_id", "=", student.id)] if student else [("id", "=", 0)]

        class_domain += [
            "|", ("academic_year_id.start_date", "=", False),
            ("academic_year_id.start_date", "<=", date_end),
            "|", ("academic_year_id.end_date", "=", False),
            ("academic_year_id.end_date", ">=", date_start),
        ]
        classes = Class.search(class_domain, order="name, id")
        enrollment_map = self._weekly_class_enrollment_map(
            classes.ids, date_start, date_end
        )
        all_partner_ids = set().union(*(enrollment_map.get(class_id, set()) for class_id in classes.ids))
        submissions = Submission.search([
            ("student_id", "in", sorted(all_partner_ids)) if all_partner_ids else ("id", "=", 0),
            ("state", "in", ("submitted", "complete")),
            ("is_course_explorer", "=", False),
            ("date_submitted", ">=", date_start),
            ("date_submitted", "<=", date_end),
            ("student_id.is_student", "=", True),
        ])
        submitted_subjects = defaultdict(set)
        submitted_partner_ids = set()
        for submission in submissions:
            submitted_partner_ids.add(submission.student_id.id)
            subjects = submission.subjects or submission.resource_id.subjects
            for subject in subjects:
                submitted_subjects[submission.student_id.id].add(subject.id)

        result = []
        for record in classes:
            enrolled_partner_ids = enrollment_map.get(record.id, set())
            subject = record.subject_id
            if subject:
                has_submission = any(
                    subject.id in submitted_subjects.get(partner_id, set())
                    for partner_id in enrolled_partner_ids
                )
            else:
                has_submission = bool(enrolled_partner_ids & submitted_partner_ids)
            if not has_submission:
                continue
            level = subject.level_id if subject else False
            result.append({
                "id": record.id,
                "name": record.display_name,
                "subject_id": subject.id if subject else False,
                "subject_name": subject.display_name if subject else "",
                "level_name": level.display_name or level.name or "" if level else "",
                "level_sequence": level.sequence or 0 if level else 0,
                "icon_url": (
                    f"/web/image/aps.subject/{subject.id}/icon"
                    if subject and subject.icon else ""
                ),
            })
        result.sort(key=lambda item: (
            item["level_sequence"],
            item["level_name"].lower(),
            item["name"].lower(),
        ))
        return result, enrollment_map

    @api.model
    def _weekly_class_options(self, date_start, date_end, selected_class_id=False):
        """Return classes visible to the user that have submissions in the period."""
        options, _enrollment_map = self._weekly_class_options_and_enrollments(
            date_start, date_end
        )
        return options

    @api.model
    def _weekly_class_student_partner_ids(self, class_id, date_start, date_end):
        if not class_id:
            return False
        enrollment_map = self._weekly_class_enrollment_map(
            [int(class_id)], date_start, date_end
        )
        return enrollment_map.get(int(class_id), set())

    @api.model
    def _weekly_submission_domain(self, student_ids, date_start, date_end, subject_ids=None):
        domain = [
            ("student_id", "in", sorted(student_ids)),
            ("state", "in", ("submitted", "complete")),
            ("is_course_explorer", "=", False),
            ("date_submitted", ">=", date_start),
            ("date_submitted", "<=", date_end),
        ]
        if subject_ids:
            domain += [
                "|",
                ("subjects", "in", list(subject_ids)),
                ("resource_id.subjects", "in", list(subject_ids)),
            ]
        return domain

    @api.model
    def _weekly_student_domain(self, student_ids):
        student_ids = sorted(student_ids)
        if len(student_ids) == 1:
            return [("student_id", "=", student_ids[0])]
        return [("student_id", "in", student_ids)]

    @api.model
    def _weekly_effective_subjects(self, submission, subject_ids=None):
        subjects = submission.subjects or submission.resource_id.subjects
        if subject_ids:
            subjects = subjects.filtered(lambda subject: subject.id in subject_ids)
        return subjects

    @api.model
    def get_grid_data(self, student_partner_id=False, date_start=False, date_end=False, type_ids=None, academic_term_id=False, class_id=False):
        user = self.env.user
        is_teacher = user.has_group("aps_sis.group_aps_teacher")
        if not is_teacher:
            student_partner_id = user.partner_id.id

        if date_start:
            date_start = fields.Date.to_date(date_start)
        if date_end:
            date_end = fields.Date.to_date(date_end)
        if not date_start:
            date_start = date.today() - timedelta(days=date.today().weekday() + 28)
        if not date_end:
            date_end = date.today()
        if academic_term_id:
            academic_term = self.env["aps.academic.term"].browse(int(academic_term_id)).exists()
            if academic_term:
                date_start = academic_term.start_date
                date_end = academic_term.end_date
        class_options, enrollment_map = self._weekly_class_options_and_enrollments(
            date_start, date_end
        )
        visible_class_ids = {item["id"] for item in class_options}
        if class_id and int(class_id) not in visible_class_ids:
            class_id = False
        class_id = int(class_id) if class_id else False
        class_student_partner_ids = enrollment_map.get(class_id, set()) if class_id else set()
        if class_id:
            selected_class = next(item for item in class_options if item["id"] == class_id)
            subject_ids = {selected_class["subject_id"]} if selected_class["subject_id"] else set()
            scoped_partner_ids = set(class_student_partner_ids)
        else:
            subject_ids = {
                item["subject_id"] for item in class_options if item["subject_id"]
            }
            scoped_partner_ids = set()
            for visible_class_id in visible_class_ids:
                scoped_partner_ids.update(enrollment_map.get(visible_class_id, set()))

        if student_partner_id and not is_teacher and not class_id:
            scoped_partner_ids = {user.partner_id.id}

        if not is_teacher:
            student_partner_id = user.partner_id.id
            if class_id and student_partner_id not in scoped_partner_ids:
                student_partner_id = False
            selected_partner_ids = {student_partner_id} if student_partner_id else set()
            group_by_student = False
        elif student_partner_id:
            student_partner_id = int(student_partner_id)
            if student_partner_id not in scoped_partner_ids:
                student_partner_id = False
            selected_partner_ids = {student_partner_id} if student_partner_id else scoped_partner_ids
            group_by_student = not student_partner_id
        else:
            selected_partner_ids = scoped_partner_ids
            group_by_student = True

        submissions = self.env["aps.resource.submission"].search(
            self._weekly_submission_domain(selected_partner_ids, date_start, date_end, subject_ids)
            if selected_partner_ids else [("id", "=", 0)]
        )
        available_types = submissions.mapped("type_id")
        submissions_by_row = defaultdict(list)
        for submission in submissions:
            effective_subjects = self._weekly_effective_subjects(submission, subject_ids)
            for subject in effective_subjects:
                submissions_by_row[
                    (submission.student_id.id, subject.id, submission.type_id.id)
                ].append(submission)
        requested_type_ids = type_ids
        type_ids = [int(value) for value in (type_ids or [])]
        rows = {}
        result_domain = (
            self._weekly_student_domain(selected_partner_ids) + [
                ("week_start", ">=", date_start - timedelta(days=date_start.weekday())),
                ("week_start", "<=", date_end),
            ]
            if selected_partner_ids else [("id", "=", 0)]
        )
        if subject_ids:
            result_domain.append(("subject_id", "in", list(subject_ids)))
        if requested_type_ids is not None:
            result_domain.append(("type_id", "in", type_ids or [0]))
        all_results = self.search(result_domain)
        if not available_types and requested_type_ids is None:
            available_types = all_results.mapped("type_id")
        selected_types = (
            available_types
            if requested_type_ids is None
            else available_types.filtered(lambda record: record.id in type_ids)
        )
        selected_type_id_set = set(selected_types.ids)
        for result in all_results:
            if result.type_id.id not in selected_type_id_set:
                continue
            row_student_id = result.student_id.id if group_by_student else False
            key = (row_student_id, result.subject_id.id, result.type_id.id)
            rows.setdefault(key, {
                "key": "%s-%s-%s" % key,
                "student_id": result.student_id.id if group_by_student else False,
                "student_name": result.student_id.display_name if group_by_student else False,
                "subject_id": result.subject_id.id,
                "subject_name": result.subject_id.display_name,
                "subject_icon_url": "/web/image/aps.subject/%s/icon" % result.subject_id.id if result.subject_id.icon else False,
                "type_id": result.type_id.id,
                "type_name": result.type_id.display_name,
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
                "submission_domain": self._weekly_student_domain(
                    {result.student_id.id} if group_by_student else selected_partner_ids
                ) + [
                    ("state", "in", ("submitted", "complete")),
                    ("is_course_explorer", "=", False),
                    ("type_id", "=", result.type_id.id),
                    "|",
                    ("subjects", "in", [result.subject_id.id]),
                    ("resource_id.subjects", "in", [result.subject_id.id]),
                    ("date_submitted", ">=", max(result.week_start, date_start)),
                    ("date_submitted", "<=", min(result.week_end, date_end)),
                ],
            })
        academic_week_map = self._weekly_academic_week_map(date_start, date_end)
        weeks = []
        cursor = date_start - timedelta(days=date_start.weekday())
        while cursor <= date_end:
            academic_week = academic_week_map.get(cursor)
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
            row_student_id, subject_id, type_id = row_key
            if row_student_id:
                row_submissions = submissions_by_row.get(
                    (row_student_id, subject_id, type_id), []
                )
            else:
                row_submissions = [
                    submission
                    for (student_id, indexed_subject_id, indexed_type_id), records
                    in submissions_by_row.items()
                    if indexed_subject_id == subject_id
                    and indexed_type_id == type_id
                    for submission in records
                ]
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
                "submission_domain": self._weekly_student_domain(
                    {row_student_id} if row_student_id else selected_partner_ids
                ) + [
                    ("state", "in", ("submitted", "complete")),
                    ("is_course_explorer", "=", False),
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
            # Keep the option list scoped to the class(es), not to the
            # currently selected student. Selecting a student only narrows
            # the grid; it must never remove the other class students from
            # this dropdown.
            student_partners = self.env["res.partner"].browse(
                sorted(scoped_partner_ids)
            ).filtered("is_student").sorted(
                key=lambda partner: partner.display_name.lower()
            )
            students = [
                {"id": partner.id, "name": partner.display_name}
                for partner in student_partners
            ]
        terms = self.env["aps.academic.term"].search([], order="start_date desc")
        return {
            "studentId": student_partner_id if not group_by_student else False,
            "classId": class_id,
            "canSelectAllStudents": is_teacher,
            "groupByStudent": group_by_student,
            "classes": class_options,
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
