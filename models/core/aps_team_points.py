from datetime import timedelta

from odoo import api, fields, models


class APSTeamPoints(models.Model):
    _name = 'aps.team.points'
    _description = 'Team Points'
    _order = 'date desc, id desc'

    team_id = fields.Many2one(
        'aps.team', string='Team', ondelete='set null',
        help='The team receiving these points. This may be assigned later when the student is placed in a team.',
    )
    team_color = fields.Char(
        related='team_id.color', string='Team Color', readonly=True,
    )
    event_id = fields.Many2one('aps.event', string='Event', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Student', ondelete='set null')
    points = fields.Float(string='Points', required=True, default=1.0)
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

    @api.model
    def cron_process_points(self):
        """Allocate team points from all supported source models.

        Currently this processes submitted or closed award votes by creating
        one team-points entry for each vote.

        The vote is linked through ``aps.team.points.record`` so it is never
        processed twice. Votes without a student team are still recorded with
        an empty team and are completed on a later cron run once the student is
        assigned to a team.
        """
        Vote = self.env['aps.award.vote'].sudo()
        Student = self.env['aps.student'].sudo().with_context(active_test=False)
        PointRecord = self.env['aps.team.points.record'].sudo()
        now = fields.Datetime.now()

        lastcall = self.env.context.get('lastcall')
        if lastcall:
            lastcall = fields.Datetime.to_datetime(lastcall)
        else:
            lastcall = now - timedelta(days=1)

        # Process votes changed since the previous scheduled run. The linked
        # record remains the authoritative duplicate check.
        votes = Vote.search([
            ('state', 'in', ['submitted', 'closed']),
            ('recipient_partner_id', '!=', False),
            ('write_date', '>=', lastcall),
        ])
        existing_ids = set(PointRecord.search([
            ('model', '=', 'aps.award.vote'),
            ('res_id', 'in', votes.ids),
        ]).mapped('res_id')) if votes else set()

        for vote in votes:
            if vote.id in existing_ids:
                continue
            student = Student.search(
                [('partner_id', '=', vote.recipient_partner_id.id)], limit=1,
            )
            point = self.sudo().create({
                'team_id': student.team_id.id if student and student.team_id else False,
                'partner_id': vote.recipient_partner_id.id,
                'points': 1.0,
                'date': vote.submitted_date or fields.Date.context_today(self),
                'comment': vote.description or 'Award vote',
            })
            PointRecord.create({
                'team_points_id': point.id,
                'model': 'aps.award.vote',
                'res_id': vote.id,
            })

        # Complete previously recorded votes that did not yet have a team.
        pending_records = PointRecord.search([
            ('model', '=', 'aps.award.vote'),
            ('team_points_id.team_id', '=', False),
        ])
        for record in pending_records:
            vote = Vote.browse(record.res_id).exists()
            if not vote or not vote.recipient_partner_id:
                continue
            student = Student.search(
                [('partner_id', '=', vote.recipient_partner_id.id)], limit=1,
            )
            if student and student.team_id:
                record.team_points_id.team_id = student.team_id.id

        return True


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