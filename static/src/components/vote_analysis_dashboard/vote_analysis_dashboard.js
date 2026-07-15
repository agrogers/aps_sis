import { Component, useState, onWillStart, onMounted, onPatched, useRef, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { FilterPresetManager } from "../../js/filter_preset_service";
import { cookie } from "@web/core/browser/cookie";

const COMPONENT_KEY = "vote_analysis_dashboard";

export class VoteAnalysisDashboard extends Component {
    static template = "aps_sis.VoteAnalysisDashboard";
    static components = { MultiRecordSelector };
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.chartRef = useRef("chart");
        this.chart = null;
        this.voteDetailsGridRef = useRef("voteDetailsGrid");
        this._voteDetailsGrid = null;
        this._voteDetailsDataView = null;
        this._isDarkMode = cookie.get("color_scheme") === "dark";
        this.filterPresets = new FilterPresetManager(this.orm, COMPONENT_KEY);

        this.state = useState({
            loading: true,
            filtersOpen: false,
            dateFrom: "",
            dateTo: "",
            selectedRoundIds: [],
            selectedCategoryIds: [],
            selectedSubCategoryIds: [],
            selectedRecipientIds: [],
            recipientType: "all",
            selectedLevelIds: [],
            selectedDepartmentIds: [],
            recipientDomain: [],
            overlay: "none",
            certificateCounts: {},
            seriesBy: "round",
            roundOptions: [],
            categoryOptions: [],
            subCategoryOptions: [],
            series: [],
            recipients: [],
            chartOrder: "value_desc",
            sortColumn: "total",
            sortDirection: "desc",
            presets: [],
            activePresetId: null,
            activePresetName: "",
            savingPreset: false,
            detailRecipient: null,
            detailRoundId: null,
            detailHeader: "",
            detailVotes: [],
            detailLoading: false,
            activeTab: "chart",
            certDetailRecipient: null,
            certDetailHeader: "",
            certDetailList: [],
            certDetailLoading: false,
            selectedVoteIds: [],
            selectedCerts: [],
            selectedCertsLoading: false,
        });

        onWillStart(async () => {
            await this.filterPresets.load();
            this.state.presets = this.filterPresets.presetList || [];
            const active = await this.filterPresets.getActivePreset();
            if (active) {
                this.state.activePresetId = active.id;
                this.state.activePresetName = active.name;
                this._applyFilterData(active.filter_data);
                await this._updateRecipientDomain();
            }
            await this._loadFilterOptions();
            await this._loadData();
        });

        onMounted(() => { this._renderChart(); });
        onPatched(() => { this._renderChart(); });
        onWillUnmount(() => { this._destroyDetailGrid(); });
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------

    async _loadFilterOptions() {
        const options = await this.orm.call("aps.award.vote", "get_vote_analysis_filter_options", [], {});
        this.state.roundOptions = options.rounds || [];
        this.state.categoryOptions = options.categories || [];
        this.state.subCategoryOptions = options.sub_categories || [];
    }

    async _loadData() {
        this.state.loading = true;
        const filters = {
            date_from: this.state.dateFrom || false,
            date_to: this.state.dateTo || false,
            round_ids: this.state.selectedRoundIds,
            series_by: this.state.seriesBy,
            category_ids: this.state.selectedCategoryIds,
            sub_category_ids: this.state.selectedSubCategoryIds,
            recipient_ids: this.state.selectedRecipientIds,
            recipient_type: this.state.recipientType,
            level_ids: this.state.selectedLevelIds,
            department_ids: this.state.selectedDepartmentIds,
            overlay: this.state.overlay,
        };
        const data = await this.orm.call("aps.award.vote", "get_vote_analysis_data", [], { filters });
        this.state.series = data.series || [];
        this.state.recipients = data.recipients || [];
        this.state.certificateCounts = data.certificate_counts || {};
        this.state.loading = false;
    }

    async _updateRecipientDomain() {
        const ids = await this.orm.call(
            "aps.award.vote", "get_recipient_domain",
            [this.state.recipientType, this.state.selectedLevelIds, this.state.selectedDepartmentIds],
            {}
        );
        this.state.recipientDomain = ids.length ? [["id", "in", ids]] : [];
    }

    // ------------------------------------------------------------------
    // Chart rendering
    // ------------------------------------------------------------------

    _renderChart() {
        if (!this.chartRef.el) { return; }
        if (this.chart) { this.chart.destroy(); this.chart = null; }

        const series = this.state.series;
        const recipients = this.chartOrderedRecipients;
        if (!series.length || !recipients.length) { return; }

        const fullNames = recipients.map((r) => r.name);
        const labels = fullNames.map((name) => this._truncateLabel(name, 20));
        const colors = ["#0d6efd","#198754","#ffc107","#dc3545","#6f42c1","#fd7e14","#20c997","#6610f2","#d63384","#0dcaf0"];

        const datasets = series.map((round, idx) => ({
            label: round.name,
            data: recipients.map((r) => r.votes[round.id] || 0),
            backgroundColor: colors[idx % colors.length],
            borderColor: colors[idx % colors.length],
            borderWidth: 1,
            yAxisID: "y",
            order: 1,
        }));

        const certCounts = this.state.certificateCounts;
        const hasOverlay = this.state.overlay === "certificates" && Object.keys(certCounts).length > 0;
        if (hasOverlay) {
            datasets.push({
                label: "Certificates",
                data: recipients.map((r) => certCounts[r.id] || 0),
                type: "line",
                borderColor: "#e11d48",
                backgroundColor: "#e11d48",
                borderWidth: 2,
                pointRadius: 4,
                pointBackgroundColor: "#e11d48",
                fill: false,
                yAxisID: "y1",
                order: 0,
                z: 10,
            });
        }

        const scales = {
            x: { stacked: true, ticks: { maxRotation: 45, minRotation: 0 } },
            y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1 }, title: { display: true, text: "Votes" }, position: "left" },
        };
        if (hasOverlay) {
            scales.y1 = {
                beginAtZero: true, ticks: { stepSize: 1 },
                title: { display: true, text: "Certificates" },
                position: "right", grid: { drawOnChartArea: false },
            };
        }

        this.chart = new Chart(this.chartRef.el, {
            type: "bar", data: { labels, datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: "Votes per Recipient by Round", position: "top" },
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { title: (items) => { const idx = items[0]?.dataIndex; return idx !== undefined ? fullNames[idx] : ""; } } },
                },
                onClick: (_event, elements) => { this._onChartClick(elements); },
                scales,
            },
        });
    }

    _truncateLabel(text, maxLen = 20) {
        const v = text || "";
        return v.length <= maxLen ? v : `${v.slice(0, maxLen - 1)}…`;
    }

    // ------------------------------------------------------------------
    // Filter event handlers
    // ------------------------------------------------------------------

    toggleFilters() { this.state.filtersOpen = !this.state.filtersOpen; }
    onTabChange(tab) {
        this.state.activeTab = tab;
        if (tab === "chart") {
            Promise.resolve().then(() => this._renderChart());
        }
        if (tab === "details" && this.state.detailRecipient && this.state.detailVotes.length > 0) {
            // Re-initialize grid when switching back to details tab
            setTimeout(() => this._initVoteDetailsGrid(this.state.detailVotes), 100);
        }
    }

    async onDateFromChange(ev) { this.state.dateFrom = ev.target.value; await this._loadData(); }
    async onDateToChange(ev) { this.state.dateTo = ev.target.value; await this._loadData(); }
    async onRoundsUpdate(selectedIds) { this.state.selectedRoundIds = selectedIds; await this._loadData(); }
    async onCategoriesUpdate(selectedIds) { this.state.selectedCategoryIds = selectedIds; await this._loadData(); }
    async onSubCategoriesUpdate(selectedIds) { this.state.selectedSubCategoryIds = selectedIds; await this._loadData(); }
    async onRecipientsUpdate(selectedIds) { this.state.selectedRecipientIds = selectedIds; await this._loadData(); }
    async onSeriesByChange(ev) { this.state.seriesBy = ev.target.value; await this._loadData(); }
    async onChartOrderChange(ev) { this.state.chartOrder = ev.target.value; }
    async onOverlayChange(ev) { this.state.overlay = ev.target.value; await this._loadData(); }

    async onRecipientTypeChange(ev) {
        this.state.recipientType = ev.target.value;
        this.state.selectedRecipientIds = [];
        await this._updateRecipientDomain();
        await this._loadData();
    }

    async onLevelsUpdate(selectedIds) {
        this.state.selectedLevelIds = selectedIds;
        this.state.selectedRecipientIds = [];
        await this._updateRecipientDomain();
        await this._loadData();
    }

    async onDepartmentsUpdate(selectedIds) {
        this.state.selectedDepartmentIds = selectedIds;
        this.state.selectedRecipientIds = [];
        await this._updateRecipientDomain();
        await this._loadData();
    }

    async clearAllFilters() {
        this.state.dateFrom = "";
        this.state.dateTo = "";
        this.state.selectedRoundIds = [];
        this.state.selectedCategoryIds = [];
        this.state.selectedSubCategoryIds = [];
        this.state.selectedRecipientIds = [];
        this.state.recipientType = "all";
        this.state.selectedLevelIds = [];
        this.state.selectedDepartmentIds = [];
        this.state.recipientDomain = [];
        this.state.overlay = "none";
        this.state.activePresetId = null;
        this.state.activePresetName = "";
        await this._loadData();
    }

    // ------------------------------------------------------------------
    // Filter preset management
    // ------------------------------------------------------------------

    _getFilterData() {
        return {
            dateFrom: this.state.dateFrom,
            dateTo: this.state.dateTo,
            seriesBy: this.state.seriesBy,
            chartOrder: this.state.chartOrder,
            selectedRoundIds: this.state.selectedRoundIds,
            selectedCategoryIds: this.state.selectedCategoryIds,
            selectedSubCategoryIds: this.state.selectedSubCategoryIds,
            selectedRecipientIds: this.state.selectedRecipientIds,
            recipientType: this.state.recipientType,
            selectedLevelIds: this.state.selectedLevelIds,
            selectedDepartmentIds: this.state.selectedDepartmentIds,
            overlay: this.state.overlay,
        };
    }

    _applyFilterData(data) {
        if (!data) { return; }
        this.state.dateFrom = data.dateFrom || "";
        this.state.dateTo = data.dateTo || "";
        this.state.seriesBy = data.seriesBy || "round";
        this.state.chartOrder = data.chartOrder || "value_desc";
        this.state.selectedRoundIds = data.selectedRoundIds || [];
        this.state.selectedCategoryIds = data.selectedCategoryIds || [];
        this.state.selectedSubCategoryIds = data.selectedSubCategoryIds || [];
        this.state.selectedRecipientIds = data.selectedRecipientIds || [];
        this.state.recipientType = data.recipientType || "all";
        this.state.selectedLevelIds = data.selectedLevelIds || [];
        this.state.selectedDepartmentIds = data.selectedDepartmentIds || [];
        this.state.overlay = data.overlay || "none";
    }

    onPresetNameInput(ev) { this.state.activePresetName = ev.target.value; this.state.activePresetId = null; }

    async onPresetSelect(ev) {
        const presetId = ev.target.value ? parseInt(ev.target.value, 10) : null;
        if (!presetId) { this.state.activePresetId = null; this.state.activePresetName = ""; return; }
        const preset = await this.filterPresets.loadPreset(presetId);
        if (!preset) { return; }
        this.state.activePresetId = presetId;
        this.state.activePresetName = preset.name;
        this._applyFilterData(preset.filter_data);
        await this._updateRecipientDomain();
        await this._loadData();
    }

    async onPresetSave() {
        const name = (this.state.activePresetName || "").trim();
        if (!name) { return; }
        this.state.savingPreset = true;
        try {
            const result = await this.filterPresets.save(name, this._getFilterData());
            this.state.activePresetId = result.id;
            this.state.activePresetName = name;
            this.state.presets = this.filterPresets.presetList || [];
            this.notification.add(`Preset "${name}" ${result.action === 'created' ? 'saved' : 'updated'}`, { type: "success" });
        } finally { this.state.savingPreset = false; }
    }

    async onPresetDelete() {
        if (!this.state.activePresetId) { return; }
        await this.filterPresets.delete(this.state.activePresetId);
        this.state.activePresetId = null;
        this.state.activePresetName = "";
        this.state.presets = this.filterPresets.presetList || [];
    }

    // ------------------------------------------------------------------
    // Chart click / drill-down
    // ------------------------------------------------------------------

    getRecipientVoteCount(roundId, recipient) { return recipient.votes[roundId] || 0; }

    onTableCellClick(recipient, seriesId) {
        this._loadDetailVotes(recipient, seriesId);
    }

    onTotalClick(recipient) {
        const allVoteIds = [];
        for (const seriesId in recipient.vote_ids || {}) {
            allVoteIds.push(...recipient.vote_ids[seriesId]);
        }
        this._loadDetailVotesByIds(recipient, allVoteIds, recipient.name + " — All Votes");
    }

    async _loadDetailVotes(recipient, seriesId) {
        this.state.detailLoading = true;
        this.state.detailRecipient = recipient;
        this.state.detailRoundId = seriesId;
        const seriesItem = this.state.series.find((r) => r.id === seriesId);
        this.state.detailHeader = recipient.name + " — " + (seriesItem ? seriesItem.name : "Series " + seriesId);
        const voteIds = (recipient.vote_ids && recipient.vote_ids[seriesId]) || [];
        await this._loadDetailVotesByIds(recipient, voteIds, this.state.detailHeader);
    }

    async _loadDetailVotesByIds(recipient, voteIds, header) {
        this.state.detailLoading = true;
        this.state.detailRecipient = recipient;
        this.state.detailHeader = header;
        this.state.selectedVoteIds = [];
        this.state.selectedCerts = [];
        this.state.selectedCertsLoading = false;
        this.state.detailVotes = (await this.orm.call("aps.award.vote", "get_vote_details", [], { vote_ids: voteIds })) || [];
        this.state.detailLoading = false;
        this.state.activeTab = "details";
        this._destroyDetailGrid();
        // Grid init after OWL DOM patch completes
        setTimeout(() => this._initVoteDetailsGrid(this.state.detailVotes), 100);
    }

    clearDetail() {
        this._destroyDetailGrid();
        this.state.detailRecipient = null;
        this.state.detailRoundId = null;
        this.state.detailHeader = "";
        this.state.detailVotes = [];
        this.state.selectedVoteIds = [];
        this.state.selectedCerts = [];
        this.state.selectedCertsLoading = false;
    }

    // ------------------------------------------------------------------
    // SlickGrid: Vote Details grid
    // ------------------------------------------------------------------

    _destroyDetailGrid() {
        if (this._voteDetailsGrid) {
            try {
                // Commit any pending edits before destroying (persists comment changes)
                if (this._voteDetailsGrid.editController) {
                    this._voteDetailsGrid.editController.commitCurrentEdit();
                }
                this._voteDetailsGrid.destroy();
            } catch (e) { /* ignore */ }
            this._voteDetailsGrid = null;
            this._voteDetailsDataView = null;
        }
    }

    _initVoteDetailsGrid(votes) {
        this._destroyDetailGrid();
        const container = this.voteDetailsGridRef.el;
        if (!container) { return; }
        if (!votes || !votes.length) { return; }

        const comp = this;
        const columns = [
            {
                id: "selected", name: '<div class="va-grid-header-check"><input type="checkbox" class="form-check-input" title="Select all"/></div>', field: "selected",
                width: 40, minWidth: 40, maxWidth: 40,
                sortable: false, editable: false, focusable: false,
                cssClass: "va-grid-cell-check",
                formatter: (rowIdx, cellIdx, value, columnDef, item) => {
                    const checked = comp.isSelectedVote(item.id) ? "checked" : "";
                    return `<input type="checkbox" class="form-check-input" data-vote-id="${item.id}" ${checked}/>`;
                },
            },
            { id: "voter_name", name: "Voter", field: "voter_name", minWidth: 120, width: 160, sortable: true, editable: false, cssClass: "va-grid-cell" },
            { id: "round_name", name: "Round", field: "round_name", minWidth: 80, width: 120, sortable: true, editable: false, cssClass: "va-grid-cell" },
            { id: "category_name", name: "Category", field: "category_name", minWidth: 100, width: 140, sortable: true, editable: false, cssClass: "va-grid-cell" },
            { id: "sub_category_name", name: "Sub-Category", field: "sub_category_name", minWidth: 100, width: 140, sortable: true, editable: false, cssClass: "va-grid-cell" },
            { id: "submitted_date", name: "Date", field: "submitted_date", minWidth: 80, width: 100, sortable: true, editable: false, cssClass: "va-grid-cell va-grid-cell-center" },
            { id: "comment", name: "Comment", field: "comment", minWidth: 100, width: 200, sortable: true, editable: true, editor: { model: Slicker.Editors.text }, cssClass: "va-grid-cell va-grid-cell-muted" },
        ];

        const data = votes.map((v, idx) => ({ ...v, _idx: idx }));

        const gridBundle = new Slicker.GridBundle(container, columns, {
            enableCellNavigation: true,
            editable: true,
            autoEdit: true,
            enableColumnReorder: false,
            enableHtmlRendering: true,
            fullWidthRows: true,
            forceFitColumns: true,
            syncColumnCellResize: true,
            rowHeight: 34,
            autoHeight: true,
            darkMode: this._isDarkMode,
        }, data);

        this._voteDetailsGrid = gridBundle.slickGrid;
        this._voteDetailsDataView = gridBundle.dataView;

        // Attach select-all header checkbox handler
        // Use setTimeout to let the grid finish rendering, then find the header checkbox
        setTimeout(() => {
            const headerEl = container.querySelector('.slick-header-column[data-id="selected"]');
            if (headerEl) {
                const cb = headerEl.querySelector(".va-grid-header-check input[type='checkbox']");
                if (cb) {
                    cb.checked = comp.allVotesSelected;
                    cb.indeterminate = comp.state.selectedVoteIds.length > 0 && !comp.allVotesSelected;
                    cb.addEventListener("change", () => {
                        comp.toggleAllVotes();
                    });
                }
            }
        }, 0);

        // Comment edit handler — persist on blur
        this._voteDetailsGrid.onCellChange.subscribe((e, args) => {
            const item = args.item;
            if (args.column.field === "comment") {
                comp.orm.call(
                    "aps.award.vote",
                    "update_vote_comment",
                    [item.id, item.comment || ""]
                ).catch((err) => console.error("Failed to save comment:", err));
            }
        });

        // Persist unsaved comment edits when editor is destroyed (tab switch, click away, etc.)
        this._voteDetailsGrid.onBeforeCellEditorDestroy.subscribe((e, args) => {
            const editor = args.editor;
            if (editor && editor.args && editor.args.column && editor.args.column.field === "comment" && editor.args.item) {
                const item = editor.args.item;
                const newValue = editor.serializeValue ? editor.serializeValue() : item.comment;
                if (newValue !== undefined && item.id) {
                    comp.orm.call(
                        "aps.award.vote",
                        "update_vote_comment",
                        [item.id, newValue || ""]
                    ).catch((err) => console.error("Failed to save comment on editor close:", err));
                }
            }
        });

        // Checkbox click handler — must return true for non-checkbox clicks to allow cell editing
        this._voteDetailsGrid.onClick.subscribe((e, args) => {
            const target = e.target;
            if (target.type === "checkbox" && target.dataset.voteId) {
                const voteId = parseInt(target.dataset.voteId, 10);
                comp.toggleVoteSelection(voteId);
                target.checked = comp.isSelectedVote(voteId);
                comp._updateDetailHeaderCheckbox();
                e.stopImmediatePropagation();
                return false;
            }
            return true;
        });

        // Resize observer
        this._detailGridResizeObserver = new ResizeObserver(() => {
            if (this._voteDetailsGrid) this._voteDetailsGrid.resizeCanvas();
        });
        this._detailGridResizeObserver.observe(container);
        setTimeout(() => this._voteDetailsGrid.resizeCanvas(), 100);
    }

    _updateDetailHeaderCheckbox() {
        const container = this.voteDetailsGridRef.el;
        if (!container) return;
        const headerCb = container.querySelector(".va-grid-header-check input[type='checkbox']");
        if (headerCb) {
            headerCb.checked = this.allVotesSelected;
            headerCb.indeterminate = this.state.selectedVoteIds.length > 0 && !this.allVotesSelected;
        }
    }

    // ------------------------------------------------------------------
    // Checkbox / certificate selection
    // ------------------------------------------------------------------

    toggleAllVotes() {
        if (this.allVotesSelected) {
            this.state.selectedVoteIds = [];
        } else {
            this.state.selectedVoteIds = this.state.detailVotes.map((v) => v.id);
        }
        this._refreshDetailCheckboxes();
    }

    get allVotesSelected() {
        return this.state.detailVotes.length > 0 && this.state.selectedVoteIds.length === this.state.detailVotes.length;
    }

    toggleVoteSelection(voteId) {
        const ids = [...this.state.selectedVoteIds];
        const idx = ids.indexOf(voteId);
        if (idx >= 0) {
            ids.splice(idx, 1);
        } else {
            ids.push(voteId);
        }
        this.state.selectedVoteIds = ids;
    }

    isSelectedVote(voteId) {
        return this.state.selectedVoteIds.includes(voteId);
    }

    _refreshDetailCheckboxes() {
        const container = this.voteDetailsGridRef.el;
        if (!container) return;
        const checkboxes = container.querySelectorAll("input[data-vote-id]");
        const selectedSet = new Set(this.state.selectedVoteIds);
        checkboxes.forEach((cb) => {
            const vid = parseInt(cb.dataset.voteId, 10);
            cb.checked = selectedSet.has(vid);
        });
        this._updateDetailHeaderCheckbox();
    }

    async loadSelectedCerts() {
        const ids = this.state.selectedVoteIds;
        if (!ids.length) {
            this.state.selectedCerts = [];
            return;
        }
        this.state.selectedCertsLoading = true;
        const partnerIds = [...new Set(
            this.state.detailVotes
                .filter((v) => ids.includes(v.id))
                .map((v) => v.recipient_id)
                .filter(Boolean)
        )];
        const allCerts = [];
        const seen = new Set();
        for (const pid of partnerIds) {
            const filters = {
                recipient_id: pid,
                date_from: this.state.dateFrom || false,
                date_to: this.state.dateTo || false,
                category_ids: this.state.selectedCategoryIds,
            };
            const certs = await this.orm.call("aps.award.vote", "get_certificate_details", [], { filters });
            for (const c of certs || []) {
                if (!seen.has(c.id)) {
                    seen.add(c.id);
                    allCerts.push(c);
                }
            }
        }
        this.state.selectedCerts = allCerts;
        this.state.selectedCertsLoading = false;
    }

    // ------------------------------------------------------------------
    // Certificate drill-down
    // ------------------------------------------------------------------

    async _loadCertDetails(recipient) {
        this.state.certDetailLoading = true;
        this.state.certDetailRecipient = recipient;
        this.state.certDetailHeader = recipient.name + " — Certificates";
        const filters = {
            recipient_id: recipient.id,
            date_from: this.state.dateFrom || false,
            date_to: this.state.dateTo || false,
            category_ids: this.state.selectedCategoryIds,
        };
        this.state.certDetailList = (await this.orm.call("aps.award.vote", "get_certificate_details", [], { filters })) || [];
        this.state.certDetailLoading = false;
        this.state.activeTab = "certs";
    }

    clearCertDetail() {
        this.state.certDetailRecipient = null;
        this.state.certDetailHeader = "";
        this.state.certDetailList = [];
    }

    // ------------------------------------------------------------------
    // Sort helpers
    // ------------------------------------------------------------------

    get sortedRecipients() {
        const recipients = [...this.state.recipients];
        const column = this.state.sortColumn;
        const direction = this.state.sortDirection === "asc" ? 1 : -1;
        recipients.sort((a, b) => {
            let aVal, bVal;
            if (column === "name") {
                aVal = (a.name || "").toLowerCase(); bVal = (b.name || "").toLowerCase();
                if (aVal < bVal) return -1 * direction;
                if (aVal > bVal) return 1 * direction;
                return 0;
            }
            if (column === "total") { aVal = a.total || 0; bVal = b.total || 0; }
            else { aVal = a.votes?.[column] || 0; bVal = b.votes?.[column] || 0; }
            if (aVal === bVal) return (a.name || "").localeCompare(b.name || "");
            return (aVal - bVal) * direction;
        });
        return recipients;
    }

    onSort(column) {
        if (this.state.sortColumn === column) this.state.sortDirection = this.state.sortDirection === "asc" ? "desc" : "asc";
        else { this.state.sortColumn = column; this.state.sortDirection = column === "name" ? "asc" : "desc"; }
    }

    getSortIconClass(column) {
        if (this.state.sortColumn !== column) return "fa fa-sort text-muted opacity-50";
        return this.state.sortDirection === "asc" ? "fa fa-sort-asc text-primary" : "fa fa-sort-desc text-primary";
    }

    isSortedColumn(column) { return this.state.sortColumn === column; }

    get chartOrderedRecipients() {
        const recipients = [...this.state.recipients];
        switch (this.state.chartOrder) {
            case "name_asc": recipients.sort((a, b) => (a.name || "").localeCompare(b.name || "")); break;
            case "name_desc": recipients.sort((a, b) => (b.name || "").localeCompare(a.name || "")); break;
            case "value_asc": recipients.sort((a, b) => a.total - b.total); break;
            case "value_desc": default: recipients.sort((a, b) => b.total - a.total); break;
        }
        return recipients;
    }

    // ------------------------------------------------------------------
    // Chart click
    // ------------------------------------------------------------------

    _onChartClick(elements) {
        if (!elements.length) { return; }
        const element = elements[0];
        const series = this.state.series;
        const recipients = this.chartOrderedRecipients;
        if (!recipients.length) { return; }

        const hasOverlay = this.state.overlay === "certificates" && Object.keys(this.state.certificateCounts).length > 0;
        const certDatasetIndex = hasOverlay ? series.length : -1;

        if (hasOverlay && element.datasetIndex === certDatasetIndex) {
            if (element.index >= 0 && element.index < recipients.length) {
                this._loadCertDetails(recipients[element.index]);
            }
            return;
        }

        if (!series.length) { return; }
        if (element.datasetIndex < 0 || element.datasetIndex >= series.length) { return; }
        if (element.index < 0 || element.index >= recipients.length) { return; }
        this._loadDetailVotes(recipients[element.index], series[element.datasetIndex].id);
    }
}

registry.category("actions").add("vote_analysis_dashboard", VoteAnalysisDashboard);