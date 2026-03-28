import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * APEX Media — Bulk Upload client action.
 *
 * Mirrors the avatar bulk-upload pattern (avatar_bulk_upload.js) but for
 * aps.media items.  Extra features over the avatar version:
 *
 *  - Collection: select an existing one OR type a new name to create it.
 *  - Categories: check any number of existing ones OR type new names
 *                (comma-separated) to create them on the fly.
 *  - Cost (points) and initial stock_available fields.
 *
 * After upload the view navigates to the newly created media items so the
 * calling list / kanban view is refreshed automatically.
 */
class MediaBulkUpload extends Component {
    static template = "aps_sis.MediaBulkUpload";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            // Type
            types: [],
            typeId: false,              // id of selected media type

            // Collection
            collections: [],
            collectionId: false,        // id of selected existing collection, or false
            showNewCollection: false,   // true when "Create New…" is selected
            newCollectionName: "",      // filled when user types a new name

            // Categories
            categories: [],
            checkedCategoryIds: [],     // ids of checked existing categories
            newCategoryNames: "",       // comma-separated new names to create

            // Item defaults applied to all uploaded files
            cost: 0,
            stockAvailable: 1,

            // Files
            files: [],                  // [{name, dataUrl, data (base64)}]

            uploading: false,
        });

        onWillStart(async () => {
            const [types, collections, categories] = await Promise.all([
                this.orm.searchRead("aps.media.type", [], ["id", "name"], { order: "name" }),
                this.orm.searchRead("aps.media.collection", [], ["id", "name"], { order: "name" }),
                this.orm.searchRead("aps.media.category", [], ["id", "name"], { order: "name" }),
            ]);
            this.state.types = types;
            this.state.collections = collections;
            this.state.categories = categories;
        });
    }

    // ── Type helper ──────────────────────────────────────────────────────

    onTypeChange(ev) {
        this.state.typeId = parseInt(ev.target.value) || false;
    }

    // ── Collection helpers ──────────────────────────────────────────────────

    onCollectionChange(ev) {
        const val = ev.target.value;
        if (val === "__new__") {
            this.state.collectionId = false;
            this.state.showNewCollection = true;
        } else {
            this.state.collectionId = parseInt(val) || false;
            this.state.showNewCollection = false;
            this.state.newCollectionName = "";
        }
    }

    onNewCollectionName(ev) {
        this.state.newCollectionName = ev.target.value.trim();
    }

    // ── Category helpers ────────────────────────────────────────────────────

    toggleCategory(id, ev) {
        const checked = ev.target.checked;
        const list = this.state.checkedCategoryIds;
        if (checked) {
            if (!list.includes(id)) list.push(id);
        } else {
            const idx = list.indexOf(id);
            if (idx !== -1) list.splice(idx, 1);
        }
    }

    // ── Cost / stock ────────────────────────────────────────────────────────

    onCostChange(ev) {
        this.state.cost = parseInt(ev.target.value) || 0;
    }

    onStockChange(ev) {
        const val = parseInt(ev.target.value);
        this.state.stockAvailable = Number.isFinite(val) && val >= 0 ? val : 1;
    }

    // ── File selection ──────────────────────────────────────────────────────

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
        input.value = "";
    }

    _readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const dataUrl = reader.result;
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

    // ── Upload ──────────────────────────────────────────────────────────────

    async upload() {
        if (!this.state.files.length) return;
        this.state.uploading = true;

        try {
            // 1. Resolve collection id (create new if needed)
            let collectionId = this.state.collectionId || false;
            if (!collectionId && this.state.newCollectionName) {
                const [created] = await this.orm.create("aps.media.collection", [
                    { name: this.state.newCollectionName },
                ]);
                collectionId = created;
            }

            // 2. Resolve category ids (create new ones for any typed names)
            const categoryIds = [...this.state.checkedCategoryIds];
            const rawNames = this.state.newCategoryNames
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean);

            // Build a lookup map for O(1) name → id access
            const existingByName = new Map(
                this.state.categories.map((c) => [c.name.toLowerCase(), c.id])
            );

            for (const catName of rawNames) {
                const existingId = existingByName.get(catName.toLowerCase());
                if (existingId != null) {
                    if (!categoryIds.includes(existingId)) categoryIds.push(existingId);
                } else {
                    const [newId] = await this.orm.create("aps.media.category", [
                        { name: catName },
                    ]);
                    categoryIds.push(newId);
                }
            }

            // 3. Call server method to create the media records
            const payload = this.state.files.map((f) => ({ name: f.name, data: f.data }));
            const result = await this.orm.call(
                "aps.media",
                "bulk_create_from_files",
                [payload, collectionId, categoryIds, this.state.cost, this.state.stockAvailable, this.state.typeId || false]
            );

            this.notification.add(
                _t("%s media item(s) uploaded successfully.", result.count),
                { type: "success" }
            );

            // 4. Navigate to the created items (refreshes list/kanban)
            if (result.ids.length === 1) {
                this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "aps.media",
                    res_id: result.ids[0],
                    views: [[false, "form"]],
                });
            } else {
                this.action.doAction({
                    type: "ir.actions.act_window",
                    name: _t("Uploaded Media Items"),
                    res_model: "aps.media",
                    domain: [["id", "in", result.ids]],
                    views: [
                        [false, "kanban"],
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

registry.category("actions").add("aps_media_bulk_upload", MediaBulkUpload);
