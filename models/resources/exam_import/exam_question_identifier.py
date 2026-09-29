"""Configurable question identifier patterns for exam paper imports."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class APSExamPaperQuestionIdentifier(models.Model):
    _name = 'aps.exam.paper.question.identifier'
    _description = 'Exam Paper Question Identifier'
    _order = 'sequence, id'

    sequence = fields.Integer(
        default=10,
        help='Rules are tried in this order; move specific overrides before universal rules.',
    )
    identifier_example = fields.Char(required=True, string='Identifier Example')
    filename_contains = fields.Char(
        string='Filename Contains',
        help='Leave empty to use this rule for every exam paper.',
    )
    hierarchy_level = fields.Selection([
        ('1', 'Root Question'),
        ('2', 'Question Part'),
        ('3', 'Question Subpart'),
    ], required=True, default='1')
    regex_pattern = fields.Char(
        required=True,
        string='Regular Expression',
        help='Matched against the complete label. The example generates a starting pattern that can be edited.',
    )

    @api.model
    def _pattern_from_example(self, example):
        parts = re.split(r'(\d+|[A-Za-z]+)', example or '')
        has_number = False
        pattern = []
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                pattern.append(r'\d+')
                has_number = True
            elif re.fullmatch(r'[A-Za-z]+', part):
                pattern.append('[A-Za-z]+' if has_number else re.escape(part))
            else:
                pattern.append(re.escape(part))
        return ''.join(pattern)

    @api.onchange('identifier_example')
    def _onchange_identifier_example(self):
        for record in self:
            if record.identifier_example:
                record.regex_pattern = self._pattern_from_example(record.identifier_example)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('regex_pattern') and vals.get('identifier_example'):
                vals['regex_pattern'] = self._pattern_from_example(vals['identifier_example'])
        return super().create(vals_list)

    @api.constrains('regex_pattern')
    def _check_regex_pattern(self):
        for record in self:
            try:
                re.compile(record.regex_pattern)
            except re.error as error:
                raise ValidationError(
                    _('The question identifier regular expression is invalid: %s') % error
                ) from error
