from odoo import api, models


class WeeklySubmissionResultReport(models.AbstractModel):
    _name = "report.aps_sis.weekly_submission_result_template"
    _description = "Weekly Submission Results Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["aps.weekly.submission.result"].browse(docids).exists()
        return {
            "doc_ids": docs.ids,
            "doc_model": "aps.weekly.submission.result",
            "docs": docs,
            "data": data or {},
        }
