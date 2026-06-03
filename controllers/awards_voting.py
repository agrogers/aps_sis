import base64
import hashlib
import hmac
import json
from datetime import date, timedelta
from urllib.parse import urlencode

from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


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

    @staticmethod
    def _sign_image_request(token, partner_id, version):
        secret = (request.env['ir.config_parameter'].sudo().get_param('database.secret') or '').encode()
        payload = f"{token}:{partner_id}:{version}".encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def _image_url(self, token, partner_id, write_date=None):
        version = write_date.isoformat() if write_date else '0'
        sig = self._sign_image_request(token, partner_id, version)
        qs = {
            'v': version,
            's': sig,
        }
        return f"/awards/vote/{token}/candidate_image/{partner_id}?{urlencode(qs)}"

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
    def voting_candidates(self, token, category_id, vote_id=None, include_images=True, **kwargs):
        import time
        t0 = time.time()
        _logger.info("[voting_candidates] called: token=%s, category_id=%s, vote_id=%s", token, category_id, vote_id)
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
        limit_to_own_students = 'no'
        allow_no_vote = False
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
                limit_to_own_students = rnd.rule_limit_candidates_to_own_students or 'no'
                allow_no_vote = bool(rnd.rule_allow_no_vote)

        # ── Compute the voter's "own students" when the rule requires it ──────
        own_student_partner_ids = []
        if limit_to_own_students in ('yes', 'optional') and vote_obj and vote_obj.exists():
            voter_partner = vote_obj.voter_partner_id
            if voter_partner:
                Class = request.env['aps.class'].sudo()
                own_classes = Class.search([
                    '|',
                    ('teacher_ids', 'in', [voter_partner.id]),
                    ('assistant_teacher_ids', 'in', [voter_partner.id]),
                ])
                if own_classes:
                    Enrollment = request.env['aps.student.class'].sudo()
                    enrollments = Enrollment.search([
                        ('home_class_id', 'in', own_classes.ids),
                        ('active', '=', True),
                    ])
                    own_student_partner_ids = (
                        enrollments.mapped('student_id.partner_id').filtered('id').ids
                    )

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
            t1 = time.time()
            _logger.info("[voting_candidates] DEPT: Searching employees in departments %s", ec_department_ids)
            Employee = request.env['hr.employee'].sudo()
            dept_employees = Employee.search([
                ('department_id', 'in', ec_department_ids),
                ('active', '=', True),
            ])
            t2 = time.time()
            _logger.info("[voting_candidates] DEPT: Found %d employees in %.3fs", len(dept_employees), t2-t1)

            # Prefetch all relational fields in batch to avoid per-record queries
            dept_employees.mapped('user_id.partner_id')
            partner_records = dept_employees.mapped('user_id.partner_id').filtered('id')
            t3 = time.time()
            _logger.info("[voting_candidates] DEPT: Found %d partners in %.3fs", len(partner_records), t3-t2)
            partner_meta_map = {
                r['id']: r['write_date']
                for r in partner_records.read(['write_date'])
            }
            t4 = time.time()
            _logger.info("[voting_candidates] DEPT: Read partner write_date for %d partners in %.3fs", len(partner_meta_map), t4-t3)

            result = []
            for emp in dept_employees:
                if not emp.user_id or not emp.user_id.partner_id:
                    continue
                partner = emp.user_id.partner_id
                if partner.id in excluded_partner_ids:
                    continue

                image_url = self._image_url(
                    token,
                    partner.id,
                    write_date=partner_meta_map.get(partner.id),
                ) if include_images else ''

                result.append({
                    'id': partner.id,
                    'name': partner.name or '',
                    'image': '',
                    'image_url': image_url,
                    'times_awarded': 0,
                    'last_awarded': None,
                    'level': '',
                    'department': emp.department_id.name or '',
                    'is_staff': True,
                    'subject_cat_ids': [],
                    'whitelisted': True,
                })

            result.sort(key=lambda x: x['name'])
            t5 = time.time()
            _logger.info("[voting_candidates] DEPT: Built result list with %d candidates in %.3fs", len(result), t5-t4)
            if result:
                _logger.info("[voting_candidates] DEPT: Sample image_url=%s", result[0].get('image_url'))
            _logger.info("[voting_candidates] DEPT: TOTAL time: %.3fs", t5-t0)
            return {
                'candidates': result,
                'sub_categories': [{'id': sc.id, 'name': sc.name} for sc in category.sub_category_ids]
                    if category.exists() else [],
                'subject_cats': [],
                'vote_limit': vote_limit,
                'show_times_awarded': show_times_awarded,
                'show_last_awarded': show_last_awarded,
                'show_level_dept': show_level_dept,
                'limit_candidates_to_own_students': limit_to_own_students,
                'own_student_partner_ids': [],
                'allow_no_vote': allow_no_vote,
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
                    'show_level_dept': show_level_dept,
                    'limit_candidates_to_own_students': limit_to_own_students,
                    'own_student_partner_ids': own_student_partner_ids,
                    'allow_no_vote': allow_no_vote}

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

        # Prefetch partner relations and batch-read write_date before the loop
        students.mapped('partner_id')
        student_partners = students.mapped('partner_id').filtered('id')
        student_meta_map = {
            r['id']: r['write_date']
            for r in student_partners.read(['write_date'])
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

            image_url = self._image_url(
                token,
                partner.id,
                write_date=student_meta_map.get(partner.id),
            ) if include_images else ''

            enrolled_cats = student.enrollment_ids.mapped('home_class_id.subject_id.category_id')
            if ec_subject_cat_ids and not is_whitelisted:
                student_subcat_ids = [i for i in enrolled_cats.ids if i in ec_subject_cat_ids]
            else:
                student_subcat_ids = enrolled_cats.ids
            all_subject_cat_ids.update(student_subcat_ids)

            result.append({
                'id': partner.id,
                'name': partner.name or '',
                'image': '',
                'image_url': image_url,
                'times_awarded': times_awarded,
                'last_awarded': last_awarded,
                'level': student.level_id.display_name or '',
                'department': '',
                'is_staff': False,
                'subject_cat_ids': student_subcat_ids,
                'whitelisted': is_whitelisted,
            })

        result.sort(key=lambda x: x['name'])

        # ── Apply own-students filter for 'yes' mode (server-side) ──────────
        if limit_to_own_students == 'yes' and own_student_partner_ids:
            own_set = set(own_student_partner_ids)
            result = [r for r in result if r['id'] in own_set]

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
            'limit_candidates_to_own_students': limit_to_own_students,
            'own_student_partner_ids': own_student_partner_ids if limit_to_own_students == 'optional' else [],
            'allow_no_vote': allow_no_vote,
        }

    @http.route('/awards/vote/<string:token>/candidate_image/<int:partner_id>',
                type='http', auth='public', website=False)
    def voting_candidate_image(self, token, partner_id, v='0', s=None, **kwargs):
        employee = self._get_employee_by_token(token)
        if not employee:
            _logger.info("[voting_candidate_image] not_found: invalid token partner_id=%s", partner_id)
            return request.not_found()

        if not s:
            _logger.info("[voting_candidate_image] not_found: missing signature partner_id=%s", partner_id)
            return request.not_found()

        expected_sig = self._sign_image_request(token, partner_id, v or '0')
        if not hmac.compare_digest(expected_sig, s):
            _logger.info("[voting_candidate_image] not_found: bad signature partner_id=%s", partner_id)
            return request.not_found()

        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists() or not partner.image_128:
            _logger.info("[voting_candidate_image] not_found: missing partner/image partner_id=%s", partner_id)
            return request.not_found()

        raw = partner.image_128
        if isinstance(raw, str):
            raw = raw.encode()
        try:
            image_bytes = base64.b64decode(raw)
        except Exception:
            return request.not_found()

        content_type = 'image/png'
        if image_bytes.startswith(b'\xff\xd8'):
            content_type = 'image/jpeg'

        etag = f'"partner-{partner.id}-{partner.write_date or "0"}"'
        if request.httprequest.headers.get('If-None-Match') == etag:
            _logger.info("[voting_candidate_image] 304 partner_id=%s", partner_id)
            return request.make_response('', headers=[('ETag', etag)], status=304)

        headers = [
            ('Content-Type', content_type),
            ('Cache-Control', 'public, max-age=86400'),
            ('ETag', etag),
        ]
        _logger.info("[voting_candidate_image] 200 partner_id=%s bytes=%s", partner_id, len(image_bytes))
        return request.make_response(image_bytes, headers=headers)

    # ------------------------------------------------------------------
    # Generic token-authenticated image route for round/set/category/vote
    # images (public users cannot hit /web/image/ for these models)
    # ------------------------------------------------------------------

    # Maps URL model slug → (odoo model name, field name)
    _PUBLIC_IMAGE_MODELS = {
        'round':    ('aps.award.vote.round',   'image'),
        'vote':     ('aps.award.vote',          'image'),
        'category': ('aps.award.category',      'image'),
        'voteset':  ('aps.award.voting.set',    'icon'),
    }

    @http.route('/awards/vote/<string:token>/model_image/<string:model_slug>/<int:record_id>',
                type='http', auth='public', website=False)
    def voting_model_image(self, token, model_slug, record_id, **kwargs):
        if not self._get_employee_by_token(token):
            return request.not_found()

        mapping = self._PUBLIC_IMAGE_MODELS.get(model_slug)
        if not mapping:
            return request.not_found()

        model_name, field_name = mapping
        record = request.env[model_name].sudo().browse(record_id)
        if not record.exists():
            return request.not_found()

        raw = getattr(record, field_name, None)
        if not raw:
            return request.not_found()

        if isinstance(raw, str):
            raw = raw.encode()
        try:
            image_bytes = base64.b64decode(raw)
        except Exception:
            return request.not_found()

        content_type = 'image/png'
        if image_bytes.startswith(b'\xff\xd8'):
            content_type = 'image/jpeg'
        elif image_bytes.lstrip()[:4] in (b'<svg', b'<?xm'):
            content_type = 'image/svg+xml'

        etag = f'"{model_slug}-{record_id}-{record.write_date or "0"}"'
        if request.httprequest.headers.get('If-None-Match') == etag:
            return request.make_response('', headers=[('ETag', etag)], status=304)

        headers = [
            ('Content-Type', content_type),
            ('Cache-Control', 'public, max-age=86400'),
            ('ETag', etag),
        ]
        return request.make_response(image_bytes, headers=headers)

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

        # ── No-vote (abstain) path: empty recipients list ──────────────────
        if not recipients:
            # Check that the round actually allows no-vote submissions
            allow_no_vote = False
            if open_pool and open_pool[0].vote_round_id:
                allow_no_vote = bool(open_pool[0].vote_round_id.rule_allow_no_vote)
            if not allow_no_vote:
                return {'error': 'No recipients provided'}
            vals = {
                'recipient_partner_id': False,
                'comment': 'No vote submitted.',
                'state': 'submitted',
                'submitted_date': date.today().isoformat(),
                'award_category_id': category.id if category.exists() else False,
            }
            if round_id:
                vals['vote_round_id'] = round_id
            if open_pool:
                vote = open_pool.pop(0)
                if vote.vote_round_id:
                    vals['vote_round_id'] = vote.vote_round_id.id
                vote.write(vals)
            else:
                vals['voter_partner_id'] = voter_partner.id
                vote = Vote.create(vals)
            submitted.append(vote.id)
            return {'success': True, 'submitted': submitted}

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
