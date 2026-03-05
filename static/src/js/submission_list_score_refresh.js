import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

patch(ListController.prototype, {
    async onRecordSaved(record, changes) {
        if (super.onRecordSaved) {
            await super.onRecordSaved(record, changes);
        }

        const resModel = this.model?.root?.resModel || this.props?.resModel;
        if (resModel !== "aps.resource.submission") {
            return;
        }

        if (!changes || !Object.prototype.hasOwnProperty.call(changes, "score")) {
            return;
        }

        if (this.__apsScoreRefreshPending) {
            return;
        }
        this.__apsScoreRefreshPending = true;

        setTimeout(async () => {
            try {
                const loadedRecords = (this.model?.root?.records || []).filter(
                    (row) => row && Number.isInteger(row.resId)
                );
                const resIds = [...new Set(loadedRecords.map((row) => row.resId))];

                if (!resIds.length) {
                    return;
                }

                const freshValues = await this.model.orm.read(
                    "aps.resource.submission",
                    resIds,
                    ["score", "result_percent", "write_date"],
                    { context: this.model?.root?.context || this.props?.context }
                );

                const byId = new Map(freshValues.map((vals) => [vals.id, vals]));
                for (const listRecord of loadedRecords) {
                    const serverValues = byId.get(listRecord.resId);
                    if (serverValues) {
                        listRecord._applyValues(serverValues);
                    }
                }

                if (this.model?.notify) {
                    this.model.notify();
                }
            } catch {
                await this.model.root.load({
                    offset: this.model.root.offset,
                    limit: this.model.root.limit,
                });
            } finally {
                this.__apsScoreRefreshPending = false;
            }
        }, 0);
    },
});
