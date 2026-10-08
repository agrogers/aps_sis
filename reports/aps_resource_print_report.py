from lxml import html
from markupsafe import Markup

from odoo import api, models


class APSResourcePrintReport(models.AbstractModel):
    _name = 'report.aps_sis.report_aps_resources_print'
    _description = 'Selected Resources Print Report'

    @api.model
    def _without_images(self, content):
        if not content:
            return Markup('')
        fragments = html.fragments_fromstring(content)
        output = []
        for fragment in fragments:
            if isinstance(fragment, str):
                output.append(fragment)
                continue
            if fragment.tag == 'img':
                continue
            for image in fragment.xpath('.//img'):
                image.drop_tree()
            output.append(html.tostring(fragment, encoding='unicode', method='html'))
        return Markup(''.join(output))

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        if not docids:
            docids = data.get('resource_ids') or self.env.context.get('active_ids', [])
        resources = self.env['aps.resources'].search(
            [('id', 'in', docids)],
            order='create_date desc, id desc',
        )

        include_images = data.get('include_images', True)
        prepared_resources = []
        for resource in resources:
            basic_fields = [
                ('Name', resource.name or ''),
                ('Parent Resources', ', '.join(resource.parent_ids.mapped('display_name'))),
                ('Type', resource.type_id.display_name or ''),
                (
                    'Category',
                    dict(resource._fields['category'].selection).get(resource.category, ''),
                ),
                ('Marks', str(resource.marks) if resource.marks is not False else ''),
                ('Weight', str(resource.weight) if resource.weight is not False else ''),
                ('Subjects', ', '.join(resource.subjects.mapped('display_name'))),
                ('Tags', ', '.join(resource.tag_ids.mapped('display_name'))),
                ('Description', resource.description or ''),
                (
                    'AI Action',
                    dict(resource._fields['ai_action'].selection).get(resource.ai_action, ''),
                ),
            ]
            sections = []
            if data.get('include_basic', True):
                sections.append({'kind': 'basic', 'title': 'Basic Information', 'fields': basic_fields})
            for key, title, content in (
                ('include_notes', 'Notes', resource.notes),
                ('include_question', 'Question', resource.question),
                ('include_model_answer', 'Model Answer', resource.answer),
                ('include_lesson_plan', 'Lesson Plan', resource.lesson_plan),
            ):
                if data.get(key, True):
                    body = Markup(content or '') if include_images else self._without_images(content)
                    sections.append({'kind': 'html', 'title': title, 'body': body})
            if data.get('include_assigned_students', True):
                students = resource.task_ids.mapped('student_id').sorted(
                    key=lambda student: (student.name or '').casefold()
                )
                sections.append({
                    'kind': 'students',
                    'title': 'Assigned Students',
                    'students': students,
                })
            prepared_resources.append({
                'record': resource,
                'sections': sections,
            })

        return {
            'doc_ids': resources.ids,
            'doc_model': 'aps.resources',
            'docs': resources,
            'prepared_resources': prepared_resources,
            'data': data,
        }