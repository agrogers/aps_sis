import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

// ─── Session-level caches (survive multiple form opens within the same page load) ───

/** @type {Object.<string, {save_mode:string, default_tab:string|false, tab_priority:string[]|null}>} */
const _configCache = {};
let _configsLoaded = false;
/** @type {Promise|null} */
let _configsLoadingPromise = null;

/**
 * userId → true when that user's states have been pre-loaded from DB into
 * localStorage for this browser session.
 * @type {Set<number>}
 */
const _statesLoadedForUser = new Set();
/** @type {Promise|null} */
let _statesLoadingPromise = null;

/** Cached reference to the ORM service (set on first form open). */
let _orm = null;

/**
 * Dirty states waiting to be flushed to the DB.
 * Key: `${userId}|${modelName}|${recordId}`
 * @type {Map<string, {model_name:string, record_id:number, tab_name:string}>}
 */
const _dirtyStates = new Map();

let _periodicFlushTimer = null;
const FLUSH_INTERVAL_MS = 5 * 60 * 1000;   // 5 minutes
const DEBOUNCE_FLUSH_MS = 30 * 1000;        // 30 seconds after last tab change
const LS_PREFIX = 'aps_tf_';                // localStorage key prefix

// ─── localStorage helpers ────────────────────────────────────────────────────

function _lsKey(userId, modelName, recordId) {
    return `${LS_PREFIX}${userId}|${modelName}|${recordId}`;
}

function _getLS(userId, modelName, recordId) {
    try {
        return localStorage.getItem(_lsKey(userId, modelName, recordId)) || null;
    } catch {
        return null;
    }
}

function _setLS(userId, modelName, recordId, tabName) {
    try {
        localStorage.setItem(_lsKey(userId, modelName, recordId), tabName);
    } catch {
        // localStorage unavailable (private mode, storage full, etc.)
    }
}

// ─── DB helpers ─────────────────────────────────────────────────────────────

/**
 * Ensure all tab-focus configurations are loaded from the DB.
 * Results are cached in _configCache for the lifetime of the browser tab.
 */
async function _ensureConfigsLoaded(orm) {
    if (_configsLoaded) return;
    if (_configsLoadingPromise) return _configsLoadingPromise;

    _configsLoadingPromise = orm
        .searchRead(
            'aps.tab.focus.config',
            [],
            ['model_name', 'save_mode', 'default_tab', 'tab_priority'],
        )
        .then((records) => {
            for (const r of records) {
                // Parse tab_priority once here so we don't repeat JSON.parse on every form open.
                let parsedPriority = null;
                if (r.tab_priority) {
                    try {
                        const p = JSON.parse(r.tab_priority);
                        parsedPriority = Array.isArray(p) ? p : null;
                    } catch {
                        parsedPriority = null;
                    }
                }
                _configCache[r.model_name] = { ...r, _tab_priority_parsed: parsedPriority };
            }
            _configsLoaded = true;
            _configsLoadingPromise = null;
        })
        .catch(() => {
            _configsLoadingPromise = null;
        });

    return _configsLoadingPromise;
}

/**
 * Pre-load all saved tab states for the current user from the DB into
 * localStorage.  Runs once per user per browser session.
 */
async function _ensureStatesLoaded(orm, userId) {
    if (_statesLoadedForUser.has(userId)) return;
    if (_statesLoadingPromise) return _statesLoadingPromise;

    _statesLoadingPromise = orm
        .call('aps.tab.focus.state', 'get_states_for_user', [])
        .then((states) => {
            for (const s of states) {
                _setLS(userId, s.model_name, s.record_id, s.tab_name);
            }
            _statesLoadedForUser.add(userId);
            _statesLoadingPromise = null;
        })
        .catch(() => {
            _statesLoadingPromise = null;
        });

    return _statesLoadingPromise;
}

// ─── Periodic / deferred DB flush ───────────────────────────────────────────

async function _flush() {
    if (_dirtyStates.size === 0 || !_orm) return;
    const states = Array.from(_dirtyStates.values());
    _dirtyStates.clear();
    try {
        await _orm.call('aps.tab.focus.state', 'save_states', [states]);
    } catch {
        // Re-queue on failure so we retry on the next flush cycle.
        for (const s of states) {
            const key = `${s.model_name}|${s.record_id}`;
            if (!_dirtyStates.has(key)) {
                _dirtyStates.set(key, s);
            }
        }
    }
}

function _schedulePeriodicFlush() {
    if (_periodicFlushTimer) return;
    _periodicFlushTimer = setInterval(_flush, FLUSH_INTERVAL_MS);
    // Also flush when the user navigates away or closes the tab.
    window.addEventListener('beforeunload', _flush);
}

function _markDirty(modelName, recordId, tabName) {
    const key = `${modelName}|${recordId}`;
    _dirtyStates.set(key, { model_name: modelName, record_id: recordId, tab_name: tabName });
}

// ─── Tab resolution helpers ──────────────────────────────────────────────────

/**
 * Given a list of candidate tab names (in priority order), return the first
 * one whose corresponding header element is present and visible in rootEl.
 */
function _firstVisibleTab(rootEl, names) {
    for (const name of names) {
        const tab = rootEl.querySelector(
            `.o_notebook_headers [name="${name}"], .o_notebook_tabs [name="${name}"]`,
        );
        if (tab && !tab.closest('.d-none') && tab.offsetParent !== null) {
            return name;
        }
    }
    return null;
}

/**
 * Activate a notebook tab by name.  Returns true if the tab was found and
 * clicked.
 */
function _activateTab(rootEl, tabName) {
    if (!tabName) return false;
    const tab = rootEl.querySelector(
        `.o_notebook_headers [name="${tabName}"], .o_notebook_tabs [name="${tabName}"]`,
    );
    if (tab && tab.click) {
        tab.click();
        return true;
    }
    return false;
}

// ─── FormController patch ────────────────────────────────────────────────────

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        const orm = useService('orm');
        const userService = useService('user');

        // Per-instance debounce timer stored on `this` so onWillUnmount can
        // reliably reference the same timer regardless of closure quirks.
        this._tabFocusDebounceTimer = null;

        onMounted(async () => {
            const rootEl = this.el || this.root?.el;
            if (!rootEl) return;

            // Only act if the form contains a notebook.
            const hasNotebook = rootEl.querySelector('.o_notebook_headers, .o_notebook_tabs');
            if (!hasNotebook) return;

            const modelName = this.model?.root?.resModel;
            if (!modelName) return;

            const userId = userService.userId;
            const recordId = this.model?.root?.resId || 0;

            // Store the ORM service reference for the periodic flush.
            if (!_orm) {
                _orm = orm;
                _schedulePeriodicFlush();
            }

            // Load configs + states (cached after first call).
            await _ensureConfigsLoaded(orm);

            const config = _configCache[modelName];
            const saveMode = config?.save_mode || 'none';

            if (saveMode !== 'none') {
                await _ensureStatesLoaded(orm, userId);
            }

            // ── Determine the tab to activate ────────────────────────────────

            let tabName = null;

            // 1. Per-record state (only in per_record mode with a real record).
            if (saveMode === 'per_record' && recordId) {
                tabName = _getLS(userId, modelName, recordId);
            }

            // 2. Per-form state fallback (most recently used tab for this model).
            if (!tabName && (saveMode === 'per_form' || saveMode === 'per_record')) {
                tabName = _getLS(userId, modelName, 0);
            }

            // 3. Default tab from configuration.
            if (!tabName && config?.default_tab) {
                tabName = config.default_tab;
            }

            // 4. Tab priority list – first visible tab wins (satisfies requirement #9).
            if (!tabName && config?._tab_priority_parsed) {
                tabName = _firstVisibleTab(rootEl, config._tab_priority_parsed);
            }

            // 5. Fallback: context default_notebook_page (existing Odoo mechanism).
            if (!tabName) {
                tabName = this.props.context?.default_notebook_page || null;
            }

            // 6. Fallback: any tab element carrying the CSS class "default-page".
            if (!tabName) {
                const el = rootEl.querySelector(
                    '.o_notebook_headers .default-page, .o_notebook_tabs .default-page',
                );
                tabName = el?.getAttribute('name') || el?.getAttribute('data-name') || null;
            }

            // Activate the resolved tab.
            _activateTab(rootEl, tabName);

            // ── Listen for tab changes ────────────────────────────────────────
            if (saveMode === 'none') return;

            const tabs = rootEl.querySelectorAll(
                '.o_notebook_headers [name], .o_notebook_tabs [name]',
            );
            tabs.forEach((tab) => {
                tab.addEventListener('click', () => {
                    const newTabName = tab.getAttribute('name');
                    if (!newTabName) return;

                    // Save per-record state.
                    if (saveMode === 'per_record' && recordId) {
                        _setLS(userId, modelName, recordId, newTabName);
                        _markDirty(modelName, recordId, newTabName);
                    }

                    // Always update per-form (most-recently-used) state.
                    _setLS(userId, modelName, 0, newTabName);
                    _markDirty(modelName, 0, newTabName);

                    // Debounced DB flush (30 s after last change).
                    if (this._tabFocusDebounceTimer) clearTimeout(this._tabFocusDebounceTimer);
                    this._tabFocusDebounceTimer = setTimeout(_flush, DEBOUNCE_FLUSH_MS);
                });
            });
        });

        onWillUnmount(() => {
            // Flush any pending dirty states before the component is destroyed,
            // then cancel the debounce to avoid double-flushes.
            if (this._tabFocusDebounceTimer) {
                clearTimeout(this._tabFocusDebounceTimer);
                this._tabFocusDebounceTimer = null;
                _flush();
            }
        });
    },
});
