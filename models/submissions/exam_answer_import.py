import base64
import hashlib
import json
import logging
import math
import re
import time
from html import escape
from io import BytesIO

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

_EXAM_ANSWER_IMPORT_PROCESSOR = 'exam_submission_answers'
_EXAM_ANSWER_IMPORT_PROMPT = 'Exam Submission Answer Import'


class APSResourceSubmissionExamAnswerImport(models.Model):
    _inherit = 'aps.resource.submission'

    can_import_student_answers = fields.Boolean(
        compute='_compute_can_import_student_answers',
    )

    @api.depends('resource_id.type_id.name')
    def _compute_can_import_student_answers(self):
        allowed_types = {'Past Paper', 'Exam'}
        for submission in self:
            submission.can_import_student_answers = (
                submission.resource_id.type_id.name in allowed_types
            )

    def action_import_student_answers(self):
        self.ensure_one()
        if not self._get_current_faculty():
            raise AccessError(_('Only faculty can import exam answers.'))
        if not self.can_import_student_answers:
            raise UserError(_('Student answers can only be imported for Past Paper or Exam resources.'))

        answer_html = self.answer or ''
        fingerprint = hashlib.sha256(answer_html.encode('utf-8')).hexdigest()
        image_tags = re.findall(r'<img\b[^>]*>', answer_html, re.IGNORECASE)
        imports = self.env['aps.exam.paper.import'].search([
            ('resource_id', '=', self.resource_id.id),
            ('state', '=', 'completed'),
        ])
        importer = imports if len(imports) == 1 else self.env['aps.exam.paper.import']
        preflight_error = False
        model = False

        if len(imports) != 1:
            preflight_error = _(
                'Expected one completed exam import for this resource, but found %s.'
            ) % len(imports)
        elif not image_tags:
            preflight_error = _('No embedded images were found in the Answer HTML.')
        else:
            try:
                model = self._get_exam_answer_import_model(importer)
            except UserError as error:
                preflight_error = str(error)

        if not preflight_error:
            active_run = self.env['aps.ai.run'].sudo().search([
                ('submission_id', '=', self.id),
                ('import_id', '=', importer.id),
                ('processor_key', '=', _EXAM_ANSWER_IMPORT_PROCESSOR),
                ('fingerprint', '=', fingerprint),
                ('state', 'in', ('queued', 'running')),
            ], limit=1)
            if active_run:
                return self._exam_answer_import_run_notification(active_run)

        run_values = {
            'submission_id': self.id,
            'import_id': importer.id if importer else False,
            'requested_by_id': self.env.user.id,
            'fingerprint': fingerprint,
            'processor_key': _EXAM_ANSWER_IMPORT_PROCESSOR,
            'ai_model_id': model.id if model else False,
            'state': 'failed' if preflight_error else 'queued',
            'status_message': preflight_error or _('Queued student answer import...'),
            'error_message': preflight_error or False,
            'exam_answer_import_result_log': preflight_error or False,
            'result_message': _('The student answer import could not be started.')
            if preflight_error else False,
            'finished_at': fields.Datetime.now() if preflight_error else False,
        }
        run = self.env['aps.ai.run'].sudo().create(run_values)
        if not preflight_error:
            run._queue_background_processing()
        return self._exam_answer_import_run_notification(run)

    @staticmethod
    def _exam_answer_import_run_notification(run):
        return {
            'type': 'ir.actions.client',
            'tag': 'aps_ai_run_progress',
            'params': {
                'runId': run.id,
                'runModel': 'aps.ai.run',
                'title': _('Import Student Answers'),
            },
        }

    @api.model
    def _get_exam_answer_import_model(self, importer):
        configured_model = (
            importer.single_page_ai_model_id
            or importer.ai_model_id
            or importer.ocr_ai_model_id
        )
        if configured_model:
            if (
                not configured_model.enabled
                or not configured_model.provider_id.enabled
                or not configured_model.supports_vision
            ):
                raise UserError(_(
                    'The exam import must use an enabled, vision-capable AI model for answer detection.'
                ))
            return configured_model

        candidates = self.env['aps.ai.model']._get_generation_candidates(
            resource=importer.resource_id,
            require_vision=True,
        )
        if not candidates:
            raise UserError(_('No enabled vision-capable AI model is available for answer detection.'))
        return candidates[:1]

    def _prepare_exam_answer_image(self, image_tag):
        image_bytes, _mime_type = self._get_submission_image_bytes(
            image_tag,
            purpose='exam answer import',
        )
        try:
            from PIL import Image, ImageOps
        except ImportError as error:
            raise UserError(_('Image cropping requires the Pillow package.')) from error

        try:
            with Image.open(BytesIO(image_bytes)) as source:
                normalized = ImageOps.exif_transpose(source).convert('RGB')
                try:
                    width, height = normalized.size
                    output = BytesIO()
                    normalized.save(output, format='PNG')
                    normalized_bytes = output.getvalue()
                finally:
                    normalized.close()
        except (Image.DecompressionBombError, OSError, ValueError) as error:
            raise UserError(_('An embedded answer image could not be decoded: %s') % error) from error

        return {
            'bytes': normalized_bytes,
            'data_uri': 'data:image/png;base64,%s' % base64.b64encode(normalized_bytes).decode('ascii'),
            'width': width,
            'height': height,
        }

    def _get_exam_answer_import_prompt(self):
        prompt = self.env['ai_prompts'].sudo().search([
            ('prompt_name', '=', _EXAM_ANSWER_IMPORT_PROMPT),
        ], limit=1)
        if not prompt or not prompt.enabled or not (prompt.prompt or '').strip():
            raise UserError(_(
                'The exam answer import prompt "%s" must exist, be enabled, and contain prompt text.'
            ) % _EXAM_ANSWER_IMPORT_PROMPT)
        return prompt

    def _detect_exam_answer_regions(self, model, prompt, image):
        user_text = _(
            'Analyze this student exam scan. The image is exactly %(width)s by %(height)s pixels. '
            'Detect every visible student response and report each answer bounding rectangle in pixel '
            'coordinates relative to this exact image. Include all printed page numbers visible in the '
            'image, even if a page has no detected answer.'
        ) % {
            'width': image['width'],
            'height': image['height'],
        }
        result = model._execute_logged_router_call(
            {
                'model': model.model_key,
                'messages': [
                    {'role': 'system', 'content': prompt.prompt},
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': user_text},
                            {'type': 'image_url', 'image_url': {'url': image['data_uri']}},
                        ],
                    },
                ],
                'temperature': 0,
                'max_completion_tokens': min(model.max_completion_tokens or 2400, 4000),
                'response_format': {'type': 'json_object'},
            },
            request_type='exam_submission_answer_regions',
            related_record=self,
            prompt_names_used=[_EXAM_ANSWER_IMPORT_PROMPT],
        )
        raw_content = model._extract_message_content(result['response_json'])
        response = model._parse_router_response_json(raw_content)
        if not isinstance(response, dict) or not isinstance(response.get('answers'), list):
            raise ValidationError(_('The vision model did not return an answers list.'))
        if not isinstance(response.get('pages_detected', []), list):
            raise ValidationError(_('The vision model returned an invalid pages_detected value.'))
        if response.get('coordinate_system') != 'pixels':
            raise ValidationError(_('The vision model must return pixel coordinates.'))
        if (
            response.get('image_width') not in (None, image['width'])
            or response.get('image_height') not in (None, image['height'])
        ):
            raise ValidationError(_('The vision model returned coordinates for a different image size.'))
        return response, raw_content, result

    @staticmethod
    def _normalise_exam_page_number(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return False
        value = str(value).strip()
        if not value:
            return False
        if value.isdecimal():
            return str(int(value))
        return re.sub(r'\s+', '', value).casefold()

    @staticmethod
    def _normalise_exam_identifier(value):
        return re.sub(r'[^a-z0-9]+', '', (value or '').casefold())

    @staticmethod
    def _exam_section_parent_identifier_context(section, importer):
        context = importer._empty_identifier_context()
        path = (section.source_key or '').split('/')
        parent_path = path[:-1]
        if not parent_path:
            return context

        root_segment = parent_path[0]
        root_label = section.root_key or (
            'Q%s' % root_segment if root_segment.isdecimal() else root_segment
        )
        context.update({
            'root_label': root_label,
            'root_segment': root_segment,
            'path': [root_segment],
        })
        if len(parent_path) > 1:
            part_segment = parent_path[1]
            context.update({
                'part_label': '%s%s' % (root_label, part_segment),
                'part_segment': part_segment,
                'path': parent_path[:2],
                'hierarchy_level': 2,
            })
        return context

    def _exam_section_matches_answer_identifier(
        self, importer, section, regions, question_identifier, identifier_rules, filename,
    ):
        requested = self._normalise_exam_identifier(question_identifier)
        aliases = [section.display_label, section.source_key]
        aliases.extend(
            region.get('detection_label')
            for region in regions
            if isinstance(region, dict)
        )
        if any(self._normalise_exam_identifier(alias) == requested for alias in aliases if alias):
            return True

        hierarchy_level = section.hierarchy_level
        kind = 'subpart' if hierarchy_level == 3 else 'part' if hierarchy_level == 2 else 'root'
        resolved = importer._resolve_rule_identifier(
            question_identifier,
            self._exam_section_parent_identifier_context(section, importer),
            identifier_rules,
            'question',
            filename,
            kind,
        )
        return bool(resolved and resolved.get('source_key') == section.source_key)

    def _find_exam_question_section(
        self, importer, printed_page_number, question_identifier, identifier_rules,
    ):
        normalized_page = self._normalise_exam_page_number(printed_page_number)
        pages = importer.page_ids.filtered(
            lambda page: page.document_type == 'question'
            and self._normalise_exam_page_number(page.printed_page_number) == normalized_page
        )
        if not pages:
            return self.env['aps.exam.paper.section'], 'page_not_found', False
        if len(pages) != 1:
            return self.env['aps.exam.paper.section'], 'ambiguous_page', False

        page = pages[0]
        filename = ' '.join((
            importer.name or '',
            importer.question_attachment_id.name or '',
        )).casefold()
        candidates = self.env['aps.exam.paper.section']
        for section in importer.section_ids.filtered('resource_id'):
            regions = [
                region for region in (section.question_regions or [])
                if isinstance(region, dict)
                and str(region.get('page_number') or '') == str(page.page_number)
            ]
            if regions and self._exam_section_matches_answer_identifier(
                importer,
                section,
                regions,
                question_identifier,
                identifier_rules,
                filename,
            ):
                candidates |= section

        if not candidates:
            return candidates, 'question_not_found', page
        if len(candidates) != 1:
            return candidates, 'ambiguous_question', page
        return candidates, False, page

    def _exam_answer_submission_belongs_to_source(self, submission):
        self.ensure_one()
        parent = submission.parent_submission_id
        visited = set()
        while parent:
            if parent == self:
                return True
            if parent.id in visited:
                return False
            visited.add(parent.id)
            parent = parent.parent_submission_id
        return False

    def _find_exam_question_submission(self, section):
        self.ensure_one()
        candidates = self.env['aps.resource.submission'].sudo().search([
            ('id', '!=', self.id),
            ('task_id.resource_id', '=', section.resource_id.id),
            ('task_id.student_id', '=', self.student_id.id),
        ])
        source_tree = candidates.filtered(
            self._exam_answer_submission_belongs_to_source
        )
        if source_tree:
            candidates = source_tree
        elif candidates.filtered('parent_submission_id'):
            candidates = self.env['aps.resource.submission']
        else:
            same_label = candidates.filtered(
                lambda submission: submission.submission_label == self.submission_label
            )
            if same_label:
                candidates = same_label

        if not candidates:
            return candidates, 'submission_not_found'
        if len(candidates) != 1:
            return candidates, 'ambiguous_submission'
        return candidates, False

    @staticmethod
    def _validate_exam_answer_bounds(detection, image):
        if not isinstance(detection, dict):
            raise ValidationError(_('An answer detection must be an object.'))
        bbox = detection.get('bbox')
        if not isinstance(bbox, dict):
            raise ValidationError(_('An answer detection has no bounding rectangle.'))
        try:
            values = {}
            for key in ('x1', 'y1', 'x2', 'y2'):
                value = bbox.get(key)
                if isinstance(value, bool):
                    raise ValueError
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError
                values[key] = round(value)
        except (TypeError, ValueError):
            raise ValidationError(_('Bounding rectangle coordinates must be finite numbers.'))
        if not (
            0 <= values['x1'] < values['x2'] <= image['width']
            and 0 <= values['y1'] < values['y2'] <= image['height']
        ):
            raise ValidationError(_('The answer bounding rectangle is outside the image or empty.'))
        return values

    @staticmethod
    def _exam_answer_import_result_line(result):
        labels = {
            'applied': _('Imported'),
            'image_failed': _('Image could not be processed'),
            'answer_invalid': _('Invalid answer detection'),
            'page_not_found': _('Printed page not found'),
            'ambiguous_page': _('Printed page is ambiguous'),
            'question_not_found': _('Question was not matched'),
            'ambiguous_question': _('Question match is ambiguous'),
            'invalid_bounds': _('Bounding rectangle is invalid'),
            'submission_not_found': _('Student submission was not found'),
            'ambiguous_submission': _('Student submission is ambiguous'),
            'crop_failed': _('Crop could not be added'),
            'not_detected': _('No answer region was detected'),
            'no_sections': _('No imported question resources exist on this page'),
            'no_answers': _('No answer regions were returned'),
        }
        source = _('Image %s') % result.get('image_number', '?')
        page = result.get('page_number') or _('unknown page')
        question = result.get('question_identifier') or _('unknown question')
        label = labels.get(result.get('status'), result.get('status') or _('Unknown'))
        detail = result.get('detail') or ''
        return '%s - page %s - %s: %s%s' % (
            source,
            page,
            question,
            label,
            (' - %s' % detail) if detail else '',
        )

    @classmethod
    def _format_exam_answer_import_log(cls, results):
        return '\n'.join(
            [cls._exam_answer_import_result_line(result) for result in results]
        ) or _('No answer regions were returned.')

    def _process_exam_answer_detection(
        self, run, importer, image, image_number, answer_number, detection, identifier_rules,
    ):
        result = {
            'image_number': image_number,
            'status': 'answer_invalid',
            'question_identifier': False,
            'page_number': False,
        }
        if not isinstance(detection, dict):
            result['detail'] = _('Detection is not an object.')
            return result, False

        page_number = detection.get('printed_page_number')
        question_identifier = detection.get('question_identifier')
        result.update({
            'page_number': str(page_number or ''),
            'question_identifier': str(question_identifier or ''),
        })
        if not self._normalise_exam_page_number(page_number) or not (
            isinstance(question_identifier, str) and question_identifier.strip()
        ):
            result['detail'] = _('Printed page number and question identifier are required.')
            return result, False

        sections, mapping_error, page = self._find_exam_question_section(
            importer,
            page_number,
            question_identifier.strip(),
            identifier_rules,
        )
        if mapping_error:
            result['status'] = mapping_error
            result['detail'] = _('No unique imported question matches this page and identifier.')
            return result, False

        section = sections[0]
        result['section_id'] = section.id
        result['page_number'] = str(page.printed_page_number or page_number)
        try:
            bounds = self._validate_exam_answer_bounds(detection, image)
        except ValidationError as error:
            result['status'] = 'invalid_bounds'
            result['detail'] = str(error)
            return result, section

        targets, target_error = self._find_exam_question_submission(section)
        if target_error:
            result['status'] = target_error
            result['detail'] = _('Question resource: %s') % section.resource_id.display_name
            return result, section

        target = targets[0].with_user(self.env.uid)
        attachment = self.env['ir.attachment']
        try:
            from PIL import Image
        except ImportError as error:
            result['status'] = 'crop_failed'
            result['detail'] = _('Image cropping requires the Pillow package.')
            return result, section

        try:
            with self.env.cr.savepoint():
                with Image.open(BytesIO(image['bytes'])) as source:
                    crop = source.crop((
                        bounds['x1'], bounds['y1'], bounds['x2'], bounds['y2'],
                    ))
                    try:
                        output = BytesIO()
                        crop.save(output, format='PNG')
                        crop_bytes = output.getvalue()
                    finally:
                        crop.close()

                attachment = self.env['ir.attachment'].create({
                    'name': 'student-answer-%s-%s-%s.png' % (
                        run.id, image_number, answer_number,
                    ),
                    'type': 'binary',
                    'datas': base64.b64encode(crop_bytes).decode('ascii'),
                    'mimetype': 'image/png',
                    'res_model': 'aps.resource.submission',
                    'res_id': target.id,
                    'description': 'aps_exam_submission_answer_import:%s:%s:%s' % (
                        run.id, section.id, answer_number,
                    ),
                })
                image_html = (
                    '<p><img src="/web/image/%s" class="img-fluid" '
                    'alt="%s"></img></p>'
                ) % (attachment.id, escape(section.display_label or question_identifier))
                answer_html = '%s%s' % ((target.answer or ''), image_html)
                target.write({
                    'answer': answer_html,
                    'state': 'submitted',
                    'auto_score': target.auto_score,
                })
        except Exception as error:
            _logger.exception(
                'Failed to crop or apply exam answer image %s, answer %s, submission %s',
                image_number, answer_number, target.id,
            )
            result['status'] = 'crop_failed'
            result['detail'] = str(error)
            return result, section

        result['status'] = 'applied'
        result['detail'] = _('Added to %s.') % target.display_name
        return result, section

    def _process_exam_submission_answer_import(self, run, started_perf):
        self.ensure_one()
        run.ensure_one()
        importer = run.import_id
        if not importer or importer.state != 'completed':
            raise UserError(_('The completed exam import for this submission is no longer available.'))

        model = run.ai_model_id or self._get_exam_answer_import_model(importer)
        prompt = self._get_exam_answer_import_prompt()
        self.invalidate_recordset(['answer'])
        if self._get_exam_answer_import_fingerprint() != run.fingerprint:
            run._write_progress({
                'state': 'skipped',
                'status_message': _('Skipped because the Answer HTML changed.'),
                'result_message': _('No images were processed because the source answer changed.'),
                'exam_answer_import_result_log': _('Skipped because the Answer HTML changed.'),
                'finished_at': fields.Datetime.now(),
            })
            return

        image_tags = re.findall(r'<img\b[^>]*>', self.answer or '', re.IGNORECASE)
        results = []
        raw_responses = []
        pages_detected = set()
        sections_detected_by_page = {}
        identifier_rules = self.env['aps.exam.paper.question.identifier'].search(
            [('active', '=', True)],
            order='sequence, id',
        )
        image_count = len(image_tags)
        ai_responses = 0
        applied_count = 0
        prompt_tokens = 0
        completion_tokens = 0
        estimated_cost = 0.0
        failure_messages = []

        for image_number, image_tag in enumerate(image_tags, 1):
            self.invalidate_recordset(['answer'])
            if self._get_exam_answer_import_fingerprint() != run.fingerprint:
                run._write_progress({
                    'state': 'skipped',
                    'status_message': _('Stopped because the Answer HTML changed.'),
                    'result_message': _('Processing stopped after the source answer changed.'),
                    'exam_answer_import_result_log': self._format_exam_answer_import_log(results),
                    'finished_at': fields.Datetime.now(),
                    'duration_ms': int((time.perf_counter() - started_perf) * 1000),
                })
                return

            try:
                image = self._prepare_exam_answer_image(image_tag)
            except Exception as error:
                _logger.exception(
                    'Could not prepare embedded exam answer image %s for submission %s',
                    image_number, self.id,
                )
                results.append({
                    'image_number': image_number,
                    'status': 'image_failed',
                    'detail': str(error),
                })
                failure_messages.append(str(error))
                run._commit_background_work()
                run._write_progress({
                    'status_message': _('Could not read answer image %s of %s.') % (
                        image_number, image_count,
                    ),
                    'exam_answer_import_result_log': self._format_exam_answer_import_log(results),
                })
                continue

            try:
                response, raw_content, call_result = self._detect_exam_answer_regions(
                    model, prompt, image,
                )
            except Exception as error:
                _logger.exception(
                    'Vision answer detection failed for image %s of submission %s',
                    image_number, self.id,
                )
                results.append({
                    'image_number': image_number,
                    'status': 'image_failed',
                    'detail': str(error),
                })
                failure_messages.append(str(error))
                run._commit_background_work()
                run._write_progress({
                    'status_message': _('Could not analyze answer image %s of %s.') % (
                        image_number, image_count,
                    ),
                    'exam_answer_import_result_log': self._format_exam_answer_import_log(results),
                })
                continue

            ai_responses += 1
            raw_responses.append({
                'image_number': image_number,
                'response': raw_content,
            })
            prompt_tokens += call_result.get('prompt_tokens') or 0
            completion_tokens += call_result.get('completion_tokens') or 0
            estimated_cost += call_result.get('estimated_cost') or 0.0

            for detected_page in response.get('pages_detected') or []:
                normalized = self._normalise_exam_page_number(detected_page)
                if normalized:
                    pages_detected.add(normalized)
            for detection in response['answers']:
                if isinstance(detection, dict):
                    normalized = self._normalise_exam_page_number(
                        detection.get('printed_page_number'),
                    )
                    if normalized:
                        pages_detected.add(normalized)

            for answer_number, detection in enumerate(response['answers'], 1):
                result, section = self._process_exam_answer_detection(
                    run,
                    importer,
                    image,
                    image_number,
                    answer_number,
                    detection,
                    identifier_rules,
                )
                results.append(result)
                if section:
                    page_key = self._normalise_exam_page_number(result.get('page_number'))
                    sections_detected_by_page.setdefault(page_key, set()).add(section.id)
                if result['status'] == 'applied':
                    applied_count += 1
                elif result.get('detail'):
                    failure_messages.append(result['detail'])

                run._commit_background_work()
                run._write_progress({
                    'status_message': _('Processed answer %s from image %s of %s.') % (
                        answer_number, image_number, image_count,
                    ),
                    'exam_answer_import_result_log': self._format_exam_answer_import_log(results),
                })

            if not response['answers']:
                results.append({
                    'image_number': image_number,
                    'status': 'no_answers',
                    'detail': _('No answer regions were returned for this image.'),
                })
                run._commit_background_work()
                run._write_progress({
                    'exam_answer_import_result_log': self._format_exam_answer_import_log(results),
                })

        for normalized_page in sorted(pages_detected):
            page_matches = importer.page_ids.filtered(
                lambda page: page.document_type == 'question'
                and self._normalise_exam_page_number(page.printed_page_number) == normalized_page
            )
            page_label = page_matches[:1].printed_page_number if page_matches else normalized_page
            if not page_matches:
                results.append({
                    'image_number': 0,
                    'page_number': page_label,
                    'status': 'page_not_found',
                    'detail': _('No question-paper page in the import has this printed page number.'),
                })
                continue
            if len(page_matches) != 1:
                results.append({
                    'image_number': 0,
                    'page_number': page_label,
                    'status': 'ambiguous_page',
                    'detail': _('More than one question-paper page has this printed page number.'),
                })
                continue

            physical_page = page_matches.page_number
            page_sections = importer.section_ids.filtered(
                lambda section: section.resource_id and any(
                    isinstance(region, dict)
                    and str(region.get('page_number') or '') == str(physical_page)
                    for region in (section.question_regions or [])
                )
            )
            if not page_sections:
                results.append({
                    'image_number': 0,
                    'page_number': page_label,
                    'status': 'no_sections',
                    'detail': _('No linked question resources are mapped to this page.'),
                })
            for section in page_sections:
                if section.id not in sections_detected_by_page.get(normalized_page, set()):
                    results.append({
                        'image_number': 0,
                        'page_number': page_label,
                        'question_identifier': section.display_label,
                        'status': 'not_detected',
                        'detail': _('The scanned page was detected, but no answer region was returned for this question.'),
                    })

        result_log = self._format_exam_answer_import_log(results)
        response_preview = json.dumps({
            'vision_responses': raw_responses,
            'answer_import_results': results,
        }, ensure_ascii=False, indent=2)
        issue_count = len(results) - applied_count
        summary = _('Imported %(imported)s answer(s); %(issues)s result(s) need review.') % {
            'imported': applied_count,
            'issues': issue_count,
        }
        if ai_responses:
            state = 'completed'
            status_message = _('Completed with issues.') if issue_count else _('Completed.')
            error_message = False
        else:
            state = 'failed'
            status_message = _('No image was analyzed successfully.')
            error_message = '\n'.join(failure_messages) or _(
                'No image was analyzed successfully.'
            )
        run._write_progress({
            'state': state,
            'status_message': status_message,
            'result_message': summary,
            'error_message': error_message,
            'exam_answer_import_result_log': result_log,
            'response_preview': response_preview,
            'ai_model_id': model.id,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'estimated_cost': estimated_cost,
            'finished_at': fields.Datetime.now(),
            'duration_ms': int((time.perf_counter() - started_perf) * 1000),
        })

    def _get_exam_answer_import_fingerprint(self):
        self.ensure_one()
        return hashlib.sha256((self.answer or '').encode('utf-8')).hexdigest()


class APSAIExamSubmissionAnswerImportRun(models.Model):
    _inherit = 'aps.ai.run'

    processor_key = fields.Selection(selection_add=[
        (_EXAM_ANSWER_IMPORT_PROCESSOR, 'Exam Submission Answer Import'),
    ], ondelete={
        _EXAM_ANSWER_IMPORT_PROCESSOR: 'set default',
    })
    exam_answer_import_result_log = fields.Text(
        string='Student Answer Import Results',
        readonly=True,
    )

    def _get_processor_display_name(self):
        if self.processor_key == _EXAM_ANSWER_IMPORT_PROCESSOR:
            return self.submission_id.display_name or _('Exam Submission')
        return super()._get_processor_display_name()

    def _serialize_status(self):
        status = super()._serialize_status()
        if self.processor_key == _EXAM_ANSWER_IMPORT_PROCESSOR:
            status['result_details'] = self.exam_answer_import_result_log or ''
        return status

    def _on_ai_queue_run_start(self):
        if self.processor_key != _EXAM_ANSWER_IMPORT_PROCESSOR:
            return super()._on_ai_queue_run_start()
        self.ensure_one()
        submission = self.submission_id
        if not submission.exists():
            self.write({
                'state': 'failed',
                'status_message': _('The source submission no longer exists.'),
                'error_message': _('The source submission for this run no longer exists.'),
                'exam_answer_import_result_log': _('The source submission for this run no longer exists.'),
                'finished_at': fields.Datetime.now(),
            })
            return
        submission.invalidate_recordset(['answer'])
        if submission._get_exam_answer_import_fingerprint() != self.fingerprint:
            self.write({
                'state': 'skipped',
                'status_message': _('Skipped because the Answer HTML changed.'),
                'result_message': _('No images were processed because the source answer changed.'),
                'exam_answer_import_result_log': _('Skipped because the Answer HTML changed.'),
                'finished_at': fields.Datetime.now(),
            })

    def _process_specialised_background(self, started_perf):
        if self.processor_key != _EXAM_ANSWER_IMPORT_PROCESSOR:
            return super()._process_specialised_background(started_perf)
        self.ensure_one()
        if self.state not in ('queued', 'running'):
            return
        submission = self.submission_id.with_user(self.requested_by_id)
        submission._process_exam_submission_answer_import(self, started_perf)
