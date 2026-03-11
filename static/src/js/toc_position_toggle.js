/**
 * TOC Position Toggle for APS SIS
 *
 * For any HTML field that contains an Odoo embedded table of contents
 * (`.o_embedded_toc_content`), this service injects a small sticky toggle
 * button at the top-right of the field (beside the math-formula edit toggle
 * when both are present).
 *
 * Clicking the button alternates the field between two modes:
 *
 *   inline  (default) — TOC is rendered in its normal document-flow position.
 *   float            — TOC panel overlays the field content, anchored to the
 *                      top-right corner, below the control buttons.
 *
 * Layout technique — zero-height sticky wrappers
 * ───────────────────────────────────────────────
 * Both the button and the floating TOC panel live inside zero-height
 * (height:0; overflow:visible) sticky divs.  Because the containers have
 * zero height they take no space in the document flow, so the field's text
 * content is never pushed aside by the button.  pointer-events:none on the
 * container (re-enabled on children) lets clicks pass through to the field.
 *
 *   .aps-float-buttons    — sticky top:4px,  z-index:10 — shared with the
 *                           math-formula edit-toggle button.
 *   .aps-toc-float-anchor — sticky top:36px, z-index:5  — holds the original
 *                           TOC element when float mode is active.
 *
 * DOM-move (not clone) strategy
 * ──────────────────────────────
 * The TOC element is MOVED (not cloned) into the anchor.  This preserves all
 * JavaScript event listeners attached by Odoo's HTML editor (hover highlights,
 * click-to-scroll navigation, etc.) and keeps ancestor CSS selectors matching
 * via a display:contents wrapper that carries the original parent classes.
 * A hidden placeholder <span> is left at the original position so the element
 * can be moved back on deactivation or before form save.
 *
 * The MutationObserver is paused during DOM moves to prevent re-process loops.
 */

import { registry } from "@web/core/registry";

// data-attribute set on .o_field_html to track the current TOC display mode.
const TOC_ATTR = "data-aps-toc";

// Selector for the TOC wrapper element produced by Odoo's HTML editor.
const TOC_SELECTOR = ".o_embedded_toc_content";

// Class added to the injected toggle button so it can be found / removed.
const BTN_CLASS = "aps-toc-float-toggle";

// Shared button-row wrapper (also used by math_formula_renderer.js).
const BTNS_WRAPPER_CLASS = "aps-float-buttons";

// Sticky anchor that holds the original TOC when float mode is active.
const TOC_ANCHOR_CLASS = "aps-toc-float-anchor";

// Class on the invisible placeholder that marks the TOC's original position.
const TOC_PLACEHOLDER_CLASS = "aps-toc-placeholder";

// MutationObserver options — stored once so _withObserverPaused can re-observe.
const OBSERVER_OPTIONS = {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
};

// Module-level reference to the observer so helpers can pause it during moves.
let _observer = null;

// ── Observer helpers ──────────────────────────────────────────────────────────

/**
 * Temporarily disconnect the observer, run fn(), then reconnect.
 * Prevents our own DOM moves from triggering further re-process cycles.
 */
function _withObserverPaused(fn) {
    if (_observer) _observer.disconnect();
    try {
        fn();
    } finally {
        if (_observer) _observer.observe(document.body, OBSERVER_OPTIONS);
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return true if fieldEl contains an embedded TOC. */
function _hasToc(fieldEl) {
    return !!fieldEl.querySelector(TOC_SELECTOR);
}

/**
 * Restore the TOC element from the floating anchor back to its original
 * inline position (tracked by a placeholder span).
 *
 * Called both at the start of each _processTocField run (ensures the TOC
 * is always back in the editor before we rebuild the UI) and directly when
 * deactivating float mode via the button.
 */
function _restoreTocToInline(fieldEl) {
    const anchor = fieldEl.querySelector(`:scope > .${TOC_ANCHOR_CLASS}`);
    if (!anchor) return;
    // The TOC lives inside a display:contents context wrapper inside the anchor.
    const tocEl = anchor.querySelector(TOC_SELECTOR);
    if (!tocEl) return;
    const placeholder = fieldEl.querySelector(`.${TOC_PLACEHOLDER_CLASS}`);
    _withObserverPaused(() => {
        if (placeholder) {
            placeholder.parentNode.insertBefore(tocEl, placeholder);
            placeholder.remove();
        } else {
            // Fallback: prepend to the editor element or the field itself.
            const editorEl =
                fieldEl.querySelector(".odoo-editor-editable") || fieldEl;
            editorEl.prepend(tocEl);
        }
    });
}

// ── Per-field processing ─────────────────────────────────────────────────────

/**
 * Ensure fieldEl has exactly one TOC toggle button injected into the shared
 * button wrapper, and a sticky TOC anchor ready for float mode.
 * Safe to call multiple times — restores and rebuilds on each call.
 */
function _processTocField(fieldEl) {
    // Always restore the TOC to its inline position before we tear down and
    // rebuild the UI.  This ensures the editor DOM is consistent during
    // re-processing (e.g. when Odoo switches between edit/readonly modes).
    _restoreTocToInline(fieldEl);

    // Remove stale UI from the previous run.
    fieldEl.querySelector(`.${BTN_CLASS}`)?.remove();
    fieldEl.querySelector(`:scope > .${TOC_ANCHOR_CLASS}`)?.remove();
    fieldEl.querySelector(`.${TOC_PLACEHOLDER_CLASS}`)?.remove();

    if (!_hasToc(fieldEl)) return;

    // ── Button wrapper ──────────────────────────────────────────────────────
    // Shared with math_formula_renderer.js.  Created here if not already present.
    let btnsWrapper = fieldEl.querySelector(`:scope > .${BTNS_WRAPPER_CLASS}`);
    if (!btnsWrapper) {
        btnsWrapper = document.createElement("div");
        btnsWrapper.className = BTNS_WRAPPER_CLASS;
        fieldEl.prepend(btnsWrapper);
    }

    // ── TOC sticky anchor ───────────────────────────────────────────────────
    // Inserted directly after the button wrapper so its sticky top:36px places
    // the panel just below the button row.
    const tocAnchor = document.createElement("div");
    tocAnchor.className = TOC_ANCHOR_CLASS;
    btnsWrapper.insertAdjacentElement("afterend", tocAnchor);

    // ── Toggle button ───────────────────────────────────────────────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `${BTN_CLASS} btn btn-sm btn-outline-secondary`;

    /**
     * Sync button label and panel content to the current float state.
     *
     * When activating:  move the original TOC element (not a clone) into
     *   tocAnchor, wrapped in a display:contents div that carries the
     *   original parent classes (.odoo-editor-editable, .o_field_html) so
     *   Odoo's ancestor-scoped CSS rules (indentation, hover styles, etc.)
     *   continue to match.  A hidden placeholder <span> is left in the
     *   TOC's original position for later restoration.
     *
     * When deactivating: move the TOC back to the placeholder position.
     */
    const syncState = () => {
        const isFloating = fieldEl.getAttribute(TOC_ATTR) === "float";
        if (isFloating) {
            btn.innerHTML = '<i class="fa fa-times" aria-hidden="true"></i> TOC';
            btn.title = "Restore table of contents to inline position";

            const tocEl = fieldEl.querySelector(TOC_SELECTOR);
            if (tocEl && !tocAnchor.contains(tocEl)) {
                _withObserverPaused(() => {
                    // Leave a hidden placeholder at the original position.
                    const placeholder = document.createElement("span");
                    placeholder.className = TOC_PLACEHOLDER_CLASS;
                    placeholder.hidden = true;
                    tocEl.insertAdjacentElement("beforebegin", placeholder);

                    // Wrap in a display:contents element that provides the same
                    // CSS ancestor context as the original editor parent so that
                    // Odoo's scoped TOC styles (indentation, hover, etc.) match.
                    const ctxWrapper = document.createElement("div");
                    ctxWrapper.className = "odoo-editor-editable o_field_html";
                    ctxWrapper.style.display = "contents";
                    ctxWrapper.appendChild(tocEl);
                    tocAnchor.appendChild(ctxWrapper);
                });
            }
        } else {
            btn.innerHTML = '<i class="fa fa-list" aria-hidden="true"></i> TOC';
            btn.title = "Float table of contents";
            _restoreTocToInline(fieldEl);
        }
    };

    btn.addEventListener("click", () => {
        const isFloating = fieldEl.getAttribute(TOC_ATTR) === "float";
        if (isFloating) {
            fieldEl.removeAttribute(TOC_ATTR);
        } else {
            fieldEl.setAttribute(TOC_ATTR, "float");
        }
        syncState();
    });

    // Sync to any pre-existing float state (e.g. field re-processed after a
    // SPA navigation while float was active).
    syncState();

    // Prepend so the TOC button appears to the right of any existing buttons
    // (flex-direction:row-reverse means first-in-DOM = rightmost visually).
    btnsWrapper.prepend(btn);
}

// ── Container scan ────────────────────────────────────────────────────────────

function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    container
        .querySelectorAll(".o_field_html, .o_field_html_readonly")
        .forEach(_processTocField);
}

// ── Debounced scheduling ──────────────────────────────────────────────────────

let _pendingTimer = null;

function _scheduleProcess(container) {
    clearTimeout(_pendingTimer);
    _pendingTimer = setTimeout(() => {
        _pendingTimer = null;
        _processContainer(container || document.body);
    }, 250);
}

// ── Odoo service registration ─────────────────────────────────────────────────

registry.category("services").add("aps_toc_position_toggle", {
    start() {
        _processContainer(document.body);

        // ── Save guard ────────────────────────────────────────────────────────
        // If a floating TOC is active when the user saves the form, the
        // original TOC element is outside odoo-editor-editable and would be
        // omitted from the serialised content, causing data loss.  Move all
        // floating TOCs back to inline before Odoo's save handler fires.
        // The closest() call exits immediately for the vast majority of clicks
        // (non-save buttons), so the per-click cost is negligible.
        document.addEventListener(
            "click",
            (e) => {
                if (!e.target.closest(".o_form_button_save, [name='button_save']"))
                    return;
                document
                    .querySelectorAll(`[${TOC_ATTR}="float"]`)
                    .forEach((fieldEl) => {
                        fieldEl.removeAttribute(TOC_ATTR);
                        _restoreTocToInline(fieldEl);
                    });
            },
            true // capture: runs before Odoo's save click handler
        );

        _observer = new MutationObserver((mutations) => {
            let shouldProcess = false;

            for (const mutation of mutations) {
                // ── Case A: Content of odoo-editor-editable changed.
                //    This is the primary trigger for editable fields: Odoo loads
                //    the field value (including any TOC) as children of this element
                //    after the wrapper is already in the DOM.
                if (
                    mutation.type === "childList" &&
                    mutation.target.classList &&
                    mutation.target.classList.contains("odoo-editor-editable")
                ) {
                    shouldProcess = true;
                    break;
                }

                // ── Case B: New field / TOC elements added (SPA nav, tab switch,
                //    readonly fields rendered server-side all at once).
                //    Nodes inside .aps-toc-float-anchor are our own moves —
                //    exclude them to avoid re-process loops.
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
                    if (node.closest(`.${TOC_ANCHOR_CLASS}`)) continue;
                    if (
                        node.classList.contains("o_field_html") ||
                        node.classList.contains("o_field_html_readonly") ||
                        node.classList.contains("o_embedded_toc_content") ||
                        (node.querySelector &&
                            node.querySelector(
                                `.o_field_html ${TOC_SELECTOR}, .o_field_html_readonly ${TOC_SELECTOR}`
                            ))
                    ) {
                        shouldProcess = true;
                        break;
                    }
                }
                if (shouldProcess) break;

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

        _observer.observe(document.body, OBSERVER_OPTIONS);

        return {};
    },
});

