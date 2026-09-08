"""Building LMS resources from detected sections, including cropped section images."""
import base64
import logging
import re
from html import escape
from io import BytesIO

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class APSExamPaperImportBuild(models.Model):
    _inherit = 'aps.exam.paper.import'

    def action_validate(self):
        self.ensure_one()
        errors = []
        seen = set()
        sections = self.section_ids.filtered('include_resource')
        for section in sections:
            if section.source_key in seen:
                errors.append(_('Duplicate section: %s') % section.display_label)
            seen.add(section.source_key)
            if not section.question_regions:
                errors.append(_('%s has no question-page region.') % section.display_label)
            if not section.answer_regions:
                errors.append(_('%s has no mark-scheme region.') % section.display_label)
            if section.maximum_mark in (False, None):
                errors.append(_('%s has no maximum mark.') % section.display_label)
        if errors:
            raise ValidationError('\n'.join(errors))
        return self._notification(_('Validation passed'), _('The detected sections are ready to build resources.'), 'success')

    def _section_regions(self, section, document_type):
        field_name = 'question_regions' if document_type == 'question' else 'answer_regions'
        regions = [dict(region) for region in (getattr(section, field_name) or [])]
        if document_type == 'question':
            regions = self._filter_question_regions(section, regions)
        if document_type == 'question' and section.include_parent_question:
            parent = self._find_parent_section(section)
            if parent:
                regions = self._section_regions(parent, document_type) + regions
        return regions

    def _filter_question_regions(self, section, regions):
        """Remove parent regions covered by a child starting at the same height."""
        if not section.root_key or not section.hierarchy_level:
            return regions
        children = self.section_ids.filtered(
            lambda candidate: candidate.sequence > section.sequence
            and candidate.hierarchy_level > section.hierarchy_level
            and self._normalise_key(candidate.root_key or candidate.source_key) == self._normalise_key(section.root_key)
        )
        filtered = []
        for parent_region in regions:
            try:
                parent_y = float(parent_region['y1'])
            except (KeyError, TypeError, ValueError):
                filtered.append(parent_region)
                continue
            skipped_by = None
            for child in children:
                for child_region in child.question_regions or []:
                    if child_region.get('page_number') != parent_region.get('page_number'):
                        continue
                    try:
                        child_y = float(child_region['y1'])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if child_y <= parent_y + 10:
                        skipped_by = (child.display_label, child_y)
                        break
                if skipped_by:
                    break
            if skipped_by:
                self._append_image_update_log(section, 'question region %s on page %s skipped: child %s starts at y1=%s; parent y1=%s; tolerance=10.' % (
                    parent_region.get('detection_label') or section.display_label,
                    parent_region.get('page_number') or 'unknown',
                    skipped_by[0], skipped_by[1], parent_y,
                ))
            else:
                filtered.append(parent_region)
        return filtered

    def _find_parent_section(self, section):
        """Find the nearest earlier, lower-level question section in the same root."""
        if not section.root_key or not section.hierarchy_level:
            return self.env['aps.exam.paper.section']
        root_key = self._normalise_key(section.root_key)
        candidates = self.section_ids.filtered(
            lambda candidate: candidate.sequence < section.sequence
            and self._normalise_key(candidate.root_key or candidate.source_key) == root_key
            and candidate.hierarchy_level < section.hierarchy_level
        ).sorted(key=lambda candidate: candidate.sequence, reverse=True)
        return candidates[:1]

    def _append_image_update_log(self, section, message):
        local_now = fields.Datetime.context_timestamp(section, fields.Datetime.now())
        section.write({
            'image_update_log': '%s[%s] %s\n' % (
                section.image_update_log or '', local_now.strftime('%Y-%m-%d %H:%M:%S'), message,
            ),
        })

    def _page_label_positions(self, document_type):
        positions = {}
        for item in self._collect_page_detections(document_type):
            regions = item['detection'].get('regions') or []
            if not regions:
                continue
            page = item['page']
            scaled_regions = [
                self._scale_region_to_page(region, page, item.get('analysis') or {})
                for region in regions
            ]
            y_value = min(
                float(region.get('y1', 0) or 0) / page.height
                for region in scaled_regions
            )
            positions.setdefault(item['page'].page_number, []).append({
                'label': item['label'],
                'normalised_label': self._normalise_key(item['label']),
                'hierarchy_level': self._label_hierarchy_level(item['label']),
                'y': y_value,
            })
        for values in positions.values():
            values.sort(key=lambda value: value['y'])
        return positions

    @staticmethod
    def _region_y_as_fraction(region, page):
        try:
            y_value = float(region.get('y1', 0))
        except (TypeError, ValueError):
            return 0.0
        coordinate_system = (region.get('ai_coordinate_system') or '').casefold()
        if coordinate_system in ('pixels', 'pixel'):
            return y_value / page.height if page.height else 0.0
        return APSExamPaperImportBuild._coordinate_as_fraction(y_value, page.height)

    @staticmethod
    def _coordinate_as_fraction(value, dimension):
        """Convert AI coordinates from 0..1, 0..1000, or rendered pixels."""
        if value <= 1:
            return value
        if value <= 1000:
            return value / 1000
        return value / dimension if dimension else 0.0

    @staticmethod
    def _coordinate_scale(region):
        coordinate_system = (region.get('ai_coordinate_system') or '').casefold()
        if coordinate_system in ('pixels', 'pixel'):
            return 'rendered pixels'
        values = []
        for key in ('x1', 'y1', 'x2', 'y2'):
            try:
                values.append(float(region.get(key, 0) or 0))
            except (TypeError, ValueError):
                continue
        if not values or max(values) <= 1:
            return 'normalized 0..1'
        if max(values) <= 1000:
            return 'normalized 0..1000'
        return 'rendered pixels'

    def _crop_bounds(self, region, page, label_positions, y_adjustment=0):
        if region.get('manual'):
            try:
                left = int(round(float(region['x1'])))
                top = int(round(float(region['y1'])))
                right = int(round(float(region['x2'])))
                bottom = int(round(float(region['y2'])))
            except (KeyError, TypeError, ValueError):
                raise ValidationError(_('Manually edited regions must contain pixel x1, y1, x2 and y2 bounds.'))
            if right - left < 150:  # This is a little arbitary. Alsmost always we want full width images. This needs to be wide enough to handle when a question label eg 1(a)(i) gets long
                left = self._CROP_LEFT
                right = page.width - self._CROP_RIGHT
            left = max(0, min(page.width - 1, left))
            top = max(0, min(page.height - 1, top))
            right = max(left + 1, min(page.width, right))
            bottom = max(top + 1, min(page.height, bottom))
            return left, top, right, bottom
        start_y = max(0.0, min(1.0, self._region_y_as_fraction(region, page)))
        next_y = None
        source_label = self._normalise_key(region.get('detection_label') or '')
        for candidate in label_positions.get(page.page_number, []):
            candidate_label = candidate.get('normalised_label', '')
            is_descendant = (
                source_label
                and candidate_label.startswith(source_label)
                and candidate_label != source_label
                and len(candidate_label) > len(source_label)
            )
            # A parent section must stop at its first child, even when the
            # vision model puts the child label a few pixels above the
            # parent's label.  Without this, Q1a's crop can run through
            # Q1a.i and become part of every later sub-question.
            if is_descendant and candidate['y'] > start_y + self._LABEL_Y_TOLERANCE:
                next_y = candidate['y']
                break
            if not is_descendant and candidate['y'] > start_y + self._LABEL_Y_TOLERANCE:
                next_y = candidate['y']
                break
        left = max(0, min(page.width, self._CROP_LEFT))
        top = max(0, min(page.height, max(self._CROP_TOP, round(start_y * page.height) - y_adjustment)))
        right = max(left + 1, min(page.width, page.width - self._CROP_RIGHT))
        bottom_limit = max(top + 1, page.height - self._CROP_BOTTOM)
        bottom = bottom_limit if next_y is None else round(next_y * page.height) - y_adjustment
        if bottom <= top:
            # A stale or slightly out-of-order detected label must never
            # produce an inverted Pillow crop. Fall back to the page limit.
            bottom = bottom_limit
        bottom = max(top + 1, min(bottom_limit, bottom))
        return left, top, right, bottom

    def _crop_section_images(self, section, document_type, log=False):
        label_positions = self._page_label_positions(document_type)
        images = []
        seen = set()
        regions = self._section_regions(section, document_type)
        if log:
            self._append_image_update_log(section, '%s: found %s region(s), label positions on page(s): %s.' % (
                document_type, len(regions), ', '.join(str(page) for page in sorted(label_positions)) or 'none',
            ))
        for index, region in enumerate(regions, 1):
            page_number = region.get('page_number')
            if not page_number:
                pages = [value for value in (section.question_pages if document_type == 'question' else section.answer_pages or '').split(',') if value]
                page_number = int(pages[index - 1]) if index <= len(pages) else False
            try:
                page_number = int(page_number) if page_number else False
            except (TypeError, ValueError):
                page_number = False
            page = self.page_ids.filtered(
                lambda item: item.document_type == document_type and item.page_number == page_number
            )[:1]
            if not page or not page.width or not page.height:
                if log:
                    self._append_image_update_log(section, '%s region %s: no rendered image/page found for page %s.' % (
                        document_type, index, page_number or 'unknown',
                    ))
                continue
            # The Y adjustment trims the label edge on both question and
            # mark-scheme crops.
            y_adjustment = self._CROP_Y_ADJUSTMENT
            bounds = self._crop_bounds(region, page, label_positions, y_adjustment)
            if log:
                self._append_image_update_log(section, '%s region %s: raw coordinates=%s (%s), page %s image %sx%s, crop x=%s..%s y=%s..%s.' % (
                    document_type, index, region, self._coordinate_scale(region), page_number,
                    page.width, page.height, *bounds,
                ))
            key = (page.id, bounds)
            if key in seen:
                if log:
                    self._append_image_update_log(section, '%s region %s: duplicate crop skipped.' % (document_type, index))
                continue
            seen.add(key)
            images.append((page, bounds))
        return images

    def _remove_section_images(self, resource, section):
        marker = 'aps_exam_import_section:%s' % section.id
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resources'), ('res_id', '=', resource.id),
            ('description', 'ilike', marker),
        ])
        attachment_ids = [str(attachment.id) for attachment in attachments]
        attachments.unlink()
        pattern = r'<div[^>]*data-aps-exam-import-section=["\']%s["\'][^>]*>.*?</div>' % section.id
        question = re.sub(pattern, '', resource.question or '', flags=re.S)
        answer = re.sub(pattern, '', resource.answer or '', flags=re.S)
        # Remove stale image HTML as well. Older generated blocks may not
        # contain the section marker, leaving a broken-image placeholder after
        # their attachments are deleted.
        for attachment_id in attachment_ids:
            image_pattern = r'<p[^>]*>\s*<img[^>]+/web/image/%s[^>]*>\s*</p>|<img[^>]+/web/image/%s[^>]*>' % (
                attachment_id, attachment_id,
            )
            question = re.sub(image_pattern, '', question, flags=re.I | re.S)
            answer = re.sub(image_pattern, '', answer, flags=re.I | re.S)
        return question, answer

    def _remove_import_images(self, resource, sections):
        """Remove all generated exam images before rebuilding a resource."""
        section_ids = sections.ids
        if not section_ids:
            return resource.question or '', resource.answer or ''
        marker = 'aps_exam_import_section:'
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'aps.resources'),
            ('res_id', '=', resource.id),
            ('description', 'ilike', marker),
        ])
        attachment_ids = [str(attachment.id) for attachment in attachments]
        attachments.unlink()
        question = resource.question or ''
        answer = resource.answer or ''
        for section_id in section_ids:
            pattern = r'<div[^>]*data-aps-exam-import-section=["\']%s["\'][^>]*>.*?</div>' % section_id
            question = re.sub(pattern, '', question, flags=re.S)
            answer = re.sub(pattern, '', answer, flags=re.S)
        for attachment_id in attachment_ids:
            image_pattern = r'<p[^>]*>\s*<img[^>]+/web/image/%s[^>]*>\s*</p>|<img[^>]+/web/image/%s[^>]*>' % (
                attachment_id, attachment_id,
            )
            question = re.sub(image_pattern, '', question, flags=re.I | re.S)
            answer = re.sub(image_pattern, '', answer, flags=re.I | re.S)
        return question, answer

    def _replace_section_images(self, resource, section, document_type, html, log=False):
        marker_pattern = r'<div[^>]*data-aps-exam-import-section=["\']%s["\'][^>]*>.*?</div>' % section.id
        if re.search(marker_pattern, html or '', flags=re.S):
            if log:
                self._append_image_update_log(section, '%s: existing generated block found; replacing it.' % document_type)
            return re.sub(marker_pattern, self._build_section_image_html(resource, section, document_type, log=log), html, flags=re.S)
        heading = '<h1>%s</h1>' % escape(section.display_label)
        image_html = self._build_section_image_html(resource, section, document_type, log=log)
        if log:
            self._append_image_update_log(section, '%s: heading %s.' % (
                document_type, 'found; inserting generated HTML' if heading in (html or '') else 'not found; generated HTML was not inserted',
            ))
        if heading in (html or ''):
            return (html or '').replace(heading, heading + image_html, 1)
        heading_pattern = r'(?P<heading><h[1-6][^>]*>\s*#?\s*%s\s*</h[1-6]>)' % re.escape(section.display_label)
        heading_match = re.search(heading_pattern, html or '', flags=re.I)
        if heading_match:
            return (html or '')[:heading_match.end()] + image_html + (html or '')[heading_match.end():]
        if image_html:
            if log:
                self._append_image_update_log(section, '%s: no matching heading; appending generated HTML.' % document_type)
            return (html or '') + image_html
        return html or ''

    def _build_section_image_html(self, resource, section, document_type, log=False):
        blocks = []
        for index, (page, bounds) in enumerate(self._crop_section_images(section, document_type, log=log), 1):
            image = page.attachment_id
            image_bytes = self._attachment_bytes(image)
            if not image_bytes:
                if log:
                    self._append_image_update_log(section, '%s image on page %s: source attachment %s has no bytes.' % (
                        document_type, page.page_number, image.id,
                    ))
                continue
            try:
                from PIL import Image
                with Image.open(BytesIO(image_bytes)) as source:
                    crop = source.crop(bounds)
                    output = BytesIO()
                    crop.save(output, format='PNG', optimize=True)
                    crop_bytes = output.getvalue()
            except ImportError as exc:
                raise UserError(_('Image insertion requires the Pillow package in the Odoo environment.')) from exc
            attachment = self.env['ir.attachment'].create({
                'name': 'exam-import-%s-%s-%s.png' % (section.source_key, document_type, index),
                'type': 'binary', 'datas': base64.b64encode(crop_bytes),
                'mimetype': 'image/png', 'res_model': 'aps.resources', 'res_id': resource.id,
                'description': 'aps_exam_import_section:%s document:%s page:%s' % (
                    section.id, document_type, page.page_number,
                ),
            })
            if log:
                self._append_image_update_log(section, '%s image on page %s: created crop attachment %s (%s bytes).' % (
                    document_type, page.page_number, attachment.id, len(crop_bytes),
                ))
            blocks.append(
                '<p><img src="/web/image/%s" class="img-fluid" style="width: 100%%;" alt="%s %s page %s"></img></p>' % (
                    attachment.id, escape(section.display_label), document_type, page.page_number,
                )
            )
        if not blocks:
            if log:
                self._append_image_update_log(section, '%s: no image HTML was generated.' % document_type)
            return ''
        return '<div data-aps-exam-import-section="%s" data-aps-exam-import-document="%s">%s</div>' % (
            section.id, document_type, ''.join(blocks),
        )

    def _refresh_section_images(self, section):
        section.ensure_one()
        local_now = fields.Datetime.context_timestamp(section, fields.Datetime.now())
        section.write({'image_update_log': '[%s] Refresh started for %s.\n' % (
            local_now.strftime('%Y-%m-%d %H:%M:%S'), section.display_label,
        )})
        if not section.resource_id:
            self._append_image_update_log(section, 'Stopped: section has no linked resource. Build Resources first.')
            raise UserError(_('Build the resources before inserting section images.'))
        resource = section.import_id.resource_id.child_ids.filtered(
            lambda item: item.name == (section.root_key or section.display_label)
        )[:1]
        if not resource:
            resource = section.resource_id
        self._append_image_update_log(section, 'Target resource is %s (%s); section resource is %s.' % (
            resource.display_name if resource else 'not found',
            resource.id if resource else 'unknown',
            section.resource_id.id,
        ))
        if not resource:
            self._append_image_update_log(section, 'Stopped: no second-level root resource was found.')
            raise UserError(_('The second-level resource for this section was not found.'))
        question, answer = self._remove_section_images(resource, section)
        self._append_image_update_log(section, 'Removed previous generated image blocks. Existing text was retained.')
        question = self._replace_section_images(resource, section, 'question', question, log=True)
        answer = self._replace_section_images(resource, section, 'mark_scheme', answer, log=True)
        resource.write({'question': question, 'answer': answer})
        self._append_image_update_log(section, 'Resource %s updated: question HTML=%s characters, answer HTML=%s characters.' % (
            resource.id, len(question), len(answer),
        ))
        self._append_image_update_log(section, 'Refresh completed.')

    def _append_section_content(self, root, section, headings, answers):
        question_html = self._build_section_image_html(root, section, 'question')
        answer_html = self._build_section_image_html(root, section, 'mark_scheme')
        headings.append('<h1>%s</h1>%s' % (escape(section.display_label), question_html))
        answers.append('<h1>%s</h1>%s' % (escape(section.display_label), answer_html))

    def action_build_resources(self):
        self.ensure_one()
        self.write({'state': 'building', 'progress': 70})
        roots = {}
        created_resource_count = 0
        reused_resource_count = 0
        included_sections = self.section_ids.filtered('include_resource').sorted(
            key=lambda s: (s.sequence, s.source_key)
        )
        for section in included_sections:
            root_key = section.root_key or section.source_key
            root = roots.get(root_key)
            if not root:
                existing_child_ids = set(self.resource_id.child_ids.ids)
                root = self._find_or_create_resource(root_key, self.resource_id)
                if root.id in existing_child_ids:
                    reused_resource_count += 1
                else:
                    created_resource_count += 1
                roots[root_key] = root

        sections_by_root = {}
        for section in included_sections:
            sections_by_root.setdefault(section.root_key or section.source_key, []).append(section)

        for root_key, sections in sections_by_root.items():
            root = roots[root_key]
            headings = []
            answers = []
            total_marks = 0.0
            root_pages = set()
            root_regions = []
            question, answer = self._remove_import_images(root, self.section_ids)
            root.write({'question': question, 'answer': answer})
            for section in sections:
                # The root-number detection (for example Q1) identifies the
                # second-level resource. It is not a child of itself. Only
                # mark-bearing descendants such as Q1a or Q1b.i become
                # third-level resources.
                if self._normalise_key(section.display_label) == self._normalise_key(root.name):
                    root_pages.update(filter(None, (section.question_pages or '').split(',')))
                    root_regions.extend(self._section_regions(section, 'question'))
                    section.write({'resource_key': str(root.id)})
                    continue
                existing_child_ids = set(root.child_ids.ids)
                child = self._find_or_create_resource(section.display_label, root)
                if child.id in existing_child_ids:
                    reused_resource_count += 1
                else:
                    created_resource_count += 1
                question_regions = self._section_regions(section, 'question')
                question_pages = set(filter(None, (section.question_pages or '').split(',')))
                question_pages.update(
                    str(region['page_number'])
                    for region in question_regions
                    if region.get('page_number')
                )
                root_pages.update(question_pages)
                total_marks += section.maximum_mark or 0.0
                root_regions.extend(question_regions)
                self._append_section_content(root, section, headings, answers)
                child.write({
                    'has_question': 'use_parent',
                    'has_answer': 'use_parent',
                    'marks': section.maximum_mark,
                    'description': section.question_summary or False,
                })
                section.resource_id = child.id
                section.write({'resource_key': str(child.id)})

            root.write({
                'has_child_resources': 'yes',
                'has_question': 'yes',
                'has_answer': 'yes',
                'question': ''.join(headings),
                'answer': ''.join(answers),
                'marks': total_marks,
                'description': False,
            })
        self.write({'state': 'completed', 'progress': 100, 'completed_at': fields.Datetime.now()})
        # Show the completion toast and then re-open the form so the refreshed
        # state, progress and section resource links are shown without a
        # manual reload.
        return self._notification(
            _('Import completed'),
            _('%s resource(s) created; %s existing resource(s) reused.') % (
                created_resource_count, reused_resource_count,
            ),
            'success',
            next=self._open_form(),
        )

    def _find_or_create_resource(self, name, parent):
        child = parent.child_ids.filtered(lambda r: r.name == name)[:1]
        if child:
            return child
        resource_type = self.env['aps.resource.types'].search([
            ('name', '=', 'Question (Past Paper)'),
        ], limit=1)
        if not resource_type:
            raise UserError(_('The resource type "Question (Past Paper)" was not found.'))
        return self.env['aps.resources'].create({
            'name': name,
            'parent_ids': [(4, parent.id)],
            'primary_parent_id': parent.id,
            'subjects': [(6, 0, parent.subjects.ids)],
            'type_id': resource_type.id,
            'has_question': 'no',
            'has_answer': 'no',
            'category': 'mandatory',
        })
