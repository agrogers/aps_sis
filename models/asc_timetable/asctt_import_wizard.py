import base64
import logging
from datetime import datetime, time as dt_time

import pytz
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError

"""
asctt_import_wizard – aSc Timetables 2012 XML import wizard
===========================================================

Parses an aSc Timetables 2012 XML export and upserts every section into the
corresponding ``asctt.*`` Odoo models.  Sections are imported in strict
dependency order so that foreign-key lookups always resolve.

Model → APEX link mapping
-------------------------
+--------------------------------------------------+----------------------+
| aSc model(s)                                     | APEX link field      |
+==================================================+======================+
| asctt.period, asctt.break                        | —                    |
| asctt.days.def, asctt.weeks.def                  | —                    |
| asctt.terms.def                                  | aps.academic.term    |
| asctt.subject                                    | aps.subject.category |
| asctt.teacher                                    | aps.teacher          |
| asctt.building, asctt.classroom                  | —                    |
| asctt.grade                                      | aps.level            |
| asctt.class                                      | aps.class            |
| asctt.group, asctt.lesson, asctt.card,           | —                    |
| asctt.classroom.supervision                      |                      |
+--------------------------------------------------+----------------------+

Upsert strategy
---------------
* Most sections: match on ``asc_id``; write existing, create new.
* ``asctt.period`` / ``asctt.break`` / ``asctt.grade``: match on ``period`` /
  ``name`` / ``grade`` integer (no stable aSc XML ID).
* ``asctt.card`` / ``asctt.classroom.supervision``: no stable XML ID –
  all existing records are deleted before batch-create.
"""

_logger = logging.getLogger(__name__)

# Binary day patterns indexed 0=Monday … 4=Friday
_DAY_PATTERNS = ['10000', '01000', '00100', '00010', '00001']


def _split_ids(value):
    """Split a comma-separated aSc ID string, dropping empty entries."""
    if not value:
        return []
    return [v.strip() for v in value.split(',') if v.strip()]


def _weeks_cycle_match(weeks_pattern, week_cycle):
    """Return True if the academic week cycle matches the aSc weeks binary pattern.

    :param weeks_pattern: aSc ``weeks`` attribute, e.g. ``'10'``, ``'01'``,
                          ``'11'``, ``'1'`` or empty.
    :param week_cycle: ``aps.academic.week.week_cycle`` value, e.g. ``'A'``,
                       ``'B'``, ``'1'``, ``'2'``.
    """
    if not weeks_pattern or weeks_pattern in ('1', '11', '111', '1111', '11111'):
        return True  # applies every week
    if weeks_pattern == '10':
        # Week A / first in alternating cycle
        return str(week_cycle).upper() in ('A', '1')
    if weeks_pattern == '01':
        # Week B / second in alternating cycle
        return str(week_cycle).upper() in ('B', '2')
    # Unknown pattern – include all to avoid silently dropping lessons
    return True


class ASCTTImportWizard(models.TransientModel):
    _name = 'asctt.import.wizard'
    _description = 'Import aSc Timetable XML'

    xml_file = fields.Binary(string='aSc XML File', required=True, attachment=False)
    xml_filename = fields.Char(string='Filename')

    # ── Timetable generation options ───────────────────────────────────────────
    apply_from_date = fields.Date(
        string='Apply From',
        required=True,
        default=fields.Date.today,
        help='Generate timetable entries starting from this date. '
             'Typically today (for "apply now") or the start of a future week/term.',
    )
    apply_to_term_id = fields.Many2one(
        'aps.academic.term',
        string='Apply To Term',
        ondelete='set null',
        help='Restrict timetable generation to this academic term. '
             'If blank, entries are generated from "Apply From" to '
             'the end of the current academic year (or 52 weeks).',
    )
    generate_timetable = fields.Boolean(
        string='Generate Timetable Entries',
        default=True,
        help='After importing, automatically generate dated timetable entries '
             'in the School Timetable (aps.timetable.entry) using the School Calendar.',
    )

    # ── Remembered settings ────────────────────────────────────────────────────

    _PARAM_FROM_DATE = 'asctt.import.wizard.apply_from_date'
    _PARAM_TERM_ID = 'asctt.import.wizard.apply_to_term_id'
    _PARAM_GEN_TT = 'asctt.import.wizard.generate_timetable'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        params = self.env['ir.config_parameter'].sudo()

        if 'apply_from_date' in fields_list:
            stored = params.get_param(self._PARAM_FROM_DATE)
            if stored:
                defaults['apply_from_date'] = stored

        if 'apply_to_term_id' in fields_list:
            stored = params.get_param(self._PARAM_TERM_ID)
            if stored:
                try:
                    term_id = int(stored)
                    if self.env['aps.academic.term'].browse(term_id).exists():
                        defaults['apply_to_term_id'] = term_id
                except (ValueError, TypeError):
                    pass

        if 'generate_timetable' in fields_list:
            stored = params.get_param(self._PARAM_GEN_TT)
            if stored is not None:
                defaults['generate_timetable'] = stored == 'True'

        return defaults

    def _save_wizard_settings(self):
        """Persist current wizard settings to ir.config_parameter."""
        params = self.env['ir.config_parameter'].sudo()
        params.set_param(self._PARAM_FROM_DATE, str(self.apply_from_date) if self.apply_from_date else '')
        params.set_param(self._PARAM_TERM_ID, str(self.apply_to_term_id.id) if self.apply_to_term_id else '')
        params.set_param(self._PARAM_GEN_TT, str(self.generate_timetable))

    # ── Public action ──────────────────────────────────────────────────────────

    def action_import(self):
        """Decode the uploaded XML file and run all section importers in order.

        Returns a ``display_notification`` action with a per-section summary
        and closes the wizard dialog on acknowledgement.
        """
        self.ensure_one()
        if not self.xml_file:
            raise UserError(_('Please select an XML file to import.'))

        try:
            xml_data = base64.b64decode(self.xml_file)
            root = etree.fromstring(xml_data)
        except Exception as exc:
            raise UserError(_('Failed to parse XML file: %s') % str(exc)) from exc

        # Import in strict dependency order so FKs resolve correctly
        stats = {
            'Periods':        self._import_periods(root),
            'Breaks':         self._import_breaks(root),
            'Day Defs':       self._import_days_defs(root),
            'Week Defs':      self._import_weeks_defs(root),
            'Term Defs':      self._import_terms_defs(root),
            'Subjects':       self._import_subjects(root),
            'Teachers':       self._import_teachers(root),
            'Buildings':      self._import_buildings(root),
            'Classrooms':     self._import_classrooms(root),
            'Grades':         self._import_grades(root),
            'Classes':        self._import_classes(root),
            'Groups':         self._import_groups(root),
            'Lessons':        self._import_lessons(root),
            'Cards':          self._import_cards(root),
            'Supervisions':   self._import_supervisions(root),
        }

        total_created = total_updated = 0
        lines = []
        for label, (created, updated) in stats.items():
            total_created += created
            total_updated += updated
            if created or updated:
                lines.append(f'  {label}: {created} created, {updated} updated')

        summary = f'{total_created} created, {total_updated} updated'
        detail = '\n'.join(lines) if lines else 'No records changed.'

        # Save wizard settings for next run
        self._save_wizard_settings()

        # Refresh teacher workload totals from the newly-updated timetable
        self.env['aps.teacher'].search([])._recompute_timetable_loads()

        # Optionally generate dated timetable entries
        if self.generate_timetable:
            entry_count = self._generate_timetable_entries()
            detail += f'\n  Timetable Entries: {entry_count} created'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('aSc Import Complete'),
                'message': summary + '\n' + detail,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ── Generic helpers ────────────────────────────────────────────────────────

    def _upsert_by_asc_id(self, model_name, asc_id, vals):
        """Upsert a record identified by ``asc_id``.

        Searches ``model_name`` for a record whose ``asc_id`` matches.  If
        found, calls ``write(vals)``; otherwise sets ``vals['asc_id']`` and
        calls ``create(vals)``.

        :returns: ``'updated'`` or ``'created'``.
        """
        Model = self.env[model_name]
        rec = Model.search([('asc_id', '=', asc_id)], limit=1)
        if rec:
            rec.write(vals)
            return 'updated'
        vals['asc_id'] = asc_id
        Model.create(vals)
        return 'created'

    def _build_asc_id_map(self, model_name):
        """Build a lookup dict ``{asc_id: record.id}`` for FK resolution.

        Only records with a non-False ``asc_id`` are included.  Call this once
        per model at the top of each ``_import_*`` method to avoid repeated
        searches inside the element loop.
        """
        records = self.env[model_name].search([('asc_id', '!=', False)])
        return {r.asc_id: r.id for r in records}

    # ── Section importers ──────────────────────────────────────────────────────

    def _import_periods(self, root):
        """Import ``<period>`` elements into ``asctt.period``.

        Matched on the integer ``period`` attribute (no stable XML ID).
        """
        created = updated = 0
        Period = self.env['asctt.period']
        for el in root.findall('.//periods/period'):
            name = el.get('name', '').strip()
            period_str = el.get('period', '').strip()
            if not name or period_str == '':
                continue
            try:
                period_num = int(period_str)
            except ValueError:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'period': period_num,
                'starttime': el.get('starttime', '').strip() or False,
                'endtime': el.get('endtime', '').strip() or False,
            }
            rec = Period.search([('period', '=', period_num)], limit=1)
            if rec:
                rec.write(vals)
                updated += 1
            else:
                Period.create(vals)
                created += 1
        return created, updated

    def _import_breaks(self, root):
        """Import ``<break>`` elements into ``asctt.break``.

        Matched on ``name`` (no stable XML ID).
        """
        created = updated = 0
        Break = self.env['asctt.break']
        for el in root.findall('.//breaks/break'):
            name = el.get('name', '').strip()
            if not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'starttime': el.get('starttime', '').strip() or False,
                'endtime': el.get('endtime', '').strip() or False,
            }
            rec = Break.search([('name', '=', name)], limit=1)
            if rec:
                rec.write(vals)
                updated += 1
            else:
                Break.create(vals)
                created += 1
        return created, updated

    def _import_days_defs(self, root):
        """Import ``<daysdef>`` elements into ``asctt.days.def`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//daysdefs/daysdef'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'days': el.get('days', '').strip() or False,
            }
            if self._upsert_by_asc_id('asctt.days.def', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_weeks_defs(self, root):
        """Import ``<weeksdef>`` elements into ``asctt.weeks.def`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//weeksdefs/weeksdef'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'weeks': el.get('weeks', '').strip() or False,
            }
            if self._upsert_by_asc_id('asctt.weeks.def', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_terms_defs(self, root):
        """Import ``<termsdef>`` elements into ``asctt.terms.def`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//termsdefs/termsdef'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'terms': el.get('terms', '').strip() or False,
            }
            if self._upsert_by_asc_id('asctt.terms.def', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_subjects(self, root):
        """Import ``<subject>`` elements into ``asctt.subject`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//subjects/subject'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
            }
            if self._upsert_by_asc_id('asctt.subject', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_teachers(self, root):
        """Import ``<teacher>`` elements into ``asctt.teacher`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//teachers/teacher'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            gender_raw = el.get('gender', '').strip()
            gender = gender_raw if gender_raw in ('M', 'F') else ''
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'firstname': el.get('firstname', '').strip() or False,
                'lastname': el.get('lastname', '').strip() or False,
                'gender': gender,
                'color': el.get('color', '').strip() or False,
                'email': el.get('email', '').strip() or False,
                'mobile': el.get('mobile', '').strip() or False,
            }
            if self._upsert_by_asc_id('asctt.teacher', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_buildings(self, root):
        """Import ``<building>`` elements into ``asctt.building`` (upsert by asc_id)."""
        created = updated = 0
        for el in root.findall('.//buildings/building'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            if self._upsert_by_asc_id('asctt.building', asc_id, {'name': name}) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_classrooms(self, root):
        """Import ``<classroom>`` elements into ``asctt.classroom`` (upsert by asc_id)."""
        created = updated = 0
        building_map = self._build_asc_id_map('asctt.building')
        for el in root.findall('.//classrooms/classroom'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'capacity': el.get('capacity', '').strip() or False,
                'building_id': building_map.get(el.get('buildingid', '').strip(), False),
            }
            if self._upsert_by_asc_id('asctt.classroom', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_grades(self, root):
        """Import ``<grade>`` elements into ``asctt.grade``.

        Matched on the integer ``grade`` attribute (no stable XML ID).
        """
        created = updated = 0
        Grade = self.env['asctt.grade']
        for el in root.findall('.//grades/grade'):
            name = el.get('name', '').strip()
            grade_str = el.get('grade', '').strip()
            if not name or grade_str == '':
                continue
            try:
                grade_num = int(grade_str)
            except ValueError:
                continue
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'grade': grade_num,
            }
            rec = Grade.search([('grade', '=', grade_num)], limit=1)
            if rec:
                rec.write(vals)
                updated += 1
            else:
                Grade.create(vals)
                created += 1
        return created, updated

    def _import_classes(self, root):
        """Import ``<class>`` elements into ``asctt.class`` (upsert by asc_id).

        Also syncs the ``classroom_ids`` many-to-many relation.
        """
        created = updated = 0
        teacher_map = self._build_asc_id_map('asctt.teacher')
        classroom_map = self._build_asc_id_map('asctt.classroom')
        Class = self.env['asctt.class']
        for el in root.findall('.//classes/class'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            if not asc_id or not name:
                continue
            classroom_ids = [
                classroom_map[i]
                for i in _split_ids(el.get('classroomids', ''))
                if i in classroom_map
            ]
            vals = {
                'name': name,
                'short': el.get('short', '').strip() or False,
                'grade': el.get('grade', '').strip() or False,
                'teacher_id': teacher_map.get(el.get('teacherid', '').strip(), False),
            }
            rec = Class.search([('asc_id', '=', asc_id)], limit=1)
            if rec:
                rec.write(vals)
                rec.classroom_ids = [(6, 0, classroom_ids)]
                updated += 1
            else:
                vals['asc_id'] = asc_id
                vals['classroom_ids'] = [(6, 0, classroom_ids)]
                Class.create(vals)
                created += 1
        return created, updated

    def _import_groups(self, root):
        """Import ``<group>`` elements into ``asctt.group`` (upsert by asc_id).

        Groups with an unknown parent ``classid`` are skipped.
        """
        created = updated = 0
        class_map = self._build_asc_id_map('asctt.class')
        for el in root.findall('.//groups/group'):
            asc_id = el.get('id', '').strip()
            name = el.get('name', '').strip()
            class_asc_id = el.get('classid', '').strip()
            if not asc_id or not name:
                continue
            class_id = class_map.get(class_asc_id)
            if not class_id:
                continue
            try:
                div_tag = int(el.get('divisiontag', '0'))
            except ValueError:
                div_tag = 0
            vals = {
                'name': name,
                'class_id': class_id,
                'entire_class': el.get('entireclass', '0') == '1',
                'division_tag': div_tag,
            }
            if self._upsert_by_asc_id('asctt.group', asc_id, vals) == 'created':
                created += 1
            else:
                updated += 1
        return created, updated

    def _import_lessons(self, root):
        """Import ``<lesson>`` elements into ``asctt.lesson`` (upsert by asc_id).

        Syncs all four many-to-many relations: ``class_ids``, ``group_ids``,
        ``teacher_ids``, and ``classroom_ids``.
        """
        created = updated = 0
        subject_map   = self._build_asc_id_map('asctt.subject')
        class_map     = self._build_asc_id_map('asctt.class')
        group_map     = self._build_asc_id_map('asctt.group')
        teacher_map   = self._build_asc_id_map('asctt.teacher')
        classroom_map = self._build_asc_id_map('asctt.classroom')
        days_def_map  = self._build_asc_id_map('asctt.days.def')
        weeks_def_map = self._build_asc_id_map('asctt.weeks.def')
        terms_def_map = self._build_asc_id_map('asctt.terms.def')
        Lesson = self.env['asctt.lesson']

        for el in root.findall('.//lessons/lesson'):
            asc_id = el.get('id', '').strip()
            if not asc_id:
                continue
            class_ids     = [class_map[i]     for i in _split_ids(el.get('classids', ''))    if i in class_map]
            group_ids     = [group_map[i]     for i in _split_ids(el.get('groupids', ''))    if i in group_map]
            teacher_ids   = [teacher_map[i]   for i in _split_ids(el.get('teacherids', ''))  if i in teacher_map]
            classroom_ids = [classroom_map[i] for i in _split_ids(el.get('classroomids', '')) if i in classroom_map]
            try:
                ppc = int(el.get('periodspercard', '0'))
            except ValueError:
                ppc = 0
            try:
                ppw = float(el.get('periodsperweek', '0'))
            except ValueError:
                ppw = 0.0
            vals = {
                'subject_id':       subject_map.get(el.get('subjectid', '').strip(), False),
                'periods_per_card': ppc,
                'periods_per_week': ppw,
                'days_def_id':      days_def_map.get(el.get('daysdefid', '').strip(), False),
                'weeks_def_id':     weeks_def_map.get(el.get('weeksdefid', '').strip(), False),
                'terms_def_id':     terms_def_map.get(el.get('termsdefid', '').strip(), False),
                'seminar_group':    el.get('seminargroup', '').strip() or False,
                'capacity':         el.get('capacity', '').strip() or False,
            }
            rec = Lesson.search([('asc_id', '=', asc_id)], limit=1)
            if rec:
                rec.write(vals)
                rec.class_ids     = [(6, 0, class_ids)]
                rec.group_ids     = [(6, 0, group_ids)]
                rec.teacher_ids   = [(6, 0, teacher_ids)]
                rec.classroom_ids = [(6, 0, classroom_ids)]
                updated += 1
            else:
                vals['asc_id']        = asc_id
                vals['class_ids']     = [(6, 0, class_ids)]
                vals['group_ids']     = [(6, 0, group_ids)]
                vals['teacher_ids']   = [(6, 0, teacher_ids)]
                vals['classroom_ids'] = [(6, 0, classroom_ids)]
                Lesson.create(vals)
                created += 1
        return created, updated

    def _import_cards(self, root):
        """Cards have no stable ID in the XML – clear all existing and recreate."""
        Card = self.env['asctt.card']
        Card.search([]).unlink()

        lesson_map    = self._build_asc_id_map('asctt.lesson')
        classroom_map = self._build_asc_id_map('asctt.classroom')

        periods = self.env['asctt.period'].search([])
        period_map = {p.period: p.id for p in periods}

        weeks_defs = self.env['asctt.weeks.def'].search([])
        weeks_def_pattern_map = {wd.weeks: wd.id for wd in weeks_defs if wd.weeks}

        to_create = []
        for el in root.findall('.//cards/card'):
            lesson_id = lesson_map.get(el.get('lessonid', '').strip())
            if not lesson_id:
                continue

            try:
                period_num = int(el.get('period', '').strip())
            except (ValueError, AttributeError):
                period_num = None
            period_id = period_map.get(period_num) if period_num is not None else False

            # Derive 1-indexed day (1=Mon … 5=Fri) from days binary pattern
            days_pattern = el.get('days', '').strip()
            day = False
            if days_pattern:
                try:
                    day = days_pattern.index('1') + 1
                except ValueError:
                    day = False

            weeks_pattern = el.get('weeks', '').strip()
            weeks_def_id = weeks_def_pattern_map.get(weeks_pattern, False) if weeks_pattern else False

            classroom_ids = [
                classroom_map[i]
                for i in _split_ids(el.get('classroomids', ''))
                if i in classroom_map
            ]
            to_create.append({
                'lesson_id':    lesson_id,
                'period_id':    period_id,
                'day':          day,
                'weeks_def_id': weeks_def_id,
                'classroom_ids': [(6, 0, classroom_ids)],
            })

        if to_create:
            Card.create(to_create)
        return len(to_create), 0

    def _import_supervisions(self, root):
        """Import ``<classroomsupervision>`` elements into ``asctt.classroom.supervision``.

        Because supervision records have no stable XML ID, all existing records
        are deleted and the full set is recreated on every import.

        The ``day`` attribute is a 0-indexed integer (0 = Monday).  It is
        stored directly on the record and also used to attempt a lookup of a
        matching single-day ``asctt.days.def`` record via ``_DAY_PATTERNS``
        (e.g. ``'10000'`` for Monday).  If no matching days_def exists in the
        database, ``days_def_id`` is left False while ``day`` retains the raw
        integer for use by the flat-row SQL view.

        Supervisions that reference an unknown ``classroomid`` are skipped.
        """
        Supervision = self.env['asctt.classroom.supervision']
        Supervision.search([]).unlink()

        teacher_map   = self._build_asc_id_map('asctt.teacher')
        classroom_map = self._build_asc_id_map('asctt.classroom')

        periods = self.env['asctt.period'].search([])
        period_map = {p.period: p.id for p in periods}

        weeks_defs = self.env['asctt.weeks.def'].search([])
        weeks_def_pattern_map = {wd.weeks: wd.id for wd in weeks_defs if wd.weeks}

        # Build days_def map from single-day patterns (e.g. "10000" → Monday)
        days_defs = self.env['asctt.days.def'].search([])
        days_def_pattern_map = {dd.days: dd.id for dd in days_defs if dd.days and ',' not in dd.days}

        to_create = []
        for el in root.findall('.//classroomsupervisions/classroomsupervision'):
            classroom_id = classroom_map.get(el.get('classroomid', '').strip())
            if not classroom_id:
                continue

            teacher_asc_id = el.get('teacherid', '').strip()
            teacher_id = teacher_map.get(teacher_asc_id, False) if teacher_asc_id else False

            try:
                period_num = int(el.get('period', '').strip())
                period_id = period_map.get(period_num, False)
            except (ValueError, AttributeError):
                period_id = False

            day_str = el.get('day', '').strip()
            days_def_id = False
            raw_day = -1
            if day_str:
                try:
                    day_int = int(day_str)
                    raw_day = day_int
                    if 0 <= day_int <= 4:
                        days_def_id = days_def_pattern_map.get(_DAY_PATTERNS[day_int], False)
                except ValueError:
                    pass

            week_str = el.get('week', '').strip()
            weeks_def_id = weeks_def_pattern_map.get(week_str, False) if week_str else False

            to_create.append({
                'teacher_id':   teacher_id,
                'classroom_id': classroom_id,
                'period_id':    period_id,
                'day':          raw_day,
                'days_def_id':  days_def_id,
                'weeks_def_id': weeks_def_id,
            })

        if to_create:
            Supervision.create(to_create)
        return len(to_create), 0

    # ── Timetable entry generation ─────────────────────────────────────────────

    def _generate_timetable_entries(self):
        """Generate ``aps.timetable.entry`` records from the current ``asctt.card`` data.

        Maps the abstract aSc timetable (day + period + weeks pattern) to real
        calendar dates using ``aps.school.calendar`` school-day records.  One
        entry is created per (teacher, card, matching school day) combination.

        :returns: Number of entries created.
        """
        self.ensure_one()
        TimetableEntry = self.env['aps.timetable.entry']

        # 1. Determine the effective date range ─────────────────────────────────
        start_date = self.apply_from_date
        term = self.apply_to_term_id
        if term:
            start_date = max(start_date, term.start_date)
            end_date = term.end_date
        else:
            # Fall back to current academic year end, or 52 weeks ahead
            current_year = self.env['aps.academic.year'].search(
                [('is_current', '=', True)], limit=1
            )
            end_date = current_year.end_date if current_year else (
                start_date.replace(year=start_date.year + 1)
            )

        # 2. Delete existing entries that overlap the new range ─────────────────
        if term:
            TimetableEntry.search([('academic_term_id', '=', term.id)]).unlink()
        else:
            TimetableEntry.search([
                ('start_datetime', '>=', datetime.combine(start_date, dt_time.min)),
            ]).unlink()

        # 3. Build school-day lookup: date → academic week ──────────────────────
        school_days = self.env['aps.school.calendar'].search([
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('date_type', '=', 'school_day'),
        ])
        # {date: week_cycle_str_or_None}
        date_to_cycle = {
            sc.date: (sc.week_id.week_cycle if sc.week_id else '')
            for sc in school_days
        }
        if not date_to_cycle:
            return 0  # no school days in range – nothing to generate

        # 4. Group school days by weekday for fast lookup ───────────────────────
        # weekday_to_dates[0] = list of Monday school dates, etc.
        from collections import defaultdict
        weekday_to_dates = defaultdict(list)
        for d in date_to_cycle:
            weekday_to_dates[d.weekday()].append(d)

        # 5. Timezone for local time → UTC conversion ───────────────────────────
        tz_name = self.env.company.partner_id.tz or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)

        # 6. Iterate cards ───────────────────────────────────────────────────────
        cards = self.env['asctt.card'].search([])
        to_create = []

        for card in cards:
            if not card.lesson_id:
                continue
            lesson = card.lesson_id

            # Teachers linked to APEX with a partner
            teachers = [
                at.aps_teacher_id
                for at in lesson.teacher_ids
                if at.aps_teacher_id and at.aps_teacher_id.partner_id
            ]
            if not teachers:
                continue

            # Subject category and name
            subject_cat = (
                lesson.subject_id.aps_subject_category_id
                if lesson.subject_id else None
            )
            subject_name = lesson.subject_id.name if lesson.subject_id else ''

            # Period times
            if not card.period_id:
                continue
            starttime_str = card.period_id.starttime or ''
            endtime_str = card.period_id.endtime or ''
            try:
                start_h, start_m = map(int, starttime_str.split(':'))
                end_h, end_m = map(int, endtime_str.split(':'))
            except (ValueError, AttributeError):
                continue

            # Weeks pattern
            weeks_pattern = card.weeks_def_id.weeks if card.weeks_def_id else ''

            # card.day is 1-indexed (1=Mon … 5=Fri); weekday() is 0-indexed
            target_weekday = (card.day or 0) - 1
            if target_weekday < 0 or target_weekday > 4:
                continue

            class_names = ', '.join(
                cl.name for cl in lesson.class_ids if cl.name
            )
            classroom = ', '.join(
                cr.name for cr in card.classroom_ids if cr.name
            )
            entry_name = f"{subject_name} – {class_names}" if class_names else subject_name or 'Lesson'

            # 7. Match against school days ────────────────────────────────────
            for sc_date in weekday_to_dates.get(target_weekday, []):
                cycle = date_to_cycle.get(sc_date, '')
                if not _weeks_cycle_match(weeks_pattern, cycle):
                    continue

                # Build UTC datetimes
                local_start = datetime.combine(sc_date, dt_time(start_h, start_m))
                local_end = datetime.combine(sc_date, dt_time(end_h, end_m))
                utc_start = user_tz.localize(local_start).astimezone(pytz.utc).replace(tzinfo=None)
                utc_end = user_tz.localize(local_end).astimezone(pytz.utc).replace(tzinfo=None)

                for teacher in teachers:
                    to_create.append({
                        'name': entry_name,
                        'teacher_id': teacher.id,
                        'partner_ids': [(4, teacher.partner_id.id)],
                        'subject_category_id': subject_cat.id if subject_cat else False,
                        'start_datetime': utc_start,
                        'stop_datetime': utc_end,
                        'classroom': classroom or False,
                        'class_names': class_names or False,
                        'subject_name': subject_name or False,
                        'academic_term_id': term.id if term else False,
                        'source_card_id': card.id,
                    })

        if to_create:
            TimetableEntry.create(to_create)
        return len(to_create)
