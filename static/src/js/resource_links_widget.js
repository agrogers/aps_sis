import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export class ResourceLinksField extends Component {
    static template = "aps_sis.ResourceLinksField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
        this.action = useService("action"); // Ensure this is here
    }

    get links() {
        const value = this.props.record.data[this.props.name];
        if (!value) return [];
        // Handle both string JSON and already-parsed array
        if (typeof value === 'string') {
            try {
                return JSON.parse(value);
            } catch (e) {
                return [];
            }
        }
        return Array.isArray(value) ? value : [];
    }

    openUrl(linkData) {
        const url = typeof linkData === 'string' ? linkData : linkData.url;
        
        if (!url) return;

        // Check if the URL is meant to trigger an Odoo Client Action
        // Example URL format: "action:lonely_s_game"
        if (url.startsWith("action:")) {
            const actionTag = url.replace("action:", "");
            this.action.doAction(actionTag, {
                additionalContext: {
                    active_id: this.props.record.resId,
                    active_model: this.props.record.resModel,
                    out_of_marks: this.props.record.data.out_of_marks || 10,
                    submission_state: this.props.record.data.state
                },
                target: 'new'
            });
        } 
        // Check if it's a standard Odoo internal path
        else if (url.startsWith("/") || url.includes(window.location.origin)) {
            // Keep it inside the Odoo SPA
            window.location.href = url; 
        } 
        // External links
        else {
            window.open(url, "_blank"); // Open external sites in a new tab
        }
    }

    getIconSrc(icon) {
        if (icon) {
            return `data:image/png;base64,${icon}`;
        }
        return false;
    }
}

export const resourceLinksField = {
    component: ResourceLinksField,
    supportedTypes: ["json"],
    extractProps({ attrs }) {
        return {};
    },
};

registry.category("fields").add("resource_links", resourceLinksField);
