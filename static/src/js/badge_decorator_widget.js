/** @odoo-module **/
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { evaluateExpr } from "@web/core/py_js/py";
import { Component } from "@odoo/owl";

const DEFAULT_DUE_DATE_CLASSES = {
    "red-pulsing": "days_till_due < 0",
    red1: "days_till_due == 0",
    red2: "days_till_due == 1",
    red4: "days_till_due == 2",
    red6: "days_till_due == 3",
    grey: "days_till_due > 3",
};

function formatBadgeDate(value, format = "DD-MMM-YY") {
    if (!value) {
        return "";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }

    const day = date.getDate();
    const day2 = String(day).padStart(2, "0");
    const monthShort = date.toLocaleString("en-US", { month: "short" });
    const monthNum = String(date.getMonth() + 1).padStart(2, "0");
    const yearFull = date.getFullYear();
    const yearShort = String(yearFull).slice(-2);

    return format
        .replace("DD", day2)
        .replace("D", day)
        .replace("MMM", monthShort)
        .replace("MM", monthNum)
        .replace("YYYY", yearFull)
        .replace("YY", yearShort);
}

function getBadgeClasses(defaultClasses, expressionClasses, context) {
    let classes = `badge ${defaultClasses || ""}`;
    for (const [className, expression] of Object.entries(expressionClasses || {})) {
        if (!expression || typeof expression !== "string") {
            continue;
        }

        try {
            if (evaluateExpr(expression, context)) {
                classes += ` text-bg-${className}`;
            }
        } catch (error) {
            console.warn(`BadgeDecorator: Evaluation failed for "${expression}"`, error);
        }
    }
    return classes;
}

export class BadgeDecoratorDisplay extends Component {
    static template = "aps_sis.BadgeDecorator";
    static props = {
        value: { type: [String, Boolean], optional: true },
        daysTillDue: { type: Number, optional: true },
        defaultClasses: { type: String, optional: true },
        expressionClasses: { type: Object, optional: true },
        dateFormat: { type: String, optional: true },
    };

    get formattedValue() {
        return formatBadgeDate(this.props.value, this.props.dateFormat || "D-MMM-YY");
    }

    get activeDecorations() {
        return getBadgeClasses(
            this.props.defaultClasses || "rounded-pill",
            this.props.expressionClasses || DEFAULT_DUE_DATE_CLASSES,
            { days_till_due: this.props.daysTillDue }
        );
    }
}

export class BadgeDecorator extends CharField {
    static template = "aps_sis.BadgeDecorator";

    get formattedValue() {
        return formatBadgeDate(
            this.props.record.data[this.props.name],
            this.props.date_format
        );
    }

    get activeDecorations() {
        return getBadgeClasses(
            this.props.default_classes,
            this.props.expression_classes,
            this.props.record.evalContext
        );
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