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
 *     A surgical approach is used to keep Odoo's OWL component DOM references
 *     intact.  The odoo-editor-editable element is NEVER replaced wholesale:
 *
 *       — Each formula text node is replaced with a
 *         <span data-aps-formula-id data-aps-formula-raw> containing KaTeX
 *         HTML.  data-aps-formula-raw holds the original LaTeX string in the
 *         DOM attribute (in memory only — never written to the database).
 *
 *       — The structural DOM above each formula span (paragraphs, headings,
 *         odoo-editor-editable itself) is completely untouched, so OWL's
 *         Wysiwyg component keeps all its element references valid.
 *
 *       — An "Edit" button (floats top-right, zero layout space) allows the
 *         user to restore each span back to its raw LaTeX text node so they
 *         can edit normally in Odoo's HTML editor.  "View" re-runs the
 *         surgical injection on the current editor content.
 *
 *     No save-protection listeners are needed.  Odoo's OdooEditor maintains
 *     its own internal model updated only by editor event handlers; our
 *     surgical DOM changes are invisible to the save path.  After a save
 *     Odoo patches the DOM from the server response and the MutationObserver
 *     fires, causing formulas to be re-rendered automatically.
 */

import { registry } from "@web/core/registry";

// ── KaTeX configuration ──────────────────────────────────────────────────────

// Used by renderMathInElement for readonly fields.
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
//   "view"     — formulas rendered (editable field, toggle shown)
//   "edit"     — raw LaTeX restored for editing (user clicked Edit)
//   "readonly" — formulas rendered (readonly field, no toggle)
const PROCESSED_ATTR = "data-aps-math";

// Must exceed the MutationObserver debounce (200 ms) so we are certain the
// observer has already processed (and skipped) our own mutations before we
// clear the in-progress guard.
const RENDERING_CLEANUP_DELAY_MS = 500;

// ── Formula detection and matching ───────────────────────────────────────────

/** Quick test: does this text contain any LaTeX delimiter? */
function _containsLatex(text) {
    return /\$|\\\(|\\\[/.test(text);
}

/**
 * Matches delimited LaTeX formula strings in a plain-text string.
 * $$ must come before $ to prevent partial match on display math.
 */
const FORMULA_RE = /\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)/g;

// ── State ────────────────────────────────────────────────────────────────────

/**
 * Set of odoo-editor-editable elements currently being modified by us.
 * The MutationObserver skips these to prevent re-trigger loops.
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

// ── Surgical formula helpers ──────────────────────────────────────────────────

/**
 * Render a single delimited formula string (e.g. "$E=mc^2$") to an HTML
 * string using katex.renderToString.  Returns null on unexpected JS error
 * (KaTeX errors are rendered inline by KaTeX itself when throwOnError is false).
 */
function _renderOneFormula(raw) {
    let inner, isDisplay;
    if (raw.startsWith("$$")) {
        inner = raw.slice(2, -2);
        isDisplay = true;
    } else if (raw.startsWith("$")) {
        inner = raw.slice(1, -1);
        isDisplay = false;
    } else if (raw.startsWith("\\[")) {
        inner = raw.slice(2, -2);
        isDisplay = true;
    } else { // \(...\)
        inner = raw.slice(2, -2);
        isDisplay = false;
    }
    try {
        return window.katex.renderToString(inner.trim(), {
            displayMode: isDisplay,
            throwOnError: false,
        });
    } catch (e) {
        console.debug("[APS Math] KaTeX renderToString error:", e);
        return null;
    }
}

/**
 * Walk *editorEl*'s text nodes and replace each LaTeX formula with a
 *   <span data-aps-formula-id="N" data-aps-formula-raw="…">…KaTeX HTML…</span>
 *
 * The raw LaTeX string is stored in data-aps-formula-raw so it can be
 * restored later.  This is kept in the DOM attribute (in memory only) —
 * it is never written to the database.
 *
 * Only text nodes are touched; the structural element tree (including the
 * odoo-editor-editable element itself) is never replaced, so OWL keeps all
 * its element references valid.
 *
 * Returns true if at least one formula was rendered.
 */
function _injectRenderedFormulas(editorEl) {
    // Collect text nodes first — the TreeWalker is live; modifying the DOM
    // while iterating can cause nodes to be skipped.
    const textNodes = [];
    const walker = document.createTreeWalker(editorEl, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        // Skip text nodes already inside one of our formula spans.
        if (node.parentElement && node.parentElement.closest("[data-aps-formula-id]")) {
            continue;
        }
        textNodes.push(node);
    }

    let totalRendered = 0;
    for (const textNode of textNodes) {
        const text = textNode.nodeValue;

        const frag = document.createDocumentFragment();
        let last = 0;
        let nodeRendered = 0;
        let m;

        FORMULA_RE.lastIndex = 0;
        while ((m = FORMULA_RE.exec(text)) !== null) {
            const raw = m[0];
            const html = _renderOneFormula(raw);
            if (html === null) continue;

            // Text before this formula.
            if (m.index > last) {
                frag.appendChild(document.createTextNode(text.slice(last, m.index)));
            }

            // Formula span — raw LaTeX stored in data attribute (never in DB).
            const span = document.createElement("span");
            span.dataset.apsFormulaId = String(++totalRendered);
            span.dataset.apsFormulaRaw = raw;
            span.innerHTML = html;
            frag.appendChild(span);

            last = m.index + raw.length;
            nodeRendered++;
        }

        if (nodeRendered === 0) continue;

        // Remaining text after the last formula.
        if (last < text.length) {
            frag.appendChild(document.createTextNode(text.slice(last)));
        }

        textNode.parentNode.replaceChild(frag, textNode);
    }

    return totalRendered > 0;
}

/**
 * Find all formula spans injected by _injectRenderedFormulas and replace each
 * one with a text node containing the original raw LaTeX string.
 * This reverses the injection for Edit mode.
 */
function _restoreRawFormulas(editorEl) {
    editorEl.querySelectorAll("[data-aps-formula-id]").forEach((span) => {
        const raw = span.dataset.apsFormulaRaw;
        if (raw && span.parentNode) {
            span.parentNode.replaceChild(document.createTextNode(raw), span);
        }
    });
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

// ── Editable-field surgical rendering ────────────────────────────────────────

/**
 * Surgically render LaTeX formulas inside an editable HTML field.
 *
 * Only individual formula text nodes are replaced — the odoo-editor-editable
 * element and all other structural elements are never modified, so OWL's
 * Wysiwyg component keeps all its DOM references intact.
 *
 * Flow:
 *   1. If previously processed, restore raw formula text nodes first so we
 *      evaluate the current LaTeX source, not stale KaTeX HTML.
 *   2. Walk text nodes; replace each LaTeX formula with a rendered span.
 *   3. Inject an Edit/View toggle button that swaps between raw and rendered.
 */
function _processEditableField(fieldEl, editorEl) {
    const mode = fieldEl.getAttribute(PROCESSED_ATTR);

    // Don't disrupt the user while they are actively editing in edit mode.
    if (mode === "edit") {
        const hasFocus =
            editorEl === document.activeElement ||
            editorEl.contains(document.activeElement);
        if (hasFocus) return;
    }

    // Remove any previously injected toggle button (may be inside the wrapper).
    fieldEl.querySelector(".aps-math-edit-toggle")?.remove();

    // Restore raw formula text nodes if we previously injected rendered spans,
    // so the content we're about to evaluate is the unmodified LaTeX source.
    if (mode === "view" || mode === "edit") {
        _renderingInProgress.add(editorEl);
        _restoreRawFormulas(editorEl);
        setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);
    }
    // Ensure the editor is editable before we re-evaluate (in case it was left
    // in contenteditable=false from a previous view-mode rendering).
    editorEl.setAttribute("contenteditable", "true");
    fieldEl.removeAttribute(PROCESSED_ATTR);

    if (!_containsLatex(editorEl.textContent)) return;

    // Surgically inject rendered spans, guarding against re-trigger loops.
    _renderingInProgress.add(editorEl);
    const rendered = _injectRenderedFormulas(editorEl);
    setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);

    if (!rendered) return;

    fieldEl.setAttribute(PROCESSED_ATTR, "view");

    // Lock the editor while formulas are displayed so the user cannot
    // accidentally edit KaTeX-rendered HTML.
    // CSS (data-aps-math="view" selector) applies pointer-events:none to the
    // entire field wrapper — this prevents any pointer event from reaching the
    // odoo-editor-editable or any ancestor, so document.selectionchange is
    // never fired and Odoo's Wysiwyg toolbar (o-we-toolbar) never appears.
    editorEl.setAttribute("contenteditable", "false");

    // ── Toggle button (inside shared zero-height sticky wrapper) ─────────────
    // The .aps-float-buttons wrapper uses height:0; overflow:visible so it
    // takes no space in the document flow — the button overlays the content
    // without pushing text aside.  Created here if toc_position_toggle.js
    // hasn't run yet; the TOC service will reuse the same wrapper.
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "aps-math-edit-toggle btn btn-sm btn-outline-secondary";
    btn.title = "This HTML field contains formulas";
    btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';

    btn.addEventListener("click", () => {
        const isViewing = fieldEl.getAttribute(PROCESSED_ATTR) === "view";
        if (isViewing) {
            // Switch to edit mode: restore raw LaTeX text nodes from data attrs.
            _renderingInProgress.add(editorEl);
            _restoreRawFormulas(editorEl);
            setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);
            // Unlock the editor so the user can type LaTeX.
            editorEl.setAttribute("contenteditable", "true");
            btn.innerHTML = '<i class="fa fa-eye" aria-hidden="true"></i> View';
            fieldEl.setAttribute(PROCESSED_ATTR, "edit");
            editorEl.focus();
        } else {
            // Switch to view mode: re-inject rendered formulas on current content.
            _renderingInProgress.add(editorEl);
            _injectRenderedFormulas(editorEl);
            setTimeout(() => _renderingInProgress.delete(editorEl), RENDERING_CLEANUP_DELAY_MS);
            // Lock the editor again.
            editorEl.setAttribute("contenteditable", "false");
            btn.innerHTML = '<i class="fa fa-pencil" aria-hidden="true"></i> Edit';
            fieldEl.setAttribute(PROCESSED_ATTR, "view");
        }
    });

    // Put the button in the shared wrapper (created by toc_position_toggle.js
    // if that service ran first, otherwise create it now).
    // Prepend the button inside the wrapper so it appears to the left of any
    // previously-added buttons (flex-direction:row-reverse reverses visual order).
    let btnsWrapper = fieldEl.querySelector(":scope > .aps-float-buttons");
    if (!btnsWrapper) {
        btnsWrapper = document.createElement("div");
        btnsWrapper.className = "aps-float-buttons";
        fieldEl.prepend(btnsWrapper);
    }
    btnsWrapper.prepend(btn);
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

// ── Toolbar-suppression selectionchange guard ─────────────────────────────────

/**
 * Capture-phase selectionchange handler that prevents Odoo's Wysiwyg toolbar
 * (o-we-toolbar) from appearing while a formula-rendered field is in view mode.
 *
 * Registered once on the document during service start (before any form view
 * or Wysiwyg component mounts) so it always runs first.  If the new selection
 * lies inside a [data-aps-math="view"] field, removeAllRanges() collapses it
 * before Odoo's bubble-phase handler reads it → toolbar never triggers.
 *
 * Re-entrance is safe: removeAllRanges() fires another selectionchange, but
 * that new event has rangeCount === 0 and returns immediately.
 */
function _onSelectionChange() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    const node = range.commonAncestorContainer;
    const el = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    if (el && el.closest(`[${PROCESSED_ATTR}="view"]`)) {
        sel.removeAllRanges();
    }
}

// ── Odoo service registration ────────────────────────────────────────────────

registry.category("services").add("aps_math_renderer", {
    start() {
        // ── Prevent Odoo's Wysiwyg toolbar from appearing in formula-rendered fields ──
        //
        // The toolbar (o-we-toolbar) is triggered by document.selectionchange, which
        // the Wysiwyg OWL component fires programmatically during its own initialisation
        // (e.g. focusing the editor to place a caret).  This event:
        //   • fires directly on document — stopPropagation() has no effect
        //   • is fired by the browser's selection engine — pointer-events:none has no effect
        //
        // _onSelectionChange is intentionally permanent for this service's lifetime.
        // Odoo v18 services have no stop() lifecycle, and the MutationObserver
        // below is similarly never disconnected.
        document.addEventListener("selectionchange", _onSelectionChange, true);

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
