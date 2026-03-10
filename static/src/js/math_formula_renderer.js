/** @odoo-module **/

/**
 * Math Formula Renderer for APS SIS
 *
 * Renders LaTeX formulas in Odoo 18 HTML fields using KaTeX.
 * Formulas are delimited by:
 *   $...$    — inline math
 *   $$...$$  — display (block) math
 *   \(...\)  — inline math (alternative)
 *   \[...\]  — display math (alternative)
 *
 * KaTeX and its auto-render extension are loaded dynamically (not through
 * Odoo's asset bundler) to avoid a conflict with Odoo's AMD module loader.
 *
 * Behaviour:
 *
 *   Readonly fields (o_readonly_modifier class present):
 *     renderMathInElement() is called directly on the content div.  No copy
 *     is created — the original element is rendered in-place.  TOC links work
 *     because headings remain in the same DOM element.
 *
 *   Editable fields:
 *     Left entirely untouched.  The user edits raw LaTeX in Odoo's standard
 *     HTML editor.  When the form is saved (or the field becomes readonly),
 *     the MutationObserver detects the o_readonly_modifier class appearing and
 *     triggers rendering automatically.
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

// ── Readonly-field rendering ─────────────────────────────────────────────────

/**
 * Render KaTeX directly in the content element of a readonly HTML field.
 * No copy is created — the original element is rendered in-place so headings
 * remain in the same DOM element and TOC scroll links work correctly.
 */
function _processReadonlyField(fieldEl) {
    const contentEl =
        fieldEl.querySelector(".odoo-editor-editable") ||
        fieldEl.querySelector(":scope > div");
    if (!contentEl) return;

    // Skip if KaTeX has already rendered this content.
    if (contentEl.querySelector(".katex")) return;

    if (!_containsLatex(contentEl.textContent)) return;

    const beforeHtml = contentEl.innerHTML;
    try {
        window.renderMathInElement(contentEl, MATH_OPTIONS);
    } catch (e) {
        console.debug("[APS Math] KaTeX error:", e);
        return;
    }
    if (contentEl.innerHTML === beforeHtml) return; // no real formulas found
}

// ── Container processing ─────────────────────────────────────────────────────

function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    container.querySelectorAll(
        ".o_field_html.o_readonly_modifier, .o_field_html_readonly"
    ).forEach(_processReadonlyField);
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
                // ── Case A: New field elements added (SPA navigation, tab switch).
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== Node.ELEMENT_NODE) continue;
                    if (
                        node.classList.contains("o_field_html") ||
                        node.classList.contains("o_field_html_readonly") ||
                        (node.querySelector && node.querySelector(
                            ".o_field_html, .o_field_html_readonly"
                        ))
                    ) {
                        shouldProcess = true;
                        break;
                    }
                }

                // ── Case B: o_readonly_modifier class added to a field element.
                //    This fires when the form switches from edit mode to view mode.
                if (
                    mutation.type === "attributes" &&
                    mutation.target.classList &&
                    mutation.target.classList.contains("o_field_html") &&
                    mutation.target.classList.contains("o_readonly_modifier")
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
