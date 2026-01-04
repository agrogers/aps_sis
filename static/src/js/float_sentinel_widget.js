/** @odoo-module **/

import { FloatField } from "@web/views/fields/float/float_field";
import { floatField } from "@web/views/fields/float/float_field";
import { registry } from "@web/core/registry";

const DEFAULT_SENTINEL = -0.01;

export class FloatSentinelField extends FloatField {

    static props = {
        ...FloatField.props,
        sentinel: { type: Number, optional: true },
    };

    get sentinel() {
        return this.props.sentinel ?? DEFAULT_SENTINEL;
    }

    /** Display: blank if sentinel, otherwise clean number */
    get formattedValue() {
        const value = this.props.record.data[this.props.name];

        if (Math.abs(value - this.sentinel) < 0.000001) {
            return "";
        }

        return Number(value).toString();  // Removes .0, keeps real decimals
    }

    // /** Live typing: handle "-" specially for UX */
    // onInput(ev) {
    //     const inputValue = ev.target.value.trim();

    //     if (inputValue === "-") {
    //         ev.target.value = "";  // Show blank while typing "-"
    //         return;  // Don't commit yet — wait for blur/Enter
    //     }

    //     // Let normal float input handling proceed
    //     super.onInput(ev);
    // }

    // /** Final commit on blur, Enter, etc. */
    // commitChanges() {
    //     if (!this.inputRef.el) {
    //         return super.commitChanges();
    //     }

    //     const inputValue = this.inputRef.el.value.trim();

    //     let commitValue;
    //     if (inputValue === "" || inputValue === "-") {
    //         commitValue = this.sentinel;
    //     } else {
    //         const parsed = parseFloat(inputValue.replace(',', '.'));
    //         commitValue = isNaN(parsed) ? this.sentinel : parsed;
    //     }

    //     // Use the official way to update the record → triggers onchange properly
    //     this._setValue(commitValue.toString());
    // }
}

export const floatSentinelField = {
    ...floatField,
    component: FloatSentinelField,

    extractProps(fieldInfo) {
        const props = floatField.extractProps ? floatField.extractProps(fieldInfo) : {};
        return {
            ...props,
            sentinel: fieldInfo.options.sentinel ?? DEFAULT_SENTINEL,
        };
    },
};

registry.category("fields").add("float_sentinel", floatSentinelField);