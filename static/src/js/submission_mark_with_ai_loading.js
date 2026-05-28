import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { AiRunProgressDialog } from "@aps_ai/js/ai_run_progress_dialog";


function getMarkWithAIButton() {
    return document.activeElement?.closest?.("button[name='action_start_mark_with_ai']") || null;
}

function restoreButtonState(state) {
    const buttonEl = state?.buttonEl;
    if (!buttonEl?.isConnected) {
        return;
    }
    buttonEl.disabled = state.originalDisabled;
    buttonEl.innerHTML = state.originalHtml;
}

// ─── FormController patch ─────────────────────────────────────────────────────

patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const isMarkWithAI = clickParams?.type === "object" && clickParams?.name === "action_start_mark_with_ai";
        const isTestMark = clickParams?.type === "object" && clickParams?.name === "action_ai_test_mark";

        if (!isMarkWithAI && !isTestMark) {
            return super.beforeExecuteActionButton(...arguments);
        }

        const canProceed = await super.beforeExecuteActionButton(...arguments);
        if (canProceed === false) {
            return false;
        }

        const buttonEl = isTestMark
            ? document.activeElement?.closest?.("button[name='action_ai_test_mark']") || null
            : getMarkWithAIButton();
        const originalHtml = buttonEl?.innerHTML;
        const originalDisabled = buttonEl?.disabled;
        const buttonState = { buttonEl, originalHtml, originalDisabled };

        if (buttonEl) {
            buttonEl.disabled = true;
            buttonEl.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i>Starting AI...';
        }

        try {
            const action = await this.env.services.orm.call(
                this.model.root.resModel,
                clickParams.name,
                [[this.model.root.resId]],
                {
                    context: {
                        ...(this.props?.context || {}),
                        active_model: this.model.root.resModel,
                        active_id: this.model.root.resId,
                        active_ids: Array.isArray(this.model.root.resIds)
                            ? this.model.root.resIds
                            : [this.model.root.resId],
                    },
                }
            );

            const runId = action?.params?.run_id;
            if (action) {
                await this.env.services.action.doAction(action);
            }
            if (runId) {
                this.env.services.dialog.add(AiRunProgressDialog, {
                    runModel: 'aps.ai.run',
                    runId,
                    title: action?.params?.title || "AI Marking Progress",
                    onCompleted: async () => {
                        if (this.model?.root?.resId) {
                            await this.model.load({
                                resId: this.model.root.resId,
                                resIds: this.model.root.resIds,
                            });
                        }
                    },
                });
            }
            return false;
        } catch (error) {
            restoreButtonState(buttonState);
            throw error;
        } finally {
            restoreButtonState(buttonState);
        }
    },
});