import { Component, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const STORAGE_KEY = "aps_teacher_classes_show_all_years";

export class LocalStorageBooleanField extends Component {
    static template = "aps_sis.LocalStorageBooleanField";
    static props = { ...standardFieldProps };

    setup() {
        onWillStart(() => {
            try {
                const value = localStorage.getItem(STORAGE_KEY);
                if (value === "true" || value === "false") {
                    return this.props.update(value === "true");
                }
            } catch (error) {}
        });
    }

    get value() {
        return Boolean(this.props.value);
    }

    onChange(event) {
        const value = event.target.checked;
        this.props.update(value);
        try {
            localStorage.setItem(STORAGE_KEY, String(value));
        } catch (error) {}
    }
}

registry.category("fields").add("local_storage_boolean", {
    component: LocalStorageBooleanField,
    supportedTypes: ["boolean"],
});
