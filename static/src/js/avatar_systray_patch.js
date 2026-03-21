/** Swap the systray profile picture with the user's chosen avatar (if set). */
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";
import { user } from "@web/core/user";

function avatarUrl(avatarId) {
    return `/web/image/aps.avatar/${encodeURIComponent(avatarId)}/image/128x128`;
}

patch(UserMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.avatarState = useState({ source: null });

        onWillStart(async () => {
            const [rec] = await this.orm.read(
                "res.users", [user.userId], ["avatar_id"],
            );
            if (rec && rec.avatar_id) {
                this.avatarState.source = avatarUrl(rec.avatar_id[0]);
            }
        });

        this.env.bus.addEventListener("aps-avatar-changed", (ev) => {
            const avatarId = ev.detail;
            this.avatarState.source = avatarId
                ? avatarUrl(avatarId) + `?t=${Date.now()}`
                : null;
        });
    },
});
