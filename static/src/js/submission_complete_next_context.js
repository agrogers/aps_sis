import { patch } from "@web/core/utils/patch";
import { evaluateExpr } from "@web/core/py_js/py";
import { FormController } from "@web/views/form/form_controller";

function parseClickContext(controller, clickParams) {
    if (!clickParams?.context) {
        return {};
    }
    if (typeof clickParams.context === "object") {
        return clickParams.context;
    }
    if (typeof clickParams.context === "string") {
        try {
            return evaluateExpr(clickParams.context, controller.model?.root?.evalContext || {});
        } catch {
            return {};
        }
    }
    return {};
}

function getDirective(opts, key) {
    return Object.prototype.hasOwnProperty.call(opts, key) ? opts[key] : undefined;
}

function toBool(value, fallback = false) {
    return value === undefined ? fallback : Boolean(value);
}

patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const parsedClickContext = parseClickContext(this, clickParams);
        const genericOpts = {
            ...parsedClickContext,
            ...(clickParams?.buttonContext || {}),
        };
        const isGenericEnabled = Boolean(
            genericOpts.generic_form_action ||
                genericOpts.move_to_next_record ||
                genericOpts.open_next_record ||
                genericOpts.preserve_form_res_ids ||
                genericOpts.keep_form_res_ids
        );
        const shouldHandle = isGenericEnabled && clickParams?.type === "object";

        if (shouldHandle) {
            const canProceed = await super.beforeExecuteActionButton(...arguments);
            if (canProceed === false) {
                return false;
            }

            const currentId = this.model?.root?.resId;
            const resIds = Array.isArray(this.model?.root?.resIds) ? [...this.model.root.resIds] : [];
            const context = {
                ...(this.props?.context || {}),
                ...genericOpts,
                active_model: this.model.root.resModel,
                active_id: currentId,
                active_ids: resIds,
            };

            const includeActiveDomain =
                genericOpts.pass_active_domain !== undefined
                    ? Boolean(genericOpts.pass_active_domain)
                    : true;
            if (includeActiveDomain && this.props?.domain) {
                context.active_domain = this.props.domain;
            }

            const action = await this.orm.call(
                this.model.root.resModel,
                clickParams.name,
                [[currentId]],
                { context }
            );

            const runtimeOpts = { ...genericOpts };
            if (action && typeof action === "object") {
                const actionCtx = action.context && typeof action.context === "object" ? action.context : {};
                const directiveKeys = [
                    "move_to_next_record",
                    "open_next_record",
                    "preserve_form_res_ids",
                    "keep_form_res_ids",
                    "success_toast_message",
                    "toast_message",
                    "success_toast_title",
                    "toast_title",
                    "success_toast_type",
                    "toast_type",
                ];
                for (const key of directiveKeys) {
                    if (Object.prototype.hasOwnProperty.call(action, key)) {
                        runtimeOpts[key] = action[key];
                    } else if (Object.prototype.hasOwnProperty.call(actionCtx, key)) {
                        runtimeOpts[key] = actionCtx[key];
                    }
                }
            }

            if (action?.type === "ir.actions.act_window") {
                const wantsNext = toBool(
                    getDirective(runtimeOpts, "move_to_next_record") ??
                        getDirective(runtimeOpts, "open_next_record"),
                    true
                );
                let targetResId = action.res_id;
                if (wantsNext && !targetResId && Array.isArray(resIds) && resIds.length) {
                    const currentIndex = resIds.indexOf(currentId);
                    if (currentIndex > -1 && currentIndex + 1 < resIds.length) {
                        targetResId = resIds[currentIndex + 1];
                    }
                }
                const actionToOpen = targetResId ? { ...action, res_id: targetResId } : action;
                const nextResIds = resIds.length ? resIds : targetResId ? [targetResId] : [];
                const preserveResIds =
                    runtimeOpts.preserve_form_res_ids !== undefined
                        ? Boolean(runtimeOpts.preserve_form_res_ids)
                        : runtimeOpts.keep_form_res_ids !== undefined
                          ? Boolean(runtimeOpts.keep_form_res_ids)
                          : true;
                const successMessage =
                    runtimeOpts.success_toast_message || runtimeOpts.toast_message || false;

                let actionToRun = actionToOpen;
                if (successMessage) {
                    actionToRun = {
                        type: "ir.actions.client",
                        tag: "display_notification",
                        params: {
                            title: runtimeOpts.success_toast_title || runtimeOpts.toast_title || "Done",
                            message: successMessage,
                            type: runtimeOpts.success_toast_type || runtimeOpts.toast_type || "success",
                            next: actionToOpen,
                        },
                    };
                }

                const doActionOptions = preserveResIds && targetResId
                    ? {
                          props: {
                              resId: targetResId,
                              resIds: nextResIds,
                          },
                      }
                    : {};
                await this.env.services.action.doAction(actionToRun, doActionOptions);
            } else if (action) {
                await this.env.services.action.doAction(action);
            }

            // Cancel default button pipeline because this button is handled above.
            return false;
        }

        return super.beforeExecuteActionButton(...arguments);
    },
});
