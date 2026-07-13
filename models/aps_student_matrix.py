from odoo import fields, models, api


class APSStudentMatrix(models.TransientModel):
    _name = 'aps.student.matrix'
    _description = 'Student Subject Matrix'

    @api.model
    def get_home_classes(self):
        """Return all home/pastoral care classes for the current academic year."""
        home_class_tag_names = {'Home Class', 'Pastoral Care Subject'}
        current_year = self.env['aps.academic.year'].search(
            [('is_current', '=', True)], limit=1
        )
        domain = [
            ('state', '=', 'enrolled'),
        ]
        if current_year:
            domain.append(('start_date', '>=', current_year.start_date))

        enrollments = self.env['aps.student.class'].search(domain)
        home_class_ids = enrollments.mapped('home_class_id')

        result = []
        seen = set()
        for cls in home_class_ids:
            if cls.id in seen:
                continue
            category = cls.subject_id.category_id
            if category and any(t.name in home_class_tag_names for t in category.tag_ids):
                seen.add(cls.id)
                result.append({'id': cls.id, 'name': cls.display_name or cls.name})

        return sorted(result, key=lambda c: c['name'])

    @api.model
    def get_matrix_data(self, class_ids):
        """
        Given a list of class_ids, return the matrix data:
        - students: sorted alphabetically
        - subjects: sorted alphabetically (from classes enrolled by those students)
        - cells: dict mapping "studentId_subjectId" -> True
        - subject_colors: dict mapping subject_id -> hex color
        - student_totals: dict mapping student_id -> count
        - subject_totals: dict mapping subject_id -> count
        """
        if not class_ids:
            return {
                'students': [],
                'subjects': [],
                'cells': {},
                'subject_colors': {},
                'student_totals': {},
                'subject_totals': {},
            }

        # Find students enrolled in the selected classes
        enrollments = self.env['aps.student.class'].search([
            ('home_class_id', 'in', class_ids),
            ('state', '=', 'enrolled'),
        ])
        student_ids = enrollments.mapped('student_id')

        if not student_ids:
            return {
                'students': [],
                'subjects': [],
                'cells': {},
                'subject_colors': {},
                'student_totals': {},
                'subject_totals': {},
            }

        # Find ALL enrollments for these students
        all_enrollments = self.env['aps.student.class'].search([
            ('student_id', 'in', student_ids.ids),
            ('state', '=', 'enrolled'),
        ])

        # Get all unique subjects from those enrollments
        all_classes = all_enrollments.mapped('home_class_id')
        subject_ids = all_classes.mapped('subject_id')

        # Build subject colors map
        subject_colors = {}
        for subject in subject_ids:
            if subject.category_id and subject.category_id.color_rgb:
                subject_colors[subject.id] = subject.category_id.color_rgb
            else:
                subject_colors[subject.id] = subject._generate_color_from_name(subject.name)

        # Build cells: which student takes which subject
        cells = {}
        student_totals = {s.id: 0 for s in student_ids}
        subject_enrolled_students = {s.id: set() for s in subject_ids}

        for enrollment in all_enrollments:
            student = enrollment.student_id
            subject = enrollment.home_class_id.subject_id
            if student.id in student_totals and subject.id in subject_enrolled_students:
                key = f"{student.id}_{subject.id}"
                if key not in cells:
                    gcse_val = subject.gcse_certificate or 0.0
                    cells[key] = {'gcse': gcse_val}
                    student_totals[student.id] += gcse_val
                    subject_enrolled_students[subject.id].add(student.id)

        # Subject totals = unique student count per subject
        subject_totals = {}
        for subject in subject_ids:
            subject_totals[subject.id] = len(subject_enrolled_students[subject.id])

        # Round student totals to 1 decimal place
        for sid in student_totals:
            student_totals[sid] = round(student_totals[sid], 1)

        # Build output lists
        students = []
        for s in student_ids.sorted(key=lambda r: r.partner_id.name or ''):
            students.append({
                'id': s.id,
                'name': s.partner_id.name or '',
                'roll': s.roll or '',
            })

        subjects = []
        for s in subject_ids.sorted(key=lambda r: r.name or ''):
            subjects.append({
                'id': s.id,
                'name': s.name or '',
                'code': s.code or '',
                'color': subject_colors.get(s.id, '#888888'),
                'gcse_certificate': s.gcse_certificate or 0.0,
            })

        return {
            'students': students,
            'subjects': subjects,
            'cells': cells,
            'subject_colors': subject_colors,
            'student_totals': student_totals,
            'subject_totals': subject_totals,
        }