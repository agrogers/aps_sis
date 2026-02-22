import re
import base64
import requests
from html.parser import HTMLParser
from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError

class ExtractHeadingContent(HTMLParser):
    """Extract content under a specific heading in HTML."""
    def __init__(self, target_heading):
        super().__init__()
        self.target_heading = target_heading.lower().strip()
        self.content_parts = []
        self.collecting = False
        self.found_target = False
        self.target_heading_level = None
        self.current_heading_text = []
        self.in_heading = False
        self.current_heading_tag = None
        
    def handle_starttag(self, tag, attrs):
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # We're entering a heading tag
            self.in_heading = True
            self.current_heading_tag = tag
            self.current_heading_text = []
            
            # Only include nested headings (deeper level than target)
            if self.collecting and self.found_target:
                heading_level = int(tag[1])
                if heading_level > self.target_heading_level:
                    # This is a nested heading, include it
                    self._append_tag(tag, attrs)
        elif self.collecting and self.found_target:
            # Only collecting content after we've found the target heading
            self._append_tag(tag, attrs)
    
    def _append_tag(self, tag, attrs):
        """Helper to properly reconstruct an opening tag with all attributes."""
        if attrs:
            attrs_str = ' '.join([f'{k}="{v}"' for k, v in attrs])
            self.content_parts.append(f'<{tag} {attrs_str}>')
        else:
            self.content_parts.append(f'<{tag}>')
                
    def handle_endtag(self, tag):
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # End of heading tag - check if text matches
            heading_text = ''.join(self.current_heading_text).strip().lower()
            heading_level = int(tag[1])
            
            if heading_text == self.target_heading and not self.found_target:
                # Found our target heading!
                self.found_target = True
                self.collecting = True
                self.target_heading_level = heading_level
            elif self.found_target and self.collecting:
                # We're collecting content from target heading
                # Stop if we hit a heading of equal or higher level (lower number = higher level)
                if heading_level <= self.target_heading_level:
                    self.collecting = False
                elif heading_level > self.target_heading_level:
                    # This is a nested heading, include its closing tag
                    self.content_parts.append(f'</{tag}>')
            
            self.in_heading = False
            self.current_heading_text = []
        elif self.collecting and self.found_target:
            # Only collect closing tags if we've found the target heading
            self.content_parts.append(f'</{tag}>')
            
    def handle_data(self, data):
        if self.in_heading:
            # Accumulate heading text for comparison
            self.current_heading_text.append(data)
            # Only add to output if we're collecting and this is a nested heading (deeper level)
            if self.collecting and self.found_target and self.current_heading_tag:
                heading_level = int(self.current_heading_tag[1])
                if heading_level > self.target_heading_level:
                    self.content_parts.append(data)
        elif self.collecting:
            # Collecting content under target heading
            self.content_parts.append(data)
    
    def get_content(self):
        return ''.join(self.content_parts).strip()


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

class APSResource(models.Model):
    _name = 'aps.resources'
    _description = 'APEX Resources'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    sequence = fields.Integer(string='Sequence', default=10)
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    name = fields.Char(string='Name', tracking=True)
    custom_name_ids = fields.One2many('aps.resource.custom.name', 'resource_id', string='Custom Names')
    # Computed JSON data of custom names for various parents for this resource
    parent_custom_name_data = fields.Json(string='Custom Names Data', compute='_compute_parent_custom_name_data', store=True)
    description = fields.Text(string='Description', tracking=True)

    has_question = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('use_parent', 'Use Parent'),
        ], string='Has Question', 
        default='no', 
        help='A resource can use the parent\'s question if set to "Use Parent".',
        required=True,
        tracking=True)
    question = fields.Html(string='Question')
    parent_question = fields.Html(string='Parent Question', compute='_compute_parent_question', store=False)

    has_answer = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ('yes_notes', 'Yes (Notes)'),
        ('use_parent', 'Use Parent'),
        ], string='Has Answer', 
        default='no', 
        help='Resources can include model answers to a question. A resource can use the parent\'s answer if set to "Use Parent".',
        required=True,
        tracking=True)
    answer = fields.Html(string='Answer', help='Model answer for the resource question.')    
    parent_answer = fields.Html(string='Parent Answer', compute='_compute_parent_answer', store=False)
    answer_is_notes = fields.Boolean(string='Answer Is Notes', compute='_compute_answer_is_notes', store=False)

    # has_default_answer = fields.Selection([
    #     ('no', 'No'),
    #     ('yes', 'Yes'),
    #     ], string='Has Default Answer', 
    #     default='no', 
    #     help='Resources can include a default answer to a question. This is helpful if you wish to provide a template for students to fill in.',
    #     required=True,
    #     tracking=True)
    default_answer = fields.Html(string='Default Answer', help='Default answer template for the resource question.')    

    has_default_answer = fields.Boolean()

    lesson_plan = fields.Html(string='Lesson Plan', help='The lesson plan for this resource.')
    has_lesson_plan = fields.Boolean(string='Has Lesson Plan', store=True)

    has_child_resources = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ], string='Has Linked Resources', 
        default='no', 
        help='Linked resources can be used to break down a resource into smaller parts. They usually contribute to the overall marks of the parent resource.',
        required=True,
        tracking=True)    

    has_supporting_resources = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
        ], string='Has Supporting Resources', 
        default='no', 
        help='Supporting resources can be used to add supplementary materials that do not contribute to the overall marks of the parent resource.',
        required=True,
        tracking=True)    

    # thumbnail = fields.Binary(string='Thumbnail', compute='_compute_thumbnail', store=True)
    thumbnail = fields.Binary(string='Thumbnail')

    type_id = fields.Many2one('aps.resource.types', string='Type', ondelete='set null', store=True, tracking=True)
    type_icon = fields.Image(string='Type Icon', compute='_compute_type_icon', readonly=True, store=True)
    type_color = fields.Char(string='Type Color', related='type_id.color', readonly=True)
    url = fields.Char(string='URL', 
                      required=False, tracking=True)
    category = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
        ('information', 'Information'),
        ], string='Category', 
        default='optional', 
        help='Identifies which resources should be assigned to students to complete.', tracking=True)
    marks = fields.Float(string='Out of Marks', digits=(16, 1), help='Maximum marks/points for this resource')
    subjects = fields.Many2many('op.subject', string='Subjects')
    tag_ids = fields.Many2many('aps.resource.tags', string='Tags')
    task_ids = fields.One2many('aps.resource.task', 'resource_id', string='Tasks')
    parent_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'child_id', 'parent_id', string='Parent Resources', domain="[('id', '!=', id)]")
    
    # Dashboard computed fields
    total_submissions = fields.Integer(string='Total Submissions', compute='_compute_dashboard_stats', store=False)
    completed_submissions = fields.Integer(string='Completed Submissions', compute='_compute_dashboard_stats', store=False)
    overdue_tasks = fields.Integer(string='Overdue Tasks', compute='_compute_dashboard_stats', store=False)
    primary_parent_id = fields.Many2one(
        'aps.resources', 
        string='Main Parent', 
        domain="[('id', 'in', parent_ids)]", 
        help='The resource used for generating the display name. Must be one of the selected parents.',
    )
    child_ids = fields.Many2many('aps.resources', 'aps_resources_rel', 'parent_id', 'child_id', string='Linked Resources', domain="[('id', '!=', id)]")
    # Removed parent_path since multiple parents don't fit tree structure
    child_count = fields.Integer(string='Total Children', compute='_compute_child_count')
    has_multiple_parents = fields.Boolean(string='Has Multiple Parents', compute='_compute_has_multiple_parents')
    supporting_resource_ids = fields.Many2many('aps.resources', 'aps_supporting_resources_rel', 'parent_id', 'child_id', string='Supporting Resources', domain="[('id', '!=', id)]") 
    supporting_resources_buttons = fields.Json(
        string='Resource Links',
        compute='_compute_supporting_resources_buttons',
        help='JSON data containing resource links with icons for the widget.'
    )
    subject_icons = fields.Image(
        string='Subject Icon',
        compute='_compute_subject_icons',
        help='Icon for the first subject associated with the resource',
        store=True,
    )
    allow_subject_editing = fields.Boolean(
        string='Allow Subject Editing',
        default=False,
        help='If enabled, users can edit the subjects associated with this resource. This is useful for resources that are shared across multiple subjects, where the subject association may need to be customized at the submission level.',
    )
    points_scale = fields.Integer(
        string='Points Scale', help="Scales the default points allocated to a resource.",
        default=1
    )
# region Computed Fields and Overrides
    @api.depends('subjects')
    def _compute_subject_icons(self):
        for record in self:
            if record.subjects:
                first = record.subjects[:1]
                record.subject_icons = first.icon if first else False
            else:
                record.subject_icons = False


    @api.depends('type_id', 'type_id.icon')
    def _compute_type_icon(self):
        # This is needed because without it the icon is never cached properly. 
        # That means there is a lot of annoying downloads on every page refresh.
        # It is duplicated in other models as well.
        for record in self:
            record.type_icon = record.type_id.icon if record.type_id else False


    @api.depends('url', 'name', 'display_name', 'type_icon', 'type_id.name',
                 'supporting_resource_ids', 'supporting_resource_ids.url', 
                 'supporting_resource_ids.name', 'supporting_resource_ids.display_name',
                 'supporting_resource_ids.type_icon', 'supporting_resource_ids.type_id.name',
                 'supporting_resource_ids.sequence')
    
    def _compute_supporting_resources_buttons(self):
        """Compute JSON data for resource links widget."""
        for resource in self:
            links = []
            # Only process if resource.id is a real id (not NewId)
            if resource.url and isinstance(resource.id, int):
                links.append({
                    'id': resource.id,
                    'name': resource.name or resource.display_name,
                    'url': resource.url,
                    'icon_url': f'/web/image/aps.resources/{resource.id}/type_icon' if resource.type_icon else False,
                    'type_name': resource.type_id.name if resource.type_id else 'Resource',
                    'is_main': True,
                })
            # Add supporting resources that have URLs and real ids
            for supporting in resource.supporting_resource_ids.sorted('sequence'):
                if supporting.url and isinstance(supporting.id, int):
                    links.append({
                        'id': supporting.id,
                        'name': supporting.name or supporting.display_name,
                        'url': supporting.url,
                        'icon_url': f'/web/image/aps.resources/{supporting.id}/type_icon' if supporting.type_icon else False,
                        'type_name': supporting.type_id.name if supporting.type_id else 'Resource',
                        'is_main': False,
                    })
            resource.supporting_resources_buttons = links

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            # Count resources that have this resource as a parent
            rec.child_count = self.search_count([('parent_ids', 'in', rec.id)])

    @api.depends('parent_ids')
    def _compute_has_multiple_parents(self):
        for rec in self:
            rec.has_multiple_parents = len(rec.parent_ids) > 1

    @api.depends('primary_parent_id.answer','has_answer')
    def _compute_parent_answer(self):
        """Get the answer to display based on has_answer setting."""
        for rec in self:
            if rec.has_answer == 'use_parent' and rec.primary_parent_id:
                parent_answer = rec.primary_parent_id.answer
                rec.parent_answer = rec._extract_from_parent_html(parent_answer, rec.name)
            else:
                rec.parent_answer = False    

    @api.depends('has_answer', 'primary_parent_id.has_answer')
    def _compute_answer_is_notes(self):
        for rec in self:
            rec.answer_is_notes = (
                rec.has_answer == 'yes_notes'
                or (rec.has_answer == 'use_parent' and rec.primary_parent_id and rec.primary_parent_id.has_answer == 'yes_notes')
            )
                
    @api.depends('primary_parent_id.question','has_question')
    def _compute_parent_question(self):
        """Get the question to display based on has_question setting."""
        for rec in self:
            if rec.primary_parent_id:
                parent_question = rec.primary_parent_id.question
                rec.parent_question = rec._extract_from_parent_html(parent_question, rec.name)
            else:
                rec.parent_question = False

    def _extract_from_parent_html(self, parent_html, resource_name):
        """
        Extract content from parent HTML based on matching heading.
        If a heading matches the resource name, extract content under that heading.
        Otherwise, return all content.
        Append a note indicating partial content.
        """
        if not parent_html or not resource_name:
            return parent_html
            
        # Try to find a matching heading
        parser = ExtractHeadingContent(resource_name)
        try:
            parser.feed(parent_html)
            extracted_content = parser.get_content()
            
            if extracted_content:
                # Add the note at the bottom
                note = '<p style="font-size: 12px; color: #888; margin-top: 10px;"><em>(Displaying a part of the parent content only.)</em></p>'
                return f'{extracted_content}{note}'
        except Exception:
            # If parsing fails, return original
            pass
            
        return parent_html

    @api.depends('primary_parent_id.display_name', 'primary_parent_id.name', 'name', 'parent_ids')
    def _compute_display_name(self):
        """Build display name from ancestor chain, removing redundant overlapping characters."""
        for rec in self:
            # Priority: 1. primary_parent_id, 2. first parent from parent_ids, 3. just name
            parent_to_use = rec.primary_parent_id or (rec.parent_ids and rec.parent_ids[0])
            
            if parent_to_use:
                parent_display = parent_to_use.display_name or parent_to_use.name or ''
                current_name = rec.name or ''
                separator = ' 🢒 '
                
                # NEW: Remove bracketed text that matches part or all of the parent
                if current_name and parent_display:
                    # Find all text in brackets (round, square, or curly)
                    bracketed_texts = re.findall(r'\([^)]+\)|\[[^\]]+\]|{[^}]+}', current_name)
                    for bracketed in bracketed_texts:
                        # Remove brackets to get the content
                        content = bracketed[1:-1]  # Remove first and last character (brackets)
                        # Check if this content appears in the parent display name
                        if content in parent_display:
                            # Remove the entire bracketed text from current_name
                            current_name = current_name.replace(bracketed, '').strip()
                
                # Find overlapping characters between start of current_name and end of parent_display
                overlap_length = 0
                parent_len = len(parent_display)
                current_len = len(current_name)
                
                # Check if current_name starts with the suffix of parent_display
                # Compare current_name[0:n] with parent_display[-n:] for increasing n
                match_found = False
                for i in range(1, min(parent_len, current_len) + 1):
                    if current_name[:i] == parent_display[-i:]:
                        overlap_length = i
                        match_found = True
                    else:
                        if match_found:
                            break
                
                # Remove overlapping characters from current_name
                if overlap_length > 0:
                    remaining_name = current_name[overlap_length:].lstrip()
                    # Strip any "." that appear at the start of the remaining name
                    remaining_name = re.sub(r'^\.+', '', remaining_name).lstrip()
                    if remaining_name:
                        rec.display_name = parent_display + separator + remaining_name
                    else:
                        rec.display_name = parent_display
                else:
                    # No overlap, concatenate normally
                    rec.display_name = parent_display + separator + current_name
            else:
                rec.display_name = rec.name or ''

    @api.depends('custom_name_ids.custom_name', 'custom_name_ids.parent_resource_id')
    def _compute_parent_custom_name_data(self):
        """Compute a Python list containing the custom names for this resource keyed by parent id.
        This uses `fields.Json` so we assign a native Python structure and let Odoo handle serialization."""
        for rec in self:
            data = []
            for c in rec.custom_name_ids:
                if c.parent_resource_id and c.custom_name:
                    # Replace NewId (in-memory) ids with False so JSON serialization succeeds
                    cid = c.id if isinstance(c.id, int) else False
                    data.append({
                        'parent_resource_id': c.parent_resource_id.id,
                        'custom_name': c.custom_name,
                        'id': cid,
                    })
            rec.parent_custom_name_data = data or False

    @api.depends('task_ids.submission_ids')
    def _compute_dashboard_stats(self):
        for rec in self:
            submissions = rec.task_ids.mapped('submission_ids')
            rec.total_submissions = len(submissions)
            rec.completed_submissions = len(submissions.filtered(lambda s: s.state == 'complete'))
            rec.overdue_tasks = len(rec.task_ids.filtered(lambda t: t.date_due and t.date_due < fields.Date.today() and t.state != 'complete'))

# region Overrides and Constraints
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

    @api.onchange('url')
    def _onchange_url(self):
        """Automatically assign resource type based on URL keywords."""
        if self.url:
            # Search for resource types that have URL keywords
            resource_types = self.env['aps.resource.types'].search([('url_keywords', '!=', False)])
            for resource_type in resource_types:
                if resource_type.url_keywords:
                    # Check if any of the keywords (comma-separated) are in the URL
                    keywords = [kw.strip().lower() for kw in resource_type.url_keywords.split(',')]
                    url_lower = self.url.lower()
                    if any(keyword in url_lower for keyword in keywords):
                        self.type_id = resource_type
                        break  # Stop at the first match

    # Removed _check_parent_loop since multiple parents make cycle detection complex

    def _sync_primary_parent(self):
        """Ensure `primary_parent_id` is set to a valid parent whenever parents exist."""
        for rec in self:
            if rec.parent_ids:
                if not rec.primary_parent_id or rec.primary_parent_id not in rec.parent_ids:
                    # Use update() to avoid cascading writes and recursion
                    rec.sudo().update({'primary_parent_id': rec.parent_ids[0].id})
            else:
                # No parents: clear primary_parent_id
                if rec.primary_parent_id:
                    rec.sudo().update({'primary_parent_id': False})

    def write(self, vals):
        result = super().write(vals)
        # Ensure primary_parent_id stays consistent after any write
        self._sync_primary_parent()
        if 'name' in vals:
            # When name changes, update display_name for self and direct children
            for rec in self:
                rec._compute_display_name()
                # Update display_name for direct children
                children = self.search([('parent_ids', 'in', rec.id)])
                if children:
                    children._compute_display_name()
        return result

    def copy(self, default=None):
        default = dict(default or {})
        name = default.get('name') or self.name or ''
        if name and not name.endswith(' (copy)'):
            default['name'] = f"{name} (copy)"
        return super().copy(default)

    @api.model
    def create(self, vals_list):
        records = super().create(vals_list)
        # Ensure primary_parent_id is set whenever parents exist on new records
        records._sync_primary_parent()
        return records

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

    @api.model
    def _default_assignment_duration(self):
        """Return the default duration for assignments (e.g., 7 days)."""
        from datetime import timedelta
        return timedelta(days=6)

# region Action Methods

    def action_force_update_display_names(self):
        """Force recompute display names for all resources in hierarchical order."""
        all_resources = self.search([])
        total_count = len(all_resources)
        updated = self.env['aps.resources']
        
        # Start with resources that have no parents (root level)
        to_process = all_resources.filtered(lambda r: not r.parent_ids)
        
        # Process in layers: update current layer, then find children of updated resources
        iteration = 0
        max_iterations = 100  # Safety limit to prevent infinite loops
        
        while to_process and iteration < max_iterations:
            # Update display names for current layer
            to_process._compute_display_name()
            updated |= to_process
            
            # Find next layer: resources whose parents are all in the updated set
            remaining = all_resources - updated
            next_layer = self.env['aps.resources']
            
            for resource in remaining:
                # Check if all parents of this resource have been updated
                if all(parent in updated for parent in resource.parent_ids):
                    next_layer |= resource
            
            to_process = next_layer
            iteration += 1
        
        # Handle any remaining resources (shouldn't happen unless there are cycles)
        remaining = all_resources - updated
        if remaining:
            remaining._compute_display_name()
            updated |= remaining
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Updated display names for {len(updated)} resources in {iteration} layers.',
                'sticky': False,
            }
        }

    def action_assign_students(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Students to Resource',
            'res_model': 'aps.assign.students.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_resource_id': self.id},
        }

    def action_delete(self):
        """Called by the form button to delete the record and close the form."""
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

