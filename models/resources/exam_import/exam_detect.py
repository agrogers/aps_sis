"""Detection of question sections from stored page-analysis responses."""
import logging
import re
from typing import Any

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class APSExamPaperImportDetect(models.Model):
    _inherit = 'aps.exam.paper.import'

    def action_detect_sections(self):
        """Build detected sections from the stored page-analysis responses."""
        self.ensure_one()
        summary = self._build_sections_from_page_analysis()
        self.write({'state': 'analysing', 'progress': 60})
        # Re-open the form so the sections list and state refresh without a
        # manual reload. (A notification with a `next` action is not reliably
        # supported, so the form action is returned directly.)
        return self._open_form()

    def _build_sections_from_page_analysis(self):
        """Resolve raw labels detected on question pages into sections."""
        self.ensure_one()
        question_detections = self._collect_page_detections('question')
        if not question_detections:
            raise UserError(_('No completed question-paper page analyses are available.'))

        resolved = {}
        for item in question_detections:
            page = item['page']
            detection = item['detection']
            key = self._normalise_key(item['label'])
            section = resolved.setdefault(key, {
                'import_id': self.id,
                'sequence': len(resolved) + 1,
                'source_key': key,
                'display_label': item['label'],
                'root_key': item['root_label'],
                'hierarchy_level': self._label_hierarchy_level(item['label']),
                'maximum_mark': False,
                'question_summary': '',
                'include_resource': True,
                'include_parent_question': False,
                'ai_include_parent_question': None,
                'question_pages': [],
                'question_regions': [],
                'answer_pages': [],
                'answer_regions': [],
                'match_confidence': 0.0,
            })
            section['question_pages'].append(page.page_number)
            section['question_regions'].extend(self._regions_with_page_data(
                detection.get('regions') or [], page, item['label'], len(section['question_regions']),
                item.get('analysis') or {},
            ))
            if detection.get('include_parent_question') is not None:
                section['include_parent_question'] = detection['include_parent_question']
                section['ai_include_parent_question'] = detection['include_parent_question']
            if detection.get('question_summary'):
                section['question_summary'] = detection['question_summary']
            if detection.get('visible_mark') is not None and section['maximum_mark'] is False:
                section['maximum_mark'] = detection['visible_mark']
            confidence = detection.get('confidence')
            if confidence is not None:
                section['match_confidence'] = max(section['match_confidence'], confidence)

        for item in self._collect_page_detections('mark_scheme'):
            section = resolved.get(self._normalise_key(item['label']))
            if not section:
                continue
            page = item['page']
            detection = item['detection']
            section['answer_pages'].append(page.page_number)
            section['answer_regions'].extend(self._regions_with_page_data(
                detection.get('regions') or [], page, item['label'], len(section['answer_regions']),
                item.get('analysis') or {},
            ))
            # The mark scheme is authoritative when it reports a mark.
            if detection.get('visible_mark') is not None:
                section['maximum_mark'] = detection['visible_mark']

        if not resolved:
            raise UserError(_('The AI did not detect any question labels.'))

        self._apply_section_defaults(resolved)

        section_model = self.env['aps.exam.paper.section']
        existing_sections = {
            section.source_key: section
            for section in self.section_ids
        }
        detected_values = []
        added_count = 0
        updated_count = 0
        already_existed_count = 0
        for section in resolved.values():
            values = dict(
                section,
                question_pages=','.join(str(p) for p in sorted(set(section['question_pages']))),
                question_regions=section['question_regions'],
                answer_pages=','.join(str(p) for p in sorted(set(section['answer_pages']))),
                answer_regions=section['answer_regions'],
            )
            # Internal tracking keys are not model fields.
            values.pop('ai_include_parent_question', None)
            existing = existing_sections.get(section['source_key'])
            if existing:
                update_values = {
                    key: value for key, value in values.items()
                    if key not in {
                        'import_id', 'sequence', 'source_key', 'display_label',
                        'hierarchy_level',
                    }
                }
                if any(existing[key] != value for key, value in update_values.items()):
                    existing.write(update_values)
                    updated_count += 1
                else:
                    already_existed_count += 1
            else:
                detected_values.append(values)
        if detected_values:
            section_model.create(detected_values)
            added_count = len(detected_values)
        return {
            'added': added_count,
            'updated': updated_count,
            'already_existed': already_existed_count,
        }

    @staticmethod
    def _apply_section_defaults(resolved):
        """Default "Include Resource" / "Include Parent Question Content":
        - level 1: include resource only
        - level 3: include resource and parent content
        - level 2 with no level-3 children: include resource and parent content
        - level 2 with level-3 children: excluded (its subparts cover it)
        """
        # A root can contain both a standalone part (Q1b) and a part with
        # subparts (Q1a.i, Q1a.ii).  Checking only ``root_key`` therefore
        # incorrectly excludes every level-2 section below Q1.  Match each
        # level-3 section to its immediate level-2 parent instead.
        level_2_parents_with_subparts = {
            re.sub(
                r'[^a-z0-9]', '', section['display_label'].split('.', 1)[0].casefold()
            ).removeprefix('q')
            for section in resolved.values()
            if section['hierarchy_level'] >= 3 and '.' in section['display_label']
        }
        for section in resolved.values():
            level = section['hierarchy_level']
            if section['ai_include_parent_question'] is not None:
                continue
            if level >= 3 or (
                level == 2
                and section['source_key'] not in level_2_parents_with_subparts
            ):
                section['include_parent_question'] = True
            if level == 2 and section['source_key'] in level_2_parents_with_subparts:
                section['include_resource'] = False

    @staticmethod
    def _regions_with_page_data(regions, page, label, start_index, analysis):
        result: list[dict[str, Any]] = []
        for index, region in enumerate(regions, start_index):
            original: dict[str, Any] = dict(region)
            region: dict[str, Any] = APSExamPaperImportDetect._scale_region_to_page(original, page, analysis)
            region.update({
                'document_type': page.document_type,
                'page_number': page.page_number,
                'detection_label': label,
                'detection_order': index,
                'ai_coordinates': original,
                'ai_image_width': analysis.get('image_width'),
                'ai_image_height': analysis.get('image_height'),
                'ai_coordinate_system': analysis.get('coordinate_system', 'pixels'),
            })
            result.append(region)
        return result

    @staticmethod
    def _scale_region_to_page(region, page, analysis) -> dict[str, Any]:
        returned_width = float(analysis.get('image_width') or page.width or 1)
        returned_height = float(analysis.get('image_height') or page.height or 1)
        coordinate_system = (analysis.get('coordinate_system') or 'pixels').casefold()
        if coordinate_system in ('pixels', 'pixel'):
            return {
                key: round(float(region.get(key, 0) or 0))
                for key in ('x1', 'y1', 'x2', 'y2')
            }
        scaled = {}
        for axis, dimension, page_dimension in (
            ('x', returned_width, page.width), ('y', returned_height, page.height),
        ):
            for suffix in ('1', '2'):
                key = '%s%s' % (axis, suffix)
                try:
                    value = float(region.get(key, 0) or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if coordinate_system in ('normalized', 'normalized_0_1', '0..1'):
                    value *= dimension
                elif coordinate_system in ('normalized_0_1000', '0..1000'):
                    value *= dimension / 1000
                scaled[key] = round(value * page_dimension / dimension)
        return scaled

    @classmethod
    def _resolve_page_label(cls, raw_label, kind, root_label, part_label):
        # Labels may be printed in several equivalent forms: ``6``, ``(a)``,
        # ``(i)``, ``6(a)(i)``, ``6a(i)``, or ``(a) (i)``. Complete labels
        # provide their own context; contextual labels such as ``(i)`` and
        # ``(a) (i)`` use the preceding root and part tracked across the
        # document, which may have been detected on an earlier page.
        value = (raw_label or '').strip()
        if not value:
            return False, root_label, part_label
        roman_labels = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        explicit = re.fullmatch(
            r'(?:Q)?(\d+)\s*(?:\(([A-Za-z])\)|([A-Za-z]))?\s*'
            r'(?:\(([ivxIVX]+)\)|\.([ivxIVX]+))?', value,
        )
        if explicit:
            number, explicit_part, plain_part, explicit_subpart, plain_subpart = explicit.groups()
            root_label = 'Q%s' % number
            part_label = (explicit_part or plain_part or '').casefold() or False
            subpart = (explicit_subpart or plain_subpart or '').casefold() or False
            if subpart and subpart not in roman_labels:
                return False, root_label, part_label
            label = '%s%s' % (root_label, part_label or '')
            return '%s.%s' % (label, subpart) if subpart and part_label else label, root_label, part_label

        part_match = re.match(
            r'^\s*\(([A-Za-z])\)\s*(?:\(([ivxIVX]+)\))?', value,
        )
        subpart_match = re.match(r'^\s*\(([ivxIVX]+)\)', value)
        compact = re.sub(r'[^A-Za-z0-9]', '', value).casefold()
        if compact.startswith('q') and compact[1:].isdigit():
            compact = compact[1:]
        if compact.isdigit():
            root_label, part_label = 'Q%s' % compact, False
            return root_label, root_label, part_label
        if not root_label:
            return False, root_label, part_label
        if subpart_match:
            subpart = subpart_match.group(1).casefold()
            if part_label and subpart in {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}:
                return '%s%s.%s' % (root_label, part_label, subpart), root_label, part_label
        if part_match and kind in ('part', 'subpart', 'continuation'):
            candidate_part = part_match.group(1).casefold()
            if candidate_part in roman_labels:
                return False, root_label, part_label
            part_label = candidate_part
            subpart = part_match.group(2)
            if subpart and subpart.casefold() in roman_labels:
                return '%s%s.%s' % (root_label, part_label, subpart.casefold()), root_label, part_label
            return '%s%s' % (root_label, part_label), root_label, part_label
        return False, root_label, part_label

    def _collect_page_detections(self, document_type):
        """Return raw AI detections resolved in page order for one document."""
        result = []
        root_label = False
        part_label = False
        pages = self.page_ids.filtered(
            lambda page: page.document_type == document_type and page.ai_state == 'complete'
        ).sorted('page_number')
        for page in pages:
            detections = list(enumerate((page.ai_response or {}).get('detections', [])))
            detections.sort(key=lambda item: (
                min((float(region.get('y1', 0) or 0) for region in item[1].get('regions', [])
                     if isinstance(region, dict)), default=float('inf')),
                item[0],
            ))
            for _, detection in detections:
                raw_label = (detection.get('raw_label') or detection.get('display_label') or '').strip()
                if not raw_label:
                    continue
                if self._is_answer_space_number(detection, raw_label, page):
                    continue
                label, root_label, part_label = self._resolve_page_label(
                    raw_label, detection.get('label_kind', ''), root_label, part_label,
                )
                if label:
                    result.append({
                        'page': page, 'detection': detection,
                        'label': label, 'root_label': root_label,
                        'analysis': page.ai_response or {},
                    })
        return result

    @staticmethod
    def _is_answer_space_number(detection, raw_label, page):
        """Exclude numbered answer lines that resemble root-question labels."""
        if detection.get('is_answer_space_number') is True:
            return True
        if not re.fullmatch(r'\d+', raw_label) or detection.get('label_kind') not in ('root', ''):
            return False
        if (detection.get('question_summary') or '').strip():
            return False
        regions = [region for region in detection.get('regions') or [] if isinstance(region, dict)]
        if not regions or not page.width or not page.height:
            return False
        try:
            width = max(float(region.get('x2', 0)) - float(region.get('x1', 0)) for region in regions)
            height = max(float(region.get('y2', 0)) - float(region.get('y1', 0)) for region in regions)
        except (TypeError, ValueError):
            return False
        return width <= page.width * 0.2 and height <= page.height * 0.08
