/** Swap the systray profile picture with the user's chosen avatar (if set). */
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { user } from "@web/core/user";
import { imageUrl } from "@web/core/utils/urls";

function avatarUrl(avatarId) {
    return `/web/image/aps.avatar/${encodeURIComponent(avatarId)}/image/128x128`;
}

patch(UserMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.avatarState = useState({ source: null });
        this.showStudentAvatar = false;
        let isDestroyed = false;

        onWillDestroy(() => {
            isDestroyed = true;
        });

        onWillStart(async () => {
            try {
                const [isStudent, isTeacher] = await Promise.all([
                    user.hasGroup("aps_sis.group_aps_student"),
                    user.hasGroup("aps_sis.group_aps_teacher"),
                ]);
                this.showStudentAvatar = isStudent && !isTeacher;
                if (!this.showStudentAvatar) {
                    return;
                }

                const [rec] = await this.orm.read(
                    "res.users", [user.userId], ["avatar_id", "avatar_image", "write_date"],
                );
                if (rec?.avatar_image) {
                    this.avatarState.source = imageUrl(
                        "res.users",
                        user.userId,
                        "avatar_image",
                        { unique: rec.write_date || String(Date.now()) },
                    );
                } else if (rec?.avatar_id) {
                    this.avatarState.source = avatarUrl(rec.avatar_id[0]);
                }
            } catch (error) {
                if (isDestroyed && error?.message === "Component is destroyed") {
                    return;
                }
                throw error;
            }
        });

        this.env.bus.addEventListener("aps-avatar-changed", (ev) => {
            if (!this.showStudentAvatar) {
                return;
            }

            const detail = ev.detail;
            if (detail && typeof detail === "object") {
                if (detail.imageBinary) {
                    this.avatarState.source = `data:${detail.imageMimeType || "image/png"};base64,${detail.imageBinary}`;
                } else {
                    this.avatarState.source = detail.avatarId
                        ? avatarUrl(detail.avatarId) + `?t=${Date.now()}`
                        : null;
                }
                return;
            }

            this.avatarState.source = typeof detail === "number"
                ? avatarUrl(detail) + `?t=${Date.now()}`
                : null;
        });
    },
});
