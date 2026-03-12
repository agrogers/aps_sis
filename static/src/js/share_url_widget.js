import { registry } from "@web/core/registry";
import { Component, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ShareUrlField extends Component {
    static template = xml`
        <div class="d-flex align-items-center gap-2 o_share_url_field flex-wrap">
            <span class="font-monospace text-muted small flex-grow-1 text-truncate"
                  style="min-width:0; max-width:480px;"
                  t-att-title="value">
                <t t-esc="value or '—'"/>
            </span>
            <button t-if="value"
                    class="btn btn-sm btn-outline-secondary"
                    t-on-click="copyToClipboard"
                    title="Copy share URL to clipboard">
                <i t-att-class="state.copied ? 'fa fa-check text-success' : 'fa fa-copy'"/>
                <t t-esc="state.copied ? ' Copied!' : ' Copy'"/>
            </button>
            <a t-if="value" t-att-href="value" target="_blank"
               class="btn btn-sm btn-outline-primary"
               title="Open share page in new tab">
                <i class="fa fa-external-link"/>
            </a>
        </div>
    `;

    static props = {
        record: Object,
        name: String,
        readonly: { type: Boolean, optional: true },
        id: { type: String, optional: true },
        className: { type: String, optional: true },
        style: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ copied: false });
        this.notification = useService("notification");
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    async copyToClipboard() {
        const url = this.value;
        if (!url) return;
        try {
            await navigator.clipboard.writeText(url);
            this.state.copied = true;
            setTimeout(() => { this.state.copied = false; }, 2000);
        } catch (error) {
            // eslint-disable-next-line no-console
            console.warn("Clipboard write failed:", error);
            this.notification.add("Failed to copy URL to clipboard", { type: "danger" });
        }
    }
}

registry.category("fields").add("share_url", {
    component: ShareUrlField,
    supportedTypes: ["char"],
    extractProps() {
        return {};
    },
});
