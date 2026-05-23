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

        # 5. Individual open votes for this voter, plus history
        voter_open_votes = []
        my_votes = []
        if voter_partner:
            voter_open_votes = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', '=', 'open'),
            ], order='due_date asc nulls last, id asc')

            my_votes = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', '!=', 'open'),
            ], order='submitted_date desc, id desc')

        values = {
            'employee': employee,
            'token': token,
            'my_votes_count': my_votes_count,
            'avg_votes': avg_votes,
            'open_votes_count': len(voter_open_votes),
            'expired_count': expired_count,
            'voter_open_votes': voter_open_votes,
            'my_votes': my_votes,
        }
        return request.render('aps_sis.awards_voting_dashboard', values)

    # ------------------------------------------------------------------
    # Candidates JSON
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/candidates/<int:category_id>',
                type='json', auth='public')
    def voting_candidates(self, token, category_id, vote_id=None, **kwargs):
        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        # category_id == 0 means the vote has no category — try to derive it
        if category_id == 0 and vote_id:
            vote_rec = request.env['aps.award.vote'].sudo().browse(int(vote_id))
            if vote_rec.exists() and vote_rec.award_category_id:
                category_id = vote_rec.award_category_id.id

        # category may legitimately be absent (student-whitelist-only rounds)
        # browse(0) can cause ORM errors — use an empty recordset when no real id
        category = request.env['aps.award.category'].sudo().browse(category_id or [])
        Certificate = request.env['aps.student.certificate'].sudo()
        Student = request.env['aps.student'].sudo()

        # ── Resolve candidate constraints from the round (single source of truth) ──
        vote_obj = None
        ec_student_ids = []
        ec_level_ids = []
        ec_subject_cat_ids = []
        if vote_id:
            vote_obj = request.env['aps.award.vote'].sudo().browse(int(vote_id))
            if vote_obj.exists() and vote_obj.vote_round_id:
                rnd = vote_obj.vote_round_id
                ec_student_ids     = rnd.eligible_candidate_student_ids.ids
                ec_level_ids       = rnd.eligible_candidate_level_ids.ids
                ec_subject_cat_ids = rnd.eligible_candidate_category_ids.ids

        # No explicit constraints on round → fall back to category level_ids
        if not ec_student_ids and not ec_level_ids and not ec_subject_cat_ids:
            if category.exists() and category.level_ids:
                ec_level_ids = category.level_ids.ids

        # Peer-voting fallback: voter partners are the candidate pool
        voter_partner_student_ids = []
        if not ec_student_ids and not ec_level_ids and vote_obj and vote_obj.vote_round_id:
            voter_partner_ids = vote_obj.vote_round_id.eligible_voter_partner_ids.ids
            if voter_partner_ids:
                voter_students = Student.search([
                    ('active', '=', True),
                    ('partner_id', 'in', voter_partner_ids),
                ])
                voter_partner_student_ids = voter_students.ids

        # If still nothing — no category, no constraints — return empty
        if not ec_student_ids and not ec_level_ids and not ec_subject_cat_ids \
                and not voter_partner_student_ids:
            return {'candidates': [], 'sub_categories': [], 'subject_cats': []}

        # ── Build student domain ──
        domain = [('active', '=', True)]
        if ec_student_ids:
            domain.append(('id', 'in', ec_student_ids))
        elif voter_partner_student_ids:
            domain.append(('id', 'in', voter_partner_student_ids))
        else:
            if ec_level_ids:
                domain.append(('level_id', 'in', ec_level_ids))

        students = Student.search(domain, order='partner_id')

        # Subject-category filter (skipped when students are explicitly whitelisted)
        if ec_subject_cat_ids and not ec_student_ids and not voter_partner_student_ids:
            filtered = Student.browse()
            for s in students:
                enrolled_cats = s.enrollment_ids.mapped('home_class_id.subject_id.category_id')
                if any(sid in enrolled_cats.ids for sid in ec_subject_cat_ids):
                    filtered |= s
            students = filtered

        is_whitelisted = bool(ec_student_ids or voter_partner_student_ids)

        result = []
        all_subject_cat_ids = set()
        for student in students:
            partner = student.partner_id

            if category.exists():
                past_certs = Certificate.search([
                    ('award_category_id', '=', category.id),
                    ('partner_id', '=', partner.id),
                ], order='certificate_date desc')
                times_awarded = len(past_certs)
                last_awarded = past_certs[0].certificate_date.isoformat() if past_certs else None
            else:
                times_awarded = 0
                last_awarded = None

            image_b64 = ''
            if partner.image_128:
                image_b64 = partner.image_128.decode() if isinstance(
                    partner.image_128, bytes) else partner.image_128

            enrolled_cats = student.enrollment_ids.mapped('home_class_id.subject_id.category_id')
            if ec_subject_cat_ids and not is_whitelisted:
                student_subcat_ids = [i for i in enrolled_cats.ids if i in ec_subject_cat_ids]
            else:
                student_subcat_ids = enrolled_cats.ids
            all_subject_cat_ids.update(student_subcat_ids)

            result.append({
                'id': partner.id,
                'name': partner.name or '',
                'image': image_b64,
                'times_awarded': times_awarded,
                'last_awarded': last_awarded,
                'level': student.level_id.display_name or '',
                'subject_cat_ids': student_subcat_ids,
                'whitelisted': is_whitelisted,
            })

        result.sort(key=lambda x: x['name'])

        SubjectCat = request.env['aps.subject.category'].sudo()
        sc_records = SubjectCat.search([('id', 'in', list(all_subject_cat_ids))], order='name')
        subject_cats = [{'id': sc.id, 'name': sc.name} for sc in sc_records]

        sub_categories = [{'id': sc.id, 'name': sc.name} for sc in category.sub_category_ids] \
            if category.exists() else []

        return {
            'candidates': result,
            'sub_categories': sub_categories,
            'subject_cats': subject_cats,
        }

    # ------------------------------------------------------------------
    # Submit vote
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/submit', type='json', auth='public')
    def voting_submit(self, token, category_id, recipients, vote_id=None, **kwargs):
        """recipients: list of {id: int, comment: str}
        If vote_id is provided, that specific open ballot is used for the first recipient.
        """
        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        voter_partner = employee.user_id.partner_id if employee.user_id else None
        if not voter_partner:
            return {'error': 'Employee has no linked user/partner'}

        Vote = request.env['aps.award.vote'].sudo()

        # Derive category: try from category_id, fall back to the vote record itself
        if not category_id and vote_id:
            pinned_for_cat = Vote.browse(int(vote_id))
            if pinned_for_cat.exists() and pinned_for_cat.award_category_id:
                category_id = pinned_for_cat.award_category_id.id
        category = request.env['aps.award.category'].sudo().browse(category_id or [])

        # If a specific vote_id is provided, pin that record as the first in the pool
        if vote_id:
            pinned = Vote.browse(int(vote_id))
            if pinned.exists() and pinned.voter_partner_id.id == voter_partner.id and pinned.state == 'open':
                open_pool = [pinned]
            else:
                open_pool = []
        else:
            # Fetch any pre-existing open votes for this voter + category to reuse
            domain = [('voter_partner_id', '=', voter_partner.id), ('state', '=', 'open')]
            if category.exists():
                domain.append(('award_category_id', '=', category.id))
            open_votes = Vote.search(domain, order='due_date asc nulls last, id asc')
            open_pool = list(open_votes)

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
                    'award_category_id': category.id if category.exists() else False,
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
