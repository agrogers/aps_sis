import re
from datetime import datetime
from odoo import models, api


class APSResource(models.Model):
    _inherit = 'aps.resources'

    def action_force_update_display_names(self):
        """Force recompute display names for all resources in hierarchical order."""
        all_resources = self.search([])
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

    def get_pace_dates(self):
        """
        Parse PACE start_date, end_date, redline_start_date, and redline_end_date
        from the notes field.

        Note: Since resource.subjects is a Many2many field, one resource can be associated
        with multiple subjects. The PACE dates parsed from this resource's notes field
        apply to ALL subjects linked to this resource.

        Expected format in notes:
            start_date: 1/Aug/2025
            end_date: 31/Dec/2027
            redline_start_date: 1/Nov/2025
            redline_end_date: 30/Jan/2027

        Returns dict with date objects or False for each key if not found.
        """
        self.ensure_one()

        result = {
            'start_date': False,
            'end_date': False,
            'redline_start_date': False,
            'redline_end_date': False,
        }

        if not self.notes:
            return result

        # Remove HTML tags to get plain text
        plain_text = re.sub(r'<[^>]+>', '', self.notes)

        # Pattern to match dates in format: day/month/year where month can be short name or full name
        # Examples: 1/Aug/2025, 31/December/2027, 15/Jan/2026
        date_pattern = r'(\d{1,2})/([A-Za-z]+)/(\d{4})'

        def _parse_date_match(match):
            """Parse a regex match containing (day, month_str, year) groups into a date."""
            try:
                day, month_str, year = match.groups()
                date_str = f"{day} {month_str} {year}"
                for fmt in ['%d %B %Y', '%d %b %Y']:
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
            except (ValueError, AttributeError):
                pass
            return False

        # Search for start_date (negative lookbehind prevents matching 'redline_start_date:')
        start_match = re.search(rf'(?<!redline_)start_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if start_match:
            result['start_date'] = _parse_date_match(start_match) or False

        # Search for end_date (negative lookbehind prevents matching 'redline_end_date:')
        end_match = re.search(rf'(?<!redline_)end_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if end_match:
            result['end_date'] = _parse_date_match(end_match) or False

        # Search for redline_start_date
        redline_start_match = re.search(rf'redline_start_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if redline_start_match:
            result['redline_start_date'] = _parse_date_match(redline_start_match) or False

        # Search for redline_end_date
        redline_end_match = re.search(rf'redline_end_date:\s*{date_pattern}', plain_text, re.IGNORECASE)
        if redline_end_match:
            result['redline_end_date'] = _parse_date_match(redline_end_match) or False

        return result

    def action_assign_students(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Students to Resource',
            'res_model': 'aps.assign.students.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_resource_id': self.id},
        }

    def action_open_child_resources_list(self):
        """Open child resources in a standard list/form view with navigation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Linked Resources: {self.name}',
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.child_ids.ids)],
            'context': {'default_parent_ids': [(6, 0, [self.id])], 'default_primary_parent_id': self.id, 'default_subjects': self.subjects.ids},
            'target': 'current',
        }

    def action_open_linked_resource(self):
        """Open this linked resource in form view with navigation across all sibling linked resources.

        Uses the ``current_parent_id`` value injected by the inline list's field context to
        retrieve the full set of sibling IDs.  Returning a ``list,form`` action with both
        ``domain`` and ``res_id`` causes Odoo's client to open the form directly for this
        record while still setting up pager navigation across all siblings.
        """
        self.ensure_one()
        parent_id = self.env.context.get('current_parent_id')
        if parent_id:
            parent = self.env['aps.resources'].browse(parent_id)
            sibling_ids = parent.child_ids.ids
        else:
            # Fallback: no parent context (e.g. called outside the inline list).
            # Open only this record; no sibling navigation will be available.
            sibling_ids = [self.id]

        ctx = dict(self.env.context)
        if parent_id:
            ctx.update({
                'default_parent_ids': [(6, 0, [parent_id])],
                'default_primary_parent_id': parent_id,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Linked Resources',
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', sibling_ids)],
            'res_id': self.id,
            'context': ctx,
            'target': 'current',
        }

    def action_open_supporting_resources_list(self):
        """Open supporting resources in a standard list/form view with navigation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Supporting Resources: {self.name}',
            'res_model': 'aps.resources',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.supporting_resource_ids.ids)],
            'context': {'default_subjects': self.subjects.ids},
            'target': 'current',
        }

    def action_delete(self):
        """Called by the form button to delete the record and close the form."""
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}
