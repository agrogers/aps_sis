import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export class ResourceLinksField extends Component {
    static template = "aps_sis.ResourceLinksField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
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

    openUrl(url) {
        if (url) {
            window.location.href = url;
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
