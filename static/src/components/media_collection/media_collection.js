import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

/**
 * APEX My Collection — student-facing collection browser.
 *
 * Groups all media items by their collection.  Items the student
 * already owns are shown in full colour with an "Owned" badge.
 * Items they don't yet own are shown greyed out with a "Buy for X pts"
 * overlay; clicking the overlay calls the same purchase action as the Shop.
 */
export class ApsMyCollection extends Component {
    static template = "aps_sis.ApsMyCollection";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            groups: [],           // [{collection, items: [{...item, owned}]}]
            pointsBalance: 0,
            loading: true,
            buying: false,
            uncollected: [],      // items with no collection
        });

        onWillStart(async () => {
            await this._loadData();
        });
    }

    async _loadData() {
        this.state.loading = true;

        const [items, collections, userMedia, userData] = await Promise.all([
            this.orm.searchRead(
                "aps.media",
                [],
                ["id", "name", "image", "type_id", "collection_id", "cost", "stock_available",
                 "date_available", "date_unavailable"],
                { order: "collection_id, name" }
            ),
            this.orm.searchRead("aps.media.collection", [], ["id", "name"], { order: "name" }),
            this.orm.searchRead(
                "aps.user.media",
                [["partner_id", "=", user.partnerId], ["status", "in", ["purchased", "for_sale"]]],
                ["media_id"]
            ),
            this.orm.read("res.users", [user.userId], ["points_balance"]),
        ]);

        const ownedIds = new Set(userMedia.map((r) => r.media_id[0]));
        this.state.pointsBalance = userData[0]?.points_balance ?? 0;

        const today = new Date().toISOString().split("T")[0];

        // Annotate items
        const annotated = items.map((item) => ({
            ...item,
            owned: ownedIds.has(item.id),
            available: this._isAvailable(item, today),
        }));

        // Group by collection
        const collectionMap = Object.fromEntries(collections.map((c) => [c.id, c.name]));
        const grouped = {};
        const uncollected = [];

        for (const item of annotated) {
            if (!item.collection_id) {
                uncollected.push(item);
                continue;
            }
            const cid = item.collection_id[0];
            if (!grouped[cid]) {
                grouped[cid] = { id: cid, name: collectionMap[cid] || item.collection_id[1], items: [] };
            }
            grouped[cid].items.push(item);
        }

        this.state.groups = Object.values(grouped).sort((a, b) => a.name.localeCompare(b.name)).map((g) => ({
            ...g,
            ownedCount: g.items.filter((i) => i.owned).length,
        }));
        this.state.uncollected = uncollected;
        this.state.loading = false;
    }

    _isAvailable(item, today) {
        // Compare using Date objects to avoid locale-sensitive string comparisons
        const todayDate = new Date(today);
        if (item.date_available) {
            const avFrom = new Date(item.date_available);
            if (avFrom > todayDate) return false;
        }
        if (item.date_unavailable) {
            const avUntil = new Date(item.date_unavailable);
            if (avUntil < todayDate) return false;
        }
        return true;
    }

    imageUrl(id) {
        return `/web/image/aps.media/${encodeURIComponent(id)}/image/256x256`;
    }

    canAfford(item) {
        return this.state.pointsBalance >= item.cost;
    }

    async buy(item) {
        if (this.state.buying || item.owned || !item.available || item.stock_available <= 0) return;
        if (!this.canAfford(item)) {
            this.notification.add(
                `You need ${item.cost - this.state.pointsBalance} more points to buy "${item.name}".`,
                { type: "warning" }
            );
            return;
        }
        this.state.buying = true;
        try {
            await this.orm.call("aps.media", "action_buy", [item.id]);
            this.notification.add(`"${item.name}" added to your collection!`, { type: "success" });
            await this._loadData();
        } catch (e) {
            this.notification.add(e.message || "Purchase failed.", { type: "danger" });
        } finally {
            this.state.buying = false;
        }
    }
}

registry.category("actions").add("aps_my_collection", ApsMyCollection);
