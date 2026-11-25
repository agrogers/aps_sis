from markupsafe import Markup, escape

from odoo import SUPERUSER_ID, _, api


def migrate(cr, version):
    cr.execute("""
        SELECT id, error_message
          FROM aps_exam_paper_import
         WHERE state = 'failed'
    """)
    failed_imports = cr.fetchall()
    cr.execute("""
        UPDATE aps_exam_paper_import
           SET state = 'completed',
               has_issues = CASE WHEN state = 'failed' THEN TRUE ELSE FALSE END
         WHERE state IN ('failed', 'cancelled')
    """)

    imports = api.Environment(cr, SUPERUSER_ID, {})['aps.exam.paper.import']
    for import_id, error_message in failed_imports:
        details = error_message or _('This import was previously marked Failed.')
        body = Markup('<p><strong>%s issue:</strong></p><pre>%s</pre>') % (
            escape(_('Import migration')), escape(details),
        )
        imports.browse(import_id).message_post(body=body, subtype_xmlid='mail.mt_note')
