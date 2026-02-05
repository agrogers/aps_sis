/** @odoo-module **/
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { evaluateExpr } from "@web/core/py_js/py";

export class BadgeDecorator extends CharField {
    static template = "aps_sis.BadgeDecorator";

    get formattedValue() {
        const value = this.props.record.data[this.props.name];
        if (!value) return "";
        
        // Simple date check
        const date = new Date(value);
        if (!isNaN(date.getTime())) {
            const format = this.props.date_format 
            const day = date.getDate();
            const day2 = String(date.getDate()).padStart(2, '0');
            const monthShort = date.toLocaleString('en-US', { month: 'short' });
            const monthNum = String(date.getMonth() + 1).padStart(2, '0');
            const yearFull = date.getFullYear();
            const yearShort = String(yearFull).slice(-2);

            // Simple replacement logic for common patterns
            return format
                .replace("DD", day2)
                .replace("D", day)
                .replace("MMM", monthShort)
                .replace("MM", monthNum)
                .replace("YYYY", yearFull)
                .replace("YY", yearShort);            
        }
        return value;
    }

    get activeDecorations() {
            const expression_classes = this.props.expression_classes || {};
            const default_classes = this.props.default_classes || "";
            let classes = "badge " + default_classes; 
            const context = this.props.record.evalContext;

            for (const [className, expression] of Object.entries(expression_classes)) {
                if (!expression || typeof expression !== "string") continue;

                try {
                    if (evaluateExpr(expression || "[]", context)) {
                        classes += ` text-bg-${className}`;
                    }
                } catch (e) {
                    // If days_till_due isn't in the view, this will catch it
                    console.warn(`BadgeDecorator: Evaluation failed for "${expression}"`, e);
                }
            }
            return classes;
    }
}

BadgeDecorator.props = {
    ...CharField.props,
    expression_classes: { type: Object, optional: true },
    default_classes: { type: String, optional: true },
    date_format: { type: String, optional: true },
};

// Create the registry object
export const badgeDecorator = {
    ...charField,
    component: BadgeDecorator,
    // Note: We use the exact signature Odoo's Field component expects
    extractProps(fieldInfo) {
        // 1. Get props from the base CharField safely
        const props = charField.extractProps(fieldInfo);
        
        // 2. Extract our custom option safely from fieldInfo
        // In Odoo 18, fieldInfo contains attrs, which contains options
        const options = fieldInfo.options || {};
        props.expression_classes = options.expression_classes || {};
        props.default_classes = options.default_classes || "";
        props.date_format = options.date_format || "DD-MMM-YY";
        
        return props;
    },
};

registry.category("fields").add("badge_decorator", badgeDecorator);