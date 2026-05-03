/**
 * APS SIS — Alpha-Numeric Field Widget
 *
 * A field widget for Char fields that can hold either a formatted number or
 * a configurable set of special codes (e.g. "A" = Absent, "C" = Cheating,
 * "-" = Excluded).
 *
 * When the alpha field name follows the convention "<name>_alpha", the widget
 * automatically keeps the paired numeric field "<name>" in sync. The numeric
 * field name can also be set explicitly via the `numeric_field` option.
 *
 * Options (set via options="{...}" in XML views):
 *   allowed_codes   {Array|string}  Special codes that may be entered.
 *                                   Array or comma-separated string.
 *                                   Default: ["-", "A", "C"]
 *   decimal_places  {number}        Decimal places for number display. Default: 2
 *   use_separator   {boolean}       Show thousands separator. Default: false
 *   numeric_field   {string}        Name of paired numeric field. Auto-derived
 *                                   from "_alpha" suffix when not set.
 *   sentinel        {number}        Value written to the numeric field for
 *                                   empty / special-code entries. Default: -0.01
 *
 * Usage example (XML view):
 *   <field name="score_alpha"
 *          widget="alpha_numeric"
 *          options="{'allowed_codes': ['-','A','C'],
 *                    'decimal_places': 2,
 *                    'use_separator': false}"/>
 */

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onWillUpdateProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { xml } from "@odoo/owl";

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * AlphaNumericField — OWL field widget for Char fields that behave like numeric
 * inputs while accepting configurable special codes (e.g. "A" = Absent).
 *
 * Architecture:
 *  - Renders a plain `<input type="text">` in edit mode and a formatted `<span>`
 *    in readonly mode, matching the look of Odoo's native numeric fields.
 *  - Validates the raw input on blur/Enter: values must be either a parseable
 *    number or one of the `allowed_codes` option values.
 *  - On commit, writes the normalised alpha value to `this.props.name` (the Char
 *    field) and, when a paired numeric field is available, also writes the
 *    corresponding float to that field so server-side computed fields (e.g.
 *    `result_percent`) recompute immediately without requiring a page reload.
 *  - Falls back to displaying the paired numeric field's value for records that
 *    pre-date the alpha field (backward compatibility).
 *
 * Key methods:
 *  - `_displayValue(alphaVal, numVal)` — returns the formatted display string.
 *  - `_validate(raw)`                  — checks input and returns `{ok, error}`.
 *  - `_commit(rawInput)`               — normalises & persists the value.
 *
 * Props (populated by `extractProps`):
 *  @prop {string[]} allowed_codes   - Codes that bypass numeric validation.
 *  @prop {number}   decimal_places  - Decimal places for number display.
 *  @prop {boolean}  use_separator   - Show thousands separator.
 *  @prop {string}   [numeric_field] - Name of the paired Float/Integer field.
 *  @prop {number}   sentinel        - Value written to numeric field for empty/code entries.
 */
export class AlphaNumericField extends Component {
    static template = xml`
        <t t-if="props.readonly">
            <span t-att-class="readonlyClass" t-esc="formattedValue"/>
        </t>
        <t t-else="">
            <div class="o_field_alpha_numeric_wrap">
                <input
                    t-ref="input"
                    type="text"
                    t-att-class="inputClass"
                    t-att-value="state.inputValue"
                    t-att-placeholder="placeholder"
                    t-on-focus="onFocus"
                    t-on-input="onInput"
                    t-on-blur="onBlur"
                    t-on-keydown="onKeyDown"
                />
                <t t-if="state.error">
                    <div class="o_alpha_numeric_error text-danger small" t-esc="state.error"/>
                </t>
            </div>
        </t>
    `;

    static props = {
        ...standardFieldProps,
        allowed_codes: { type: Array, optional: true },
        decimal_places: { type: Number, optional: true },
        use_separator: { type: Boolean, optional: true },
        numeric_field: { type: String, optional: true },
        sentinel: { type: Number, optional: true },
    };

    setup() {
        this.inputRef = useRef("input");
        this.state = useState({
            inputValue: this._displayValue(
                this.props.record.data[this.props.name] || "",
                this.props.numeric_field
                    ? this.props.record.data[this.props.numeric_field]
                    : null,
            ),
            error: null,
            hasFocus: false,
        });

        onWillUpdateProps((next) => {
            // Refresh display when the record data changes from outside (e.g. server
            // recompute) but only when the input is not focused.
            if (!this.state.hasFocus) {
                const newAlpha = next.record.data[next.name] || "";
                const newNum = next.numeric_field
                    ? next.record.data[next.numeric_field]
                    : null;
                this.state.inputValue = this._displayValue(newAlpha, newNum);
            }
        });
    }

    // ── Derived accessors ────────────────────────────────────────────────────

    get allowedCodes() {
        const raw = this.props.allowed_codes || ["-", "A", "C"];
        return raw.map((c) => String(c).toUpperCase());
    }

    get decimalPlaces() {
        const dp = this.props.decimal_places;
        return dp !== undefined && dp !== null ? dp : 2;
    }

    get useSeparator() {
        return this.props.use_separator ?? false;
    }

    get sentinelValue() {
        return this.props.sentinel ?? -0.01;
    }

    /** Raw value stored in the alpha Char field. */
    get _rawAlpha() {
        return this.props.record.data[this.props.name] || "";
    }

    /** Raw value stored in the paired numeric Float/Integer field (or null). */
    get _rawNumeric() {
        if (!this.props.numeric_field) return null;
        return this.props.record.data[this.props.numeric_field] ?? null;
    }

    /** True when the current stored value is one of the allowed special codes. */
    get isSpecialCode() {
        return this._isCode(this._rawAlpha);
    }

    /** CSS classes for the readonly span. */
    get readonlyClass() {
        if (this.isSpecialCode) {
            return "o_alpha_numeric_value o_alpha_code text-muted fst-italic";
        }
        return "o_alpha_numeric_value o_alpha_number";
    }

    /** CSS classes for the edit-mode input element. */
    get inputClass() {
        let cls = "o_input o_alpha_numeric_input";
        if (this.state.error) cls += " border-danger";
        if (this._isCode(this.state.inputValue)) cls += " fst-italic text-muted";
        return cls;
    }

    /** Placeholder text shown when the input is empty. */
    get placeholder() {
        return this.allowedCodes.join(", ");
    }

    /** Formatted value for readonly display. */
    get formattedValue() {
        return this._displayValue(this._rawAlpha, this._rawNumeric);
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    _isCode(val) {
        if (!val) return false;
        return this.allowedCodes.includes(String(val).trim().toUpperCase());
    }

    _parseNum(val) {
        if (val === null || val === undefined) return null;
        const cleaned = String(val).replace(/,/g, "").trim();
        const n = parseFloat(cleaned);
        return !isNaN(n) && isFinite(n) ? n : null;
    }

    _formatNum(n) {
        try {
            return n.toLocaleString(undefined, {
                minimumFractionDigits: this.decimalPlaces,
                maximumFractionDigits: this.decimalPlaces,
                useGrouping: this.useSeparator,
            });
        } catch (_) {
            return String(n);
        }
    }

    /**
     * Compute the display string from the alpha field value with a fallback to
     * the paired numeric field for records that pre-date the alpha field.
     */
    _displayValue(alphaVal, numVal) {
        if (alphaVal && String(alphaVal).trim()) {
            const t = String(alphaVal).trim();
            if (this._isCode(t)) return t.toUpperCase();
            const n = this._parseNum(t);
            if (n !== null) return this._formatNum(n);
            return t;
        }
        // Fall back to the numeric field for backward compatibility.
        if (numVal !== null && numVal !== undefined) {
            const sentinel = this.props.sentinel ?? -0.01;
            if (Math.abs(numVal - sentinel) > 0.000001) {
                return this._formatNum(numVal);
            }
        }
        return "";
    }

    _validate(raw) {
        const val = String(raw || "").trim();
        if (!val) return { ok: true };
        if (this._isCode(val)) return { ok: true };
        if (this._parseNum(val) !== null) return { ok: true };
        return {
            ok: false,
            error: `Enter a number or one of: ${this.allowedCodes.join(", ")}`,
        };
    }

    // ── Event handlers ───────────────────────────────────────────────────────

    onFocus() {
        this.state.hasFocus = true;
        // Show the raw stored alpha value while editing (strip formatting).
        this.state.inputValue = this._rawAlpha;
        this.state.error = null;
    }

    onInput(ev) {
        this.state.inputValue = ev.target.value;
        this.state.error = null;
    }

    async onBlur(ev) {
        this.state.hasFocus = false;
        await this._commit(ev.target.value);
    }

    async onKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            await this._commit(ev.target.value);
        } else if (ev.key === "Escape") {
            this.state.inputValue = this._displayValue(this._rawAlpha, this._rawNumeric);
            this.state.error = null;
        }
    }

    async _commit(rawInput) {
        const trimmed = String(rawInput || "").trim();
        const validation = this._validate(trimmed);
        if (!validation.ok) {
            this.state.error = validation.error;
            return;
        }
        this.state.error = null;

        let normalized = "";
        let numericValue = this.sentinelValue;

        if (trimmed) {
            if (this._isCode(trimmed)) {
                normalized = trimmed.toUpperCase();
                numericValue = this.sentinelValue;
            } else {
                const n = this._parseNum(trimmed);
                if (n !== null) {
                    normalized = String(n);   // store clean number string
                    numericValue = n;
                }
            }
        }

        // Build the record update — always write the alpha field.
        const updates = { [this.props.name]: normalized };

        // Also update the paired numeric field when it is present on the record.
        const numField = this.props.numeric_field;
        if (numField && this.props.record.fields && numField in this.props.record.fields) {
            updates[numField] = numericValue;
        }

        // Reflect the formatted value in the input immediately.
        this.state.inputValue = this._displayValue(normalized, numericValue);

        await this.props.record.update(updates);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Registry descriptor
// ─────────────────────────────────────────────────────────────────────────────

export const alphaNumericField = {
    component: AlphaNumericField,
    supportedTypes: ["char"],
    displayName: "Alpha Numeric",
    supportedOptions: [
        {
            label: "Allowed Codes",
            name: "allowed_codes",
            type: "string",
            help: 'Comma-separated list or JSON array of allowed special codes, e.g. ["-","A","C"]',
        },
        {
            label: "Decimal Places",
            name: "decimal_places",
            type: "number",
        },
        {
            label: "Use Thousands Separator",
            name: "use_separator",
            type: "boolean",
        },
        {
            label: "Numeric Field",
            name: "numeric_field",
            type: "string",
            help: 'Name of the paired numeric field to keep in sync. Auto-derived from the "_alpha" suffix when not set.',
        },
        {
            label: "Sentinel Value",
            name: "sentinel",
            type: "number",
            help: "Value written to the numeric field when the alpha field is empty or holds a special code. Default: -0.01",
        },
    ],

    extractProps({ name, options }) {
        // Derive the paired numeric field name from the "_alpha" suffix convention.
        const stripped = name.replace(/_alpha$/, "");
        let numericField = options.numeric_field || (stripped !== name ? stripped : null);

        // allowed_codes can arrive as a JSON array string or comma-separated.
        let allowedCodes = options.allowed_codes;
        if (typeof allowedCodes === "string") {
            // Try JSON first, then fall back to comma-split.
            try {
                allowedCodes = JSON.parse(allowedCodes);
            } catch (_) {
                allowedCodes = allowedCodes.split(",").map((s) => s.trim()).filter(Boolean);
            }
        }
        allowedCodes = Array.isArray(allowedCodes) ? allowedCodes : ["-", "A", "C"];

        return {
            allowed_codes: allowedCodes,
            decimal_places:
                options.decimal_places !== undefined
                    ? parseInt(options.decimal_places, 10)
                    : 2,
            use_separator: options.use_separator ?? false,
            numeric_field: numericField || undefined,
            sentinel:
                options.sentinel !== undefined
                    ? parseFloat(options.sentinel)
                    : -0.01,
        };
    },
};

registry.category("fields").add("alpha_numeric", alphaNumericField);
