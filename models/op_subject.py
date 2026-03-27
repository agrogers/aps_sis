from odoo import fields, models, api


class OpSubject(models.Model):
    _inherit = 'op.subject'
    _order = 'name'
    # teachers_ids = fields.Many2many(
    #     'op.faculty',
    #     relation='op_subject_teachers_rel',
    #     string='Teachers',
    #     help='Faculty members teaching this subject'
    # )

    # assistant_teachers_ids = fields.Many2many(
    #     'op.faculty',
    #     relation='op_subject_assistant_teachers_rel',
    #     string='Assistant Teachers',
    #     help='Assistant faculty members for this subject'
    # )

    faculty_ids = fields.Many2many(
        'op.faculty',
        relation='op_faculty_op_subject_rel',
        column1='op_subject_id',
        column2='op_faculty_id',
        string='Faculty Members',
        help='Faculty members linked to this subject'
    )
    icon = fields.Image(
        string="Icon",
        max_width=64,
        max_height=64,
        help="Subject icon (e.g. for visual identification in lists)"
    )
    category_id = fields.Many2one(
        'aps.subject.category',
        string='Subject Category',
        help='Category this subject belongs to'
    )

    @staticmethod
    def _generate_color_from_name(name):
        """
        Generate a deterministic hex color based on a string.
        Uses string hash to ensure same name always produces same color.
        
        Args:
            name: String to generate color from (e.g., subject name)
        
        Returns:
            Hex color string (e.g., '#FF5733')
        """
        if not name:
            return '#6c757d'
        
        # Generate simple hash from string
        hash_val = sum(ord(c) for c in str(name))
        
        # Use hash to generate HSL color with good saturation and lightness
        hue = (hash_val % 360)  # 0-360 for hue
        saturation = 70 + (hash_val % 20)  # 70-90% for vibrant colors
        lightness = 45 + ((hash_val // 360) % 15)  # 45-60% for readable colors
        
        # Convert HSL to RGB
        import colorsys
        rgb = colorsys.hls_to_rgb(hue / 360.0, lightness / 100.0, saturation / 100.0)
        
        # Convert RGB (0-1) to hex (0-255)
        r = int(rgb[0] * 255)
        g = int(rgb[1] * 255)
        b = int(rgb[2] * 255)
        
        return f'#{r:02x}{g:02x}{b:02x}'

    @api.model
    def get_subject_colors_map(self, subject_ids=None):
        """
        Get a mapping of subject IDs to their category colors.
        Used by dashboard to ensure consistent coloring across charts.
        Generates deterministic colors based on subject names if no color is specified.
        
        Args:
            subject_ids: List of subject IDs to get colors for. If None, gets all subjects.
        
        Returns:
            Dict mapping subject_id -> color_rgb (hex color string)
        """
        domain = [('id', 'in', subject_ids)] if subject_ids else []
        subjects = self.search(domain)
        
        color_map = {}
        for subject in subjects:
            if subject.category_id and subject.category_id.color_rgb:
                # Use category color if specified
                color_map[subject.id] = subject.category_id.color_rgb
            else:
                # Generate color based on subject name
                color_map[subject.id] = self._generate_color_from_name(subject.name)
        
        return color_map