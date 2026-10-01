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
        question_pages = self.page_ids.filtered(
            lambda page: page.document_type == 'question' and page.ai_state == 'complete'
        )
        if not question_pages:
            raise UserError(_('No completed question-paper page analyses are available.'))

        question_detections = self._collect_page_detections('question')
        if not question_detections:
            raise UserError(_(
                'Completed question-paper page analyses are present, but no question labels could be resolved '
                'into sections. Review the AI Detected Labels and ensure active Question Identifiers rules '
                'recognize their identifier components.'
            ))

        resolved = {}
        for item in question_detections:
            page = item['page']
            detection = item['detection']
            key = item['source_key']
            section = resolved.setdefault(key, {
                'import_id': self.id,
                'sequence': len(resolved) + 1,
                'source_key': key,
                'display_label': item['label'],
                'root_key': item['root_label'],
                'hierarchy_level': item['hierarchy_level'],
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
                detection.get('regions') or [], page, item['raw_label'], len(section['question_regions']),
                item.get('analysis') or {}, item['source_key'],
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
            section = resolved.get(item['source_key'])
            if not section:
                continue
            page = item['page']
            detection = item['detection']
            section['answer_pages'].append(page.page_number)
            section['answer_regions'].extend(self._regions_with_page_data(
                detection.get('regions') or [], page, item['raw_label'], len(section['answer_regions']),
                item.get('analysis') or {}, item['source_key'],
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
                        'import_id', 'sequence', 'source_key',
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
        - level 2 with level-3 children: include parent content but no resource
        """
        ordered_sections = list(resolved.values())
        level_2_parents_with_subparts = set()
        for section in ordered_sections:
            if section['hierarchy_level'] == 3 and '/' in section['source_key']:
                level_2_parents_with_subparts.add(section['source_key'].rsplit('/', 1)[0])
        for section in resolved.values():
            level = section['hierarchy_level']
            if section['ai_include_parent_question'] is not None:
                continue
            if level in (2, 3):
                section['include_parent_question'] = True
            if level == 2 and section['source_key'] in level_2_parents_with_subparts:
                section['include_resource'] = False

    @staticmethod
    def _regions_with_page_data(regions, page, label, start_index, analysis, source_key):
        result: list[dict[str, Any]] = []
        for index, region in enumerate(regions, start_index):
            original: dict[str, Any] = dict(region)
            region: dict[str, Any] = APSExamPaperImportDetect._scale_region_to_page(original, page, analysis)
            region.update({
                'document_type': page.document_type,
                'page_number': page.page_number,
                'detection_label': label,
                'source_key': source_key,
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

    @staticmethod
    def _empty_identifier_context():
        return {
            'root_label': False,
            'root_segment': False,
            'part_label': False,
            'part_segment': False,
            'path': [],
        }

    def _match_identifier_component(
        self, value, position, hierarchy_level, rules, document_type, filename,
    ):
        remaining = value[position:]
        for rule in rules:
            if rule.hierarchy_level != str(hierarchy_level):
                continue
            if rule.document_type not in ('all', document_type):
                continue
            if rule.filename_contains and rule.filename_contains.casefold() not in filename:
                continue
            match = re.match(rule.regex_pattern, remaining, flags=re.IGNORECASE)
            if not match:
                continue
            identifier = match.group(0).strip()
            if rule.canonical_key_regex:
                key_match = re.search(
                    rule.canonical_key_regex, identifier, flags=re.IGNORECASE,
                )
                if not key_match or not key_match.group(0):
                    continue
                identifier = key_match.group(0)
            if identifier:
                return identifier, position + match.end()
        return False, position

    def _resolve_rule_identifier(
        self, raw_label, context, rules, document_type, filename, kind,
    ):
        """Resolve configured identifier components and extend the path context."""
        value = (raw_label or '').strip()
        if not value:
            return False

        components = []
        position = 0
        root_identifier, root_end = self._match_identifier_component(
            value, position, 1, rules, document_type, filename,
        )
        if root_identifier:
            components.append((1, root_identifier))
            position = root_end
            part_identifier, part_end = self._match_identifier_component(
                value, position, 2, rules, document_type, filename,
            )
            if part_identifier:
                components.append((2, part_identifier))
                position = part_end
                subpart_identifier, subpart_end = self._match_identifier_component(
                    value, position, 3, rules, document_type, filename,
                )
                if subpart_identifier:
                    components.append((3, subpart_identifier))
                    position = subpart_end
        else:
            subpart_identifier = False
            if context.get('part_segment'):
                subpart_identifier, subpart_end = self._match_identifier_component(
                    value, position, 3, rules, document_type, filename,
                )
            if subpart_identifier:
                components.append((3, subpart_identifier))
                position = subpart_end
            elif kind != 'root' and context.get('root_segment'):
                part_identifier, part_end = self._match_identifier_component(
                    value, position, 2, rules, document_type, filename,
                )
                if part_identifier:
                    components.append((2, part_identifier))
                    position = part_end
                    subpart_identifier, subpart_end = self._match_identifier_component(
                        value, position, 3, rules, document_type, filename,
                    )
                    if subpart_identifier:
                        components.append((3, subpart_identifier))
                        position = subpart_end

        if not components or value[position:].strip():
            return False

        next_context = dict(context)
        next_context['path'] = list(context.get('path') or [])
        label = False
        for hierarchy_level, identifier in components:
            segment = self._normalise_identifier_component(identifier, hierarchy_level)
            if not segment:
                return False
            if hierarchy_level == 1:
                root_label = 'Q%s' % segment if segment.isdigit() else identifier
                next_context.update({
                    'root_label': root_label,
                    'root_segment': segment,
                    'part_label': False,
                    'part_segment': False,
                    'path': [segment],
                })
                label = root_label
            elif hierarchy_level == 2:
                if not next_context.get('root_label'):
                    return False
                part_label = '%s%s' % (next_context['root_label'], segment)
                next_context.update({
                    'part_label': part_label,
                    'part_segment': segment,
                    'path': next_context['path'][:1] + [segment],
                })
                label = part_label
            else:
                if not next_context.get('part_label'):
                    return False
                label = '%s.%s' % (next_context['part_label'], segment)
                next_context['path'] = next_context['path'][:2] + [segment]
            next_context['hierarchy_level'] = hierarchy_level

        context.clear()
        context.update(next_context)
        return {
            'label': label,
            'root_label': next_context['root_label'],
            'hierarchy_level': next_context['hierarchy_level'],
            'source_key': '/'.join(next_context['path']),
        }

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
        if subpart_match and isinstance(part_label, tuple):
            subpart = subpart_match.group(1).casefold()
            return '%s.%s' % (part_label[1], subpart), root_label, part_label
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

    def _resolve_configured_identifier(
        self, raw_label, root_label, part_label, rules=None, document_type=None,
    ):
        filename = ' '.join((
            self.name or '',
            self.question_attachment_id.name or '',
        )).casefold()
        if rules is None:
            rules = self.env['aps.exam.paper.question.identifier'].search([], order='sequence, id')
        for rule in rules:
            if document_type and rule.document_type not in ('all', document_type):
                continue
            if rule.filename_contains and rule.filename_contains.casefold() not in filename:
                continue
            if not re.fullmatch(rule.regex_pattern, raw_label, flags=re.IGNORECASE):
                continue
            canonical_key = raw_label
            if rule.canonical_key_regex:
                key_match = re.search(rule.canonical_key_regex, raw_label, flags=re.IGNORECASE)
                if not key_match or not key_match.group(0):
                    continue
                canonical_key = key_match.group(0)
            level = int(rule.hierarchy_level)
            if level == 1:
                return canonical_key, canonical_key, False, level
            if not root_label:
                continue
            if level == 2:
                contextual_part = re.fullmatch(r'\(([A-Za-z])\)', canonical_key)
                if contextual_part:
                    label = '%s%s' % (root_label, contextual_part.group(1).casefold())
                    return label, root_label, ('configured', label), level
                return canonical_key, root_label, ('configured', canonical_key), level
            contextual_subpart = re.fullmatch(r'\(([ivxIVX]+)\)', canonical_key)
            if contextual_subpart:
                if isinstance(part_label, tuple):
                    part = part_label[1]
                elif part_label:
                    part = '%s%s' % (root_label, part_label)
                else:
                    continue
                return '%s.%s' % (part, contextual_subpart.group(1).casefold()), root_label, part_label, level
            return canonical_key, root_label, part_label, level
        return False, root_label, part_label, 0

    def _collect_page_detections(self, document_type):
        """Return raw AI detections resolved in page order for one document."""
        result = []
        context = self._empty_identifier_context()
        identifier_rules = self.env['aps.exam.paper.question.identifier'].search(
            [('active', '=', True)], order='sequence, id',
        )
        filename = ' '.join((
            self.name or '',
            self.question_attachment_id.name or '',
        )).casefold()
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
                resolved = self._resolve_rule_identifier(
                    raw_label, context, identifier_rules, document_type, filename,
                    detection.get('label_kind', ''),
                )
                if not resolved:
                    continue
                result.append({
                    'page': page, 'detection': detection,
                    **resolved,
                    'raw_label': raw_label,
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
