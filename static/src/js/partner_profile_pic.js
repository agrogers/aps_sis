/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

class PartnerProfilePic extends Component {
    static template = "aps_sis.PartnerProfilePic";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            partners: [],      // [{id, name, image_128, newImage, newImagePreview, dragOver}]
            saving: false,
        });
    }

    // ─── Partner search via Odoo SelectCreateDialog ───

    onAddPartner() {
        this.dialog.add(SelectCreateDialog, {
            resModel: "res.partner",
            title: _t("Select Partner(s)"),
            multiSelect: true,
            domain: [],
            context: {},
            onSelected: (records) => {
                this._addPartnerRecords(records);
            },
        });
    }

    async _addPartnerRecords(resIds) {
        // resIds is an array of partner ids
        const existingIds = new Set(this.state.partners.map((p) => p.id));
        const newIds = resIds.filter((id) => !existingIds.has(id));
        if (!newIds.length) return;

        const partners = await this.orm.read(
            "res.partner",
            newIds,
            ["id", "name", "image_128"]
        );
        for (const p of partners) {
            this.state.partners.push({
                id: p.id,
                name: p.name,
                image_128: p.image_128,
                newImage: null,
                newImagePreview: null,
                dragOver: false,
            });
        }
    }

    // ─── Remove partner from grid ───

    removePartner(index) {
        this.state.partners.splice(index, 1);
    }

    clearAll() {
        this.state.partners = [];
    }

    // ─── Drag & Drop handlers ───

    onDragOver(ev, index) {
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = "copy";
        this.state.partners[index].dragOver = true;
    }

    onDragLeave(ev, index) {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.partners[index].dragOver = false;
    }

    onDrop(ev, index) {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.partners[index].dragOver = false;

        const files = ev.dataTransfer.files;
        if (!files || !files.length) return;

        const file = files[0];
        if (!file.type.startsWith("image/")) {
            this.notification.add(_t("Please drop an image file."), {
                type: "warning",
            });
            return;
        }

        this._readFileForPartner(file, index);
    }

    _readFileForPartner(file, index) {
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = reader.result;
            const base64 = dataUrl.split(",")[1] || "";
            this.state.partners[index].newImage = base64;
            this.state.partners[index].newImagePreview = dataUrl;
        };
        reader.readAsDataURL(file);
    }

    // ─── Also allow click to select a file ───

    onClickImage(index) {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.onchange = (ev) => {
            const file = ev.target.files[0];
            if (file && file.type.startsWith("image/")) {
                this._readFileForPartner(file, index);
            }
        };
        input.click();
    }

    // ─── Image source helper ───

    getImageSrc(partner) {
        if (partner.newImagePreview) {
            return partner.newImagePreview;
        }
        if (partner.image_128) {
            return "data:image/png;base64," + partner.image_128;
        }
        return null;
    }

    hasImage(partner) {
        return !!(partner.newImagePreview || partner.image_128);
    }

    get hasChanges() {
        return this.state.partners.some((p) => p.newImage);
    }

    get changeCount() {
        return this.state.partners.filter((p) => p.newImage).length;
    }

    // ─── Save all changes ───

    async save() {
        const updates = this.state.partners
            .filter((p) => p.newImage)
            .map((p) => ({ id: p.id, image_1920: p.newImage }));

        if (!updates.length) {
            this.notification.add(_t("No changes to save."), { type: "info" });
            return;
        }

        this.state.saving = true;
        try {
            await this.orm.call(
                "res.partner",
                "bulk_update_profile_images",
                [updates]
            );
            this.notification.add(
                _t("%s profile picture(s) updated.", updates.length),
                { type: "success" }
            );
            // Mark saved: move newImage into image_128, clear newImage
            for (const partner of this.state.partners) {
                if (partner.newImage) {
                    partner.image_128 = partner.newImage;
                    partner.newImage = null;
                    partner.newImagePreview = null;
                }
            }
        } catch (e) {
            this.notification.add(
                _t("Save failed: %s", e.message || e),
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }
}

registry
    .category("actions")
    .add("aps_partner_profile_pic", PartnerProfilePic);
