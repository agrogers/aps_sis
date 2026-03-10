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
 * Both libraries are UMD bundles that call define(["katex"], ...) which
 * Odoo's bundler misinterprets as module dependencies.  By temporarily
 * setting define.amd = false before each <script> tag is appended, the
 * scripts fall through to the plain-global export path (window.katex /
 * window.renderMathInElement) and Odoo's module system is left unaffected.
 * The define.amd flag is restored in each script's onload handler, which
 * fires after the script has fully executed.
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

const KATEX_BASE = "/aps_sis/static/src/lib/katex";

// ── Dynamic script loading that bypasses Odoo's AMD module system ────────────

/**
 * Load a plain-JS (UMD) library as a browser global, bypassing Odoo's AMD
 * module loader.
 *
 * Odoo sets window.define with define.amd = {} (truthy), which causes UMD
 * bundles to take the AMD path.  Temporarily clearing define.amd to false
 * before the <script> tag is appended means the scripts execute with AMD
 * detection disabled.  Because script.onload fires *after* the script has
 * fully executed, restoring define.amd there guarantees that the rest of
 * Odoo's module system is unaffected.
 *
 * @param {string} src  Absolute URL path to the script
 * @returns {Promise<void>}
 */
function _loadScriptAsGlobal(src) {
    return new Promise((resolve, reject) => {
        // Skip if already loaded — use a safe array search instead of CSS
        // attribute selector to avoid any escaping concerns with the src path.
        if (Array.from(document.scripts).some((s) => s.getAttribute("src") === src)) {
            resolve();
            return;
        }

        // Save and disable AMD so UMD bundles fall back to window.* exports
        const savedAmd = window.define && window.define.amd;
        if (window.define) {
            window.define.amd = false;
        }

        const _restore = () => {
            if (window.define) {
                // Use explicit undefined-check to correctly restore any falsy
                // original value (e.g. false) rather than replacing it with {}
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
        // NOTE: The script executes asynchronously (download + parse + run),
        // but define.amd is already false at the moment of execution.
        // onload is only called after execution, so define.amd is restored
        // at exactly the right time.
    });
}

/**
 * Load KaTeX CSS dynamically so that the relative fonts/ URLs inside
 * katex.min.css resolve correctly (Odoo's bundler would rebase the paths).
 */
let _cssLoaded = false;
function _ensureKaTeXCSS() {
    if (_cssLoaded) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `${KATEX_BASE}/katex.min.css`;
    document.head.appendChild(link);
    _cssLoaded = true;
}

/**
 * Load katex.min.js then auto-render.min.js sequentially (auto-render
 * requires window.katex to already be present).
 * Returns a Promise that resolves once both are ready.
 */
let _katexLoadPromise = null;
function _loadKaTeX() {
    if (_katexLoadPromise) return _katexLoadPromise;
    _katexLoadPromise = _loadScriptAsGlobal(`${KATEX_BASE}/katex.min.js`)
        .then(() => _loadScriptAsGlobal(`${KATEX_BASE}/auto-render.min.js`))
        .catch((err) => {
            // Log the failure but keep _katexLoadPromise set so callers share
            // the same resolved/rejected state and don't silently retry on
            // each MutationObserver fire.  Math formulas will simply not
            // render if the scripts cannot be loaded.
            console.warn(err.message);
        });
    return _katexLoadPromise;
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
        // Only run if KaTeX has finished loading
        if (window.renderMathInElement) {
            _processContainer(container || document.body);
        }
    }, 80);
}

// ── Odoo service registration ────────────────────────────────────────────────

registry.category("services").add("aps_math_renderer", {
    start() {
        // Load KaTeX CSS and JS (both dynamically, bypassing Odoo bundler)
        _ensureKaTeXCSS();
        _loadKaTeX().then(() => {
            // Initial render of any HTML fields already in the DOM
            _processContainer(document.body);
        });

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
