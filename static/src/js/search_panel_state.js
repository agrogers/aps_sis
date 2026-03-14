import { patch } from "@web/core/utils/patch";
import { SearchModel } from "@web/search/search_model";
import { user } from "@web/core/user";

const STORAGE_PREFIX = "aps_searchpanel";

function getStorageKey(resModel, userId) {
    return `${STORAGE_PREFIX}:${userId}:${resModel}`;
}

/**
 * Collect the current active state of each section, keyed by fieldName so the
 * state survives across page loads (section map IDs are re-generated each time).
 *
 * For filters, the value IDs are the many2many record IDs which are stable.
 * For categories, activeValueId is the many2one record ID which is also stable.
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
 * Patch Odoo 18's SearchModel to persist search panel filter/category
 * selections in localStorage so that panels always open with the user's
 * last-used state.
 *
 * Storage key: `aps_searchpanel:<userId>:<resModel>` — per-user, per-model.
 *
 * We patch SearchModel (not SearchPanel) to avoid any OWL lifecycle-hook
 * registration issues that can occur when patching OWL component prototypes.
 * All patched methods are plain JavaScript, so the patch is always reliable.
 */
patch(SearchModel.prototype, {
    /**
     * Intercept load() to capture whether any searchpanel_default_* context
     * keys were passed by the caller.  Odoo's _extractSearchDefaultsFromGlobalContext()
     * deletes those keys from globalContext before _fetchSections is called, so
     * this is the only opportunity to read them.
     *
     * If defaults were supplied by the view/action we must NOT restore our
     * saved state — the caller's explicit defaults should win.
     */
    async load(config) {
        const ctx = config?.context || {};
        const searchPanelDefaultPattern = /^searchpanel_default_/;
        this._apsHasPanelDefaults = Object.keys(ctx).some((k) =>
            searchPanelDefaultPattern.test(k)
        );
        // Reset restore flag so a fresh load always re-evaluates whether to restore.
        this._apsStateRestored = false;
        return super.load(config);
    },

    /**
     * Called after categories and filters have their values fetched.
     * Restore the saved selection on the FIRST fetch only — subsequent
     * re-fetches happen when the domain changes and we must not override
     * the user's current live selection.
     */
    async _fetchSections(categoriesToLoad, filtersToLoad) {
        await super._fetchSections(categoriesToLoad, filtersToLoad);
        if (!this._apsStateRestored) {
            this._apsStateRestored = true;
            this._apsRestoreSearchPanelState();
        }
    },

    /** Save state whenever a category value is toggled by the user. */
    toggleCategoryValue(sectionId, valueId) {
        super.toggleCategoryValue(sectionId, valueId);
        if (!this._apsRestoringState) {
            this._apsSaveSearchPanelState();
        }
    },

    /** Save state whenever filter values are toggled by the user. */
    toggleFilterValues(sectionId, valueIds, forceTo = null) {
        super.toggleFilterValues(sectionId, valueIds, forceTo);
        if (!this._apsRestoringState) {
            this._apsSaveSearchPanelState();
        }
    },

    /** Save state whenever sections are cleared by the user. */
    clearSections(sectionIds) {
        super.clearSections(sectionIds);
        if (!this._apsRestoringState) {
            this._apsSaveSearchPanelState();
        }
    },

    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------

    _apsSaveSearchPanelState() {
        try {
            if (!this.sections?.size) return;
            const userId = user.userId;
            const resModel = this.resModel;
            if (!resModel || !userId) return;
            const state = collectSectionState(this.sections);
            localStorage.setItem(getStorageKey(resModel, userId), JSON.stringify(state));
        } catch (err) {
            console.debug("[search_panel_state] Failed to save state:", err);
        }
    },

    _apsRestoreSearchPanelState() {
        try {
            if (!this.sections?.size) return;
            // If the view/action supplied explicit searchpanel_default_* context keys,
            // those caller-provided defaults take priority — do not overwrite them with
            // whatever the user last selected in a previous session.
            if (this._apsHasPanelDefaults) return;
            const userId = user.userId;
            const resModel = this.resModel;
            if (!resModel || !userId) return;
            const saved = localStorage.getItem(getStorageKey(resModel, userId));
            if (!saved) return;
            const savedState = JSON.parse(saved);
            if (!savedState) return;

            // Directly mutate all sections in one pass, then call _notify() once
            // to recalculate the search domain and re-query the list view.
            let anyRestored = false;
            this._apsRestoringState = true;
            try {
                for (const [, section] of this.sections) {
                    const savedSection = savedState[section.fieldName];
                    if (!savedSection || savedSection.type !== section.type) continue;
                    if (section.type === "category") {
                        const valId = savedSection.activeValueId;
                        if (valId && section.values?.has(valId)) {
                            section.activeValueId = valId;
                            anyRestored = true;
                        }
                    } else if (section.type === "filter") {
                        for (const vId of savedSection.checkedIds || []) {
                            const value = section.values?.get(vId);
                            if (value) {
                                value.checked = true;
                                anyRestored = true;
                            }
                        }
                    }
                }
            } finally {
                this._apsRestoringState = false;
            }

            // Wait for _notify() to become effective using requestAnimationFrame.
            //
            // We cannot call _notify() synchronously here because:
            //   1. blockNotification = true while inside load() — _notify() is a no-op.
            //   2. useBus registers the "update" listener via useEffect, which only
            //      runs after OWL's first render (after onWillStart resolves).
            //
            // requestAnimationFrame fires before each browser paint (~16 ms).
            // OWL schedules its render as a microtask (Promise.resolve()), so by the
            // time the next animation frame fires, load() has completed (clearing
            // blockNotification), and OWL has fully rendered and run useEffect to
            // register the listener.  We keep retrying each frame until
            // blockNotification is false, making the timing deterministic rather than
            // relying on an arbitrary fixed delay.
            if (anyRestored) {
                const model = this;
                let retries = 0;
                const MAX_RETRIES = 100; // ~1.6 s safety cap at 16 ms/frame
                const tryNotify = () => {
                    if (!model.blockNotification) {
                        model._notify();
                    } else if (retries++ < MAX_RETRIES) {
                        requestAnimationFrame(tryNotify);
                    } else {
                        console.warn("[search_panel_state] _notify() still blocked after max retries — saved filter state may not have applied.");
                    }
                };
                requestAnimationFrame(tryNotify);
            }
        } catch (err) {
            console.debug("[search_panel_state] Failed to restore state:", err);
        }
    },
});

