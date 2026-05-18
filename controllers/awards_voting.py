import base64
import json
from datetime import date, timedelta

from odoo import http
from odoo.http import request


class AwardsVotingController(http.Controller):

    def _get_employee_by_token(self, token):
        """Return the employee matching the token, or None."""
        if not token or len(token) < 16:
            return None
        return request.env['hr.employee'].sudo().search(
            [('access_token', '=', token)], limit=1
        )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>', type='http', auth='public', website=False)
    def voting_dashboard(self, token, **kwargs):
        employee = self._get_employee_by_token(token)
        if not employee:
            return request.not_found()

        voter_partner = employee.user_id.partner_id if employee.user_id else None
        Vote = request.env['aps.award.vote'].sudo()
        Category = request.env['aps.award.category'].sudo()

        twelve_months_ago = date.today() - timedelta(days=365)

        # 1. Votes submitted by this employee in last 12 months
        my_votes_count = 0
        if voter_partner:
            my_votes_count = Vote.search_count([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', '=', 'submitted'),
                ('submitted_date', '>=', twelve_months_ago.isoformat()),
            ])

        # 2. Average votes per voter over the same period
        all_votes = Vote.search([
            ('state', '=', 'submitted'),
            ('submitted_date', '>=', twelve_months_ago.isoformat()),
        ])
        voter_ids = set(v.voter_partner_id.id for v in all_votes if v.voter_partner_id)
        avg_votes = round(len(all_votes) / len(voter_ids)) if voter_ids else 0

        # 3. Open categories (voting_active=True)
        open_categories = Category.search([('voting_active', '=', True)])

        # 4. Categories that have closed since open_date where this voter never voted
        expired_count = 0
        if voter_partner:
            closed_categories = Category.search([
                ('voting_active', '=', False),
                ('open_date', '!=', False),
            ])
            for cat in closed_categories:
                voted = Vote.search_count([
                    ('award_category_id', '=', cat.id),
                    ('voter_partner_id', '=', voter_partner.id),
                    ('state', '=', 'submitted'),
                    ('submitted_date', '>=', cat.open_date.isoformat()),
                ])
                if not voted:
                    expired_count += 1

        # 5. Per-category open vote count and earliest due date for this voter
        cat_stats = {}
        my_votes = []
        if voter_partner:
            all_cat_votes = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', 'in', ['open', 'submitted', 'closed']),
                ('award_category_id', 'in', open_categories.ids),
            ])
            for cat in open_categories:
                cat_votes = all_cat_votes.filtered(lambda v: v.award_category_id.id == cat.id)
                open_votes = cat_votes.filtered(lambda v: v.state == 'open')
                submitted_votes = cat_votes.filtered(lambda v: v.state == 'submitted')
                closed_votes = cat_votes.filtered(lambda v: v.state == 'closed')
                due_dates = [v.due_date for v in open_votes if v.due_date]
                cat_stats[cat.id] = {
                    'open_count': len(open_votes),
                    'submitted_count': len(submitted_votes),
                    'closed_count': len(closed_votes),
                    'due_date': min(due_dates).strftime('%#d %b %Y') if due_dates else None,
                }

            my_votes = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
            ], order='submitted_date desc, id desc')

        values = {
            'employee': employee,
            'token': token,
            'my_votes_count': my_votes_count,
            'avg_votes': avg_votes,
            'open_categories': open_categories,
            'expired_count': expired_count,
            'cat_stats': cat_stats,
            'my_votes': my_votes,
        }
        return request.render('aps_sis.awards_voting_dashboard', values)

    # ------------------------------------------------------------------
    # Candidates JSON
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/candidates/<int:category_id>',
                type='json', auth='public')
    def voting_candidates(self, token, category_id, level_id=None,
                          subject_category_id=None, **kwargs):
        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        category = request.env['aps.award.category'].sudo().browse(category_id)
        if not category.exists():
            return {'error': 'Category not found'}

        Certificate = request.env['aps.student.certificate'].sudo()
        Student = request.env['aps.student'].sudo()

        domain = [('active', '=', True)]
        if level_id:
            domain.append(('level_id', '=', int(level_id)))
        elif category.level_ids:
            domain.append(('level_id', 'in', category.level_ids.ids))

        students = Student.search(domain, order='partner_id')

        # Filter by subject category if requested
        if subject_category_id:
            sid = int(subject_category_id)
            filtered = Student
            for s in students:
                enrolled_cats = s.enrollment_ids.mapped(
                    'home_class_id.subject_id.category_id'
                )
                if sid in enrolled_cats.ids:
                    filtered |= s
            students = filtered

        result = []
        for student in students:
            partner = student.partner_id

            past_certs = Certificate.search([
                ('award_category_id', '=', category_id),
                ('partner_id', '=', partner.id),
            ], order='certificate_date desc')
            times_awarded = len(past_certs)
            last_awarded = past_certs[0].certificate_date.isoformat() if past_certs else None

            image_b64 = ''
            if partner.image_128:
                image_b64 = partner.image_128.decode() if isinstance(
                    partner.image_128, bytes) else partner.image_128

            result.append({
                'id': partner.id,
                'name': partner.name or '',
                'image': image_b64,
                'times_awarded': times_awarded,
                'last_awarded': last_awarded,
                'level': student.level_id.display_name or '',
            })

        result.sort(key=lambda x: x['name'])

        sub_categories = [
            {'id': sc.id, 'name': sc.name}
            for sc in category.sub_category_ids
        ]

        return {'candidates': result, 'sub_categories': sub_categories}

    # ------------------------------------------------------------------
    # Submit vote
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/submit', type='json', auth='public')
    def voting_submit(self, token, category_id, recipients, **kwargs):
        """recipients: list of {id: int, comment: str}"""
        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        voter_partner = employee.user_id.partner_id if employee.user_id else None
        if not voter_partner:
            return {'error': 'Employee has no linked user/partner'}

        category = request.env['aps.award.category'].sudo().browse(int(category_id))
        if not category.exists():
            return {'error': 'Category not found'}

        Vote = request.env['aps.award.vote'].sudo()

        # Fetch any pre-existing open votes for this voter + category to reuse
        open_votes = Vote.search([
            ('voter_partner_id', '=', voter_partner.id),
            ('award_category_id', '=', category.id),
            ('state', '=', 'open'),
        ], order='due_date asc nulls last, id asc')
        open_pool = list(open_votes)  # consume from front (earliest due date first)

        submitted = []
        for rec in recipients:
            pid = rec.get('id')
            comment = rec.get('comment', '')
            sub_category_id = rec.get('sub_category_id') or False
            if not pid:
                continue
            partner = request.env['res.partner'].sudo().browse(int(pid))
            if not partner.exists():
                continue
            vals = {
                'recipient_partner_id': partner.id,
                'comment': comment,
                'state': 'submitted',
                'submitted_date': date.today().isoformat(),
                'award_sub_category_id': int(sub_category_id) if sub_category_id else False,
            }
            if open_pool:
                # Reuse an existing open record
                vote = open_pool.pop(0)
                vote.write(vals)
            else:
                # No open record to reuse — create a new one
                vals.update({
                    'award_category_id': category.id,
                    'voter_partner_id': voter_partner.id,
                })
                vote = Vote.create(vals)
            submitted.append(vote.id)

        return {'success': True, 'submitted': submitted}

    # ------------------------------------------------------------------
    # Delete / revert submitted vote
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/vote/<int:vote_id>/delete',
                type='json', auth='public')
    def voting_delete_vote(self, token, vote_id, **kwargs):
        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        voter_partner = employee.user_id.partner_id if employee.user_id else None
        if not voter_partner:
            return {'error': 'No linked partner'}

        vote = request.env['aps.award.vote'].sudo().browse(vote_id)
        if not vote.exists():
            return {'error': 'Vote not found'}
        if vote.voter_partner_id.id != voter_partner.id:
            return {'error': 'Not authorised'}
        if vote.state != 'submitted':
            return {'error': 'Only submitted votes can be removed'}

        if vote.due_date:
            # Has a due date — revert to open for re-use
            vote.write({
                'state': 'open',
                'recipient_partner_id': False,
                'award_sub_category_id': False,
                'comment': False,
                'submitted_date': False,
            })
            return {'action': 'reverted'}
        else:
            # No due date — permanently delete
            vote.unlink()
            return {'action': 'deleted'}
