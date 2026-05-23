from odoo import models, fields, api


class APSLocation(models.Model):
    _name = 'aps.location'
    _description = 'APEX Location'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    location_type = fields.Selection([
        ('classroom', 'Classroom'),
        ('sports_field', 'Sports Field'),
        ('playground', 'Playground'),
        ('hall', 'Hall'),
        ('lab', 'Lab'),
        ('library', 'Library'),
        ('outdoor', 'Outdoor Area'),
        ('other', 'Other'),
    ], string='Type', default='classroom', required=True)
    building = fields.Char(string='Building')
    floor = fields.Char(string='Floor')
    capacity = fields.Integer(string='Capacity')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(string='Active', default=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'building', 'floor')
    def _compute_display_name(self):
        for record in self:
            parts = [record.name]
            if record.building:
                parts.append(record.building)
            if record.floor:
                parts.append(record.floor)
            record.display_name = ' – '.join(parts)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Location name must be unique!'),
    ]
