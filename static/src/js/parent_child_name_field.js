import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class ParentChildNameField extends Component {
    static template = "aps_sis.ParentChildNameField";
    static props = { ...standardFieldProps };

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

    get hideCreate() {
        // Read widget options from attrs if present: options={'hide_create': True}
        const attrs = this.props.attrs || (this.props.record && this.props.record.fields && this.props.record.fields[this.props.name] && this.props.record.fields[this.props.name].attrs) || null;
        if (!attrs) return false;
        const options = attrs.options || {};
        // Accept boolean True, 1, or string representations
        return options.hide_create === true || options.hide_create === 1 || options.hide_create === '1' || options.hide_create === 'True' || options.hide_create === 'true';
    }

    async onClick() {
        if (this.name_id) {
            // Open existing custom name in a popup form and wait for it to close
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'aps.resource.custom.name',
                res_id: this.name_id,
                views: [[false, 'form']],
                target: 'new',
            };
            await this._openCustomNameForm(action);
            return;
        }
        // If there is no existing entry and the widget is configured to hide create, do nothing
        if (this.hideCreate) {
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
            await this._openCustomNameForm(action);
        } catch (e) {
            this.notification.add({ title: 'Error', message: e.message || 'Could not open custom name form', type: 'danger' });
        }
    }

    async _openCustomNameForm(action) {
        // action is the act_window used to open the custom-name form (target: 'new')
        try {
            await this.env.services.action.doAction(action);
            // After the popup closes, fetch latest data directly from DB and update pill
            await this._fetchAndUpdate();
        } catch (e) {
            // ignore user cancelled dialog
        }
    }

    async _fetchAndUpdate() {
        try {
            const pid = this.parent_id;
            const rid = this.resource_id;
            if (!pid || !rid) {
                this.state.liveName = false;
                this.state.liveId = false;
                return;
            }
            const res = await rpc({
                model: 'aps.resource.custom.name',
                method: 'search_read',
                args: [[['parent_resource_id','=',pid], ['resource_id','=',rid]] , ['id','custom_name']],
                kwargs: {limit: 1},
            });
            if (res && res.length) {
                this.state.liveName = res[0].custom_name;
                this.state.liveId = String(res[0].id);
            } else {
                this.state.liveName = false;
                this.state.liveId = false;
            }
        } catch (e) {
            // On error clear live values
            this.state.liveName = false;
            this.state.liveId = false;
        }
    }
}

export const parentChildNameField = {
    component: ParentChildNameField,
    supportedTypes: ["char"],
    extractProps() { return {}; },
};

registry.category('fields').add('parent_child_name_pill', parentChildNameField);
