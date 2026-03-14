import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { onMounted, onWillUnmount } from "@odoo/owl";

// ─── Session-level caches (survive multiple form opens within the same page load) ───

/**
 * Config cache keyed by "model_name|form_name".
 * @type {Object.<string, {save_mode:string, default_tab:{string:string,name:string}|false, tab_priority:{string:string,name:string}[]}>}
 */
const _configCache = {};
let _configsLoaded = false;
/** @type {Promise|null} */
let _configsLoadingPromise = null;

/**
 * Set of "model_name|form_name" keys for forms that have already been
 * registered in aps.tab.focus.forms during this browser session.
 * @type {Set<string>}
 */
const _registeredForms = new Set();

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
 * Key: `${userId}|${modelName}|${formName}|${recordId}`
 * @type {Map<string, {model_name:string, record_id:number, tab_string:string}>}
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

function _setLS(userId, modelName, recordId, tabString) {
    try {
        localStorage.setItem(_lsKey(userId, modelName, recordId), tabString);
    } catch {
        // localStorage unavailable (private mode, storage full, etc.)
    }
}

// ─── Tab collection helpers ──────────────────────────────────────────────────

/**
 * Collect all notebook tab buttons from rootEl and return them as an array of
 * {string, name} objects.  Tabs are identified by their visible string label
 * (textContent), which is always present.  The name attribute is included when
 * available, but tabs without one are still captured.
 */
function _collectTabs(rootEl) {
    const buttons = rootEl.querySelectorAll(
        '.o_notebook_headers button, .o_notebook_tabs button',
    );
    const tabs = [];
    for (const btn of buttons) {
        const label = btn.textContent.trim();
        if (!label) continue;
        tabs.push({
            string: label,
            name: btn.getAttribute('name') || '',
        });
    }
    return tabs;
}

// ─── DB helpers ─────────────────────────────────────────────────────────────

/**
 * Ensure all tab-focus configurations are loaded from the DB via the
 * ``get_configs_for_js`` Python method.
 * Results are cached in _configCache for the lifetime of the browser tab.
 */
async function _ensureConfigsLoaded(orm) {
    if (_configsLoaded) return;
    if (_configsLoadingPromise) return _configsLoadingPromise;

    _configsLoadingPromise = orm
        .call('aps.tab.focus.config', 'get_configs_for_js', [])
        .then((configs) => {
            for (const [key, cfg] of Object.entries(configs)) {
                _configCache[key] = cfg;
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
                _setLS(userId, s.model_name, s.record_id, s.tab_string);
            }
            _statesLoadedForUser.add(userId);
            _statesLoadingPromise = null;
        })
        .catch(() => {
            _statesLoadingPromise = null;
        });

    return _statesLoadingPromise;
}

/**
 * Register a form and its tabs in aps.tab.focus.forms (once per session).
 * Failures are silently swallowed so a registration error never breaks the form.
 */
async function _registerForm(orm, modelName, formName, tabs) {
    const key = `${modelName}|${formName}`;
    if (_registeredForms.has(key)) return;
    _registeredForms.add(key);  // optimistically mark to avoid duplicate calls
    try {
        await orm.call('aps.tab.focus.forms', 'register_form', [modelName, formName, tabs]);
    } catch {
        _registeredForms.delete(key);  // allow retry on next visit if it failed
    }
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

function _markDirty(modelName, recordId, tabString) {
    const key = `${modelName}|${recordId}`;
    _dirtyStates.set(key, { model_name: modelName, record_id: recordId, tab_string: tabString });
}

// ─── Tab resolution helpers ──────────────────────────────────────────────────

/**
 * Find a tab button in rootEl that matches a {string, name} descriptor.
 * Tries name-attribute match first, falls back to text-content match.
 */
function _findTabElement(rootEl, tabInfo) {
    if (tabInfo.name) {
        const byName = rootEl.querySelector(
            `.o_notebook_headers [name="${tabInfo.name}"], .o_notebook_tabs [name="${tabInfo.name}"]`,
        );
        if (byName) return byName;
    }
    if (tabInfo.string) {
        const allButtons = rootEl.querySelectorAll(
            '.o_notebook_headers button, .o_notebook_tabs button',
        );
        for (const btn of allButtons) {
            if (btn.textContent.trim() === tabInfo.string) return btn;
        }
    }
    return null;
}

/**
 * Given a list of candidate tab descriptors ({string, name}) in priority
 * order, return the string label of the first one whose tab header element is
 * present and visible in rootEl.
 */
function _firstVisibleTab(rootEl, tabInfoList) {
    for (const tabInfo of tabInfoList) {
        const el = _findTabElement(rootEl, tabInfo);
        if (el && !el.closest('.d-none') && el.offsetParent !== null) {
            return tabInfo.string;
        }
    }
    return null;
}

/**
 * Activate a notebook tab by its string label (or name attr).
 * Returns true if the tab was found and clicked.
 */
function _activateTab(rootEl, tabString) {
    if (!tabString) return false;
    // Try to find by string first; also try by name in case string is stored as name.
    const el = _findTabElement(rootEl, { string: tabString, name: tabString });
    if (el && el.click) {
        el.click();
        return true;
    }
    return false;
}

// ─── FormController patch ────────────────────────────────────────────────────

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        const orm = useService('orm');

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

            // Derive a stable form identifier.  Prefer the arch XML-ID (e.g.
            // "module.view_name_form") when available; fall back to the numeric
            // view ID from the environment config.
            const formName =
                this.props?.archInfo?.xmlid ||
                String(this.env?.config?.viewId || 'default');

            const userId = user.userId;
            const recordId = this.model?.root?.resId || 0;

            // Store the ORM service reference for the periodic flush.
            if (!_orm) {
                _orm = orm;
                _schedulePeriodicFlush();
            }

            // Collect tab info from the DOM (string label + optional name attr).
            const tabsOnForm = _collectTabs(rootEl);

            // Register this form+tabs in aps.tab.focus.forms (fire-and-forget).
            _registerForm(orm, modelName, formName, tabsOnForm);

            // Load configs + states (cached after first call).
            await _ensureConfigsLoaded(orm);

            const configKey = `${modelName}|${formName}`;
            const config = _configCache[configKey];
            const saveMode = config?.save_mode || 'none';

            if (saveMode !== 'none') {
                await _ensureStatesLoaded(orm, userId);
            }

            // ── Determine the tab to activate ────────────────────────────────

            let tabString = null;

            // 1. Per-record state (only in per_record mode with a real record).
            if (saveMode === 'per_record' && recordId) {
                tabString = _getLS(userId, modelName, recordId);
            }

            // 2. Per-form state fallback (most recently used tab for this model).
            if (!tabString && (saveMode === 'per_form' || saveMode === 'per_record')) {
                tabString = _getLS(userId, modelName, 0);
            }

            // 3. Default tab from configuration (a {string, name} descriptor).
            if (!tabString && config?.default_tab) {
                const defEl = _findTabElement(rootEl, config.default_tab);
                if (defEl) tabString = config.default_tab.string;
            }

            // 4. Tab priority list – first visible tab wins (requirement #9).
            if (!tabString && config?.tab_priority?.length) {
                tabString = _firstVisibleTab(rootEl, config.tab_priority);
            }

            // 5. Fallback: context default_notebook_page (existing Odoo mechanism).
            if (!tabString) {
                tabString = this.props.context?.default_notebook_page || null;
            }

            // 6. Fallback: any tab element carrying the CSS class "default-page".
            if (!tabString) {
                const el = rootEl.querySelector(
                    '.o_notebook_headers .default-page, .o_notebook_tabs .default-page',
                );
                if (el) {
                    tabString =
                        el.getAttribute('name') ||
                        el.textContent.trim() ||
                        null;
                }
            }

            // Activate the resolved tab.
            _activateTab(rootEl, tabString);

            // ── Listen for tab changes ────────────────────────────────────────
            if (saveMode === 'none') return;

            const tabButtons = rootEl.querySelectorAll(
                '.o_notebook_headers button, .o_notebook_tabs button',
            );
            tabButtons.forEach((tab) => {
                tab.addEventListener('click', () => {
                    const newTabString = tab.textContent.trim();
                    if (!newTabString) return;

                    // Save per-record state.
                    if (saveMode === 'per_record' && recordId) {
                        _setLS(userId, modelName, recordId, newTabString);
                        _markDirty(modelName, recordId, newTabString);
                    }

                    // Always update per-form (most-recently-used) state.
                    _setLS(userId, modelName, 0, newTabString);
                    _markDirty(modelName, 0, newTabString);

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
