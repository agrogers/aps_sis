import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useRecordObserver } from "@web/model/relational_model/utils";

const STORAGE_KEY = "aps_teacher_classes_show_all_years";

export class LocalStorageBooleanField extends Component {
    static template = "aps_sis.LocalStorageBooleanField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({});
        useRecordObserver((record) => {
            this.state.value = record.data[this.props.name];
        });
        onWillStart(() => {
            try {
                const value = localStorage.getItem(STORAGE_KEY);
                if (value === "true" || value === "false") {
                    return this.props.record.update({ [this.props.name]: value === "true" });
                }
            } catch (error) {}
        });
    }

    get value() {
        return Boolean(this.state.value);
    }

    onChange(event) {
        const value = event.target.checked;
        this.state.value = value;
        this.props.record.update({ [this.props.name]: value });
        try {
            localStorage.setItem(STORAGE_KEY, String(value));
        } catch (error) {}
    }
}

registry.category("fields").add("local_storage_boolean", {
    component: LocalStorageBooleanField,
    supportedTypes: ["boolean"],
});
