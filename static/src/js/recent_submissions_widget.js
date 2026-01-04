/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { xml } from "@odoo/owl";
import { markup } from "@odoo/owl";

export class RecentSubmissionsField extends CharField {
    static template = xml`
        <div class="d-flex flex-wrap gap-1">
            <t t-foreach="this.pills" t-as="pill" t-key="pill_index">
                <button type="button"
                        t-on-click="() => this.openRecord(pill)"
                        t-att-class="'badge ' + pill.color + ' text-decoration-none '"
                        title=""
                        data-bs-toggle=""
                        data-tooltip="">
                    <t t-esc="pill.text"/>
                </button>
            </t>
        </div>
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
        const raw = this.props.record.data[this.props.name] || '{"pills": []}';
        const data = JSON.parse(raw);
        this.pills = data.pills || [];
    }

       
    openRecord(pill) {
         this.env.services.action.doAction({
        type: 'ir.actions.act_window',
        res_model: pill.res_model,
        res_id: pill.id,
        views: [[false, 'form']],
        target: 'current',
        });
    };
}  

export const recentSubmissionsField = {
    ...charField,
    component: RecentSubmissionsField,
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

registry.category("fields").add("recent_submissions", recentSubmissionsField);
