from odoo import api, fields, models


class APSAwardCandidateWizard(models.TransientModel):
    _name = 'aps.award.candidate.wizard'
    _description = 'Add Eligible Candidates Wizard'

    vote_round_id = fields.Many2one(
        'aps.award.vote.round',
        string='Vote Round',
        required=True,
        ondelete='cascade',
    )
    mode = fields.Selection(
        selection=[
            ('level', 'Levels'),
            ('category', 'Subject Categories'),
            ('student', 'Students'),
        ],
        required=True,
    )

    level_ids = fields.Many2many(
        'aps.level',
        'aps_award_cand_wizard_level_rel',
        'wizard_id',
        'level_id',
        string='Levels',
    )
    category_ids = fields.Many2many(
        'aps.subject.category',
        'aps_award_cand_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Subject Categories',
    )
    student_ids = fields.Many2many(
        'aps.student',
        'aps_award_cand_wizard_student_rel',
        'wizard_id',
        'student_id',
        string='Students',
    )

    def _merge_ids(self, existing, new_ids):
        """Merge new IDs into existing list, preserving order and deduplicating."""
        return list(dict.fromkeys((existing or []) + new_ids))

    def action_confirm(self):
        self.ensure_one()
        round_rec = self.vote_round_id
        data = dict(round_rec.eligible_candidates or {})

        if self.mode == 'level':
            data['level_ids'] = self._merge_ids(data.get('level_ids'), self.level_ids.ids)
        elif self.mode == 'category':
            data['subject_category_ids'] = self._merge_ids(data.get('subject_category_ids'), self.category_ids.ids)
        elif self.mode == 'student':
            data['student_ids'] = self._merge_ids(data.get('student_ids'), self.student_ids.ids)

        round_rec.eligible_candidates = data
        return {'type': 'ir.actions.act_window_close'}
