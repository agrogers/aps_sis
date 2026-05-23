from odoo import models, fields, api


class ASCTTDashboard(models.TransientModel):
    _name = 'asctt.dashboard'
    _description = 'aSc Timetable Dashboard'

    count_periods = fields.Integer(string='Periods', compute='_compute_counts', store=False)
    count_breaks = fields.Integer(string='Breaks', compute='_compute_counts', store=False)
    count_days_defs = fields.Integer(string='Day Definitions', compute='_compute_counts', store=False)
    count_weeks_defs = fields.Integer(string='Week Definitions', compute='_compute_counts', store=False)
    count_terms_defs = fields.Integer(string='Term Definitions', compute='_compute_counts', store=False)
    count_subjects = fields.Integer(string='Subjects', compute='_compute_counts', store=False)
    count_teachers = fields.Integer(string='Teachers', compute='_compute_counts', store=False)
    count_buildings = fields.Integer(string='Buildings', compute='_compute_counts', store=False)
    count_classrooms = fields.Integer(string='Classrooms', compute='_compute_counts', store=False)
    count_grades = fields.Integer(string='Grades', compute='_compute_counts', store=False)
    count_classes = fields.Integer(string='Classes', compute='_compute_counts', store=False)
    count_groups = fields.Integer(string='Groups', compute='_compute_counts', store=False)
    count_lessons = fields.Integer(string='Lessons', compute='_compute_counts', store=False)
    count_cards = fields.Integer(string='Cards', compute='_compute_counts', store=False)
    count_supervisions = fields.Integer(string='Classroom Supervisions', compute='_compute_counts', store=False)

    @api.depends()
    def _compute_counts(self):
        for rec in self:
            rec.count_periods = self.env['asctt.period'].search_count([])
            rec.count_breaks = self.env['asctt.break'].search_count([])
            rec.count_days_defs = self.env['asctt.days.def'].search_count([])
            rec.count_weeks_defs = self.env['asctt.weeks.def'].search_count([])
            rec.count_terms_defs = self.env['asctt.terms.def'].search_count([])
            rec.count_subjects = self.env['asctt.subject'].search_count([])
            rec.count_teachers = self.env['asctt.teacher'].search_count([])
            rec.count_buildings = self.env['asctt.building'].search_count([])
            rec.count_classrooms = self.env['asctt.classroom'].search_count([])
            rec.count_grades = self.env['asctt.grade'].search_count([])
            rec.count_classes = self.env['asctt.class'].search_count([])
            rec.count_groups = self.env['asctt.group'].search_count([])
            rec.count_lessons = self.env['asctt.lesson'].search_count([])
            rec.count_cards = self.env['asctt.card'].search_count([])
            rec.count_supervisions = self.env['asctt.classroom.supervision'].search_count([])

    def _open_list_view(self, model_name, title):
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': model_name,
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_open_periods(self):
        return self._open_list_view('asctt.period', 'Periods')

    def action_open_breaks(self):
        return self._open_list_view('asctt.break', 'Breaks')

    def action_open_days_defs(self):
        return self._open_list_view('asctt.days.def', 'Day Definitions')

    def action_open_weeks_defs(self):
        return self._open_list_view('asctt.weeks.def', 'Week Definitions')

    def action_open_terms_defs(self):
        return self._open_list_view('asctt.terms.def', 'Term Definitions')

    def action_open_subjects(self):
        return self._open_list_view('asctt.subject', 'Subjects')

    def action_open_teachers(self):
        return self._open_list_view('asctt.teacher', 'Teachers')

    def action_open_buildings(self):
        return self._open_list_view('asctt.building', 'Buildings')

    def action_open_classrooms(self):
        return self._open_list_view('asctt.classroom', 'Classrooms')

    def action_open_grades(self):
        return self._open_list_view('asctt.grade', 'Grades')

    def action_open_classes(self):
        return self._open_list_view('asctt.class', 'Classes')

    def action_open_groups(self):
        return self._open_list_view('asctt.group', 'Groups')

    def action_open_lessons(self):
        return self._open_list_view('asctt.lesson', 'Lessons')

    def action_open_cards(self):
        return self._open_list_view('asctt.card', 'Cards')

    def action_open_supervisions(self):
        return self._open_list_view('asctt.classroom.supervision', 'Classroom Supervisions')

    def action_import_xml(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import aSc Timetable XML',
            'res_model': 'asctt.import.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_flat_view(self):
        action = self.env.ref('aps_sis.asctt_flat_row_action')
        return action.read()[0]

    def action_open_timetable(self):
        action = self.env.ref('aps_sis.aps_timetable_entry_action')
        return action.read()[0]
