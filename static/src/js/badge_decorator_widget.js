/** @odoo-module **/
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { evaluateExpr } from "@web/core/py_js/py_utils";

export class BadgeDecorator extends CharField {
    static template = "aps_sis.BadgeDecorator";

    get activeDecorations() {
        const css_classes = this.props.css_classes || {};
        let classes = "badge"; // Start with base badge class

        // Odoo 18 evalContext contains the field values of the current row
        const context = this.props.record.evalContext;

        for (const [className, expression] of Object.entries(css_classes)) {
            try {
                if (evaluateExpr(expression, context)) {
                    // Use the text-bg- prefix to get Odoo's high-contrast badge styling
                    classes += ` text-bg-${className}`;
                }
            } catch (e) {
                console.error("BadgeDecorator: Expression error", e);
            }
        }
        return classes;
    }
}

BadgeDecorator.props = {
    ...CharField.props,
    css_classes: { type: Object, optional: true },
};

BadgeDecorator.extractProps = ({ attrs }) => {
    return {
        ...charField.extractProps({ attrs }),
        css_classes: attrs.options.css_classes || {},
    };
};

registry.category("fields").add("badge_decorator", {
    ...charField,
    component: BadgeDecorator,
});