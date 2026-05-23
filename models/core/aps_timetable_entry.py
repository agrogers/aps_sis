from odoo import api, fields, models


class APSTimetableEntry(models.Model):
    """One lesson occurrence on a real calendar date.

    Generated from ``asctt.card`` records by
    ``asctt.import.wizard._generate_timetable_entries()``.  One record is
    created per (teacher, card, matching school day) combination so that the
    Odoo calendar view can render each teacher's timetable independently.
    """

    _name = 'aps.timetable.entry'
    _description = 'School Timetable Entry'
    _order = 'start_datetime, teacher_id'

    name = fields.Char(string='Title', required=True)

    # ── Teacher ───────────────────────────────────────────────────────────────
    teacher_id = fields.Many2one(
        'aps.teacher',
        string='Teacher',
        required=True,
        ondelete='cascade',
        index=True,
    )
    # Stored related so that the calendar filter sidebar can group by partner.
    partner_id = fields.Many2one(
        'res.partner',
        related='teacher_id.partner_id',
        store=True,
        string='Teacher Contact',
        index=True,
    )
    # Many2many required by the Odoo calendar view's write_model sidebar.
    # Always contains the single teacher partner (makes the calendar filter work).
    partner_ids = fields.Many2many(
        'res.partner',
        'aps_timetable_entry_partner_rel',
        'entry_id',
        'partner_id',
        string='Attendees',
        compute='_compute_partner_ids',
        store=True,
    )

    # ── Subject / colour ──────────────────────────────────────────────────────
    subject_category_id = fields.Many2one(
        'aps.subject.category',
        string='Subject Category',
        ondelete='set null',
        index=True,
    )
    # Integer colour index (0-10) driven by the subject category.
    # Used by the Odoo calendar view ``color`` attribute.
    color = fields.Integer(
        related='subject_category_id.color',
        store=True,
        string='Color Index',
    )
    subject_name = fields.Char(string='Subject')

    # ── Time ──────────────────────────────────────────────────────────────────
    start_datetime = fields.Datetime(string='Start', required=True, index=True)
    stop_datetime = fields.Datetime(string='End', required=True)

    # ── Details ───────────────────────────────────────────────────────────────
    classroom = fields.Char(string='Classroom')
    class_names = fields.Char(string='Classes')

    # ── Context ───────────────────────────────────────────────────────────────
    academic_term_id = fields.Many2one(
        'aps.academic.term',
        string='Term',
        ondelete='set null',
        index=True,
    )
    source_card_id = fields.Many2one(
        'asctt.card',
        string='Source Card',
        ondelete='set null',
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('teacher_id.partner_id')
    def _compute_partner_ids(self):
        for rec in self:
            partner = rec.teacher_id.partner_id
            rec.partner_ids = [(6, 0, [partner.id])] if partner else [(5,)]
