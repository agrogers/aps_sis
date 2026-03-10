/** @odoo-module **/

/**
 * Math Formula Renderer for APS SIS
 *
 * Renders LaTeX formulas in HTML fields using KaTeX.
 * Formulas are delimited by:
 *   $...$    — inline math
 *   $$...$$  — display (block) math
 *   \(...\)  — inline math (alternative)
 *   \[...\]  — display math (alternative)
 *
 * KaTeX and its auto-render extension are loaded dynamically (not through
 * Odoo's asset bundler) to avoid a conflict with Odoo's AMD module loader.
 *
 * Behaviour by field type:
 *
 *   Readonly fields (o_readonly_modifier class present):
 *     renderMathInElement() is called directly on the content div.  No copy
 *     is created — the original element is rendered in-place.  TOC links work
 *     because headings remain in the same DOM element.
 *
 *   Editable fields that contain LaTeX:
 *     The original LaTeX HTML is stored in a WeakMap.  renderMathInElement()
 *     is then called directly on the odoo-editor-editable div so only one
 *     copy of the content is ever in the DOM.
 *
 *     A small "Edit" button floats at the top-right corner of the field.
 *     Clicking it restores the original LaTeX into the editor so the user
 *     can make changes.  Clicking "View" re-renders the updated LaTeX.
 *
 *     Save protection: capture-phase listeners on the save button and Ctrl+S
 *     restore the original LaTeX back into the editor before Odoo reads the
 *     field value, ensuring the LaTeX source (not the rendered HTML) is saved.
 *     After the save Odoo patches the DOM, the MutationObserver fires, and
 *     the field is re-rendered automatically.
 */

import { registry } from "@web/core/registry";

// ── KaTeX configuration ──────────────────────────────────────────────────────

const MATH_OPTIONS = {
    delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$",  right: "$",  display: false },
        { left: "\\(", right: "\\)", display: false },
        { left: "\\[", right: "\\]", display: true  },
    ],
    throwOnError: false,
    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
    ignoredClasses: ["katex", "katex-html"],
};

const KATEX_BASE = "/aps_sis/static/src/lib/katex";

// Attribute on .o_field_html that tracks our current display state:
//   "view"     — KaTeX rendered in-place (editable field)
//   "edit"     — original LaTeX restored for editing (user clicked Edit)
//   "readonly" — KaTeX rendered in-place (readonly field, no toggle)
const PROCESSED_ATTR = "data-aps-math";

// How long to mark an editorEl as "rendering in progress" after we set its
// innerHTML.  Must exceed the MutationObserver debounce (200 ms) so we are
// certain the observer has already processed (and skipped) our own mutation
// before we clear the flag.  2.5× the debounce gives comfortable headroom.
const RENDERING_CLEANUP_DELAY_MS = 500;

// After calling _restoreAllForSave() we wait this long before force-re-rendering
// any field still in "saving" state.  Covers the case where Odoo does not update
// the DOM after a save (content unchanged on the server) so the MutationObserver
// never fires.  1 500 ms is generous enough for most network conditions.
const SAVE_FALLBACK_DELAY_MS = 1500;

// ── State ────────────────────────────────────────────────────────────────────

/**
 * Stores the original LaTeX HTML string for each editorEl while the field
 * is displaying the KaTeX-rendered version.  Used to restore for editing
 * or before a save.
 */
const _originalHtmlMap = new WeakMap();

/**
 * Set of editorEl elements where WE are currently setting innerHTML
 * programmatically (rendering or restoring).  The MutationObserver skips
 * these elements to prevent an infinite render → observe → render loop.
 */
const _renderingInProgress = new Set();

// ── Dynamic script loading that bypasses Odoo's AMD module system ────────────

function _loadScriptAsGlobal(src) {
    return new Promise((resolve, reject) => {
        if (Array.from(document.scripts).some((s) => s.getAttribute("src") === src)) {
            resolve();
            return;
        }

        const savedAmd = window.define && window.define.amd;
        if (window.define) {
            window.define.amd = false;
        }

        const _restore = () => {
            if (window.define) {
                window.define.amd = savedAmd !== undefined ? savedAmd : {};
            }
        };

        const script = document.createElement("script");
        script.src = src;
        script.onload = () => { _restore(); resolve(); };
        script.onerror = () => {
            _restore();
            reject(new Error(`[APS Math] Failed to load ${src}`));
        };

        document.head.appendChild(script);
    });
}

let _cssLoaded = false;
function _ensureKaTeXCSS() {
    if (_cssLoaded) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `${KATEX_BASE}/katex.min.css`;
    document.head.appendChild(link);
    _cssLoaded = true;
}

let _katexLoadPromise = null;
function _loadKaTeX() {
    if (_katexLoadPromise) return _katexLoadPromise;
    _katexLoadPromise = _loadScriptAsGlobal(`${KATEX_BASE}/katex.min.js`)
        .then(() => _loadScriptAsGlobal(`${KATEX_BASE}/auto-render.min.js`))
        .catch((err) => {
            console.warn(err.message);
        });
    return _katexLoadPromise;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Quick test: does this text contain any LaTeX delimiter? */
function _containsLatex(text) {
    return /\$|\\\(|\\\[/.test(text);
}

/**
 * Set innerHTML on *el* and mark *el* as "in-progress" so the MutationObserver
 * ignores the mutation.  The in-progress mark is cleared after the observer's
 * debounce window (500 ms > 200 ms debounce) to ensure we never permanently
 * block observation.
 */
function _setHtml(el, html) {
    _renderingInProgress.add(el);
    el.innerHTML = html;
    setTimeout(() => _renderingInProgress.delete(el), RENDERING_CLEANUP_DELAY_MS);
}

// ── Save protection ───────────────────────────────────────────────────────────

/**
 * Prepare all editable HTML fields for an imminent record save:
 *
 *  "view" mode fields — the editorEl currently holds KaTeX-rendered HTML.
 *    Restore the original LaTeX so Odoo reads and saves the correct source.
 *    Mark as "saving"; the MutationObserver re-renders after Odoo updates the DOM.
 *
 *  "edit" mode fields — the editorEl already holds LaTeX (user is editing).
 *    Nothing to restore, but update the WeakMap entry to capture any edits
 *    made during this session so that the re-render after save uses the new
 *    LaTeX, not the pre-session original.
 *
 * Must run BEFORE Odoo reads the field value (use capture-phase listeners).
 */
function _restoreAllForSave() {
    document.querySelectorAll(`.o_field_html[${PROCESSED_ATTR}="view"]`).forEach((fieldEl) => {
        const editorEl = fieldEl.querySelector(".odoo-editor-editable");
        if (!editorEl) return;
        const orig = _originalHtmlMap.get(editorEl);
        if (orig === undefined) return;
        // Restore LaTeX HTML — Odoo will now read the correct source.
        _setHtml(editorEl, orig);
        fieldEl.setAttribute(PROCESSED_ATTR, "saving");
    });

    // If the user saves while in "edit" mode, the editorEl already has the
    // current (edited) LaTeX — no restore needed.  But update the WeakMap so
    // that when _processEditableField re-renders after save it uses the new
    // content, not the original pre-session LaTeX.
    document.querySelectorAll(`.o_field_html[${PROCESSED_ATTR}="edit"]`).forEach((fieldEl) => {
        const editorEl = fieldEl.querySelector(".odoo-editor-editable");
        if (editorEl) {
            _originalHtmlMap.set(editorEl, editorEl.innerHTML);
        }
    });

    // Fallback: if Odoo does NOT update the DOM after saving (e.g. the server
    // returns the same content), the MutationObserver never fires and the field
    // stays in "saving" state.  Force a re-render after a generous timeout.
    setTimeout(() => {
        if (!window.renderMathInElement) return;
        document.querySelectorAll(`.o_field_html[${PROCESSED_ATTR}="saving"]`).forEach((fieldEl) => {
            const editorEl = fieldEl.querySelector(".odoo-editor-editable");
            if (editorEl) _processEditableField(fieldEl, editorEl);
        });
    }, SAVE_FALLBACK_DELAY_MS);
}

function _installSaveProtection() {
    // Save button click
    document.addEventListener("click", (e) => {
        if (e.target && e.target.closest(
            ".o_form_button_save, .o_form_button_save_manually, [data-action='save']"
        )) {
            _restoreAllForSave();
        }
    }, true);

    // Ctrl+S / Cmd+S keyboard shortcut
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s" && !e.defaultPrevented) {
            _restoreAllForSave();
        }
    }, true);
}

// ── Readonly-field rendering ─────────────────────────────────────────────────

/**
 * Render KaTeX directly in the content element of a readonly HTML field.
 * No copy is created — the original element is rendered in-place so headings
 * remain in the same DOM element and TOC scroll links work correctly.
 */
function _processReadonlyField(fieldEl) {
    if (fieldEl.getAttribute(PROCESSED_ATTR) === "readonly") return;

    const contentEl =
        fieldEl.querySelector(".odoo-editor-editable") ||
        fieldEl.querySelector(":scope > div");
    if (!contentEl) return;
    if (!_containsLatex(contentEl.textContent)) return;

    const beforeHtml = contentEl.innerHTML;
    try {
        window.renderMathInElement(contentEl, MATH_OPTIONS);
    } catch (e) {
        console.debug("[APS Math] KaTeX error:", e);
        return;
    }
    if (contentEl.innerHTML === beforeHtml) return; // no real formulas found

    fieldEl.setAttribute(PROCESSED_ATTR, "readonly");
}

// ── Editable-field in-place rendering ────────────────────────────────────────

/**
 * Render KaTeX directly in the odoo-editor-editable div, storing the original
 * LaTeX HTML in _originalHtmlMap for later restoration.
 *
 * Flow:
 *   1. Cleanup: remove any previously injected button; restore original LaTeX
 *      if the field was previously in "view" or "edit" mode.
 *   2. Check for LaTeX; skip if none.
 *   3. Store original HTML, render KaTeX in-place, set data-aps-math="view".
 *   4. Add floating "Edit" button that swaps between raw LaTeX and rendered view.
 */
function _processEditableField(fieldEl, editorEl) {
    const mode = fieldEl.getAttribute(PROCESSED_ATTR);

    // Don't disrupt the user while they are actively editing.
    if (mode === "edit") {
        const hasFocus =
            editorEl === document.activeElement ||
            editorEl.contains(document.activeElement);
        if (hasFocus) return;
    }

    // ── Clean up any previously injected button ──────────────────────────────
    fieldEl.querySelector(":scope > .aps-math-edit-toggle")?.remove();

    // ── Restore original LaTeX if we previously modified the editor HTML ─────
    // This covers re-processing after a save or a field content refresh.
    if (mode === "view" || mode === "edit") {
        const stored = _originalHtmlMap.get(editorEl);
        if (stored !== undefined) {
            _setHtml(editorEl, stored);
            _originalHtmlMap.delete(editorEl);
        }
    }
    fieldEl.removeAttribute(PROCESSED_ATTR);

    // ── Fresh evaluation from the (now LaTeX) content ────────────────────────
    if (!_containsLatex(editorEl.textContent)) return;

    const originalHTML = editorEl.innerHTML;

    // Render KaTeX directly into the editor element.
    _renderingInProgress.add(editorEl);
    try {
        window.renderMathInElement(editorEl, MATH_OPTIONS);
    } catch (e) {
        console.debug("[APS Math] KaTeX error:", e);
        _renderingInProgress.delete(editorEl);
        return;
    }
    setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);

    // If nothing changed there were no real formulas — nothing to do.
    if (editorEl.innerHTML === originalHTML) return;

    _originalHtmlMap.set(editorEl, originalHTML);
    fieldEl.setAttribute(PROCESSED_ATTR, "view");

    // ── Toggle button (floats top-right, zero extra form space) ─────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "aps-math-edit-toggle btn btn-sm btn-outline-secondary";
    btn.title = "This html field contains formulas";
    btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';

    btn.addEventListener("click", () => {
        const isViewing = fieldEl.getAttribute(PROCESSED_ATTR) === "view";
        if (isViewing) {
            // ── Switch to edit mode: restore original LaTeX ──────────────────
            const orig = _originalHtmlMap.get(editorEl);
            if (orig !== undefined) {
                _setHtml(editorEl, orig);
            }
            btn.innerHTML = '<i class="fa fa-eye" aria-hidden="true"></i> View';
            fieldEl.setAttribute(PROCESSED_ATTR, "edit");
            editorEl.focus();
        } else {
            // ── Switch back to view mode: capture any edits and re-render ────
            // Store the current (possibly edited) LaTeX as the new original.
            _originalHtmlMap.set(editorEl, editorEl.innerHTML);
            _renderingInProgress.add(editorEl);
            try {
                window.renderMathInElement(editorEl, MATH_OPTIONS);
            } catch (e) {
                console.debug("[APS Math] KaTeX error:", e);
            }
            setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);
            btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';
            fieldEl.setAttribute(PROCESSED_ATTR, "view");
        }
    });

    fieldEl.appendChild(btn);
}

// ── Container processing ─────────────────────────────────────────────────────

function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    // Readonly fields — render in-place, no toggle button.
    const readonlyFields = container.querySelectorAll(
        ".o_field_html.o_readonly_modifier, .o_field_html_readonly"
    );
    readonlyFields.forEach(_processReadonlyField);

    // Editable fields — render in-place with Edit/View toggle button.
    const editableFields = container.querySelectorAll(
        ".o_field_html:not(.o_readonly_modifier)"
    );
    editableFields.forEach((fieldEl) => {
        // Skip "saving" state — the field will be re-processed by the observer
        // once Odoo updates the DOM after the save completes.
        if (fieldEl.getAttribute(PROCESSED_ATTR) === "saving") return;
        const editorEl = fieldEl.querySelector(".odoo-editor-editable");
        if (editorEl) {
            _processEditableField(fieldEl, editorEl);
        }
    });
}

// ── Debounced scheduling ─────────────────────────────────────────────────────

let _pendingTimer = null;

function _scheduleProcess(container) {
    clearTimeout(_pendingTimer);
    _pendingTimer = setTimeout(() => {
        _pendingTimer = null;
        if (window.renderMathInElement) {
            _processContainer(container || document.body);
        }
    }, 200);
}

// ── Odoo service registration ────────────────────────────────────────────────

registry.category("services").add("aps_math_renderer", {
    start() {
        _ensureKaTeXCSS();
        _loadKaTeX().then(() => {
            _processContainer(document.body);
        });

        _installSaveProtection();

        const observer = new MutationObserver((mutations) => {
            let shouldProcess = false;
            for (const mutation of mutations) {
                // ── Case A: Content of odoo-editor-editable changed (e.g., after save).
                //    Skip mutations we caused ourselves (in-place rendering / restoration).
                //    Also skip while the editor has focus (user is actively typing).
                if (
                    mutation.type === "childList" &&
                    mutation.target.classList &&
                    mutation.target.classList.contains("odoo-editor-editable") &&
                    !_renderingInProgress.has(mutation.target) &&
                    !mutation.target.contains(document.activeElement)
                ) {
                    shouldProcess = true;
                    break;
                }

                // ── Case B: New field widget elements added (SPA navigation, tab switch).
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
                    if (
                        node.classList.contains("odoo-editor-editable") ||
                        node.classList.contains("o_field_html") ||
                        node.classList.contains("o_field_html_readonly") ||
                        (node.querySelector && node.querySelector(
                            ".o_field_html .odoo-editor-editable"
                        ))
                    ) {
                        shouldProcess = true;
                        break;
                    }
                }

                // ── Case C: o_readonly_modifier class added/removed at runtime.
                if (
                    mutation.type === "attributes" &&
                    mutation.target.classList &&
                    mutation.target.classList.contains("o_field_html")
                ) {
                    shouldProcess = true;
                }

                if (shouldProcess) break;
            }
            if (shouldProcess) {
                _scheduleProcess(document.body);
            }
        });

        observer.observe(document.body, {
            childList:  true,
            subtree:    true,
            attributes: true,
            attributeFilter: ["class"],
        });

        return {};
    },
});
