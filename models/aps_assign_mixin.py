from odoo import api, models


class APSAssignMixin(models.AbstractModel):
    _name = 'aps.assign.mixin'
    _description = 'APEX Assignment Shared Logic'

    def _assign_students_field_name(self):
        raise NotImplementedError()

    def _assign_resources_field_name(self):
        raise NotImplementedError()

    def _set_assign_students(self, student_partner_ids):
        field_name = self._assign_students_field_name()
        field = self._fields[field_name]

        if field.type == 'many2many':
            return [(6, 0, student_partner_ids)]

        if field.type == 'one2many':
            return [(5, 0, 0)] + [(0, 0, {'student_id': pid}) for pid in student_partner_ids]

        return False

    def _set_assign_resources(self, resource_ids):
        field_name = self._assign_resources_field_name()
        field = self._fields[field_name]
        commands = [(5, 0, 0)]
        sequence = 10
        
        # Get the comodel to check which fields exist
        comodel = self.env[field.comodel_name]
        
        for resource_id in resource_ids:
            vals = {
                'resource_id': resource_id,
                'sequence': sequence,
            }
            # Only add optional fields if they exist on the target model
            if 'parent_resource_id' in comodel._fields:
                vals['parent_resource_id'] = self.resource_id.id if hasattr(self, 'resource_id') else False
            if 'selected' in comodel._fields:
                vals['selected'] = True
            
            commands.append((0, 0, vals))
            sequence += 10

        if field.type == 'many2many':
            return [(6, 0, resource_ids)]

        if field.type == 'one2many':
            return commands

        return False

    @api.onchange('subjects')
    def _onchange_subjects_shared(self):
        for rec in self:
            if not rec.subjects:
                rec[self._assign_students_field_name()] = False
                continue

            students = rec.env['op.student'].search([
                ('course_detail_ids.state', '=', 'running'),
                ('course_detail_ids.subject_ids', 'in', rec.subjects.ids),
            ])
            student_partner_ids = students.mapped('partner_id').ids
            rec[self._assign_students_field_name()] = rec._set_assign_students(student_partner_ids)

    @api.onchange('resource_id')
    def _onchange_resource_id_shared(self):
        for rec in self:
            if rec.resource_id:
                all_descendants = rec.resource_id._get_all_descendants()
                resource_ids = [rec.resource_id.id] + all_descendants.ids
                rec[self._assign_resources_field_name()] = rec._set_assign_resources(resource_ids)
            else:
                rec[self._assign_resources_field_name()] = False
