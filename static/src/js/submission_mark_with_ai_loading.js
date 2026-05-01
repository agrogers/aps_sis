import { Component, markup, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { escape } from "@web/core/utils/strings";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";

const POLL_INTERVAL_MS = 1500;

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

function renderMarkdownLikeHtml(text) {
    const normalizedText = (text || "").replace(/(^|\n)Assistant:\s*/g, "$1");
    const escaped = escape(normalizedText);
    let html = escaped
        .replace(/```([\s\S]*?)```/g, '<pre class="mb-2"><code>$1</code></pre>')
        .replace(/^###\s+(.*)$/gm, '<h6 class="mb-2">$1</h6>')
        .replace(/^##\s+(.*)$/gm, '<h5 class="mb-2">$1</h5>')
        .replace(/^#\s+(.*)$/gm, '<h4 class="mb-2">$1</h4>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.*?)__/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/_(.*?)_/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');

    html = html.replace(/\n/g, '<br/>');
    return markup(html);
}

// ─── Resource Test Mark Dialog ────────────────────────────────────────────────

class AIMarkProgressDialog extends Component {
    static template = "aps_sis.AIMarkProgressDialog";
    static components = { Dialog };
    static props = ["recordId", "runId", "close", "title?", "onCompleted?", "statusModel?"];

    setup() {
        this.orm = useService("orm");
        this.thinkingPanelRef = useRef("thinkingPanel");
        this.previewPanelRef = useRef("previewPanel");
        this.state = useState({
            loading: true,
            state: "queued",
            statusMessage: "Starting AI marking...",
            resultMessage: "",
            errorMessage: "",
            thinkingText: "",
            responsePreview: "",
            durationMs: 0,
            promptTokens: 0,
            completionTokens: 0,
            estimatedCost: 0,
            aiModelName: "",
        });
        this._pollTimer = null;
        this._completionHandled = false;

        onWillStart(async () => {
            await this.refreshStatus();
            this.startPolling();
        });

        onPatched(() => {
            const panel = this.thinkingPanelRef.el || this.previewPanelRef.el;
            if (panel) {
                panel.scrollTop = panel.scrollHeight;
            }
        });

        onWillUnmount(() => this.stopPolling());
    }

    get dialogTitle() {
        return this.props.title || "AI Marking Progress";
    }

    get isTerminal() {
        return this.state.state === "completed" || this.state.state === "failed";
    }

    get formattedDuration() {
        const totalMs = this.state.durationMs || 0;
        const seconds = Math.floor(totalMs / 1000);
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return minutes ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
    }

    get renderedThinkingHtml() {
        return renderMarkdownLikeHtml(this.state.thinkingText);
    }

    get renderedResponsePreviewHtml() {
        return renderMarkdownLikeHtml(this.state.responsePreview);
    }

    startPolling() {
        if (this.isTerminal || this._pollTimer) {
            return;
        }
        this._pollTimer = setInterval(() => {
            this.refreshStatus();
        }, POLL_INTERVAL_MS);
    }

    stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    async refreshStatus() {
        const statusModel = this.props.statusModel || "aps.resource.submission";
        const status = await this.orm.call(
            statusModel,
            "action_get_ai_run_status",
            [[this.props.recordId], this.props.runId]
        );

        this.state.loading = false;
        this.state.state = status.state;
        this.state.statusMessage = status.status_message || "";
        this.state.resultMessage = status.result_message || "";
        this.state.errorMessage = status.error_message || "";
        this.state.thinkingText = status.thinking_text || "";
        this.state.responsePreview = status.response_preview || "";
        this.state.durationMs = status.duration_ms || 0;
        this.state.promptTokens = status.prompt_tokens || 0;
        this.state.completionTokens = status.completion_tokens || 0;
        this.state.estimatedCost = status.estimated_cost || 0;
        this.state.aiModelName = status.ai_model_name || "";

        if (status.is_terminal) {
            this.stopPolling();
            if (status.state === "completed" && !this._completionHandled && this.props.onCompleted) {
                this._completionHandled = true;
                await this.props.onCompleted();
            }
        }
    }
}

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
                this.env.services.dialog.add(AIMarkProgressDialog, {
                    recordId: this.model.root.resId,
                    statusModel: this.model.root.resModel,
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