import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";

const VIEW_STATE_KEY = `aps_sis_past_paper_progress_${user.userId}`;

function restoreViewState() {
    try {
        const saved = JSON.parse(window.localStorage.getItem(VIEW_STATE_KEY) || "null");
        return saved && typeof saved === "object" ? saved : {};
    } catch {
        return {};
    }
}

export class PastPaperProgress extends Component {
    static template = "aps_sis.PastPaperProgress";
    static components = { PercentPie };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.rootRef = useRef("root");
        this._scrollSaveFrame = null;
        const saved = restoreViewState();
        this.state = useState({
            loading: true,
            error: false,
            role: false,
            categories: [],
            students: [],
            papers: [],
            categoryId: Number(saved.categoryId) || 0,
            studentId: Number(saved.studentId) || 0,
            paperFilter: ["all", "attempted", "new"].includes(saved.paperFilter)
                ? saved.paperFilter
                : "all",
            searchText: typeof saved.searchText === "string" ? saved.searchText : "",
            activePaperId: false,
            activeQuestionId: false,
            selectedPaperId: Number(saved.selectedPaperId) || 0,
            scrollTop: Math.max(0, Number(saved.scrollTop) || 0),
            hoveredQuestionId: false,
            tooltipStyle: "",
            submissionViews: [],
        });
        this.onCategoryChange = this.onCategoryChange.bind(this);
        this.onStudentChange = this.onStudentChange.bind(this);
        this.onPaperFilterChange = this.onPaperFilterChange.bind(this);
        this.onPaperSearchInput = this.onPaperSearchInput.bind(this);
        this.onPaperClick = this.onPaperClick.bind(this);
        this.onPaperKeydown = this.onPaperKeydown.bind(this);
        this.onScroll = this.onScroll.bind(this);
        this.onQuestionMouseEnter = this.onQuestionMouseEnter.bind(this);
        this.onQuestionMouseLeave = this.onQuestionMouseLeave.bind(this);
        this.onQuestionClick = this.onQuestionClick.bind(this);
        this.onHistoryClick = this.onHistoryClick.bind(this);
        this.closePaperDialog = this.closePaperDialog.bind(this);
        this.stopDialogClick = this.stopDialogClick.bind(this);
        this.assignPaper = this.assignPaper.bind(this);
        onWillStart(() => this.load());
        onMounted(() => {
            if (this.rootRef.el) {
                this.rootRef.el.scrollTop = this.state.scrollTop;
            }
        });
        onWillUnmount(() => {
            if (this.rootRef.el) {
                this.state.scrollTop = this.rootRef.el.scrollTop;
            }
            if (this._scrollSaveFrame !== null) {
                window.cancelAnimationFrame(this._scrollSaveFrame);
                this._scrollSaveFrame = null;
            }
            this.saveViewState();
        });
    }

    get visiblePapers() {
        let papers = this.state.papers;
        if (this.state.paperFilter === "attempted") {
            papers = papers.filter((paper) => paper.has_attempts);
        } else if (this.state.paperFilter === "new") {
            papers = papers.filter((paper) => !paper.has_attempts);
        }
        const searchText = this.state.searchText.trim().toLowerCase();
        return searchText
            ? papers.filter((paper) => (paper.name || "").toLowerCase().includes(searchText))
            : papers;
    }

    get activePaper() {
        return this.state.papers.find(
            (paper) => paper.id === this.state.activePaperId
        );
    }

    get activeQuestion() {
        return this.activePaper?.questions.find(
            (question) => question.id === this.state.activeQuestionId
        );
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const categoryId = Number(this.state.categoryId) || false;
            const studentId = Number(this.state.studentId) || false;
            const data = await this.orm.call(
                "aps.resources",
                "get_past_paper_progress_data",
                [categoryId, studentId]
            );
            Object.assign(this.state, data, { loading: false, error: false });
        } catch (error) {
            this.state.loading = false;
            this.state.error = error.message || "Unable to load Past Paper progress.";
        }
    }

    async onCategoryChange(event) {
        this.state.categoryId = Number(event.target.value) || 0;
        this.state.activePaperId = false;
        this.state.activeQuestionId = false;
        this.saveViewState();
        await this.load();
    }

    async onStudentChange(event) {
        this.state.studentId = Number(event.target.value) || 0;
        this.state.categoryId = 0;
        this.state.activePaperId = false;
        this.state.activeQuestionId = false;
        this.saveViewState();
        await this.load();
    }

    onPaperFilterChange(event) {
        this.state.paperFilter = event.target.value;
        this.saveViewState();
    }

    onPaperSearchInput(event) {
        this.state.searchText = event.target.value;
        this.saveViewState();
    }

    onScroll(event) {
        this.state.scrollTop = event.currentTarget.scrollTop;
        if (this._scrollSaveFrame === null) {
            this._scrollSaveFrame = window.requestAnimationFrame(() => {
                this._scrollSaveFrame = null;
                this.saveViewState();
            });
        }
    }

    saveViewState() {
        try {
            window.localStorage.setItem(VIEW_STATE_KEY, JSON.stringify({
                categoryId: this.state.categoryId,
                studentId: this.state.studentId,
                paperFilter: this.state.paperFilter,
                searchText: this.state.searchText,
                selectedPaperId: this.state.selectedPaperId,
                scrollTop: this.state.scrollTop,
            }));
        } catch {
            // Browser storage can be unavailable or full.
        }
    }

    onPaperClick(event) {
        const paperId = Number(event.currentTarget.dataset.paperId);
        this.state.selectedPaperId = paperId;
        this.state.activePaperId = paperId;
        this.state.activeQuestionId = false;
        this.saveViewState();
    }

    onPaperKeydown(event) {
        if (
            event.currentTarget === event.target
            && (event.key === "Enter" || event.key === " ")
        ) {
            event.preventDefault();
            this.onPaperClick(event);
        }
    }

    onQuestionMouseEnter(event) {
        this.state.hoveredQuestionId = Number(event.currentTarget.dataset.questionId);
        const rect = event.currentTarget.getBoundingClientRect();
        const width = Math.min(320, window.innerWidth - 16);
        let top = rect.bottom + 8;
        if (top + 180 > window.innerHeight) {
            top = Math.max(8, rect.top - 188);
        }
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
        this.state.tooltipStyle = `top: ${top}px; left: ${left}px;`;
    }

    onQuestionMouseLeave() {
        this.state.hoveredQuestionId = false;
    }

    async onQuestionClick(event) {
        event.stopPropagation();
        const paperId = Number(event.currentTarget.dataset.paperId);
        const questionId = Number(event.currentTarget.dataset.questionId);
        const paper = this.state.papers.find((item) => item.id === paperId);
        const question = paper?.questions.find(
            (item) => item.id === questionId
        );
        if (!paper || !question) {
            return;
        }
        if (!question.attempts) {
            this.state.selectedPaperId = paper.id;
            this.state.activePaperId = paper.id;
            this.state.activeQuestionId = question.id;
            this.state.hoveredQuestionId = false;
            this.saveViewState();
            return;
        }
        await this.openSubmissions(
            `Question submissions: ${question.name}`,
            question.related_resource_ids
        );
    }

    async onHistoryClick(event) {
        event.stopPropagation();
        const index = Number(event.currentTarget.dataset.historyIndex);
        const history = this.activePaper?.history[index];
        if (!history) {
            return;
        }
        await this.openSubmissions(
            `Past Paper submissions: ${history.label}`,
            this.activePaper.related_resource_ids,
            history.submission_ids
        );
    }

    async openSubmissions(name, resourceIds, submissionIds = false) {
        const studentId = Number(this.state.student_id) || Number(this.state.studentId);
        const domain = [
            ["task_id.student_id", "=", studentId],
            ["task_id.resource_id", "in", resourceIds],
        ];
        if (submissionIds) {
            domain.push(["id", "in", submissionIds]);
        }
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "aps.resource.submission",
            views: this.state.submission_views,
            domain,
            context: {},
        });
    }

    closePaperDialog() {
        this.state.activePaperId = false;
        this.state.activeQuestionId = false;
        this.state.hoveredQuestionId = false;
    }

    stopDialogClick(event) {
        event.stopPropagation();
    }

    async assignPaper() {
        const paper = this.activePaper;
        if (!paper) {
            return;
        }
        const question = this.activeQuestion;
        this.state.loading = true;
        this.state.error = false;
        try {
            const action = await this.orm.call(
                "aps.resources",
                question
                    ? "action_assign_past_paper_question"
                    : "action_assign_past_paper",
                question
                    ? [
                        paper.id,
                        question.id,
                        Number(this.state.studentId) || false,
                        Number(this.state.categoryId) || false,
                    ]
                    : [
                    paper.id,
                    Number(this.state.studentId) || false,
                    Number(this.state.categoryId) || false,
                    ]
            );
            this.closePaperDialog();
            await this.actionService.doAction(action);
        } catch (error) {
            this.state.loading = false;
            this.state.error = error.message || (
                question
                    ? "Unable to assign this question."
                    : "Unable to start this Past Paper."
            );
        }
    }

    questionStyle(question) {
        const attempts = Number(question.attempts) || 0;
        const score = Number(question.weighted_result);
        const borderColor = attempts
            && question.weighted_result !== false
            && Number.isFinite(score)
            ? getColorForPercent(score)
            : "#cbd2d9";
        const color = borderColor.slice(1);
        const red = Number.parseInt(color.slice(0, 2), 16);
        const green = Number.parseInt(color.slice(2, 4), 16);
        const blue = Number.parseInt(color.slice(4, 6), 16);
        const opacity = Math.max(0, Math.min(attempts * 0.1, 1));
        const displayedRed = Math.round(255 + (red - 255) * opacity);
        const displayedGreen = Math.round(255 + (green - 255) * opacity);
        const displayedBlue = Math.round(255 + (blue - 255) * opacity);
        const displayedLuminance = (
            displayedRed * 0.299
            + displayedGreen * 0.587
            + displayedBlue * 0.114
        );
        const borderWidth = question.has_children ? 2 : 1;
        return [
            `--attempt-fill: rgba(${red}, ${green}, ${blue}, ${opacity})`,
            `--attempt-text: ${displayedLuminance < 128 ? "#fff" : "#212529"}`,
            `border: ${borderWidth}px solid ${borderColor}`,
        ].join(";");
    }

    paperAttemptMarks(paper) {
        const completedAttempts = Math.max(
            0,
            Math.floor(Number(paper.completed_paper_attempts) || 0)
        );
        const partialAttempts = Math.max(
            0,
            Math.floor(Number(paper.partial_paper_attempts) || 0)
        );
        return "\u{1F5F9}".repeat(completedAttempts)
            + "\u2610".repeat(partialAttempts);
    }

    paperAttemptLabel(paper) {
        const completedAttempts = Number(paper.completed_paper_attempts) || 0;
        const partialAttempts = Number(paper.partial_paper_attempts) || 0;
        const statuses = [];
        if (completedAttempts) {
            statuses.push(`${completedAttempts} completed`);
        }
        if (partialAttempts) {
            statuses.push(`${partialAttempts} partially completed`);
        }
        return `${statuses.join(", ")} paper attempts`;
    }

    paperStyle(paper) {
        const gray = Number(paper.completed_paper_attempts) > 0 ? 204 : 255;
        return `--paper-progress-color: rgb(${gray}, ${gray}, ${gray})`;
    }
}

registry.category("actions").add("aps_sis_past_paper_progress", PastPaperProgress);
