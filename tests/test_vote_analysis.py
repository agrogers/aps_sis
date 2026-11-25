from odoo import fields
from odoo.tests.common import TransactionCase


class TestVoteAnalysis(TransactionCase):

    def test_detail_rows_group_recipient_voter_and_date_with_matching_vote_ids(self):
        Vote = self.env['aps.award.vote']
        voters = self.env['res.partner'].create([
            {'name': 'First Analysis Voter'},
            {'name': 'Second Analysis Voter'},
        ])
        recipient = self.env['res.partner'].create({'name': 'Analysis Recipient'})
        rounds = self.env['aps.award.vote.round'].create([
            {
                'name': name,
                'datetime_start': '2026-01-01 00:00:00',
                'datetime_end': '2026-12-31 00:00:00',
            }
            for name in ('First Analysis Round', 'Second Analysis Round')
        ])
        base = {'recipient_partner_id': recipient.id, 'state': 'submitted'}
        votes = Vote.create([
            dict(base, vote_round_id=rounds[0].id, voter_partner_id=voters[0].id, submitted_date='2026-01-05'),
            dict(base, vote_round_id=rounds[1].id, voter_partner_id=voters[0].id, submitted_date='2026-01-05'),
            dict(base, vote_round_id=rounds[0].id, voter_partner_id=voters[1].id, submitted_date='2026-01-05'),
            dict(base, vote_round_id=rounds[0].id, voter_partner_id=voters[0].id, submitted_date=False),
        ])
        data = Vote.get_vote_analysis_data({'round_ids': rounds.ids})
        rows = {(row['voter_id'], row['submitted_date']): row for row in data['detail_rows']}
        day = fields.Date.to_date('2026-01-05')
        self.assertEqual(len(rows), 3)
        first = rows[(voters[0].id, day)]
        self.assertEqual(first['id'], recipient.id)
        self.assertEqual(first['voter_name'], voters[0].display_name)
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['votes'], {rounds[0].id: 1, rounds[1].id: 1})
        self.assertEqual(first['vote_ids'], {rounds[0].id: [votes[0].id], rounds[1].id: [votes[1].id]})
        self.assertEqual(rows[(voters[1].id, day)]['vote_ids'], {rounds[0].id: [votes[2].id]})
        self.assertEqual(rows[(voters[0].id, False)]['vote_ids'], {rounds[0].id: [votes[3].id]})
        self.assertEqual(data['recipients'][0]['total'], 4)

        filtered = Vote.get_vote_analysis_data({'round_ids': [rounds[1].id]})
        self.assertEqual(len(filtered['detail_rows']), 1)
        self.assertEqual(filtered['detail_rows'][0]['vote_ids'], {rounds[1].id: [votes[1].id]})

        sets = self.env['aps.award.voting.set'].create([
            {'name': 'First Analysis Set'},
            {'name': 'Second Analysis Set'},
        ])
        rounds[0].voting_set_ids = [(6, 0, sets.ids)]
        by_set = Vote.get_vote_analysis_data({
            'round_ids': [rounds[0].id],
            'series_by': 'voting_set',
        })
        first = next(row for row in by_set['detail_rows']
                     if row['voter_id'] == voters[0].id and row['submitted_date'] == day)
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['vote_ids'], {sets[0].id: [votes[0].id], sets[1].id: [votes[0].id]})

    def test_latest_vote_date_uses_only_votes_in_the_selected_series_and_filters(self):
        Vote = self.env['aps.award.vote']
        voter = self.env['res.partner'].create({'name': 'Analysis Voter'})
        recipients = self.env['res.partner'].create([
            {'name': 'Dated Recipient'},
            {'name': 'Undated Recipient'},
        ])
        category = self.env['aps.award.category'].create({'name': 'Analysis Category'})
        subcategory = self.env['aps.award.sub.category'].create({
            'name': 'Analysis Subcategory',
            'category_id': category.id,
        })
        voting_set = self.env['aps.award.voting.set'].create({'name': 'Analysis Set'})
        rounds = self.env['aps.award.vote.round'].create([
            {
                'name': name,
                'datetime_start': '2026-01-01 00:00:00',
                'datetime_end': '2026-12-31 00:00:00',
                'voting_set_ids': [(4, voting_set.id)],
            }
            for name in ('Analysis Round One', 'Analysis Round Two')
        ])
        base = {
            'voter_partner_id': voter.id,
            'award_category_id': category.id,
            'award_sub_category_id': subcategory.id,
            'state': 'submitted',
        }
        Vote.create([
            dict(base, vote_round_id=rounds[0].id, recipient_partner_id=recipients[0].id, submitted_date='2026-01-05'),
            dict(base, vote_round_id=rounds[1].id, recipient_partner_id=recipients[0].id, submitted_date='2026-02-05'),
            dict(base, vote_round_id=rounds[0].id, recipient_partner_id=recipients[1].id, submitted_date=False, state='closed'),
            dict(base, vote_round_id=rounds[0].id, recipient_partner_id=recipients[0].id,
                 submitted_date='2026-03-05', award_sub_category_id=False),
        ])

        for series_by in ('round', 'category', 'sub_category', 'voting_set'):
            data = Vote.get_vote_analysis_data({
                'round_ids': rounds.ids,
                'series_by': series_by,
            })
            by_id = {recipient['id']: recipient for recipient in data['recipients']}
            expected_date = '2026-02-05' if series_by == 'sub_category' else '2026-03-05'
            self.assertEqual(by_id[recipients[0].id]['latest_vote_date'], fields.Date.to_date(expected_date))
            self.assertFalse(by_id[recipients[1].id]['latest_vote_date'])

        data = Vote.get_vote_analysis_data({
            'round_ids': [rounds[0].id],
            'sub_category_ids': subcategory.ids,
        })
        by_id = {recipient['id']: recipient for recipient in data['recipients']}
        self.assertEqual(by_id[recipients[0].id]['latest_vote_date'], fields.Date.to_date('2026-01-05'))
