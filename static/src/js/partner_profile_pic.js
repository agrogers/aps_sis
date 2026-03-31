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
            overflow: [],      // images shifted past the last partner (FIFO)
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
        this.state.overflow = [];
    }

    // ─── Shift images left/right from a given index ───

    shiftImagesRight(index) {
        // Move the clicked image one slot to the right.
        // Only cascade if the target slot is occupied (collision).
        const partners = this.state.partners;
        let i = index;
        // Find the end of the contiguous chain starting at index+1
        let target = i + 1;
        if (target >= partners.length) {
            // Already at the rightmost slot — push to overflow
            this.state.overflow.push({
                newImage: partners[i].newImage,
                newImagePreview: partners[i].newImagePreview,
            });
            partners[i].newImage = null;
            partners[i].newImagePreview = null;
            return;
        }
        // Walk right to find the last occupied slot in the chain
        let chainEnd = target;
        while (chainEnd < partners.length && partners[chainEnd].newImage) {
            chainEnd++;
        }
        // chainEnd is the first empty slot (or past the array)
        if (chainEnd >= partners.length) {
            // Push the last image in the chain to overflow
            const last = partners[partners.length - 1];
            this.state.overflow.push({
                newImage: last.newImage,
                newImagePreview: last.newImagePreview,
            });
            chainEnd = partners.length - 1;
        }
        // Shift the chain rightward from chainEnd back to target
        for (let j = chainEnd; j > target; j--) {
            partners[j].newImage = partners[j - 1].newImage;
            partners[j].newImagePreview = partners[j - 1].newImagePreview;
        }
        // Move clicked image into target
        partners[target].newImage = partners[i].newImage;
        partners[target].newImagePreview = partners[i].newImagePreview;
        partners[i].newImage = null;
        partners[i].newImagePreview = null;
    }

    shiftImagesLeft(index) {
        // Move the clicked image one slot to the left.
        // Only cascade if the target slot is occupied (collision).
        const partners = this.state.partners;
        let target = index - 1;
        if (target < 0) {
            // Already at leftmost slot — image is discarded
            partners[index].newImage = null;
            partners[index].newImagePreview = null;
            // Pull from overflow to fill any gap at the end
            this._fillFromOverflow();
            return;
        }
        if (!partners[target].newImage) {
            // Target is empty — just move, no cascade
            partners[target].newImage = partners[index].newImage;
            partners[target].newImagePreview = partners[index].newImagePreview;
            partners[index].newImage = null;
            partners[index].newImagePreview = null;
            this._fillFromOverflow();
            return;
        }
        // Target is occupied — walk left to find the start of the chain
        let chainStart = target;
        while (chainStart > 0 && partners[chainStart - 1].newImage) {
            chainStart--;
        }
        if (chainStart === 0) {
            // The leftmost image in the chain falls off; discard it
            for (let j = chainStart; j < target; j++) {
                partners[j].newImage = partners[j + 1].newImage;
                partners[j].newImagePreview = partners[j + 1].newImagePreview;
            }
        } else {
            // There's an empty slot at chainStart - 1; shift chain into it
            for (let j = chainStart - 1; j < target; j++) {
                partners[j].newImage = partners[j + 1].newImage;
                partners[j].newImagePreview = partners[j + 1].newImagePreview;
            }
        }
        // Move clicked image into target
        partners[target].newImage = partners[index].newImage;
        partners[target].newImagePreview = partners[index].newImagePreview;
        partners[index].newImage = null;
        partners[index].newImagePreview = null;
        this._fillFromOverflow();
    }

    _fillFromOverflow() {
        // If there's overflow and the last partner slot is empty, restore from overflow
        const partners = this.state.partners;
        if (!partners.length) return;
        const last = partners[partners.length - 1];
        if (!last.newImage && this.state.overflow.length) {
            const restored = this.state.overflow.shift();
            last.newImage = restored.newImage;
            last.newImagePreview = restored.newImagePreview;
        }
    }

    clearImage(index) {
        const partner = this.state.partners[index];
        partner.newImage = null;
        partner.newImagePreview = null;
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

    _readFileToOverflow(file) {
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = reader.result;
            const base64 = dataUrl.split(",")[1] || "";
            this.state.overflow.push({
                newImage: base64,
                newImagePreview: dataUrl,
            });
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

    hasImageAt(index) {
        const p = this.state.partners[index];
        return p && !!(p.newImage || p.newImagePreview);
    }

    get hasChanges() {
        return this.state.partners.some((p) => p.newImage);
    }

    get changeCount() {
        return this.state.partners.filter((p) => p.newImage).length;
    }

    // ─── Bulk upload: select multiple files, apply alphabetically ───

    onUploadMultiplePhotos() {
        if (!this.state.partners.length) {
            this.notification.add(_t("Please add partners first."), { type: "warning" });
            return;
        }
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.multiple = true;
        input.onchange = (ev) => this._applyBulkFiles(ev.target.files);
        input.click();
    }

    _applyBulkFiles(fileList) {
        if (!fileList || !fileList.length) return;

        // Sort files with natural ordering (1.jpg, 2.jpg, 10.jpg)
        const sortedFiles = Array.from(fileList)
            .filter((f) => f.type.startsWith("image/"))
            .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));

        if (!sortedFiles.length) {
            this.notification.add(_t("No image files selected."), { type: "warning" });
            return;
        }

        // Sort partners alphabetically by name (case-insensitive)
        const sortedPartners = [...this.state.partners].sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
        );

        // Apply min(files, partners) images; extras go to overflow
        const count = Math.min(sortedFiles.length, sortedPartners.length);
        for (let i = 0; i < count; i++) {
            const file = sortedFiles[i];
            const partner = sortedPartners[i];
            // Find the actual index in state.partners
            const idx = this.state.partners.findIndex((p) => p.id === partner.id);
            if (idx !== -1) {
                this._readFileForPartner(file, idx);
            }
        }

        // Store extra photos in the overflow buffer
        const extraFiles = sortedFiles.slice(count);
        for (const file of extraFiles) {
            this._readFileToOverflow(file);
        }

        const skipped = extraFiles.length;
        let msg = count + _t(" photo(s) applied to partners alphabetically.");
        if (skipped > 0) {
            msg += " " + skipped + _t(" extra photo(s) stored in buffer.");
        }
        this.notification.add(msg, { type: "info" });
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
                updates.length + _t(" profile picture(s) updated."),
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
                _t("Save failed: ") + (e.message || e),
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
