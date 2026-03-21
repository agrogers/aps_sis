/** Swap the systray profile picture with the user's chosen avatar (if set). */
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";

patch(UserMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        onWillStart(async () => {
            const [rec] = await this.orm.read(
                "res.users", [user.userId], ["avatar_id"],
            );
            if (rec && rec.avatar_id) {
                const avatarId = rec.avatar_id[0];
                this.source = `/web/image/aps.avatar/${encodeURIComponent(avatarId)}/image/128x128`;
            }
        });
    },
});
