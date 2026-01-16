from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class SubmissionReport(models.AbstractModel):
    _name = 'report.aps_sis.report_submission_template'
    _description = 'Submission Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Prepare report values including docs and data options"""
        _logger.info("=== REPORT _get_report_values CALLED ===")
        _logger.info("docids: %s", docids)
        _logger.info("data: %s", data)
        
        # If docids is empty, try to get from data
        if not docids and data and 'submission_ids' in data:
            docids = data['submission_ids']
            _logger.info("Using submission_ids from data: %s", docids)
        
        if not docids:
            _logger.warning("No docids provided to report!")
            return {}
            
        docs = self.env['aps.resource.submission'].browse(docids)
        _logger.info("docs found: %s", len(docs))
        
        # Group submissions by resource
        grouped_submissions = {}
        for submission in docs:
            resource_name = submission.resource_id.display_name
            if resource_name not in grouped_submissions:
                grouped_submissions[resource_name] = []
            grouped_submissions[resource_name].append(submission)
        
        # Sort groups by resource name
        sorted_groups = sorted(grouped_submissions.items())
        
        result = {
            'doc_ids': docids,
            'doc_model': 'aps.resource.submission',
            'docs': docs,  # Keep original docs for backward compatibility
            'grouped_submissions': sorted_groups,  # List of (resource_name, submissions) tuples
            'data': data or {},
        }
        _logger.info("Returning result with %s groups", len(sorted_groups))
        return result
