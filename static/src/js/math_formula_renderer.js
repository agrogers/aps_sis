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
 *
 * Behaviour by field type:
 *   Readonly fields (o_readonly_modifier class present):
 *     Math is rendered directly in-place.
 *
 *   Editable fields that contain LaTeX:
 *     A rendered preview div replaces the live editor visually.  A small
 *     toggle button at the top of the field lets the user switch between the
 *     rendered view and the raw editor.  The editor div's innerHTML is never
 *     modified, so Odoo always saves the original LaTeX source.
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

// Attribute set on .o_field_html wrappers we have already processed so that
// re-runs of _processContainer skip them.
const PROCESSED_ATTR = "data-aps-math";

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

/** Quick test: does this text contain any LaTeX delimiter? */
function _containsLatex(text) {
    return /\$|\\\(|\\\[/.test(text);
}

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

// ── Editable-field overlay toggle ────────────────────────────────────────────

/**
 * For an editable HTML field (.o_field_html without o_readonly_modifier) that
 * contains LaTeX:
 *
 *  1. A rendered preview div (.aps-math-preview) is created from the editor's
 *     current innerHTML and injected immediately after the editor div.
 *  2. The live editor div is hidden (display:none).  Its innerHTML is never
 *     changed, so Odoo always reads — and saves — the original LaTeX source.
 *  3. A small toggle button is inserted at the top of the field widget so the
 *     user can switch between the rendered preview and the raw editor.
 *
 * When the user toggles to "edit" mode the editor is shown and focused.
 * When they toggle back to "view" mode the preview is rebuilt from the
 * editor's current content (picking up any edits the user made).
 */
function _processEditableField(fieldEl, editorEl) {
    // Skip if already processed by us
    if (fieldEl.hasAttribute(PROCESSED_ATTR)) return;
    // Skip if no LaTeX delimiters in the field content
    if (!_containsLatex(editorEl.textContent)) return;

    // Render math into a throw-away clone first to confirm real formulas exist
    const preview = document.createElement("div");
    preview.className = "aps-math-preview";
    preview.innerHTML = editorEl.innerHTML;
    try {
        window.renderMathInElement(preview, MATH_OPTIONS);
    } catch (e) {
        console.debug("[APS Math] KaTeX error:", e);
        return;
    }
    // If rendering made no visible change there are no real formulas — bail
    if (preview.innerHTML === editorEl.innerHTML) return;

    // Mark this field as processed (value tracks current display mode)
    fieldEl.setAttribute(PROCESSED_ATTR, "view");

    // Insert the rendered preview right after the editor div and hide editor
    editorEl.insertAdjacentElement("afterend", preview);
    editorEl.style.display = "none";

    // ── Toggle button ────────────────────────────────────────────────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "aps-math-edit-toggle btn btn-sm btn-outline-secondary mb-1";
    btn.innerHTML = '<i class="fa fa-pencil me-1"></i>Edit formula';

    btn.addEventListener("click", () => {
        const viewing = fieldEl.getAttribute(PROCESSED_ATTR) === "view";
        if (viewing) {
            // Switch to edit mode: show raw editor, hide preview
            preview.style.display = "none";
            editorEl.style.display = "";
            btn.innerHTML = '<i class="fa fa-eye me-1"></i>View formula';
            fieldEl.setAttribute(PROCESSED_ATTR, "edit");
            editorEl.focus();
        } else {
            // Switch back to view mode: rebuild preview from current editor
            // content (captures any edits the user just made), then hide editor
            preview.innerHTML = editorEl.innerHTML;
            try {
                window.renderMathInElement(preview, MATH_OPTIONS);
            } catch (e) {
                console.debug("[APS Math] KaTeX error:", e);
            }
            editorEl.style.display = "none";
            preview.style.display = "";
            btn.innerHTML = '<i class="fa fa-pencil me-1"></i>Edit formula';
            fieldEl.setAttribute(PROCESSED_ATTR, "view");
        }
    });

    // Place the toggle button as the very first child of the field widget so
    // it sits above both the editor div and the preview div.
    fieldEl.insertBefore(btn, fieldEl.firstChild);
}

// ── Container processing ─────────────────────────────────────────────────────

/**
 * Process all HTML fields inside *container*:
 *
 *  • Readonly fields (o_readonly_modifier present) — render math directly
 *    in-place inside the .odoo-editor-editable div.
 *  • Editable fields (no o_readonly_modifier) that contain LaTeX — delegate
 *    to _processEditableField which creates a rendered preview + toggle.
 */
function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    // ── 1. Readonly fields ───────────────────────────────────────────────────
    // In Odoo 18 the readonly modifier adds the class o_readonly_modifier to
    // the outermost .o_field_html div (user-confirmed class name).
    // The alternative selector handles contexts where a dedicated readonly
    // wrapper class is used instead.
    const readonlyEditors = container.querySelectorAll(
        ".o_field_html.o_readonly_modifier .odoo-editor-editable, " +
        ".o_field_html_readonly .odoo-editor-editable"
    );
    readonlyEditors.forEach(_renderMathIn);

    // ── 2. Editable fields ───────────────────────────────────────────────────
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
