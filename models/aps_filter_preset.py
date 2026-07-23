from odoo import api, fields, models
from odoo.exceptions import UserError


class APSFilterPreset(models.Model):
    _name = 'aps.filter.preset'
    _description = 'Saved Filter Preset'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    component_key = fields.Char(string='Component', required=True, index=True)
    filter_data = fields.Json(string='Filter Data', default=dict)
    is_active = fields.Boolean(string='Active', default=False)

    _sql_constraints = [
        ('name_user_component_uniq', 'unique(name, user_id, component_key)',
         'A preset with this name already exists for this user and component.'),
    ]

    # ------------------------------------------------------------------
    # RPC methods for frontend
    # ------------------------------------------------------------------

    @api.model
    def get_presets(self, component_key):
        """Return list of {id, name, is_active} for current user + component_key."""
        records = self.search_read(
            [('user_id', '=', self.env.uid), ('component_key', '=', component_key)],
            ['id', 'name', 'is_active'],
        )
        return records

    @api.model
    def get_active_preset(self, component_key):
        """Return the active preset for this component+user, or None."""
        record = self.search([
            ('user_id', '=', self.env.uid),
            ('component_key', '=', component_key),
            ('is_active', '=', True),
        ], limit=1)
        if record:
            return {
                'id': record.id,
                'name': record.name,
                'filter_data': record.filter_data or {},
            }
        return None

    @api.model
    def get_preset(self, preset_id):
        """Return {name, filter_data} for a single preset."""
        record = self.browse(preset_id)
        if not record.exists() or record.user_id.id != self.env.uid:
            raise UserError('Preset not found or access denied.')
        return {
            'name': record.name,
            'filter_data': record.filter_data or {},
        }

    @api.model
    def upsert_preset(self, component_key, name, filter_data):
        """Create or update a preset. If one exists with same name+user+key, overwrite."""
        if not name or not name.strip():
            raise UserError('Preset name is required.')
        name = name.strip()
        # Use SQL domain bypass to avoid Odoo's automatic active=True filter
        # (Odoo treats any field named 'active' as an archive flag and filters it out)
        existing = self.sudo().search([
            ('user_id', '=', self.env.uid),
            ('component_key', '=', component_key),
            ('name', '=', name),
        ], limit=1)
        if existing:
            existing.filter_data = filter_data or {}
            existing.is_active = True
            self._deactivate_others(component_key, existing.id)
            return {'id': existing.id, 'name': existing.name, 'action': 'updated'}
        record = self.create({
            'name': name,
            'component_key': component_key,
            'filter_data': filter_data or {},
            'is_active': True,
        })
        self._deactivate_others(component_key, record.id)
        return {'id': record.id, 'name': record.name, 'action': 'created'}

    @api.model
    def set_active_preset(self, component_key, preset_id):
        """Set a preset as active and deactivate others."""
        record = self.browse(preset_id)
        if not record.exists() or record.user_id.id != self.env.uid:
            raise UserError('Preset not found or access denied.')
        record.is_active = True
        self._deactivate_others(component_key, preset_id)
        return True

    @api.model
    def clear_active_preset(self, component_key):
        """Clear the active preset for this component+user."""
        self.search([
            ('user_id', '=', self.env.uid),
            ('component_key', '=', component_key),
            ('is_active', '=', True),
        ]).write({'is_active': False})
        return True

    @api.model
    def delete_preset(self, preset_id):
        """Delete a preset owned by the current user."""
        record = self.browse(preset_id)
        if not record.exists() or record.user_id.id != self.env.uid:
            raise UserError('Preset not found or access denied.')
        record.unlink()
        return True

    def _deactivate_others(self, component_key, current_id):
        """Set is_active=False for all other presets of this user+component."""
        self.search([
            ('user_id', '=', self.env.uid),
            ('component_key', '=', component_key),
            ('is_active', '=', True),
            ('id', '!=', current_id),
        ]).write({'is_active': False})