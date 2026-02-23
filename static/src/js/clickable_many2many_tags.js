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
    static props = {
        ...Many2ManyTagsField.props,
        no_add: { type: Boolean, optional: false },
        no_open: { type: Boolean, optional: false },
    };
    static template = xml`
        <div
            class="o_field_widget o_field_many2many_tags o_field_clickable_many2many_tags"
            t-att-class="{'o_tags_input o_input': !props.readonly and !props.no_add}"
            t-ref="many2ManyTagsField"
        >
            <div class="o_field_tags d-inline-flex flex-wrap gap-1 mw-100 o_tags_input o_input">
                <TagsList tags="tags"/>
                <div t-if="!props.no_add and showM2OSelectionField" style="width: auto !important" class="o_field_many2many_selection d-inline-flex w-100" t-ref="autoComplete">
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
        if (this.props.no_open) {
            return props;
        }
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
    extractProps(params) {
        // We MUST pass both arguments to the base extractProps using ...arguments
        // This prevents the 'no_create' undefined error because it passes the 'field' object
        const props = many2ManyTagsField.extractProps(...arguments);
        props.no_add = params.attrs.no_add === "1" || params.attrs.no_add === "True";
        props.no_open = params.attrs.no_open === "1" || params.attrs.no_open === "True";
        return props;
    },
};

registry.category("fields").add("clickable_many2many_tags", clickableMany2ManyTags);