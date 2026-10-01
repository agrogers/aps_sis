"""Configurable question identifier patterns for exam paper imports."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class APSExamPaperQuestionIdentifier(models.Model):
    _name = 'aps.exam.paper.question.identifier'
    _description = 'Exam Paper Question Identifier'
    _order = 'sequence, id'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        default=10,
        help='Rules are tried in this order; move specific overrides before universal rules.',
    )
    identifier_example = fields.Char(required=True, string='Identifier Example')
    description = fields.Text(string='Description')
    document_type = fields.Selection([
        ('all', 'Any Document'),
        ('question', 'Question Paper'),
        ('mark_scheme', 'Mark Scheme'),
    ], required=True, default='all', string='Document Type')
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
        help='Matched against an identifier component at the current position in the label.',
    )
    canonical_key_regex = fields.Char(
        string='Canonical Key Regex',
           help='Optional regex searched in the matched identifier component. Its matched text links equivalent '
               'labels across documents.',
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

    @api.constrains('canonical_key_regex')
    def _check_canonical_key_regex(self):
        for record in self:
            if not record.canonical_key_regex:
                continue
            try:
                pattern = re.compile(record.canonical_key_regex)
            except re.error as error:
                raise ValidationError(
                    _('The canonical key regular expression is invalid: %s') % error
                ) from error


