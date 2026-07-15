/**
 * Reusable filter preset manager for OWL components.
 *
 * Usage:
 *   import { FilterPresetManager } from "@aps_sis/js/filter_preset_service";
 *   setup() {
 *       this.presets = new FilterPresetManager(this.orm, "my_component_key");
 *       onWillStart(() => this.presets.load());
 *   }
 *   // Load the active preset on mount
 *   const active = await this.presets.getActivePreset();
 *   // Load a preset's filter data
 *   const data = await this.presets.loadPreset(presetId);
 *   // Save current filters (auto-sets as active)
 *   const result = await this.presets.save(name, currentFilterData);
 *   // Set a preset as active
 *   await this.presets.setActive(presetId);
 *   // Delete a preset
 *   await this.presets.delete(presetId);
 */
export class FilterPresetManager {
    /**
     * @param {Object} orm - The Odoo ORM service (useService("orm"))
     * @param {string} componentKey - Unique identifier for this dashboard/form
     */
    constructor(orm, componentKey) {
        this.orm = orm;
        this.componentKey = componentKey;
        /** @type {Array<{id: number, name: string, active: boolean}>} */
        this.presetList = [];
    }

    /**
     * Load list of presets for this component + user.
     */
    async load() {
        this.presetList = await this.orm.call(
            "aps.filter.preset",
            "get_presets",
            [this.componentKey],
            {}
        );
        return this.presetList;
    }

    /**
     * Get the currently active preset for this component+user, or null.
     * @returns {Promise<{id: number, name: string, filter_data: Object}|null>}
     */
    async getActivePreset() {
        return await this.orm.call(
            "aps.filter.preset",
            "get_active_preset",
            [this.componentKey],
            {}
        );
    }

    /**
     * Set a preset as the active one.
     * @param {number} presetId
     */
    async setActive(presetId) {
        await this.orm.call(
            "aps.filter.preset",
            "set_active_preset",
            [this.componentKey, presetId],
            {}
        );
        await this.load();
    }

    /**
     * Clear the active preset marker (without deleting anything).
     */
    async clearActive() {
        await this.orm.call(
            "aps.filter.preset",
            "clear_active_preset",
            [this.componentKey],
            {}
        );
        await this.load();
    }

    /**
     * Load a single preset's filter data by ID.
     * @param {number} presetId
     * @returns {Promise<{name: string, filter_data: Object}>}
     */
    async loadPreset(presetId) {
        return await this.orm.call(
            "aps.filter.preset",
            "get_preset",
            [presetId],
            {}
        );
    }

    /**
     * Save (create or update) a preset and set it as active.
     * @param {string} name
     * @param {Object} filterData - JSON-serializable filter state
     * @returns {Promise<{id: number, name: string, action: string}>}
     */
    async save(name, filterData) {
        const result = await this.orm.call(
            "aps.filter.preset",
            "upsert_preset",
            [this.componentKey, name, filterData],
            {}
        );
        await this.load();
        return result;
    }

    /**
     * Delete a preset.
     * @param {number} presetId
     */
    async delete(presetId) {
        await this.orm.call(
            "aps.filter.preset",
            "delete_preset",
            [presetId],
            {}
        );
        await this.load();
    }
}