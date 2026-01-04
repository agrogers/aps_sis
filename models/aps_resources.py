import re
import base64
import requests
from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError

class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'Resource (APS)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    # Removed _parent_store since we now support multiple parents
    _order = 'sequence, name'

    sequence = fields.Integer(string='Sequence', default=10)
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    name = fields.Char(string='Name', tracking=True)
    description = fields.Text(string='Description', tracking=True)

    question = fields.Html(string='Question')
    answer = fields.Html(string='Answer')
    thumbnail = fields.Binary(string='Thumbnail', compute='_compute_thumbnail', store=True)

    type_id = fields.Many2one('aps.resource.types', string='Type', ondelete='set null')
    type_icon = fields.Binary(string='Type Icon', related='type_id.icon', readonly=True)
    type_color = fields.Char(string='Type Color', related='type_id.color', readonly=True)
    url = fields.Char(string='URL', 
                      required=False, tracking=True)
    category = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
        ('information', 'Information'),
        ], string='Category', default='optional', help='Identifies which resources should be assigned to students to complete.', tracking=True)
    marks = fields.Float(string='Marks', digits=(16, 1), help='Maximum marks/points for this resource')
    subjects = fields.Many2many('op.subject', string='Subjects')
    task_ids = fields.One2many('aps.resource.task', 'resource_id', string='Tasks')
    parent_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'child_id', 'parent_id', string='Parent Resources', domain="[('id', '!=', id)]")
    primary_parent_id = fields.Many2one(
        'aps.resources', 
        string='Main Parent', 
        domain="[('id', 'in', parent_ids)]", 
        help='The resource used for generating the display name. Must be one of the selected parents.',
    )
    child_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'parent_id', 'child_id', string='Child Resources', domain="[('id', '!=', id)]")
    # Removed parent_path since multiple parents don't fit tree structure
    child_count = fields.Integer(string='Total Children', compute='_compute_child_count')
    has_multiple_parents = fields.Boolean(string='Has Multiple Parents', compute='_compute_has_multiple_parents')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        parent_id = self.env.context.get('default_primary_parent_id')
        if parent_id and 'primary_parent_id' in fields_list:
            res['primary_parent_id'] = parent_id

        # Handle many2many default for parent_ids
        default_parent_ids = self.env.context.get('default_parent_ids')
        if default_parent_ids and 'parent_ids' in fields_list:
            res['parent_ids'] = default_parent_ids
            # Extract parent ID from the many2many command and set primary_parent_id
            if default_parent_ids and len(default_parent_ids) > 0:
                command = default_parent_ids[0]
                if len(command) >= 3 and command[0] == 6 and command[2]:  # (6, 0, [ids])
                    parent_ids_list = command[2]
                    if parent_ids_list and 'primary_parent_id' in fields_list and not res.get('primary_parent_id'):
                        res['primary_parent_id'] = parent_ids_list[0]

        # Set default type_id to the most recently used type
        if 'type_id' in fields_list and not res.get('type_id'):
            # Find the most recent resource with a type_id
            recent_resource = self.search([('type_id', '!=', False)], order='write_date desc', limit=1)
            if recent_resource:
                res['type_id'] = recent_resource.type_id.id

        return res

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            # Count resources that have this resource as a parent
            rec.child_count = self.search_count([('parent_ids', 'in', rec.id)])

    @api.depends('parent_ids')
    def _compute_has_multiple_parents(self):
        for rec in self:
            rec.has_multiple_parents = len(rec.parent_ids) > 1

    @api.depends('primary_parent_id.display_name', 'primary_parent_id.name', 'name', 'parent_ids')
    def _compute_display_name(self):
        """Build display name using the primary parent's full path if available."""
        for rec in self:
            # Priority: 1. primary_parent_id, 2. first parent from parent_ids, 3. just name
            parent_to_use = rec.primary_parent_id or (rec.parent_ids and rec.parent_ids[0])
            
            if parent_to_use:
                parent_display = parent_to_use.display_name or parent_to_use.name or ''
                rec.display_name = f"{parent_display}🢒{rec.name or ''}"
            else:
                rec.display_name = rec.name or ''

    @api.depends('question', 'answer')
    def _compute_thumbnail(self):
        """Extract first image from question or answer HTML and store as thumbnail."""
        for rec in self:
            thumbnail_data = False
            html_content = rec.question or rec.answer or ''
            
            # Find first img src in HTML
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
            if match:
                img_src = match.group(1)
                try:
                    # Handle base64 data URLs
                    if img_src.startswith('data:image'):
                        # Extract base64 part after comma
                        base64_data = img_src.split(',', 1)
                        if len(base64_data) > 1:
                            thumbnail_data = base64_data[1]
                    # Handle Odoo attachment URLs (relative paths)
                    elif img_src.startswith('/web/image') or img_src.startswith('/web/content'):
                        # For internal Odoo images, try to get from attachment
                        # Extract attachment id if present
                        att_match = re.search(r'/web/(?:image|content)/(\d+)', img_src)
                        if att_match:
                            att_id = int(att_match.group(1))
                            attachment = self.env['ir.attachment'].sudo().browse(att_id)
                            if attachment.exists() and attachment.datas:
                                thumbnail_data = attachment.datas
                    # Handle external URLs
                    elif img_src.startswith('http'):
                        response = requests.get(img_src, timeout=5)
                        if response.status_code == 200:
                            thumbnail_data = base64.b64encode(response.content).decode('utf-8')
                except Exception:
                    # Silently fail - thumbnail is optional
                    pass
            
            rec.thumbnail = thumbnail_data

    @api.constrains('primary_parent_id', 'parent_ids')
    def _check_primary_parent(self):
        for rec in self:
            if rec.primary_parent_id and rec.primary_parent_id not in rec.parent_ids:
                raise ValidationError("The primary parent must be one of the selected parent resources.")

    @api.onchange('parent_ids')
    def _onchange_parent_ids(self):
        """Clear primary parent if it's no longer in the parent list, or set it if not set."""
        if self.primary_parent_id and self.primary_parent_id not in self.parent_ids:
            self.primary_parent_id = False
        elif not self.primary_parent_id and self.parent_ids:
            # Set primary parent to the first parent if not set
            self.primary_parent_id = self.parent_ids[0]

    # Removed _check_parent_loop since multiple parents make cycle detection complex

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals:
            # When name changes, update display_name for self and direct children
            for rec in self:
                rec._compute_display_name()
                # Update display_name for direct children
                children = self.search([('parent_ids', 'in', rec.id)])
                if children:
                    children._compute_display_name()
        return result

    def _get_all_descendants(self):
        """Recursively get all descendants of this resource in the graph."""
        descendants = self.env['aps.resources']
        to_process = self.child_ids  # Direct children
        
        while to_process:
            descendants |= to_process
            next_level = self.env['aps.resources']
            for child in to_process:
                next_level |= child.child_ids
            to_process = next_level - descendants  # Avoid duplicates
        
        return descendants

    def action_assign_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Students',
            'res_model': 'aps.assign.students.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('aps_sis.view_aps_assign_students_wizard').id,
            'target': 'new',
            'context': {
                'default_resource_id': self.id,
            },
        }

