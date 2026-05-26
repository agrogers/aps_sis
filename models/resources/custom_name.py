from odoo import models, fields


class ResourceCustomName(models.Model):
    _name = 'aps.resource.custom.name'
    _description = 'Custom Resource Name for Parent/Child'
    _rec_name = 'custom_name'
    _sql_constraints = [
        ('unique_parent_child', 'unique(parent_resource_id, resource_id)', 'Custom name must be unique per parent/child pair.')
    ]

    parent_resource_id = fields.Many2one('aps.resources', string='Parent Resource', required=True, ondelete='cascade')
    resource_id = fields.Many2one('aps.resources', string='Resource', required=True, ondelete='cascade')
    custom_name = fields.Char(string='Custom Name', required=True)

    def action_delete(self):
        """Delete the custom name and close the popup when invoked from the form header."""
        self.ensure_one()
        self.unlink()
        return {'type': 'ir.actions.act_window_close', 'tag': 'reload'}
