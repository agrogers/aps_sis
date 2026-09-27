from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    obsolete_xmlids = (
        'aps_sis.menu_apex_enrolment_forecast',
        'aps_sis.action_aps_enrolment_forecast',
        'aps_sis.aps_enrolment_forecast_detail_list',
        'aps_sis.access_aps_enrolment_forecast_manager',
        'aps_sis.access_aps_enrolment_forecast_detail_manager',
    )
    for xmlid in obsolete_xmlids:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.unlink()