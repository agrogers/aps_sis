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
 *   .aps-toc-float-anchor — sticky top:36px, z-index:5  — holds a clone of
 *                           the TOC element when float mode is active.
 *
 * The floating panel is styled via .aps-toc-float-anchor in math_formula.css.
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

// Sticky anchor that holds the TOC clone when float mode is active.
const TOC_ANCHOR_CLASS = "aps-toc-float-anchor";

// Class added to the cloned TOC so CSS can distinguish it from the original.
const TOC_CLONE_CLASS = "aps-toc-clone";

// Selector that matches only the original TOC, not any injected clone.
const TOC_ORIGINAL_SELECTOR = `${TOC_SELECTOR}:not(.${TOC_CLONE_CLASS})`;

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return true if fieldEl contains an embedded TOC (excluding clones). */
function _hasToc(fieldEl) {
    return !!fieldEl.querySelector(TOC_ORIGINAL_SELECTOR);
}

// ── Per-field processing ─────────────────────────────────────────────────────

/**
 * Ensure fieldEl has exactly one TOC toggle button injected into the shared
 * button wrapper, and a sticky TOC anchor sibling ready for float mode.
 * Safe to call multiple times — removes any stale elements first.
 */
function _processTocField(fieldEl) {
    if (!_hasToc(fieldEl)) return;

    // Remove any previously injected button and anchor (e.g. after DOM refresh).
    fieldEl.querySelector(`.${BTN_CLASS}`)?.remove();
    fieldEl.querySelector(`:scope > .${TOC_ANCHOR_CLASS}`)?.remove();

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

    /** Sync button text/title and TOC anchor content to the current float state. */
    const syncState = () => {
        const isFloating = fieldEl.getAttribute(TOC_ATTR) === "float";
        if (isFloating) {
            btn.innerHTML = '<i class="fa fa-times" aria-hidden="true"></i> TOC';
            btn.title = "Restore table of contents to inline position";
            // Populate anchor with a fresh clone of the original TOC.
            const tocEl = fieldEl.querySelector(TOC_ORIGINAL_SELECTOR);
            if (tocEl) {
                tocAnchor.innerHTML = "";
                const clone = tocEl.cloneNode(true);
                clone.classList.add(TOC_CLONE_CLASS);
                tocAnchor.appendChild(clone);
            }
        } else {
            btn.innerHTML = '<i class="fa fa-list" aria-hidden="true"></i> TOC';
            btn.title = "Float table of contents";
            tocAnchor.innerHTML = "";
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

    // Sync to any pre-existing float state (e.g. field re-processed after save).
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
                //    Exclude our own injected clones to avoid a re-process loop.
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
                    if (
                        node.classList.contains("o_field_html") ||
                        node.classList.contains("o_field_html_readonly") ||
                        (node.classList.contains("o_embedded_toc_content") &&
                            !node.classList.contains(TOC_CLONE_CLASS)) ||
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
