import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { user } from "@web/core/user";

/* ─── Avatar Picker Dialog ─── */

class AvatarPickerDialog extends Component {
    static template = "aps_sis.AvatarPickerDialog";
    static components = { Dialog };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            categories: [],
            avatars: [],
            filtered: [],
            activeCat: false,
            query: "",
        });

        onWillStart(async () => {
            const [categories, avatars] = await Promise.all([
                this.orm.searchRead(
                    "aps.avatar.category", [], ["id", "name"], { order: "name" }
                ),
                this.orm.searchRead(
                    "aps.avatar", [], ["id", "name", "category_id"],
                    { order: "category_id, name" }
                ),
            ]);
            this.state.categories = categories;
            this.state.avatars = avatars;
            this.applyFilters();
        });
    }

    imageUrl(id) {
        return `/web/image/aps.avatar/${encodeURIComponent(id)}/image/96x96`;
    }

    onSearch(ev) {
        this.state.query = ev.target.value.toLowerCase();
        this.applyFilters();
    }

    filterCategory(catId) {
        this.state.activeCat = this.state.activeCat === catId ? false : catId;
        this.applyFilters();
    }

    showAll() {
        this.state.activeCat = false;
        this.applyFilters();
    }

    applyFilters() {
        let list = this.state.avatars;
        const cat = this.state.activeCat;
        const q = this.state.query;
        if (cat) {
            list = list.filter((a) => a.category_id && a.category_id[0] === cat);
        }
        if (q) {
            list = list.filter((a) => a.name.toLowerCase().includes(q));
        }
        this.state.filtered = list;
    }

    pick(avatar) {
        this.props.onSelect(avatar.id, avatar.name);
        this.props.close();
    }

    clear() {
        this.props.onSelect(false, "");
        this.props.close();
    }
}

/* ─── Avatar Selector Field Widget ─── */

class AvatarSelectorField extends Component {
    static template = "aps_sis.AvatarSelectorField";
    static props = { ...standardFieldProps };

    setup() {
        this.dialogService = useService("dialog");
    }

    get avatarId() {
        const v = this.props.record.data[this.props.name];
        if (!v) return false;
        if (Array.isArray(v)) return v[0];
        if (typeof v === "object") return v.id || v.resId || false;
        if (typeof v === "number") return v;
        return false;
    }

    get avatarName() {
        const v = this.props.record.data[this.props.name];
        if (!v) return "";
        if (Array.isArray(v)) return v[1] || "";
        if (typeof v === "object") return v.display_name || "";
        return "";
    }

    get imageUrl() {
        const id = this.avatarId;
        return id ? `/web/image/aps.avatar/${encodeURIComponent(id)}/image/30x30` : false;
    }

    openPicker() {
        if (this.props.readonly) return;
        this.dialogService.add(AvatarPickerDialog, {
            currentId: this.avatarId,
            onSelect: (id, name) => {
                this.props.record.update({
                    [this.props.name]: id ? [id, name] : false,
                });
                // If editing the current user's profile, notify systray
                const recModel = this.props.record.resModel;
                const recId = this.props.record.resId;
                if ((recModel === "res.users" && recId === user.userId) ||
                    (recModel === "op.student")) {
                    this.env.bus.dispatchEvent(
                        new CustomEvent("aps-avatar-changed", { detail: id })
                    );
                }
            },
        });
    }
}

export const avatarSelectorField = {
    component: AvatarSelectorField,
    supportedTypes: ["many2one"],
};

registry.category("fields").add("avatar_selector", avatarSelectorField);
