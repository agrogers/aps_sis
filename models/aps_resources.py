import re
import base64
import requests
from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError

class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'Resource (APS)' 
    _parent_store = True

    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    name = fields.Char(string='Name')
    description = fields.Text(string='Description')

    question = fields.Html(string='Question')
    answer = fields.Html(string='Answer')
    thumbnail = fields.Binary(string='Thumbnail', compute='_compute_thumbnail', store=True)

    type_id = fields.Many2one('aps.resource.types', string='Type', ondelete='set null')
    type_icon = fields.Binary(string='Type Icon', related='type_id.icon', readonly=True)
    type_color = fields.Char(string='Type Color', related='type_id.color', readonly=True)
    url = fields.Char(string='URL', 
                      required=False)
    category = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
        ('information', 'Information'),
        ], string='Category', default='optional', help='Identifies which resources should be assigned to students to complete.')
    relevance = fields.Float(string='Relevance', default=1.0, help='Relevance score for the resource (higher values indicate higher relevance).')
    assignment_ids = fields.One2many('aps.resource.assignment', 'resource_id', string='Assignments')
    parent_id = fields.Many2one('aps.resources', string='Parent Resource', index=True, ondelete='set null')
    child_ids = fields.Many2many('aps.resources', 'aps_resources_child_rel', 'parent_id', 'child_id', string='Child Resources', domain="[('id', '!=', id)]")
    parent_path = fields.Char(index=True)
    child_count = fields.Integer(string='Total Children', compute='_compute_child_count')

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            if rec.id:
                # Use parent_path to find all descendants efficiently
                # All children have parent_path starting with this record's path
                count = self.search_count([
                    ('parent_path', 'like', f'{rec.parent_path}%'),
                    ('id', '!=', rec.id)
                ])
                rec.child_count = count
            else:
                rec.child_count = 0

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

    @api.depends('parent_path', 'name')
    def _compute_display_name(self):
        """Build display name from ancestor chain, removing redundant prefixes."""
        for rec in self:
            if not rec.parent_path:
                rec.display_name = rec.name or ''
                continue
            
            # Get all ancestor IDs from parent_path (e.g., "1/5/12/" -> [1, 5, 12])
            path_ids = [int(p) for p in rec.parent_path.strip('/').split('/') if p]
            if not path_ids:
                rec.display_name = rec.name or ''
                continue
            
            # Fetch all ancestors in order
            ancestors = self.browse(path_ids)
            
            # Build display name, removing redundant parts from immediate parent
            result = ''
            prev_name = ''
            separator = '🢒'
            for ancestor in ancestors:
                ancestor_name = ancestor.name or ''
                if not result:
                    # First part, use as-is
                    result = ancestor_name
                else:
                    # Check if current name starts with previous ancestor's name
                    if ancestor_name.startswith(prev_name):
                        # Remove the redundant prefix from immediate parent
                        suffix = ancestor_name[len(prev_name):]
                        if suffix:
                            # Add space only if suffix doesn't start with punctuation
                            if suffix[0].isalnum():
                                result += separator + suffix
                            else:
                                result += suffix
                    else:
                        # No overlap with immediate parent, add with space
                        result += separator + ancestor_name
                prev_name = ancestor_name
            
            rec.display_name = result

    @api.constrains('parent_id')
    def _check_parent_loop(self):
        if not self._check_recursion():
            raise ValidationError('Recursive resource hierarchy detected. A resource cannot be its own ancestor.')

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

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals:
            # When name changes, update display_name for all descendants
            for rec in self:
                descendants = self.search([('parent_path', 'like', f'{rec.parent_path}%'), ('id', '!=', rec.id)])
                if descendants:
                    descendants._compute_display_name()
        return result

