from collections import Counter

from odoo import api, fields, models


class CreateLinkedResourcesWizard(models.TransientModel):
    _name = 'aps.create.linked.resources'
    _description = 'Create Linked Resources from Field Headings'

    resource_id = fields.Many2one(
        'aps.resources', string='Resource', required=True, readonly=True,
        ondelete='cascade',
    )
    source_field = fields.Selection([
        ('question', 'Question'),
        ('answer', 'Answer'),
        ('notes', 'Notes'),
        ('lesson_plan', 'Lesson Plan'),
    ], string='Source Field', required=True, default='question')
    heading_count = fields.Integer(string='Headings Found', compute='_compute_headings', readonly=True)
    heading_preview = fields.Text(string='Headings Preview', compute='_compute_headings', readonly=True)

    # ------------------------------------------------------------------
    # Computed preview
    # ------------------------------------------------------------------

    @api.depends('source_field', 'resource_id')
    def _compute_headings(self):
        for rec in self:
            html = rec.resource_id[rec.source_field] if rec.resource_id and rec.source_field else False
            headings = self.env['aps.resources']._extract_top_headings_from_html(html or '')
            rec.heading_count = len(headings)
            rec.heading_preview = '\n'.join(f'• {h}' for h in headings) if headings else ''

    # ------------------------------------------------------------------
    # Create linked resources
    # ------------------------------------------------------------------

    def action_create(self):
        """Create missing linked resources and order them by top-level headings."""
        self.ensure_one()
        resource = self.resource_id

        html = resource[self.source_field]
        if not html:
            return self._notification(
                'No Content',
                f'The {self.source_field_label} field is empty.',
                'warning',
            )

        headings = self.env['aps.resources']._extract_top_headings_from_html(html)
        if not headings:
            return self._notification(
                'No Headings Found',
                f'No headings (H1–H6) were found in the {self.source_field_label} field.',
                'warning',
            )

        existing_by_name = {}
        for child in resource.child_ids.sorted(key=lambda child: (child.sequence, child.id)):
            existing_by_name.setdefault(child.name, []).append(child)

        first_existing = next(
            (
                (index, existing_by_name[title][0].sequence)
                for index, title in enumerate(headings)
                if title in existing_by_name
            ),
            None,
        )
        if first_existing is None:
            sequence = max(resource.child_ids.mapped('sequence'), default=0)
        else:
            index, first_sequence = first_existing
            # Leave room for new headings before the first existing match.
            sequence = first_sequence - index - 1

        remaining_headings = Counter(headings)
        created = self.env['aps.resources']
        skipped = []
        reordered_count = 0
        for title in headings:
            remaining_headings[title] -= 1
            if title in existing_by_name:
                matches = existing_by_name[title]
                # Associate surplus same-named resources with the last matching heading.
                match_count = len(matches) if not remaining_headings[title] else 1
                for child in matches[:match_count]:
                    sequence = max(sequence + 1, child.sequence)
                    if child.sequence != sequence:
                        child.sequence = sequence
                        reordered_count += 1
                del matches[:match_count]
                skipped.append(title)
                continue
            sequence += 1
            vals = {
                'name': title,
                'sequence': sequence,
                'parent_ids': [(4, resource.id)],
                'primary_parent_id': resource.id,
                'subjects': [(6, 0, resource.subjects.ids)],
                'type_id': resource.type_id.id,
            }
            # Set has_* fields based on source field
            if self.source_field == 'question':
                vals['has_question'] = 'use_parent'
                vals['has_answer'] = 'use_parent'
            elif self.source_field == 'answer':
                vals['has_answer'] = 'use_parent'
                vals['has_question'] = 'use_parent'
            elif self.source_field == 'notes':
                vals['has_notes'] = 'use_parent'
            # lesson_plan: no has_* fields set on children

            child = self.env['aps.resources'].create(vals)
            created |= child

        if not created and not skipped:
            return self._notification(
                'Nothing to Create',
                'No new headings found to create resources from.',
                'warning',
            )

        # Mark parent as having linked resources and refresh display names
        if created:
            resource.has_child_resources = 'yes'
        resource._compute_display_name()

        msg_parts = []
        if created:
            msg_parts.append(f'Created {len(created)} linked resource(s).')
        if skipped:
            msg_parts.append(f'Skipped {len(skipped)} already existing: {", ".join(skipped)}.')
        if reordered_count:
            msg_parts.append(
                f'Reordered {reordered_count} existing resource(s) to match heading order. '
                'If shared, their sequences also affect their other parents.'
            )

        return {
            'type': 'ir.actions.act_window_close',
            'infos': {
                'notification': {
                    'title': 'Resources Created',
                    'message': ' '.join(msg_parts),
                    'type': 'success',
                    'sticky': bool(skipped),
                },
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def source_field_label(self):
        return dict(self._fields['source_field'].selection).get(self.source_field, self.source_field)

    def _notification(self, title, message, msg_type='info', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': msg_type,
                'sticky': sticky,
            },
        }
