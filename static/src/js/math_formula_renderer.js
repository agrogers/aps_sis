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
 *     A rendered preview div is created from the field content.  Both the
 *     original source div and the preview are placed in the same CSS Grid cell
 *     (grid-area 1/1) so they overlap; the source is visibility:hidden so
 *     headings remain at their correct scroll positions for TOC navigation.
 *
 *   Editable fields that contain LaTeX:
 *     Same grid-stacking approach.  A small "Edit" button floats at the
 *     top-right corner of the field and lets the user switch between the
 *     rendered view and the raw editor (data-aps-math="edit"), which CSS
 *     handles by hiding the preview and restoring the source's visibility.
 *     The editor div's innerHTML is never modified, so Odoo always saves the
 *     original LaTeX source.
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

// Attribute on .o_field_html that tracks our current display state:
//   "view"     — preview shown (editable field, formula mode)
//   "edit"     — raw editor shown (user clicked Edit button)
//   "readonly" — preview shown (readonly field, no toggle)
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
 * Build and return a rendered preview div from *sourceEl*'s innerHTML.
 * Returns null if KaTeX made no visible change (no real formulas present).
 */
function _buildPreview(sourceEl) {
    const preview = document.createElement("div");
    preview.className = "aps-math-preview";
    preview.innerHTML = sourceEl.innerHTML;
    try {
        window.renderMathInElement(preview, MATH_OPTIONS);
    } catch (e) {
        console.debug("[APS Math] KaTeX error:", e);
        return null;
    }
    // If nothing changed there are no real formulas
    if (preview.innerHTML === sourceEl.innerHTML) return null;
    return preview;
}

// ── Readonly-field rendering ─────────────────────────────────────────────────

/**
 * For a readonly HTML field (.o_field_html.o_readonly_modifier):
 *  - Creates a rendered preview from the content element's HTML.
 *  - Both source and preview are placed in the same CSS Grid cell (grid-area
 *    1/1) via the data-aps-math="readonly" attribute.  CSS makes the source
 *    visibility:hidden so it is invisible but still occupies its correct
 *    layout position — Odoo's TOC links can still scroll to headings inside it.
 *  - No toggle button is added (user cannot edit anyway).
 */
function _processReadonlyField(fieldEl) {
    if (fieldEl.getAttribute(PROCESSED_ATTR) === "readonly") return;

    // Find the content container.  Prefer the Odoo editor div; fall back to
    // any direct block-level child div.
    const contentEl =
        fieldEl.querySelector(".odoo-editor-editable") ||
        fieldEl.querySelector(":scope > div");
    if (!contentEl) return;
    if (!_containsLatex(contentEl.textContent)) return;

    const preview = _buildPreview(contentEl);
    if (!preview) return;

    fieldEl.setAttribute(PROCESSED_ATTR, "readonly");
    // Insert preview after the source element.  CSS grid-area:1/1 on both
    // puts them in the same cell; source is visibility:hidden via CSS.
    contentEl.insertAdjacentElement("afterend", preview);
}

// ── Editable-field overlay toggle ────────────────────────────────────────────

/**
 * For an editable HTML field (.o_field_html without o_readonly_modifier):
 *
 *  1. Cleans up any previously injected preview/button (handles re-processing
 *     after a record save where OWL patches the field in-place rather than
 *     recreating the DOM element).
 *  2. Checks for LaTeX; if none found, leaves the field unmodified.
 *  3. Creates a rendered preview div after the editor div.  CSS Grid area
 *     stacking (triggered by data-aps-math="view") overlays the preview on
 *     the source; the source is visibility:hidden so TOC links still work.
 *  4. Inserts a small "Edit" button that floats at the top-right corner of
 *     the field wrapper, toggling between rendered view and raw editor.
 *
 * The editor div's innerHTML is NEVER modified so Odoo always reads and saves
 * the original LaTeX source.  All visibility transitions (view ↔ edit) are
 * handled entirely by CSS via the data-aps-math attribute value.
 */
function _processEditableField(fieldEl, editorEl) {
    const mode = fieldEl.getAttribute(PROCESSED_ATTR);

    // While the user is actively typing (editor has focus), don't disrupt them.
    if (mode === "edit") {
        const editorHasFocus =
            editorEl === document.activeElement ||
            editorEl.contains(document.activeElement);
        if (editorHasFocus) return;
    }

    // ── Clean up previously injected elements ────────────────────────────────
    // This handles the case where OWL patches the field in-place after a save
    // (the same .o_field_html DOM element is reused, so our PROCESSED_ATTR and
    // injected children survive the patch).
    const existingPreview = fieldEl.querySelector(":scope > .aps-math-preview");
    const existingBtn    = fieldEl.querySelector(":scope > .aps-math-edit-toggle");
    if (existingPreview) existingPreview.remove();
    if (existingBtn)     existingBtn.remove();
    // Removing data-aps-math also removes the CSS grid stacking rule and the
    // visibility:hidden on the editor element — no inline style manipulation needed.
    fieldEl.removeAttribute(PROCESSED_ATTR);

    // ── Fresh evaluation ─────────────────────────────────────────────────────
    if (!_containsLatex(editorEl.textContent)) return;

    const preview = _buildPreview(editorEl);
    if (!preview) return;

    // Setting data-aps-math="view" triggers CSS grid stacking and makes the
    // editor visibility:hidden while the preview is visible.
    fieldEl.setAttribute(PROCESSED_ATTR, "view");
    editorEl.insertAdjacentElement("afterend", preview);

    // ── Toggle button (floats top-right, zero extra form space) ─────────────
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "aps-math-edit-toggle btn btn-sm btn-outline-secondary";
    btn.title = "This html field contains formulas";
    btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';
    // position:relative on the field wrapper is set by CSS (.o_field_html[data-aps-math])

    btn.addEventListener("click", () => {
        const viewing = fieldEl.getAttribute(PROCESSED_ATTR) === "view";
        if (viewing) {
            // Switch to edit mode: CSS hides preview and restores editor
            // visibility when data-aps-math changes to "edit".
            btn.innerHTML = '<i class="fa fa-eye" aria-hidden="true"></i> View';
            fieldEl.setAttribute(PROCESSED_ATTR, "edit");
            editorEl.focus();
        } else {
            // Switch back to view mode: rebuild preview from current editor
            // content (captures any edits the user just made).
            preview.innerHTML = editorEl.innerHTML;
            try {
                window.renderMathInElement(preview, MATH_OPTIONS);
            } catch (e) {
                console.debug("[APS Math] KaTeX error:", e);
            }
            btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';
            // CSS re-applies grid stacking and visibility:hidden on editor.
            fieldEl.setAttribute(PROCESSED_ATTR, "view");
        }
    });

    // Append the button as the last child — it is absolutely positioned so
    // it floats over the top-right corner and takes no layout space.
    fieldEl.appendChild(btn);
}

// ── Container processing ─────────────────────────────────────────────────────

/**
 * Process all HTML fields inside *container*:
 *
 *  • Readonly fields (o_readonly_modifier present) — show a rendered preview;
 *    no toggle button; original content div hidden.
 *  • Editable fields (no o_readonly_modifier) — show rendered preview by
 *    default with an "Edit" button floating at top-right to toggle raw editor.
 */
function _processContainer(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;

    // ── 1. Readonly fields ───────────────────────────────────────────────────
    // In Odoo 18 the wrapper div carries classes:
    //   o_field_widget  o_readonly_modifier  o_field_html
    // We match on the combination .o_field_html.o_readonly_modifier.
    // The fallback selector handles alternative readonly class names.
    const readonlyFields = container.querySelectorAll(
        ".o_field_html.o_readonly_modifier, .o_field_html_readonly"
    );
    readonlyFields.forEach(_processReadonlyField);

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
    }, 200);
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

        // Watch for DOM changes that indicate an HTML field appeared or its
        // content was updated (e.g., Odoo navigation, record save).
        const observer = new MutationObserver((mutations) => {
            let shouldProcess = false;
            for (const mutation of mutations) {
                // ── Case A: Odoo updates odoo-editor-editable content in-place
                //    after a save (OWL patches children rather than replacing
                //    the whole .o_field_html element).  Only trigger when the
                //    editor does not have focus so we don't disrupt live typing.
                if (
                    mutation.type === "childList" &&
                    mutation.target.classList &&
                    mutation.target.classList.contains("odoo-editor-editable") &&
                    !mutation.target.contains(document.activeElement)
                ) {
                    shouldProcess = true;
                    break;
                }

                // ── Case B: Odoo adds or replaces field widget elements
                //    (navigation to a new record, tab switch, etc.)
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

                // ── Case C: The o_readonly_modifier class is added/removed
                //    (field switches between editable and readonly at runtime)
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
