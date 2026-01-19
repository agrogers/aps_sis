/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";

class ClickableMany2ManyTagsField extends Many2ManyTagsField {
    getTagProps(record) {
        const props = super.getTagProps(record);
        // Override the onClick to open the record instead of removing
        props.onClick = (ev) => {
            ev.stopPropagation();
            this.env.services.action.doAction({
                type: 'ir.actions.act_window',
                res_model: this.relation,
                res_id: record.resId,
                views: [[false, 'form']],
            });
        };
        return props;
    }
}

export const clickableMany2ManyTags = {
    ...many2ManyTagsField,
    component: ClickableMany2ManyTagsField,
};

registry.category("fields").add("clickable_many2many_tags", clickableMany2ManyTags);