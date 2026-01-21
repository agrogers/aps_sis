/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";
import { TagsList } from "@web/core/tags_list/tags_list";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { xml } from "@odoo/owl";

class ClickableMany2ManyTagsField extends Many2ManyTagsField {
    static template = xml`
        <div
            class="o_field_widget o_field_many2many_tags o_field_clickable_many2many_tags"
            t-att-class="{'o_tags_input o_input': !props.readonly}"
            t-ref="many2ManyTagsField"
        >
            <div class="o_field_tags d-inline-flex flex-wrap gap-1 mw-100 o_tags_input o_input">
                <TagsList tags="tags"/>
                <div t-if="showM2OSelectionField" style="width: auto !important" class="o_field_many2many_selection d-inline-flex w-100" t-ref="autoComplete">
                    <Many2XAutocomplete
                        id="props.id"
                        placeholder="tags.length ? '' : props.placeholder"
                        resModel="relation"
                        autoSelect="true"
                        fieldString="string"
                        activeActions="activeActions"
                        update="update"
                        quickCreate="activeActions.create ? quickCreate : null"
                        context="props.context"
                        getDomain.bind="getDomain"
                        isToMany="true"
                        nameCreateField="props.nameCreateField"
                        noSearchMore="props.noSearchMore"
                        getOptionClassnames.bind="getOptionClassnames"
                    />
                </div>
            </div>
        </div>
    `;

    getTagProps(record) {
        const props = super.getTagProps(record);
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