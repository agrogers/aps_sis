from odoo import api, fields, models


class APSAwardVote(models.Model):
    _name = 'aps.award.vote'
    _description = 'Award Vote'
    _order = 'submitted_date desc, id desc'

    description = fields.Text(
        string='Description',
        compute='_compute_description_fields', store=True, readonly=False,
    )
    short_description = fields.Text(
        string='Short Description',
        compute='_compute_description_fields', store=True, readonly=False,
    )
    image = fields.Image(
        string='Image',
        compute='_compute_description_fields', store=True, readonly=False,
    )

    @api.depends(
        'vote_round_id.description', 'vote_round_id.short_description', 'vote_round_id.image',
        'award_category_id.description', 'award_category_id.short_description', 'award_category_id.image',
    )
    def _compute_description_fields(self):
        for rec in self:
            rnd = rec.vote_round_id
            cat = rec.award_category_id
            rec.description = (rnd and rnd.description) or (cat and cat.description) or False
            rec.short_description = (rnd and rnd.short_description) or (cat and cat.short_description) or False
            rec.image = (rnd and rnd.image) or (cat and cat.image) or False

    award_category_id = fields.Many2one(
        'aps.award.category',
        string='Award Category',
        required=False,
        ondelete='restrict',
    )
    award_sub_category_id = fields.Many2one(
        'aps.award.sub.category',
        string='Award Sub-Category',
        ondelete='restrict',
        domain="[('category_id', '=', award_category_id)]",
    )
    academic_week_id = fields.Many2one(
        'aps.academic.week',
        string='Academic Week',
        ondelete='restrict',
    )
    recipient_partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=False,
        ondelete='restrict',
    )
    voter_partner_id = fields.Many2one(
        'res.partner',
        string='Voter',
        required=True,
        ondelete='restrict',
    )
    note = fields.Text(string='Note')
    comment = fields.Text(string='Comment')
    submitted_date = fields.Date(string='Date')
    open_date = fields.Date(string='Open Date')
    due_date = fields.Date(string='Due Date')
    vote_round_id = fields.Many2one(
        'aps.award.vote.round',
        string='Vote Round',
        required=False,
        ondelete='set null',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('open', 'Open'),
            ('submitted', 'Submitted'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='open',
        required=True,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Related / convenience fields for list, pivot, graph views
    # ------------------------------------------------------------------

    round_name = fields.Char(
        related='vote_round_id.name', string='Round', store=True, readonly=True,
    )
    round_status = fields.Selection(
        related='vote_round_id.status', string='Round Status', store=True, readonly=True,
    )
    round_image = fields.Image(
        related='vote_round_id.image', string='Round Image', store=True, readonly=True,
    )
    round_datetime_start = fields.Datetime(
        related='vote_round_id.datetime_start', string='Round Start', store=True, readonly=True,
    )
    round_datetime_end = fields.Datetime(
        related='vote_round_id.datetime_end', string='Round End', store=True, readonly=True,
    )
    category_name = fields.Char(
        related='award_category_id.name', string='Category', store=True, readonly=True,
    )
    category_image = fields.Image(
        related='award_category_id.image', string='Category Image', store=True, readonly=True,
    )
    recipient_name = fields.Char(
        related='recipient_partner_id.name', string='Recipient Name', store=True, readonly=True,
    )
    voter_name = fields.Char(
        related='voter_partner_id.name', string='Voter Name', store=True, readonly=True,
    )
    voter_access_token = fields.Char(
        string='Voter Access Token',
        compute='_compute_voter_access_token',
    )

    @api.depends('voter_partner_id')
    def _compute_voter_access_token(self):
        for rec in self:
            if not rec.voter_partner_id:
                rec.voter_access_token = ''
                continue
            rec.voter_access_token = rec.voter_partner_id.sudo()._get_or_create_access_token()

    # ------------------------------------------------------------------
    # Vote Analysis Dashboard RPC methods
    # ------------------------------------------------------------------

    @api.model
    def get_vote_analysis_filter_options(self):
        """Return available filter options for the vote analysis dashboard."""
        rounds = self.env['aps.award.vote.round'].search_read(
            [('status', 'in', ['open', 'closed', 'finalised'])],
            ['id', 'name'],
        )
        categories = self.env['aps.award.category'].search_read([], ['id', 'name'])
        sub_categories = self.env['aps.award.sub.category'].search_read([], ['id', 'name'])
        voting_sets = self.env['aps.award.voting.set'].search_read([], ['id', 'name'])
        return {
            'rounds': rounds,
            'categories': categories,
            'sub_categories': sub_categories,
            'voting_sets': voting_sets,
        }

    @api.model
    def get_recipient_domain(self, recipient_type, level_ids=None, department_ids=None):
        """Return partner IDs matching the recipient type filter.

        When type is 'student' or 'staff', returns ALL partners of that type.
        If level_ids or department_ids are provided, narrows the result to those.
        """
        if recipient_type == 'student':
            domain = []
            if level_ids:
                domain.append(('level_id', 'in', level_ids))
            students = self.env['aps.student'].search(domain)
            return [s.partner_id.id for s in students if s.partner_id]
        if recipient_type == 'staff':
            domain = [('active', '=', True)]
            if department_ids:
                domain.append(('department_id', 'in', department_ids))
            employees = self.env['hr.employee'].search(domain)
            return [e.user_id.partner_id.id for e in employees if e.user_id and e.user_id.partner_id]
        return []

    @api.model
    def get_vote_analysis_data(self, filters=None):
        """Return aggregated vote data for the analysis dashboard.

        Args:
            filters: dict with optional keys:
                - date_from: str (YYYY-MM-DD) or False
                - date_to: str (YYYY-MM-DD) or False
                - round_ids: list of round IDs or empty
                - category_ids: list of category IDs or empty
                - sub_category_ids: list of sub-category IDs or empty
                - recipient_ids: list of partner IDs or empty
                - series_by: str - 'round', 'category', 'sub_category', or 'voting_set'
                - recipient_type: str - 'all', 'student', or 'staff'
                - level_ids: list of level IDs (for student filter)
                - department_ids: list of department IDs (for staff filter)
                - overlay: str - 'none' or 'certificates'

        Returns:
            dict with keys:
                - series: list of {id, name} for the series dimension
                - recipients: list of {id, name, votes: {series_id: count}, total}
                - certificate_counts: dict of {partner_id: int} (empty dict when overlay != 'certificates')
        """
        filters = filters or {}
        series_by = filters.get('series_by', 'round')
        domain = [('state', 'in', ['submitted', 'closed'])]

        if filters.get('date_from'):
            domain.append(('submitted_date', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('submitted_date', '<=', filters['date_to']))
        if filters.get('round_ids'):
            domain.append(('vote_round_id', 'in', filters['round_ids']))
        if filters.get('category_ids'):
            domain.append(('award_category_id', 'in', filters['category_ids']))
        if filters.get('sub_category_ids'):
            domain.append(('award_sub_category_id', 'in', filters['sub_category_ids']))
        # Two-layer recipient filtering: type-based pool + explicit selection
        type_partner_ids = self.get_recipient_domain(
            filters.get('recipient_type', 'all'),
            filters.get('level_ids'),
            filters.get('department_ids'),
        )
        explicit_ids = filters.get('recipient_ids', [])
        if type_partner_ids:
            if explicit_ids:
                # Intersection: only recipients in both the type pool AND explicitly selected
                final_ids = list(set(type_partner_ids) & set(explicit_ids))
            else:
                final_ids = type_partner_ids
            domain.append(('recipient_partner_id', 'in', final_ids))
        elif explicit_ids:
            domain.append(('recipient_partner_id', 'in', explicit_ids))

        # Fetch votes with all possible series fields
        votes = self.search_read(
            domain,
            ['recipient_partner_id', 'vote_round_id', 'award_category_id', 'award_sub_category_id'],
        )

        # Map series IDs to names
        series_names = {}
        series_ids_in_data = set()

        # Pre-fetch voting set data if needed
        round_to_voting_sets = {}
        if series_by == 'voting_set':
            round_ids = set()
            for v in votes:
                rid = v['vote_round_id'][0] if v['vote_round_id'] else False
                if rid:
                    round_ids.add(rid)
            if round_ids:
                voting_set_records = self.env['aps.award.vote.round'].search_read(
                    [('id', 'in', list(round_ids))],
                    ['id', 'voting_set_ids'],
                )
                round_to_voting_sets = {}
                for r in voting_set_records:
                    round_to_voting_sets[r['id']] = r.get('voting_set_ids', [])
                # Load voting set names
                all_vs_ids = set()
                for vs_list in round_to_voting_sets.values():
                    all_vs_ids.update(vs_list)
                if all_vs_ids:
                    vs_records = self.env['aps.award.voting.set'].search_read(
                        [('id', 'in', list(all_vs_ids))],
                        ['id', 'name'],
                    )
                    series_names = {r['id']: r['name'] for r in vs_records}

        elif series_by == 'category':
            cat_ids = set()
            for v in votes:
                cid = v['award_category_id'][0] if v['award_category_id'] else False
                if cid:
                    cat_ids.add(cid)
            if cat_ids:
                cat_records = self.env['aps.award.category'].search_read(
                    [('id', 'in', list(cat_ids))],
                    ['id', 'name'],
                )
                series_names = {r['id']: r['name'] for r in cat_records}

        elif series_by == 'sub_category':
            sub_ids = set()
            for v in votes:
                sid = v['award_sub_category_id'][0] if v['award_sub_category_id'] else False
                if sid:
                    sub_ids.add(sid)
            if sub_ids:
                sub_records = self.env['aps.award.sub.category'].search_read(
                    [('id', 'in', list(sub_ids))],
                    ['id', 'name'],
                )
                series_names = {r['id']: r['name'] for r in sub_records}

        else:  # 'round' (default)
            for v in votes:
                rid = v['vote_round_id'][0] if v['vote_round_id'] else False
                if rid:
                    series_ids_in_data.add(rid)
            if series_ids_in_data:
                round_records = self.env['aps.award.vote.round'].search_read(
                    [('id', 'in', list(series_ids_in_data))],
                    ['id', 'name'],
                )
                series_names = {r['id']: r['name'] for r in round_records}

        # Aggregate: recipient -> series item -> count + vote IDs
        recipient_data = {}
        for v in votes:
            partner = v['recipient_partner_id']
            if not partner:
                continue
            vid = v['id']
            pid = partner[0]
            pname = partner[1]

            def _ensure_recipient(d, p_id, p_name):
                if p_id not in d:
                    d[p_id] = {'id': p_id, 'name': p_name, 'votes': {}, 'total': 0, 'vote_ids': {}}

            def _add_vote(d, p_id, s_id, vote_id):
                d[p_id]['votes'][s_id] = d[p_id]['votes'].get(s_id, 0) + 1
                d[p_id]['total'] += 1
                if s_id not in d[p_id]['vote_ids']:
                    d[p_id]['vote_ids'][s_id] = []
                d[p_id]['vote_ids'][s_id].append(vote_id)
                if s_id not in series_ids_in_data:
                    series_ids_in_data.add(s_id)

            # Determine the series ID for this vote
            if series_by == 'voting_set':
                rid = v['vote_round_id'][0] if v['vote_round_id'] else False
                vs_ids = round_to_voting_sets.get(rid, []) if rid else []
                for vs_id in vs_ids:
                    _ensure_recipient(recipient_data, pid, pname)
                    _add_vote(recipient_data, pid, vs_id, vid)
            elif series_by == 'category':
                sid = v['award_category_id'][0] if v['award_category_id'] else False
                if sid:
                    _ensure_recipient(recipient_data, pid, pname)
                    _add_vote(recipient_data, pid, sid, vid)
            elif series_by == 'sub_category':
                sid = v['award_sub_category_id'][0] if v['award_sub_category_id'] else False
                if sid:
                    _ensure_recipient(recipient_data, pid, pname)
                    _add_vote(recipient_data, pid, sid, vid)
            else:  # 'round'
                sid = v['vote_round_id'][0] if v['vote_round_id'] else False
                if sid:
                    _ensure_recipient(recipient_data, pid, pname)
                    _add_vote(recipient_data, pid, sid, vid)

        # Sort by total descending, then name
        recipients = sorted(
            recipient_data.values(),
            key=lambda r: (-r['total'], r['name']),
        )

        # Build series list sorted by the order they appear in the data
        series_list = [
            {'id': sid, 'name': series_names.get(sid, f'#{sid}')}
            for sid in sorted(series_ids_in_data)
        ]

        # Certificate overlay
        certificate_counts = {}
        if filters.get('overlay') == 'certificates':
            cert_domain = []
            if filters.get('category_ids'):
                cert_domain.append(('award_category_id', 'in', filters['category_ids']))
            if filters.get('date_from'):
                cert_domain.append(('date_awarded', '>=', filters['date_from']))
            if filters.get('date_to'):
                cert_domain.append(('date_awarded', '<=', filters['date_to']))
            # Apply same recipient type restrictions
            if type_partner_ids:
                cert_domain.append(('partner_id', 'in', type_partner_ids))
            elif explicit_ids:
                cert_domain.append(('partner_id', 'in', explicit_ids))

            certs = self.env['aps.certificate'].search_read(
                cert_domain, ['partner_id']
            )
            for c in certs:
                pid = c['partner_id'][0] if c['partner_id'] else False
                if pid:
                    certificate_counts[pid] = certificate_counts.get(pid, 0) + 1

        return {
            'series': series_list,
            'recipients': recipients,
            'certificate_counts': certificate_counts,
        }

    @api.model
    def get_vote_details(self, vote_ids=None):
        """Return individual vote records by their IDs.

        Args:
            vote_ids: list of vote record IDs

        Returns:
            list of dicts with keys: id, recipient_name, voter_name, round_name,
            category_name, sub_category_name, submitted_date, state, comment, has_certificate
        """
        if not vote_ids:
            return []

        votes = self.search_read(
            [('id', 'in', vote_ids)],
            ['recipient_partner_id', 'voter_partner_id', 'vote_round_id',
             'award_category_id', 'award_sub_category_id', 'submitted_date', 'state', 'comment'],
        )

        # Find which votes already have a certificate linked, and how many
        cert_links = self.env['aps.certificate'].search_read(
            [('related_vote_ids', 'in', vote_ids)],
            ['related_vote_ids'],
        )
        cert_usage_count = {}
        for cert in cert_links:
            for vid in (cert.get('related_vote_ids') or []):
                cert_usage_count[vid] = cert_usage_count.get(vid, 0) + 1

        result = []
        for v in votes:
            result.append({
                'id': v['id'],
                'recipient_name': v['recipient_partner_id'][1] if v['recipient_partner_id'] else '',
                'recipient_id': v['recipient_partner_id'][0] if v['recipient_partner_id'] else False,
                'voter_name': v['voter_partner_id'][1] if v['voter_partner_id'] else '',
                'voter_id': v['voter_partner_id'][0] if v['voter_partner_id'] else False,
                'round_name': v['vote_round_id'][1] if v['vote_round_id'] else '',
                'round_id': v['vote_round_id'][0] if v['vote_round_id'] else False,
                'category_name': v['award_category_id'][1] if v['award_category_id'] else '',
                'category_id': v['award_category_id'][0] if v['award_category_id'] else False,
                'sub_category_name': v['award_sub_category_id'][1] if v['award_sub_category_id'] else '',
                'submitted_date': v['submitted_date'] or '',
                'state': v['state'] or '',
                'comment': v['comment'] or '',
                'has_certificate': v['id'] in cert_usage_count,
                'cert_usage_count': cert_usage_count.get(v['id'], 0),
            })
        return result

    @api.model
    def update_vote_comment(self, vote_id, comment):
        """Update the comment field of a vote record."""
        vote = self.browse(vote_id)
        if vote.exists():
            vote.write({'comment': comment or ''})
            return True
        return False

    @api.model
    def get_certificate_details(self, filters=None):
        """Return certificate records for a given recipient.

        Args:
            filters: dict with keys:
                - recipient_id: int (required) - partner ID
                - date_from: str (YYYY-MM-DD) or False
                - date_to: str (YYYY-MM-DD) or False
                - category_ids: list of category IDs or empty

        Returns:
            list of dicts with keys: id, event, award_category_name,
            date_awarded, certificate_template_name
        """
        filters = filters or {}
        if not filters.get('recipient_id'):
            return []

        domain = [('partner_id', '=', filters['recipient_id'])]

        if filters.get('date_from'):
            domain.append(('date_awarded', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('date_awarded', '<=', filters['date_to']))
        if filters.get('category_ids'):
            domain.append(('award_category_id', 'in', filters['category_ids']))

        certs = self.env['aps.certificate'].search_read(
            domain,
            ['event', 'award_category_id', 'award_sub_category_id', 'date_awarded',
             'certificate_template_id', 'related_partner_ids'],
        )

        result = []
        for c in certs:
            related_names = ', '.join(
                [pid[1] for pid in (c.get('related_partner_ids') or []) if isinstance(pid, (list, tuple)) and len(pid) > 1]
            )
            result.append({
                'id': c['id'],
                'event': c['event'] or '',
                'award_category_name': c['award_category_id'][1] if c['award_category_id'] else '',
                'award_sub_category_name': c['award_sub_category_id'][1] if c['award_sub_category_id'] else '',
                'date_awarded': c['date_awarded'] or '',
                'certificate_template_name': c['certificate_template_id'][1] if c['certificate_template_id'] else '',
                'related_partner_names': related_names,
            })
        return result

    @api.model
    def create_certificate_from_selected_votes(self, vote_ids, recipient_id):
        """Create an aps.certificate from selected votes for a recipient.

        Args:
            vote_ids: list of selected vote record IDs
            recipient_id: partner ID of the recipient

        Returns:
            dict with created certificate details or error info:
                - success: bool
                - certificate_id: int (if success)
                - recipient_name: str
                - error: str (if not success)
        """
        if not vote_ids or not recipient_id:
            return {'success': False, 'error': 'Missing vote IDs or recipient ID'}

        # Fetch the selected votes
        votes = self.search_read(
            [('id', 'in', vote_ids)],
            ['voter_partner_id', 'vote_round_id', 'award_category_id', 'award_sub_category_id',
             'comment', 'recipient_partner_id'],
        )
        if not votes:
            return {'success': False, 'error': 'No valid votes found'}

        # Get the award category from the first selected vote
        first_vote = votes[0]
        category_id = first_vote['award_category_id'][0] if first_vote['award_category_id'] else False

        # Look up certificate template from the award category
        certificate_template_id = False
        if category_id:
            category = self.env['aps.award.category'].browse(category_id)
            if category.exists() and category.certificate_template_id:
                certificate_template_id = category.certificate_template_id.id

        if not certificate_template_id:
            return {'success': False, 'error': 'No certificate template found for the award category. Please configure a Default Certificate Template on the Category.'}

        # Get the round name from the first selected vote for the event field
        round_id = first_vote['vote_round_id'][0] if first_vote['vote_round_id'] else False
        round_name = first_vote['vote_round_id'][1] if first_vote['vote_round_id'] else ''
        event = round_name or 'Award Certificate'

        # Collect all unique voter partner IDs
        voter_ids = set()
        for v in votes:
            vid = v['voter_partner_id'][0] if v['voter_partner_id'] else False
            if vid:
                voter_ids.add(vid)

        # Collect all non-empty comments
        comments = []
        for v in votes:
            comment = (v.get('comment') or '').strip()
            if comment:
                comments.append(comment)
        notes = '\n'.join(comments) if comments else ''

        # Look up the recipient name
        recipient = self.env['res.partner'].browse(recipient_id)
        recipient_name = recipient.name if recipient.exists() else ''

        # Create the certificate
        cert_vals = {
            'partner_id': recipient_id,
            'event': event,
            'certificate_template_id': certificate_template_id,
            'date_awarded': fields.Date.today(),
            'notes': notes,
            'related_partner_ids': [(6, 0, list(voter_ids))],
            'related_vote_ids': [(6, 0, [v['id'] for v in votes])],
        }
        if category_id:
            cert_vals['award_category_id'] = category_id

        # Get the sub-category from the first selected vote
        sub_category_id = first_vote['award_sub_category_id'][0] if first_vote.get('award_sub_category_id') else False
        if sub_category_id:
            cert_vals['award_sub_category_id'] = sub_category_id

        certificate = self.env['aps.certificate'].create(cert_vals)

        return {
            'success': True,
            'certificate_id': certificate.id,
            'recipient_name': recipient_name,
            'event': event,
        }
