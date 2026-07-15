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

        # Aggregate: recipient -> series item -> count
        recipient_data = {}
        for v in votes:
            partner = v['recipient_partner_id']
            if not partner:
                continue
            pid = partner[0]
            pname = partner[1]

            # Determine the series ID for this vote
            if series_by == 'voting_set':
                rid = v['vote_round_id'][0] if v['vote_round_id'] else False
                vs_ids = round_to_voting_sets.get(rid, []) if rid else []
                for vs_id in vs_ids:
                    if pid not in recipient_data:
                        recipient_data[pid] = {'id': pid, 'name': pname, 'votes': {}, 'total': 0}
                    recipient_data[pid]['votes'][vs_id] = recipient_data[pid]['votes'].get(vs_id, 0) + 1
                    recipient_data[pid]['total'] += 1
                    if vs_id not in series_ids_in_data:
                        series_ids_in_data.add(vs_id)
            elif series_by == 'category':
                sid = v['award_category_id'][0] if v['award_category_id'] else False
                if sid:
                    if pid not in recipient_data:
                        recipient_data[pid] = {'id': pid, 'name': pname, 'votes': {}, 'total': 0}
                    recipient_data[pid]['votes'][sid] = recipient_data[pid]['votes'].get(sid, 0) + 1
                    recipient_data[pid]['total'] += 1
                    if sid not in series_ids_in_data:
                        series_ids_in_data.add(sid)
            elif series_by == 'sub_category':
                sid = v['award_sub_category_id'][0] if v['award_sub_category_id'] else False
                if sid:
                    if pid not in recipient_data:
                        recipient_data[pid] = {'id': pid, 'name': pname, 'votes': {}, 'total': 0}
                    recipient_data[pid]['votes'][sid] = recipient_data[pid]['votes'].get(sid, 0) + 1
                    recipient_data[pid]['total'] += 1
                    if sid not in series_ids_in_data:
                        series_ids_in_data.add(sid)
            else:  # 'round'
                sid = v['vote_round_id'][0] if v['vote_round_id'] else False
                if sid:
                    if pid not in recipient_data:
                        recipient_data[pid] = {'id': pid, 'name': pname, 'votes': {}, 'total': 0}
                    recipient_data[pid]['votes'][sid] = recipient_data[pid]['votes'].get(sid, 0) + 1
                    recipient_data[pid]['total'] += 1
                    if sid not in series_ids_in_data:
                        series_ids_in_data.add(sid)

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

            certs = self.env['aps.student.certificate'].search_read(
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
    def get_vote_details(self, filters=None):
        """Return individual vote records for drill-down on a chart bar click.

        Args:
            filters: dict with keys including recipient_id and round_id for the drill-down.

        Returns:
            list of dicts with keys: id, recipient_name, voter_name, round_name,
            category_name, submitted_date, state, comment
        """
        filters = filters or {}
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
        if filters.get('recipient_ids'):
            domain.append(('recipient_partner_id', 'in', filters['recipient_ids']))
        if filters.get('recipient_id'):
            domain.append(('recipient_partner_id', '=', filters['recipient_id']))
        if filters.get('round_id'):
            domain.append(('vote_round_id', '=', filters['round_id']))
        if filters.get('category_id'):
            domain.append(('award_category_id', '=', filters['category_id']))
        if filters.get('sub_category_id'):
            domain.append(('award_sub_category_id', '=', filters['sub_category_id']))

        votes = self.search_read(
            domain,
            ['recipient_partner_id', 'voter_partner_id', 'vote_round_id',
             'award_category_id', 'award_sub_category_id', 'submitted_date', 'state', 'comment'],
        )

        result = []
        for v in votes:
            result.append({
                'id': v['id'],
                'recipient_name': v['recipient_partner_id'][1] if v['recipient_partner_id'] else '',
                'voter_name': v['voter_partner_id'][1] if v['voter_partner_id'] else '',
                'round_name': v['vote_round_id'][1] if v['vote_round_id'] else '',
                'category_name': v['award_category_id'][1] if v['award_category_id'] else '',
                'sub_category_name': v['award_sub_category_id'][1] if v['award_sub_category_id'] else '',
                'submitted_date': v['submitted_date'] or '',
                'state': v['state'] or '',
                'comment': v['comment'] or '',
            })
        return result

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

        certs = self.env['aps.student.certificate'].search_read(
            domain,
            ['event', 'award_category_id', 'date_awarded', 'certificate_template_id'],
        )

        result = []
        for c in certs:
            result.append({
                'id': c['id'],
                'event': c['event'] or '',
                'award_category_name': c['award_category_id'][1] if c['award_category_id'] else '',
                'date_awarded': c['date_awarded'] or '',
                'certificate_template_name': c['certificate_template_id'][1] if c['certificate_template_id'] else '',
            })
        return result
