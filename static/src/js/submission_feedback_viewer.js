import { Component, markup, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { escape } from "@web/core/utils/strings";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class SubmissionFeedbackViewer extends Component {
    static template = "aps_sis.SubmissionFeedbackViewer";
    static props = {
        ...standardFieldProps,
        answerField: { type: String, optional: true },
    };

    setup() {
        this.state = useState({
            activeFeedbackId: undefined,
        });
    }

    get isTargeted() {
        return !!this.props.record.data.ai_targeted_feedback;
    }

    get answerChunks() {
        const chunks = this.props.record.data.ai_answer_chunks;
        return Array.isArray(chunks) ? chunks : [];
    }

    get answerChunkedHtml() {
        return this.props.record.data.ai_answer_chunked_html || "";
    }

    get feedbackItems() {
        const items = this.props.record.data.ai_feedback_items;
        return Array.isArray(items) ? items : [];
    }

    get chunkOrderById() {
        const orderMap = {};
        this.answerChunks.forEach((chunk, index) => {
            if (chunk?.id) {
                orderMap[chunk.id] = index;
            }
        });
        return orderMap;
    }

    get feedbackLinksById() {
        const links = this.props.record.data.ai_feedback_links;
        const map = {};
        for (const link of Array.isArray(links) ? links : []) {
            if (!link?.feedback_id) {
                continue;
            }
            map[link.feedback_id] = Array.isArray(link.chunk_ids) ? link.chunk_ids : [];
        }
        return map;
    }

    get currentFeedbackId() {
        if (this.state.activeFeedbackId !== undefined) {
            return this.state.activeFeedbackId;
        }
        const firstLinked = this.orderedFeedbackItems.find((item) => (this.feedbackLinksById[item.id] || []).length);
        return firstLinked?.id || this.orderedFeedbackItems[0]?.id || null;
    }

    get activeChunkIds() {
        const feedbackId = this.currentFeedbackId;
        return feedbackId ? (this.feedbackLinksById[feedbackId] || []) : [];
    }

    get activeFeedbackItem() {
        const feedbackId = this.currentFeedbackId;
        return this.linkedFeedbackItems.find((item) => item.id === feedbackId) || null;
    }

    get orderedFeedbackItems() {
        return this.feedbackItems
            .map((item, index) => ({ item, index }))
            .sort((left, right) => {
                const leftOrder = this._getFeedbackSortKey(left.item);
                const rightOrder = this._getFeedbackSortKey(right.item);
                if (leftOrder !== rightOrder) {
                    return leftOrder - rightOrder;
                }
                return left.index - right.index;
            })
            .map(({ item }) => item);
    }

    get linkedFeedbackItems() {
        return this.orderedFeedbackItems.filter((item) => (this.feedbackLinksById[item.id] || []).length > 0);
    }

    get renderedFeedbackItems() {
        return this.linkedFeedbackItems.map((item) => ({
            ...item,
            chunkIds: this.feedbackLinksById[item.id] || [],
            isActive: this.currentFeedbackId === item.id,
            toneClass: this._getToneClass(item),
            itemClass: this._buildItemClass(item),
        }));
    }

    get activeJustification() {
        return this.activeFeedbackItem?.justification || "";
    }

    get activeToneClass() {
        return this.activeFeedbackItem ? this._getToneClass(this.activeFeedbackItem) : "";
    }

    _getFeedbackSortKey(item) {
        const chunkIds = this.feedbackLinksById[item.id] || [];
        if (!chunkIds.length) {
            return Number.POSITIVE_INFINITY;
        }
        const orders = chunkIds
            .map((chunkId) => this.chunkOrderById[chunkId])
            .filter((order) => Number.isInteger(order));
        if (!orders.length) {
            return Number.POSITIVE_INFINITY;
        }
        return Math.min(...orders);
    }

    _buildItemClass(item) {
        const classes = [this._getToneClass(item)];
        if (this.currentFeedbackId === item.id) {
            classes.push("is-active");
        }
        return classes.join(" ");
    }

    _getToneClass(item) {
        const rawType = String(item?.type || "").toLowerCase();
        const rawText = String(item?.text || "").toLowerCase();
        const signal = `${rawType} ${rawText}`;
        if (["success", "positive", "correct", "strength"].some((token) => signal.includes(token))) {
            return "is-success";
        }
        if (["error", "concept_error", "incorrect", "issue", "warning", "spelling", "grammar", "punctuation", "misspell", "wrong"].some((token) => signal.includes(token))) {
            return "is-error";
        }
        if (["info", "hint", "note", "neutral", "observation", "suggestion"].some((token) => signal.includes(token))) {
            return "is-info";
        }
        return "is-info";
    }

    get hasStructuredItems() {
        return this.isTargeted && this.linkedFeedbackItems.length > 0;
    }

    get answerMarkup() {
        if (this.isTargeted && this.answerChunkedHtml) {
            const activeChunkIds = new Set(this.activeChunkIds);
            const toneClass = this.activeFeedbackItem ? this._getToneClass(this.activeFeedbackItem) : "is-info";
            const parser = new DOMParser();
            const doc = parser.parseFromString(`<div>${this.answerChunkedHtml}</div>`, "text/html");
            for (const node of doc.body.querySelectorAll("[data-chunk-id]")) {
                node.classList.add("aps-ai-answer-chunk");
                node.classList.remove("is-success", "is-error", "is-info");
                if (activeChunkIds.has(node.dataset.chunkId)) {
                    node.classList.add("is-active", toneClass);
                } else {
                    node.classList.remove("is-active");
                }
            }
            return markup(doc.body.firstElementChild?.innerHTML || this.answerChunkedHtml);
        }
        const answerField = this.props.answerField || "answer";
        return markup(this.props.record.data[answerField] || '<p class="text-muted mb-0">No answer supplied.</p>');
    }

    get feedbackMarkup() {
        return markup(this.props.record.data[this.props.name] || '<p class="text-muted mb-0">No feedback available.</p>');
    }

    onFeedbackClick(ev) {
        const feedbackId = ev.currentTarget.dataset.feedbackId;
        this.state.activeFeedbackId = feedbackId === this.currentFeedbackId ? null : feedbackId;
    }
}

export const submissionFeedbackViewerField = {
    component: SubmissionFeedbackViewer,
    supportedTypes: ["html"],
    extractProps({ options }) {
        return {
            answerField: options.answer_field || "answer",
        };
    },
};

registry.category("fields").add("submission_feedback_viewer", submissionFeedbackViewerField);