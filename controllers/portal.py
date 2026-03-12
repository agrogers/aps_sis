# Portal views are QWEB templates which means i have to recreate the views that i want
# That's a pain. So I will change the student users to Internal Users for now to be able to see the views.

from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal


class APSPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'submission_count' in counters:
            submission_count = http.request.env['aps.resource.submission'].search_count([
                ('task_id.student_id.user_id', '=', http.request.env.user.id)
            ])
            values['submission_count'] = submission_count
        return values

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
        return http.request.render('aps_sis.resource_share_page', {'resource': resource})

