from odoo import models, api
from .html_parser import ExtractHeadingContent


class APSResource(models.Model):
    _inherit = 'aps.resources'

    # ── Onchange handlers ─────────────────────────────────────────────────────

    @api.onchange('has_notes', 'primary_parent_id')
    def _compute_parent_notes(self):
        """Get the parent notes to display based on has_notes setting."""
        for rec in self:
            rec.notes = rec._notes_from_parent() if rec.has_notes == 'use_parent' else rec.notes

    @api.onchange('has_question', 'primary_parent_id')
    def _onchange_parent_question_value(self):
        for rec in self:
            rec.question = rec._question_from_parent() if rec.has_question == 'use_parent' else rec.question

    @api.onchange('has_answer', 'primary_parent_id')
    def _onchange_parent_answer_value(self):
        for rec in self:
            rec.answer = rec._answer_from_parent() if rec.has_answer == 'use_parent' else rec.answer

    # ── Content derivation helpers ────────────────────────────────────────────

    def _notes_from_parent(self):
        self.ensure_one()
        if self.has_notes == 'use_parent' and self.primary_parent_id:
            parent_notes = self.primary_parent_id.notes
            return self._extract_from_parent_html(parent_notes, self.name)
        return False

    def _question_from_parent(self):
        self.ensure_one()
        if self.has_question == 'use_parent' and self.primary_parent_id:
            inherited_question = self.primary_parent_id.question
            return self._extract_from_parent_html(inherited_question, self.name)
        return False

    def _answer_from_parent(self):
        self.ensure_one()
        if self.has_answer == 'use_parent' and self.primary_parent_id:
            inherited_answer = self.primary_parent_id.answer
            return self._extract_from_parent_html(inherited_answer, self.name)
        return False

    def _extract_from_parent_html(self, parent_html, resource_name):
        """
        Extract content from parent HTML based on matching heading.
        If a heading matches the resource name, extract content under that heading.
        Otherwise, return all content.
        Appends a note indicating partial content.
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
                # note = '<p style="font-size: 12px; color: #888; margin-top: 10px;"><em>(Displaying a part of the parent content only.)</em></p>'
                note = ''
                return f'{extracted_content}{note}'
        except Exception:
            # If parsing fails, return original
            pass

        return parent_html

    # ── Child update propagation ──────────────────────────────────────────────

    def _update_child_notes(self):
        """Update any child notes that are using this resource as parent."""
        for rec in self:
            child_resources = self.env['aps.resources'].search([
                ('primary_parent_id', '=', rec.id),
                ('has_notes', '=', 'use_parent')
            ])
            if child_resources:
                for child in child_resources:
                    child.update({'notes': child._notes_from_parent()})

    def _update_child_questions(self):
        for rec in self:
            child_resources = self.env['aps.resources'].search([
                ('primary_parent_id', '=', rec.id),
                ('has_question', '=', 'use_parent')
            ])
            if child_resources:
                for child in child_resources:
                    child.update({'question': child._question_from_parent()})

    def _update_child_answers(self):
        for rec in self:
            child_resources = self.env['aps.resources'].search([
                ('primary_parent_id', '=', rec.id),
                ('has_answer', '=', 'use_parent')
            ])
            if child_resources:
                for child in child_resources:
                    child.update({'answer': child._answer_from_parent()})

    def _sync_notes_from_parent(self):
        for rec in self.filtered(lambda r: r.has_notes == 'use_parent' and r.primary_parent_id):
            synced_notes = rec._notes_from_parent()
            if rec.notes != synced_notes:
                rec.update({'notes': synced_notes})

    def _sync_questions_from_parent(self):
        for rec in self.filtered(lambda r: r.has_question == 'use_parent' and r.primary_parent_id):
            synced_question = rec._question_from_parent()
            if rec.question != synced_question:
                rec.update({'question': synced_question})

    def _sync_answers_from_parent(self):
        for rec in self.filtered(lambda r: r.has_answer == 'use_parent' and r.primary_parent_id):
            synced_answer = rec._answer_from_parent()
            if rec.answer != synced_answer:
                rec.update({'answer': synced_answer})
