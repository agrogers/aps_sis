# Portal views are QWEB templates which means i have to recreate the views that i want
# That's a pain. So I will change the student users to Internal Users for now to be able to see the views.

import re
from markupsafe import Markup
from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal


# ---------------------------------------------------------------------------
# Share-page HTML processing helpers
# ---------------------------------------------------------------------------

def _slugify_heading(text, seen):
    """Turn a heading text into a URL-safe id, deduplicating with *seen*."""
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_-]+', '-', slug).strip('-') or 'heading'
    base = slug
    counter = 1
    while slug in seen:
        slug = f'{base}-{counter}'
        counter += 1
    seen.add(slug)
    return slug


def _process_notes_html(html):
    """Prepare the notes HTML for the public share page.

    1. Adds stable ``id`` attributes to every heading that lacks one so that
       anchor links in the TOC work correctly.
    2. Replaces ``data-embedded="tableOfContent"`` elements (Odoo editor
       embedded blocks) with a simple, readable TOC generated from the
       headings found in the document.

    Returns a :class:`markupsafe.Markup` string (already safe to pass to
    ``t-out`` in a QWeb template).
    """
    if not html:
        return Markup('')

    seen_ids = set()
    heading_list = []   # list of (level, id, text)

    # ── Step 1: stamp IDs onto headings that don't have one ─────────────────

    def _stamp_heading(m):
        tag = m.group(1)          # e.g. 'h2'
        attrs = m.group(2)        # everything between <h2 and >
        content = m.group(3)      # inner HTML
        level = int(tag[1])

        # Extract plain text from inner HTML for the slug / TOC label
        plain_text = re.sub(r'<[^>]+>', '', content).strip()
        if not plain_text:
            return m.group(0)

        # Reuse existing id if present, otherwise create one
        existing_id = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
        if existing_id:
            heading_id = existing_id.group(1)
            seen_ids.add(heading_id)
        else:
            heading_id = _slugify_heading(plain_text, seen_ids)
            attrs = f' id="{heading_id}"' + (' ' + attrs.strip() if attrs.strip() else '')

        heading_list.append((level, heading_id, plain_text))
        return f'<{tag}{attrs}>{content}</{tag}>'

    html = re.sub(
        r'<(h[1-6])([^>]*)>(.*?)</\1>',
        _stamp_heading,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # ── Step 2: build a TOC from the collected headings ──────────────────────

    _INDENT_PX_PER_LEVEL = 16  # pixels of left-padding added per heading depth level

    def _build_toc_html():
        if not heading_list:
            return ''
        min_level = min(lvl for lvl, _, _ in heading_list)
        items = []
        for level, hid, text in heading_list:
            indent = (level - min_level) * _INDENT_PX_PER_LEVEL
            items.append(
                f'<li style="padding-left:{indent}px">'
                f'<a href="#{hid}">{text}</a>'
                f'</li>'
            )
        return (
            '<nav class="aps-share-toc card shadow-sm mb-4">'
            '<div class="card-header bg-light py-2 px-4">'
            '<h5 class="mb-0 aps-card-header-title">Contents</h5>'
            '</div>'
            '<div class="card-body p-3">'
            '<ul class="aps-share-toc-list list-unstyled mb-0">'
            + ''.join(items) +
            '</ul>'
            '</div>'
            '</nav>'
        )

    # ── Step 3: replace each embedded TOC placeholder ────────────────────────

    toc_html = _build_toc_html()

    # Use depth-counting to correctly handle arbitrary nesting of div elements.
    toc_result = []
    pos = 0
    has_embedded_re = re.compile(r"data-embedded=[\"']tableOfContent[\"']", re.IGNORECASE)
    close_re_cache = {}

    while pos < len(html):
        m = has_embedded_re.search(html, pos)
        if not m:
            toc_result.append(html[pos:])
            break

        tag_start = html.rfind('<', pos, m.start())
        if tag_start == -1:
            toc_result.append(html[pos:])
            break

        open_tag_m = re.match(r'<(\w+)([^>]*)>', html[tag_start:], re.IGNORECASE | re.DOTALL)
        if not open_tag_m:
            toc_result.append(html[pos:tag_start + 1])
            pos = tag_start + 1
            continue

        tag_name = open_tag_m.group(1).lower()

        if open_tag_m.group(0).rstrip().endswith('/>'):
            toc_result.append(html[pos:tag_start])
            toc_result.append(toc_html)
            pos = tag_start + len(open_tag_m.group(0))
            continue

        scan_pos = tag_start + len(open_tag_m.group(0))
        depth = 1
        open_re = re.compile(r'<' + re.escape(tag_name) + r'\b', re.IGNORECASE)
        if tag_name not in close_re_cache:
            close_re_cache[tag_name] = re.compile(r'</' + re.escape(tag_name) + r'\s*>', re.IGNORECASE)
        c_re = close_re_cache[tag_name]

        while depth > 0 and scan_pos < len(html):
            next_open = open_re.search(html, scan_pos)
            next_close = c_re.search(html, scan_pos)
            if next_close is None:
                scan_pos = len(html)
                break
            if next_open and next_open.start() < next_close.start():
                depth += 1
                scan_pos = next_open.end()
            else:
                depth -= 1
                if depth == 0:
                    toc_result.append(html[pos:tag_start])
                    toc_result.append(toc_html)
                    pos = next_close.end()
                    break
                scan_pos = next_close.end()
        else:
            toc_result.append(html[pos:tag_start])
            toc_result.append(toc_html)
            pos = len(html)

    html = ''.join(toc_result)

    return Markup(html)


class APSPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'parent_child_count' in counters:
            values['parent_child_count'] = len(self._get_parent_students())
        if 'submission_count' in counters:
            submission_count = http.request.env['aps.resource.submission'].search_count([
                ('task_id.student_id.user_id', '=', http.request.env.user.id)
            ])
            values['submission_count'] = submission_count
        return values

    def _get_parent_students(self, partner=None, env=None):
        env = env or http.request.env
        partner = partner or env.user.partner_id
        relations = env['res.partner.relation.all'].sudo().search([
            ('this_partner_id', '=', partner.id),
            ('active', '=', True),
            ('other_partner_id.is_student', '=', True),
        ])
        guardian_types = {'is guardian of', 'pays for', 'is parent of'}
        child_partner_ids = relations.filtered(
            lambda relation: (relation.type_selection_id.name or '').casefold() in guardian_types
        ).mapped('other_partner_id').ids
        if not child_partner_ids:
            return env['aps.student']
        return env['aps.student'].sudo().search([
            ('partner_id', 'in', child_partner_ids),
            ('active', '=', True),
        ], order='partner_id')

    def _get_child_progress(self, student, env=None):
        env = env or http.request.env
        submissions = env['aps.resource.submission'].sudo().search([
            ('student_id', '=', student.partner_id.id),
            ('submission_active', '=', True),
        ], order='date_assigned desc, id desc')
        today = fields.Date.today()
        scored_submissions = submissions.filtered(
            lambda submission: submission.state in ('submitted', 'complete')
            and submission.score != -0.01
            and submission.out_of_marks > 0
        )

        subject_results = {}
        for submission in scored_submissions:
            subjects = submission.subjects or submission.resource_id.subjects
            for subject in subjects:
                result = subject_results.setdefault(subject.id, {
                    'name': subject.display_name,
                    'total': 0,
                    'count': 0,
                })
                result['total'] += submission.result_percent
                result['count'] += 1
        subject_chart = [{
            'name': result['name'],
            'average': min(100, max(0, round(result['total'] / result['count']))),
            'count': result['count'],
        } for result in subject_results.values()]

        completed = submissions.filtered(lambda submission: submission.state == 'complete')
        overdue = submissions.filtered(
            lambda submission: submission.state == 'assigned'
            and submission.date_due
            and submission.date_due < today
        )
        return {
            'total_tasks': len(submissions),
            'to_submit': len(submissions.filtered(lambda submission: submission.state == 'assigned')),
            'submitted': len(submissions.filtered(lambda submission: submission.state == 'submitted')),
            'completed': len(completed),
            'overdue': len(overdue),
            'average_score': min(100, max(0, round(
                sum(scored_submissions.mapped('result_percent')) / len(scored_submissions)
            ))) if scored_submissions else False,
            'subject_chart': subject_chart,
            'recent_submissions': submissions[:10],
        }

    @http.route('/my/children', type='http', auth='user', website=True)
    def portal_my_children(self, **kw):
        students = self._get_parent_students()
        return http.request.render('aps_sis.portal_my_children', {
            'students': students,
            'page_name': 'children',
        })

    @http.route('/my/children/<int:student_id>', type='http', auth='user', website=True)
    def portal_child_progress(self, student_id, **kw):
        student = self._get_parent_students().filtered(lambda child: child.id == student_id)
        if not student:
            return http.request.not_found()
        student = student[0]
        values = self._get_child_progress(student)
        values.update({
            'student': student,
            'page_name': 'child_progress',
        })
        return http.request.render('aps_sis.portal_child_progress', values)

    @http.route(['/my/submissions', '/my/submissions/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_submissions(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        APS = http.request.env['aps.resource.submission']
        
        domain = [('task_id.student_id.user_id', '=', http.request.env.user.id)]
        submission_count = APS.search_count(domain)
        pager = http.request.website.pager(
            url='/my/submissions',
            total=submission_count,
            page=page,
            step=self._items_per_page,
        )
        submissions = APS.search(domain, limit=self._items_per_page, offset=pager['offset'])
        values.update({
            'submissions': submissions,
            'page_name': 'submission',
            'pager': pager,
            'default_url': '/my/submissions',
        })
        return http.request.render('aps_sis.portal_my_submissions', values)

    @http.route('/resource/share/<string:token>', type='http', auth='public', website=True)
    def resource_share(self, token, **kw):
        resource = http.request.env['aps.resources'].sudo().search(
            [('share_token', '=', token)], limit=1
        )
        if not resource:
            return http.request.not_found()
        notes_html = _process_notes_html(resource.notes or '')
        return http.request.render('aps_sis.resource_share_page', {
            'resource': resource,
            'notes_html': notes_html,
        })
