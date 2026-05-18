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
        avg_votes = round(len(all_votes) / len(voter_ids), 1) if voter_ids else 0

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

        # 5. Ad hoc categories
        adhoc_categories = Category.search([
            ('adhoc_vote', '=', True),
            ('voting_active', '=', True),
        ])

        values = {
            'employee': employee,
            'token': token,
            'my_votes_count': my_votes_count,
            'avg_votes': avg_votes,
            'open_categories': open_categories,
            'expired_count': expired_count,
            'adhoc_categories': adhoc_categories,
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

        Vote = request.env['aps.award.vote'].sudo()
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

        open_date = category.open_date
        result = []
        for student in students:
            partner = student.partner_id

            vote_domain = [
                ('award_category_id', '=', category_id),
                ('recipient_partner_id', '=', partner.id),
                ('state', '=', 'submitted'),
            ]
            if open_date:
                vote_domain.append(('submitted_date', '>=', open_date.isoformat()))

            past_votes = Vote.search(vote_domain, order='submitted_date desc')
            times_awarded = len(past_votes)
            last_awarded = past_votes[0].submitted_date.isoformat() if past_votes else None

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
        return {'candidates': result}

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
        created = []
        for rec in recipients:
            pid = rec.get('id')
            comment = rec.get('comment', '')
            if not pid:
                continue
            partner = request.env['res.partner'].sudo().browse(int(pid))
            if not partner.exists():
                continue
            vote = Vote.create({
                'award_category_id': category.id,
                'recipient_partner_id': partner.id,
                'voter_partner_id': voter_partner.id,
                'comment': comment,
                'state': 'submitted',
                'submitted_date': date.today().isoformat(),
            })
            created.append(vote.id)

        return {'success': True, 'created': created}
