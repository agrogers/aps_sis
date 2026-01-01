/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { xml } from "@odoo/owl";
import { markup } from "@odoo/owl";

export class UrlIconField extends CharField {
    // static template = "web.CharField";
    static template = xml`
        <t t-if="props.html">
            <div class="o_field_html_char">
                <t t-out="formattedHtml"/>
            </div>
        </t>
        <t t-else="">
            <CharField t-props="{
                record:props.record,
                name:props.name,
                readonly: props.readonly
                }"/>
        </t>
    `;

    static props = {
        ...CharField.props,
        resModel: { type: String, optional: true },
        onlySearchable: { type: Boolean, optional: true },
        followRelations: { type: Boolean, optional: true },
        html: { type: Boolean, optional: true },
    };

    static components = { CharField };

    setup() {
        super.setup();
    } 

    get formattedHtml() {
        
        const url = this.props.record._values.url
        // if (this.env.config?.viewType === "list" && url) {
        if (this.props.html && url) {
            return markup(`<a href="${url}" target="_blank" title="${url}">
                        <i class="fa fa-external-link"></i>
                    </a>`);
        }
        // For form view, return normal value
        return url || "";
    }      
 
}

export const urlIconField = {
    ...charField,
    component: UrlIconField,
    supportedOptions: [
        {
            label: "HTML",
            name: "html",
            type: "boolean",
            default: false,
        },
    ],
    extractProps({ options }) {
        return {
            html: options.html ?? false,
        };
    },
};

registry.category("fields").add("url_icon", urlIconField);
