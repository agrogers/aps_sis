import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class ParentChildNameField extends Component {
    static template = "aps_sis.ParentChildNameField";
    static props = { ...standardFieldProps,
        enabled: { type: Boolean, optional: true },
     };

    setup() {
        this.action = useService('action');
        this.notification = useService('notification');
        this.state = useState({ liveName: false, liveId: false });
    }

    get name() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return false;
        let data = [];
        if (typeof raw === 'string') {
            try {
                data = JSON.parse(raw);
            } catch (e) {
                return false;
            }
        } else if (Array.isArray(raw)) {
            data = raw;
        }
        const pid = this.parent_id;
        if (!pid) return false;
        // Prefer live fetched name if present
        if (this.state.liveName !== false) {
            return this.state.liveName || false;
        }
        const entry = data.find(e => String(e.parent_resource_id) === String(pid));
        return entry ? entry.custom_name : false;
    }

    get name_id() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return false;
        let data = [];
        if (typeof raw === 'string') {
            try { data = JSON.parse(raw); } catch (e) { return false; }
        } else if (Array.isArray(raw)) { data = raw; }
        const pid = this.parent_id;
        if (!pid) return false;
        // Prefer fetched id
        if (this.state.liveId) {
            return this.state.liveId;
        }
        const entry = data.find(e => String(e.parent_resource_id) === String(pid));
        return entry ? entry.id : false;
    }

    get parent_id() {
        // Prefer explicit value computed on the record (backwards compat),
        // otherwise try to read the context passed to this field in the view.
 
        const fromRecord = this.props.record && this.props.record.data && this.props.record.data['parent_resource_id'];
        if (fromRecord) {
            return this.props.record.data['parent_resource_id'][0];
        }

        const attrs = this.props.attrs || (this.props.record && this.props.record.fields && this.props.record.fields[this.props.name] && this.props.record.fields[this.props.name].attrs) || null;
        if (attrs && attrs.context && attrs.context.current_parent_id) {
            return attrs.context.current_parent_id;
        }

        // This is the one that works. 
        const recContext = this.props.record && this.props.record.context;
        if (recContext && recContext.current_parent_id) {
            return recContext.current_parent_id;
        }
        return false;
    }

    get resource_id() {
        // record res id is available as this.props.record.resId
        return this.props.record.resId || this.props.record.id || false;
    }

    get enabled() {
        if (this.props.enabled === undefined) return true;
        return this.props.enabled === true || this.props.enabled === 1 || this.props.enabled === '1' || this.props.enabled === 'True' || this.props.enabled === 'true';
    }

    async onClick() {
        if (!this.enabled) { return; }
        if (this.name_id ) {
            // Open existing custom name in a popup form and wait for it to close
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'aps.resource.custom.name',
                res_id: this.name_id,
                views: [[false, 'form']],
                target: 'new',
            };
            this.action.doAction(action);
            return;
        }

        // Open a creation form for this parent/resource pair using action with context defaults (avoid rpc service)
        try {
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'aps.resource.custom.name',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                context: {
                    default_parent_resource_id: this.parent_id,
                    default_resource_id: this.resource_id,
                    default_custom_name: '',
                },
            };
            this.action.doAction(action);
        } catch (e) {
            this.notification.add({ title: 'Error', message: e.message || 'Could not open custom name form', type: 'danger' });
        }
    }
}

export const parentChildNameField = {
    component: ParentChildNameField,
    supportedTypes: ["char"],
    extractProps({ options }) {
        return {
            enabled: options.enabled ?? true,
        };
    },};

registry.category('fields').add('parent_child_name_pill', parentChildNameField);
