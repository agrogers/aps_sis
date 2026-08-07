from odoo import api, fields, models


class APSTeamPoints(models.Model):
    _name = 'aps.team.points'
    _description = 'Team Points'
    _order = 'date desc, id desc'

    team_id = fields.Many2one('aps.team', string='Team', required=True, ondelete='cascade')
    event_id = fields.Many2one('aps.event', string='Event', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Student', ondelete='set null')
    points = fields.Float(string='Points', required=True)
    weighted_points = fields.Float(string='Weighted Points')
    associated_record_ids = fields.One2many(
        'aps.team.points.record', 'team_points_id',
        string='Associated Records',
    )
    comment = fields.Text(string='Comment')
    date = fields.Date(string='Date', required=True, default=fields.Date.today)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('team_id', 'date')
    def _compute_display_name(self):
        for record in self:
            team_name = record.team_id.display_name or ''
            date_str = record.date and record.date.strftime('%Y-%m-%d') or ''
            record.display_name = f"{team_name} - {date_str}" if team_name and date_str else (team_name or date_str)


class APSTeamPointsRecord(models.Model):
    _name = 'aps.team.points.record'
    _description = 'Team Points Associated Record'
    _order = 'id'

    team_points_id = fields.Many2one(
        'aps.team.points', string='Team Points',
        required=True, ondelete='cascade',
    )
    model = fields.Char(string='Model', required=True)
    res_id = fields.Integer(string='Record ID', required=True)

    display_name = fields.Char(compute='_compute_display_name', store=False)

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.model}#{record.res_id}"

    _sql_constraints = [
        (
            'unique_model_res_id',
            'unique(model, res_id)',
            'This record has already been associated with a team points entry.',
        ),
    ]