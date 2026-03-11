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
 * The floating panel is styled via data-aps-toc="float" in math_formula.css.
 */

import { registry } from "@web/core/registry";

// data-attribute set on .o_field_html to track the current TOC display mode.
const TOC_ATTR = "data-aps-toc";

// Selector for the TOC wrapper element produced by Odoo's HTML editor.
const TOC_SELECTOR = ".o_embedded_toc_content";

// Class added to the injected toggle button so it can be found / removed.
const BTN_CLASS = "aps-toc-float-toggle";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return true if fieldEl contains an embedded TOC. */
function _hasToc(fieldEl) {
    return !!fieldEl.querySelector(TOC_SELECTOR);
}

// ── Per-field processing ─────────────────────────────────────────────────────

/**
 * Ensure fieldEl has exactly one TOC toggle button injected.
 * Safe to call multiple times — removes any stale button first.
 */
function _processTocField(fieldEl) {
    if (!_hasToc(fieldEl)) return;

    // Remove any previously injected button (e.g. after DOM refresh).
    fieldEl.querySelector(`:scope > .${BTN_CLASS}`)?.remove();

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `${BTN_CLASS} btn btn-sm btn-outline-secondary`;
    btn.title = "Toggle table of contents position";
    btn.innerHTML = '<i class="fa fa-list" aria-hidden="true"></i> TOC';

    btn.addEventListener("click", () => {
        const isFloating = fieldEl.getAttribute(TOC_ATTR) === "float";
        if (isFloating) {
            fieldEl.removeAttribute(TOC_ATTR);
            btn.innerHTML = '<i class="fa fa-list" aria-hidden="true"></i> TOC';
            btn.title = "Float table of contents";
        } else {
            fieldEl.setAttribute(TOC_ATTR, "float");
            btn.innerHTML = '<i class="fa fa-times" aria-hidden="true"></i> TOC';
            btn.title = "Restore table of contents to inline position";
        }
    });

    // Prepend so float:right anchors it top-right.  Both this button and the
    // math-formula edit toggle use float:right; the browser stacks them
    // horizontally (last-prepended appears leftmost).
    fieldEl.prepend(btn);
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
            }

            if (shouldProcess) {
                _scheduleProcess(document.body);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        return {};
    },
});
