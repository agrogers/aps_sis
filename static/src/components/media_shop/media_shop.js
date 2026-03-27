import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

/**
 * APEX Media Shop — student-facing marketplace.
 *
 * Shows all purchasable media items in a responsive card grid.
 * Students can filter by collection and type, search by name,
 * and buy items with a single click (deducts points via server action).
 */
export class ApsMediaShop extends Component {
    static template = "aps_sis.ApsMediaShop";
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
            items: [],
            filtered: [],
            collections: [],
            types: [],
            ownedIds: new Set(),
            activeCollection: false,
            activeType: false,
            query: "",
            pointsBalance: 0,
            loading: true,
            buying: false,
        });

        onWillStart(async () => {
            await this._loadData();
        });
    }

    async _loadData() {
        this.state.loading = true;

        const today = new Date().toISOString().split("T")[0];

        const [items, collections, types, userMedia, userData] = await Promise.all([
            this.orm.searchRead(
                "aps.media",
                [
                    ["stock_available", ">", 0],
                    ["date_available", "<=", today],
                    "|",
                    ["date_unavailable", "=", false],
                    ["date_unavailable", ">=", today],
                ],
                ["id", "name", "image", "type_id", "collection_id", "category_ids",
                 "cost", "stock_available"],
                { order: "name" }
            ),
            this.orm.searchRead("aps.media.collection", [], ["id", "name"], { order: "name" }),
            this.orm.searchRead("aps.media.type", [], ["id", "name"], { order: "name" }),
            this.orm.searchRead(
                "aps.user.media",
                [["partner_id", "=", user.partnerId], ["status", "in", ["purchased", "for_sale"]]],
                ["media_id"]
            ),
            this.orm.read("res.users", [user.userId], ["points_balance"]),
        ]);

        this.state.items = items;
        this.state.collections = collections;
        this.state.types = types;
        this.state.ownedIds = new Set(userMedia.map((r) => r.media_id[0]));
        this.state.pointsBalance = userData[0]?.points_balance ?? 0;
        this.state.loading = false;

        this._applyFilters();
    }

    _applyFilters() {
        let list = this.state.items;
        const col = this.state.activeCollection;
        const typ = this.state.activeType;
        const q = this.state.query.toLowerCase().trim();

        if (col) {
            list = list.filter((i) => i.collection_id && i.collection_id[0] === col);
        }
        if (typ) {
            list = list.filter((i) => i.type_id && i.type_id[0] === typ);
        }
        if (q) {
            list = list.filter((i) => i.name.toLowerCase().includes(q));
        }
        this.state.filtered = list;
    }

    onSearch(ev) {
        this.state.query = ev.target.value;
        this._applyFilters();
    }

    filterCollection(id) {
        this.state.activeCollection = this.state.activeCollection === id ? false : id;
        this._applyFilters();
    }

    filterType(id) {
        this.state.activeType = this.state.activeType === id ? false : id;
        this._applyFilters();
    }

    clearFilters() {
        this.state.activeCollection = false;
        this.state.activeType = false;
        this.state.query = "";
        this._applyFilters();
    }

    imageUrl(id) {
        return `/web/image/aps.media/${encodeURIComponent(id)}/image/256x256`;
    }

    isOwned(item) {
        return this.state.ownedIds.has(item.id);
    }

    canAfford(item) {
        return this.state.pointsBalance >= item.cost;
    }

    getPointsDeficit(item) {
        return item.cost - this.state.pointsBalance;
    }

    async buy(item) {
        if (this.state.buying) return;
        this.state.buying = true;
        try {
            await this.orm.call("aps.media", "action_buy", [item.id]);
            this.notification.add(`"${item.name}" added to your collection!`, {
                type: "success",
            });
            await this._loadData();
        } catch (e) {
            this.notification.add(e.message || "Purchase failed.", { type: "danger" });
        } finally {
            this.state.buying = false;
        }
    }
}

registry.category("actions").add("aps_media_shop", ApsMediaShop);
