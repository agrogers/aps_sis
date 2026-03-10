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
 *     The original LaTeX HTML is stored in a WeakMap (in memory only — never
 *     persisted to the database).  renderMathInElement() is then called
 *     directly on the odoo-editor-editable div so only one copy of the
 *     content is ever in the DOM.
 *
 *     A small "Edit" button floats at the top-right corner of the field.
 *     Clicking it restores the original LaTeX into the editor so the user
 *     can make changes.  Clicking "View" re-renders the updated LaTeX.
 *
 *     No save-protection listeners are needed.  Odoo's OdooEditor maintains
 *     its own internal model that is only updated by editor event handlers;
 *     our direct renderMathInElement() DOM changes are ignored by the editor
 *     and never affect what gets saved.  After a save Odoo patches the DOM
 *     from the server response, the MutationObserver fires, and the field is
 *     re-rendered automatically.
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

// ── State ────────────────────────────────────────────────────────────────────

/**
 * Stores the original LaTeX HTML string for each editorEl while the field
 * is displaying the KaTeX-rendered version.  Kept in memory only — never
 * written to the database.  Used to restore raw LaTeX for editing or to
 * detect what changed before re-rendering.
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
 * LaTeX HTML in _originalHtmlMap (in memory only) for later restoration.
 *
 * Flow:
 *   1. Cleanup: remove any previously injected button; restore original LaTeX
 *      if the field was previously in "view" or "edit" mode.
 *   2. Check for LaTeX; skip if none.
 *   3. Store original HTML in memory, render KaTeX in-place, set data-aps-math="view".
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

    // Store original LaTeX in memory (not in the database).
    _originalHtmlMap.set(editorEl, originalHTML);
    fieldEl.setAttribute(PROCESSED_ATTR, "view");

    // ── Toggle button (floats top-right, zero extra form space) ─────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "aps-math-edit-toggle btn btn-sm btn-outline-secondary";
    btn.title = "This HTML field contains formulas";
    btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';

    btn.addEventListener("click", () => {
        const isViewing = fieldEl.getAttribute(PROCESSED_ATTR) === "view";
        if (isViewing) {
            // ── Switch to edit mode: restore original LaTeX from memory ──────
            const orig = _originalHtmlMap.get(editorEl);
            if (orig !== undefined) {
                _setHtml(editorEl, orig);
            }
            btn.innerHTML = '<i class="fa fa-eye" aria-hidden="true"></i> View';
            fieldEl.setAttribute(PROCESSED_ATTR, "edit");
            editorEl.focus();
        } else {
            // ── Switch back to view mode: capture any edits and re-render ────
            // Store the current (possibly edited) LaTeX as the new original
            // in memory.  Odoo's model already holds this value since it is
            // updated by the editor's own event handlers — we only track it
            // here so we can restore it if the user clicks Edit again.
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
                        // Broad descendant check: addedNodes may be a wrapper
                        // container holding multiple fields (SPA nav, tab switch).
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
