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
 *   inline  (default) — TOC renders in its normal document-flow position.
 *   float            — The TOC element itself becomes a zero-height sticky
 *                      container; its children overflow out as a right-aligned
 *                      panel.  No DOM moves are needed: the element stays in
 *                      its original position so all JS event listeners (hover
 *                      highlights, click-to-scroll) and CSS ancestor rules
 *                      (indentation) are preserved automatically.
 *
 * The CSS in math_formula.css overrides the `overflow-auto` class on the
 * div immediately above `.odoo-editor-editable`, which is what prevented
 * `position:sticky` from working inside the editor content area.
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

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return true if fieldEl contains an embedded TOC. */
function _hasToc(fieldEl) {
    return !!fieldEl.querySelector(TOC_SELECTOR);
}

// ── Per-field processing ─────────────────────────────────────────────────────

/**
 * Ensure fieldEl has exactly one TOC toggle button injected into the shared
 * button wrapper.  Safe to call multiple times — removes any stale button first.
 */
function _processTocField(fieldEl) {
    fieldEl.querySelector(`.${BTN_CLASS}`)?.remove();

    if (!_hasToc(fieldEl)) return;

    // ── Button wrapper ──────────────────────────────────────────────────────
    // Shared with math_formula_renderer.js.  Created here if not already present.
    let btnsWrapper = fieldEl.querySelector(`:scope > .${BTNS_WRAPPER_CLASS}`);
    if (!btnsWrapper) {
        btnsWrapper = document.createElement("div");
        btnsWrapper.className = BTNS_WRAPPER_CLASS;
        fieldEl.prepend(btnsWrapper);
    }

    // ── Toggle button ───────────────────────────────────────────────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `${BTN_CLASS} btn btn-sm btn-outline-secondary`;

    /** Sync button label to the current float state. */
    const syncState = () => {
        const isFloating = fieldEl.getAttribute(TOC_ATTR) === "float";
        btn.innerHTML = isFloating
            ? '<i class="fa fa-times" aria-hidden="true"></i> TOC'
            : '<i class="fa fa-list" aria-hidden="true"></i> TOC';
        btn.title = isFloating
            ? "Restore table of contents to inline position"
            : "Float table of contents";
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

    // Sync to any pre-existing float state (e.g. after SPA navigation).
    // Default to floating if no explicit mode has been set yet.
    if (!fieldEl.hasAttribute(TOC_ATTR)) {
        fieldEl.setAttribute(TOC_ATTR, "float");
    }
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

        const observer = new MutationObserver((mutations) => {
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
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
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

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["class"],
        });

        return {};
    },
});
