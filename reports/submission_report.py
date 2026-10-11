from odoo import models, api
import logging
from lxml import html

_logger = logging.getLogger(__name__)


class SubmissionReport(models.AbstractModel):
    _name = 'report.aps_sis.report_submission_template'
    _description = 'Submission Report'

    @staticmethod
    def _remove_images(content):
        if not content:
            return content
        root = html.fragment_fromstring(content, create_parent='div')
        for image in root.xpath('.//img'):
            image.drop_tree()
        return (root.text or '') + ''.join(
            html.tostring(child, encoding='unicode') for child in root
        )

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
        
        data = data or {}
        report_order = data.get('report_order', 'resource_student')
        include_images = data.get('include_images', True)
        grouped_submissions = {}
        submission_content = {}
        for submission in docs:
            resource = submission.resource_id
            student = submission.student_id
            if report_order == 'student_resource':
                primary_id = student.id or 0
                primary_name = student.display_name or student.name or ''
            else:
                primary_id = resource.id or 0
                primary_name = resource.display_name or resource.name or ''

            primary_group = grouped_submissions.setdefault(primary_id, {
                'name': primary_name,
                'resources': {},
            })
            resource_id = resource.id or 0
            resource_group = primary_group['resources'].setdefault(resource_id, {
                'short_name': resource.name or '',
                'long_name': resource.display_name or resource.name or '',
                'submissions': [],
            })
            resource_group['submissions'].append(submission)

            model_answer = submission.model_answer or ''
            answer = submission.answer or ''
            feedback = submission.feedback or ''
            if not include_images:
                model_answer = self._remove_images(model_answer)
                answer = self._remove_images(answer)
                feedback = self._remove_images(feedback)
            submission_content[submission.id] = {
                'model_answer': model_answer,
                'answer': answer,
                'feedback': feedback,
            }

        sorted_groups = []
        for primary_group in grouped_submissions.values():
            primary_group['resources'] = sorted(
                primary_group['resources'].values(),
                key=lambda item: (item['long_name'] or '').casefold(),
            )
            for resource_group in primary_group['resources']:
                resource_group['submissions'].sort(
                    key=lambda submission: (
                        submission.student_id.display_name or '',
                        submission.id,
                    )
                )
            sorted_groups.append(primary_group)
        sorted_groups.sort(key=lambda item: (item['name'] or '').casefold())
        
        result = {
            'doc_ids': docids,
            'doc_model': 'aps.resource.submission',
            'docs': docs,  # Keep original docs for backward compatibility
            'grouped_submissions': sorted_groups,
            'submission_content': submission_content,
            'report_order': report_order,
            'data': data,
        }
        _logger.info("Returning result with %s groups", len(sorted_groups))
        return result
