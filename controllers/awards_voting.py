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

    @staticmethod
    def _image_b64(partner):
        """Return base64-encoded image_128 for *partner* as a string, or ''."""
        if not partner.image_128:
            return ''
        img = partner.image_128
        return img.decode() if isinstance(img, bytes) else img

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
        my_vote_groups = []
        if voter_partner:
            voter_open_votes = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', '=', 'open'),
            ], order='due_date asc nulls last, id asc')

            my_votes_raw = Vote.search([
                ('voter_partner_id', '=', voter_partner.id),
                ('state', '!=', 'open'),
            ], order='submitted_date desc, id desc')

            # Auto-close submitted votes whose due_date has passed.
            today = date.today()
            overdue = my_votes_raw.filtered(
                lambda v: v.state == 'submitted' and v.due_date and v.due_date < today
            )
            if overdue:
                overdue.write({'state': 'closed'})

            # Group votes that belong to the same round into a single display row.
            # Votes with no round are each their own group.
            seen_round_ids = {}
            for v in my_votes_raw:
                rnd_id = v.vote_round_id.id if v.vote_round_id else None
                # has_due = submitted with a future due date (still undoable)
                has_due = v.state == 'submitted' and bool(v.due_date) and v.due_date >= today
                if rnd_id and rnd_id in seen_round_ids:
                    seen_round_ids[rnd_id]['votes'].append(v)
                    # If any vote in the group is still undoable, keep has_due True
                    if has_due:
                        seen_round_ids[rnd_id]['has_due'] = True
                else:
                    group = {
                        'rep': v,
                        'votes': [v],
                        'has_due': has_due,
                        'state': v.state,
                    }
                    my_vote_groups.append(group)
                    if rnd_id:
                        seen_round_ids[rnd_id] = group

        values = {
            'employee': employee,
            'token': token,
            'my_votes_count': my_votes_count,
            'avg_votes': avg_votes,
            'open_votes_count': len(voter_open_votes),
            'expired_count': expired_count,
            'voter_open_votes': voter_open_votes,
            'my_vote_groups': my_vote_groups,
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
        ec_department_ids = []
        ineligible_exclude_voter = False
        ineligible_partner_ids = []
        vote_limit = 0
        show_times_awarded = True
        show_last_awarded  = True
        show_level_dept    = True
        if vote_id:
            vote_obj = request.env['aps.award.vote'].sudo().browse(int(vote_id))
            if vote_obj.exists() and vote_obj.vote_round_id:
                rnd = vote_obj.vote_round_id
                ec_student_ids     = rnd.eligible_candidate_student_ids.ids
                ec_level_ids       = rnd.eligible_candidate_level_ids.ids
                ec_subject_cat_ids = rnd.eligible_candidate_category_ids.ids
                ec_department_ids  = rnd.eligible_candidate_department_ids.ids
                ineligible_exclude_voter = rnd.ineligible_candidate_exclude_voter
                ineligible_partner_ids   = rnd.ineligible_candidate_partner_ids.ids
                if rnd.rule_limit_votes:
                    vote_limit = rnd.rule_limit_votes_count or 1
                show_times_awarded = rnd.rule_show_times_awarded
                show_last_awarded  = rnd.rule_show_last_awarded
                show_level_dept    = rnd.rule_show_level_dept

        # ── Determine the voter's own partner_id for exclusion ──
        voter_partner_id = None
        if ineligible_exclude_voter and vote_obj and vote_obj.voter_partner_id:
            voter_partner_id = vote_obj.voter_partner_id.id

        # Build full set of partner IDs to exclude from results
        excluded_partner_ids = set(ineligible_partner_ids)
        if voter_partner_id:
            excluded_partner_ids.add(voter_partner_id)

        # ── Department-based staff candidates ──────────────────────────────────
        if ec_department_ids:
            Employee = request.env['hr.employee'].sudo()
            dept_employees = Employee.search([
                ('department_id', 'in', ec_department_ids),
                ('active', '=', True),
            ])

            # Prefetch all relational fields in batch to avoid per-record queries
            dept_employees.mapped('user_id.partner_id')
            partner_records = dept_employees.mapped('user_id.partner_id').filtered('id')
            # Batch-read image_128 (binary fields are not included in default prefetch)
            partner_image_map = {
                r['id']: r['image_128']
                for r in partner_records.read(['image_128'])
            }

            result = []
            for emp in dept_employees:
                if not emp.user_id or not emp.user_id.partner_id:
                    continue
                partner = emp.user_id.partner_id
                if partner.id in excluded_partner_ids:
                    continue

                img = partner_image_map.get(partner.id)
                image_b64 = (img.decode() if isinstance(img, bytes) else img) if img else ''

                result.append({
                    'id': partner.id,
                    'name': partner.name or '',
                    'image': image_b64,
                    'times_awarded': 0,
                    'last_awarded': None,
                    'level': '',
                    'department': emp.department_id.name or '',
                    'is_staff': True,
                    'subject_cat_ids': [],
                    'whitelisted': True,
                })

            result.sort(key=lambda x: x['name'])
            return {
                'candidates': result,
                'sub_categories': [{'id': sc.id, 'name': sc.name} for sc in category.sub_category_ids]
                    if category.exists() else [],
                'subject_cats': [],
                'vote_limit': vote_limit,
                'show_times_awarded': show_times_awarded,
                'show_last_awarded': show_last_awarded,
                'show_level_dept': show_level_dept,
            }

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
            return {'candidates': [], 'sub_categories': [], 'subject_cats': [], 'vote_limit': vote_limit,
                    'show_times_awarded': show_times_awarded, 'show_last_awarded': show_last_awarded,
                    'show_level_dept': show_level_dept}

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

        # Prefetch partner relations and batch-read images before the loop
        students.mapped('partner_id')
        student_partners = students.mapped('partner_id').filtered('id')
        student_image_map = {
            r['id']: r['image_128']
            for r in student_partners.read(['image_128'])
        }

        # Batch-load all certificates for this category in one query (avoid N+1)
        certs_by_partner = {}
        if category.exists() and student_partners:
            all_certs = Certificate.search([
                ('award_category_id', '=', category.id),
                ('partner_id', 'in', student_partners.ids),
            ], order='certificate_date desc')
            for c in all_certs:
                pid = c.partner_id.id
                certs_by_partner.setdefault(pid, []).append(c)

        result = []
        all_subject_cat_ids = set()
        for student in students:
            partner = student.partner_id
            if partner.id in excluded_partner_ids:
                continue

            if category.exists():
                partner_certs = certs_by_partner.get(partner.id, [])
                times_awarded = len(partner_certs)
                last_awarded = partner_certs[0].certificate_date.isoformat() if partner_certs else None
            else:
                times_awarded = 0
                last_awarded = None

            img = student_image_map.get(partner.id)
            image_b64 = (img.decode() if isinstance(img, bytes) else img) if img else ''

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
                'department': '',
                'is_staff': False,
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
            'vote_limit': vote_limit,
            'show_times_awarded': show_times_awarded,
            'show_last_awarded': show_last_awarded,
            'show_level_dept': show_level_dept,
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

        # Determine the vote_round_id to stamp on every submitted vote.
        # Priority: pinned ballot's round → first open-pool ballot's round → None.
        round_id = False
        if open_pool:
            round_id = open_pool[0].vote_round_id.id or False

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
                'award_category_id': category.id if category.exists() else False,
            }
            if round_id:
                vals['vote_round_id'] = round_id
            if open_pool:
                # Reuse an existing open record
                vote = open_pool.pop(0)
                # Keep the round from this specific ballot if it has one
                if vote.vote_round_id:
                    vals['vote_round_id'] = vote.vote_round_id.id
                vote.write(vals)
            else:
                # No open record to reuse — create a new one
                vals['voter_partner_id'] = voter_partner.id
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

    # ------------------------------------------------------------------
    # Bulk delete / revert a group of votes (same round)
    # ------------------------------------------------------------------

    @http.route('/awards/vote/<string:token>/votes/delete',
                type='json', auth='public')
    def voting_delete_votes_bulk(self, token, vote_ids=None, **kwargs):
        if not vote_ids or not isinstance(vote_ids, list):
            return {'error': 'No vote_ids provided'}

        employee = self._get_employee_by_token(token)
        if not employee:
            return {'error': 'Invalid token'}

        voter_partner = employee.user_id.partner_id if employee.user_id else None
        if not voter_partner:
            return {'error': 'No linked partner'}

        votes = request.env['aps.award.vote'].sudo().browse(
            [int(vid) for vid in vote_ids]
        ).exists()

        # Security: all votes must belong to this voter and be submitted
        if any(v.voter_partner_id.id != voter_partner.id for v in votes):
            return {'error': 'Not authorised'}
        if any(v.state != 'submitted' for v in votes):
            return {'error': 'Only submitted votes can be removed'}

        revert_vals = {
            'state': 'open',
            'recipient_partner_id': False,
            'award_sub_category_id': False,
            'comment': False,
            'submitted_date': False,
        }
        to_revert = votes.filtered(lambda v: v.due_date)
        to_delete = votes.filtered(lambda v: not v.due_date)
        if to_revert:
            to_revert.write(revert_vals)
        if to_delete:
            to_delete.unlink()

        return {'action': 'done'}
