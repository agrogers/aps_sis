import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

class AvatarBulkUpload extends Component {
    static template = "aps_sis.AvatarBulkUpload";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            categoryId: false,
            categories: [],
            files: [],       // {name, dataUrl, data (base64 without prefix)}
            uploading: false,
        });

        onWillStart(async () => {
            const cats = await this.orm.searchRead(
                "aps.avatar.category",
                [],
                ["id", "name"],
                { order: "name" }
            );
            this.state.categories = cats;
        });
    }

    onCategoryChange(ev) {
        this.state.categoryId = parseInt(ev.target.value) || false;
    }

    onFileSelect(ev) {
        const input = ev.target;
        if (!input.files || !input.files.length) return;

        const promises = [];
        for (const file of input.files) {
            if (!file.type.startsWith("image/")) continue;
            promises.push(this._readFile(file));
        }

        Promise.all(promises).then((results) => {
            this.state.files.push(...results);
        });

        // reset input so the same files can be re-selected
        input.value = "";
    }

    _readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const dataUrl = reader.result;
                // Strip the data:image/...;base64, prefix
                const base64 = dataUrl.split(",")[1] || "";
                resolve({ name: file.name, dataUrl, data: base64 });
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    removeFile(index) {
        this.state.files.splice(index, 1);
    }

    clearAll() {
        this.state.files = [];
    }

    async upload() {
        if (!this.state.files.length) return;
        this.state.uploading = true;
        try {
            const payload = this.state.files.map((f) => ({
                name: f.name,
                data: f.data,
            }));
            const result = await this.orm.call(
                "aps.avatar",
                "bulk_create_from_files",
                [payload, this.state.categoryId]
            );
            this.notification.add(
                _t("%s avatar(s) uploaded successfully.", result.count),
                { type: "success" }
            );
            // Navigate to the created avatars
            if (result.ids.length === 1) {
                this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "aps.avatar",
                    res_id: result.ids[0],
                    views: [[false, "form"]],
                });
            } else {
                this.action.doAction({
                    type: "ir.actions.act_window",
                    name: _t("Uploaded Avatars"),
                    res_model: "aps.avatar",
                    domain: [["id", "in", result.ids]],
                    views: [
                        [false, "list"],
                        [false, "form"],
                    ],
                });
            }
        } catch (e) {
            this.notification.add(
                _t("Upload failed: %s", e.message || e),
                { type: "danger" }
            );
        } finally {
            this.state.uploading = false;
        }
    }
}

registry.category("actions").add("aps_avatar_bulk_upload", AvatarBulkUpload);
