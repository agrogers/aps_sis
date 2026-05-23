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

    def action_open_periods(self):
        return {'type': 'ir.actions.act_window', 'name': 'Periods', 'res_model': 'asctt.period', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_breaks(self):
        return {'type': 'ir.actions.act_window', 'name': 'Breaks', 'res_model': 'asctt.break', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_days_defs(self):
        return {'type': 'ir.actions.act_window', 'name': 'Day Definitions', 'res_model': 'asctt.days.def', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_weeks_defs(self):
        return {'type': 'ir.actions.act_window', 'name': 'Week Definitions', 'res_model': 'asctt.weeks.def', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_terms_defs(self):
        return {'type': 'ir.actions.act_window', 'name': 'Term Definitions', 'res_model': 'asctt.terms.def', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_subjects(self):
        return {'type': 'ir.actions.act_window', 'name': 'Subjects', 'res_model': 'asctt.subject', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_teachers(self):
        return {'type': 'ir.actions.act_window', 'name': 'Teachers', 'res_model': 'asctt.teacher', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_buildings(self):
        return {'type': 'ir.actions.act_window', 'name': 'Buildings', 'res_model': 'asctt.building', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_classrooms(self):
        return {'type': 'ir.actions.act_window', 'name': 'Classrooms', 'res_model': 'asctt.classroom', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_grades(self):
        return {'type': 'ir.actions.act_window', 'name': 'Grades', 'res_model': 'asctt.grade', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_classes(self):
        return {'type': 'ir.actions.act_window', 'name': 'Classes', 'res_model': 'asctt.class', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_groups(self):
        return {'type': 'ir.actions.act_window', 'name': 'Groups', 'res_model': 'asctt.group', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_lessons(self):
        return {'type': 'ir.actions.act_window', 'name': 'Lessons', 'res_model': 'asctt.lesson', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_cards(self):
        return {'type': 'ir.actions.act_window', 'name': 'Cards', 'res_model': 'asctt.card', 'view_mode': 'list,form', 'target': 'current'}

    def action_open_supervisions(self):
        return {'type': 'ir.actions.act_window', 'name': 'Classroom Supervisions', 'res_model': 'asctt.classroom.supervision', 'view_mode': 'list,form', 'target': 'current'}
