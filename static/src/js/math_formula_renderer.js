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
 * This renderer runs as an Odoo service and uses a MutationObserver to
 * detect new or updated HTML field content, re-rendering math whenever
 * the DOM changes.  It only processes read-only HTML fields so that the
 * raw LaTeX source is preserved in the database and visible when editing.
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
    // Never process content inside these tags (avoids double-rendering or
    // corrupting code blocks that might legitimately contain $ characters)
    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
    // Skip elements that have already been rendered by KaTeX
    ignoredClasses: ["katex", "katex-html"],
};

// CSS is loaded dynamically (NOT via Odoo's asset bundler) so that the
// relative `fonts/` URLs inside katex.min.css resolve correctly.
let _cssLoaded = false;
function _ensureKaTeXCSS() {
    if (_cssLoaded) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/aps_sis/static/src/lib/katex/katex.min.css";
    document.head.appendChild(link);
    _cssLoaded = true;
}

// ── Rendering helpers ────────────────────────────────────────────────────────

/**
 * Render math in a single DOM element.
 * Guards against rendering inside active editors (contenteditable="true").
 */
function _renderMathIn(el) {
    if (!el || !window.renderMathInElement) return;
    // Do not modify live editor content — the raw LaTeX must stay untouched
    // so that the correct value is saved to the database.
    if (el.getAttribute("contenteditable") === "true") return;
    if (el.querySelector('[contenteditable="true"]')) return;
    try {
        window.renderMathInElement(el, MATH_OPTIONS);
    } catch (err) {
        // Silently swallow errors so a broken formula never breaks the UI
        console.debug("[APS Math] KaTeX error:", err);
    }
}

/**
 * Find and process all readonly HTML fields inside *container*.
 * Both the Odoo-18 `.o_readonly` variant and the `.o_field_html_readonly`
 * selector used in some contexts are handled.
 */
function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    // Selector: the inner editable div of a readonly HTML field widget.
    // .o_field_html.o_readonly        — standard Odoo 18 read mode
    // .o_field_html_readonly           — alternative class used in some contexts
    const editableDivs = container.querySelectorAll(
        ".o_field_html.o_readonly .odoo-editor-editable, " +
        ".o_field_html_readonly .odoo-editor-editable"
    );
    editableDivs.forEach(_renderMathIn);
}

// ── Debounced scheduling ─────────────────────────────────────────────────────

let _pendingTimer = null;

function _scheduleProcess(container) {
    clearTimeout(_pendingTimer);
    _pendingTimer = setTimeout(() => {
        _pendingTimer = null;
        _processContainer(container || document.body);
    }, 80);
}

// ── Odoo service registration ────────────────────────────────────────────────

registry.category("services").add("aps_math_renderer", {
    start() {
        // Load KaTeX CSS (fonts need relative path resolution, so this must
        // be a dynamic <link> rather than an Odoo asset bundle entry).
        _ensureKaTeXCSS();

        // Render any HTML fields already present when the service starts.
        _scheduleProcess(document.body);

        // Watch for new or replaced HTML field content as Odoo navigates
        // between records or reloads field values after saves.
        const observer = new MutationObserver((mutations) => {
            let shouldProcess = false;
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
                    // Quick check: does this subtree contain an HTML field?
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
                if (shouldProcess) break;
            }
            if (shouldProcess) {
                _scheduleProcess(document.body);
            }
        });

        observer.observe(document.body, { childList: true, subtree: true });

        return {};
    },
});
