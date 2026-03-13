import { patch } from "@web/core/utils/patch";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { onMounted, onPatched } from "@odoo/owl";

const STORAGE_PREFIX = "aps_searchpanel";

function getStorageKey(resModel, userId) {
    return `${STORAGE_PREFIX}:${userId}:${resModel}`;
}

/**
 * Collect the current active state of each section, keyed by fieldName so the
 * state survives across page loads (section map IDs are re-generated each time).
 */
function collectSectionState(sections) {
    const state = {};
    for (const [, section] of sections) {
        if (!section.fieldName) continue;
        if (section.type === "category") {
            state[section.fieldName] = {
                type: "category",
                activeValueId: section.activeValueId || false,
            };
        } else if (section.type === "filter") {
            const checkedIds = [];
            if (section.values) {
                for (const [vId, val] of section.values) {
                    if (val.checked) checkedIds.push(vId);
                }
            }
            state[section.fieldName] = { type: "filter", checkedIds };
        }
    }
    return state;
}

/**
 * Patch Odoo's SearchPanel to persist the selected category/filter values in
 * localStorage so that the panel always opens with the user's last-used state.
 *
 * The storage key is `aps_searchpanel:<userId>:<resModel>`, giving each user
 * their own independent state for every model that has a search panel.
 */
patch(SearchPanel.prototype, {
    setup() {
        super.setup();

        const resModel = this.env.searchModel?.resModel;
        const userId = this.env.services.user?.userId;
        if (!resModel || !userId) {
            console.debug(
                "[search_panel_state] Skipping state persistence: resModel or userId unavailable."
            );
            return;
        }

        const storageKey = getStorageKey(resModel, userId);

        // Track the last persisted snapshot to avoid redundant localStorage writes.
        let _lastSavedSnapshot = null;

        // After the initial render the sections are populated — restore saved state.
        onMounted(() => {
            try {
                const saved = localStorage.getItem(storageKey);
                if (!saved) return;
                const savedState = JSON.parse(saved);
                if (!savedState || !this.model?.sections?.size) return;

                for (const [sectionId, section] of this.model.sections) {
                    const sectionSaved = savedState[section.fieldName];
                    if (!sectionSaved || sectionSaved.type !== section.type) continue;

                    if (section.type === "category") {
                        const valId = sectionSaved.activeValueId;
                        if (
                            valId &&
                            valId !== section.activeValueId &&
                            section.values?.has(valId)
                        ) {
                            this.model.toggleSearchPanelSectionValue(sectionId, valId);
                        }
                    } else if (section.type === "filter") {
                        for (const vId of sectionSaved.checkedIds || []) {
                            if (
                                section.values?.has(vId) &&
                                !section.values.get(vId).checked
                            ) {
                                this.model.toggleSearchPanelSectionValue(sectionId, vId);
                            }
                        }
                    }
                }
            } catch (err) {
                console.debug("[search_panel_state] Failed to restore state:", err);
            }
        });

        // After each re-render save the current state only when it has changed.
        onPatched(() => {
            try {
                if (!this.model?.sections?.size) return;
                const state = collectSectionState(this.model.sections);
                const snapshot = JSON.stringify(state);
                if (snapshot === _lastSavedSnapshot) return;
                _lastSavedSnapshot = snapshot;
                localStorage.setItem(storageKey, snapshot);
            } catch (err) {
                console.debug("[search_panel_state] Failed to save state:", err);
            }
        });
    },
});
