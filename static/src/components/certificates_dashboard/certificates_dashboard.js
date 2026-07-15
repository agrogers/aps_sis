import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class CertificatesDashboard extends Component {
    static template = "aps_sis.CertificatesDashboard";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({ counts: {} });

        onWillStart(async () => {
            await this._loadCounts();
        });
    }

    async _loadCounts() {
        const models = [
            "aps.certificate",
            "aps.certificate.template",
            "aps.award.category",
            "aps.award.sub.category",
            "aps.award.vote.round",
            "aps.award.vote",
        ];
        const results = await Promise.allSettled(
            models.map(async (model) => {
                const count = await this.orm.searchCount(model, []);
                return { model, count };
            })
        );
        const counts = {};
        for (const r of results) {
            if (r.status === "fulfilled") {
                counts[r.value.model] = r.value.count;
            }
        }
        Object.assign(this.state.counts, counts);
    }

    count(model) {
        const v = this.state.counts[model];
        return v !== undefined ? v : "…";
    }

    open(xmlId) {
        this.actionService.doAction(xmlId);
    }
}

registry.category("actions").add("certificates_dashboard", CertificatesDashboard);
