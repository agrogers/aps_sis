(function () {
    'use strict';

    const AwardsVoting = {
        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        _token: null,
        _categoryId: null,
        _categoryName: null,
        _candidates: [],       // full list from server
        _filtered: [],         // after search + filter
        _selected: new Set(),  // selected partner IDs
        _comments: new Map(), // per-student comments, keyed by partner id
        _sortKey: 'name',
        _sortAsc: true,

        // ----------------------------------------------------------------
        // Modal open / close
        // ----------------------------------------------------------------
        openModal(btn) {
            this._token       = btn.dataset.token;
            this._categoryId  = parseInt(btn.dataset.categoryId, 10);
            this._categoryName = btn.dataset.categoryName;
            this._selected.clear();
            this._comments.clear();
            this._sortKey = 'name';
            this._sortAsc = true;

            document.getElementById('av-modal-cat-name').textContent = this._categoryName;
            document.getElementById('av-modal-selection-summary').style.display = 'none';
            document.getElementById('av-submit-btn').style.display = 'none';
            document.getElementById('av-search').value = '';
            document.getElementById('av-candidate-list').innerHTML =
                '<tr><td colspan="6" class="av-loading">Loading candidates…</td></tr>';

            document.getElementById('av-modal').style.display = 'flex';
            document.body.style.overflow = 'hidden';

            this._populateFilters();
            this.loadCandidates();
        },

        closeModal() {
            document.getElementById('av-modal').style.display = 'none';
            document.body.style.overflow = '';
        },

        overlayClick(e) {
            if (e.target === document.getElementById('av-modal')) this.closeModal();
        },

        // ----------------------------------------------------------------
        // Filters — populate from categories level_ids / subject_category_ids
        // ----------------------------------------------------------------
        _populateFilters() {
            // We populate generically; the server already filters by category.
            // The dropdowns are filled from the returned candidate data.
            document.getElementById('av-filter-level').innerHTML =
                '<option value="">All Year Levels</option>';
            document.getElementById('av-filter-subject-cat').innerHTML =
                '<option value="">All Subject Categories</option>';
        },

        // ----------------------------------------------------------------
        // Load candidates via JSON RPC (no filters — filtering is client-side)
        // ----------------------------------------------------------------
        loadCandidates() {
            this._jsonRpc(
                `/awards/vote/${this._token}/candidates/${this._categoryId}`,
                {}
            ).then(result => {
                if (result.error) {
                    this._showError('Could not load candidates: ' + result.error);
                    return;
                }
                this._candidates = result.candidates || [];
                this._populateLevelFilter();
                this._applySearch();
                this._renderTable();
            }).catch(() => {
                document.getElementById('av-candidate-list').innerHTML =
                    '<tr><td colspan="7" class="av-no-results">Failed to load candidates. Please try again.</td></tr>';
            });
        },

        _populateLevelFilter() {
            const levels = [...new Set(this._candidates.map(c => c.level).filter(Boolean))].sort();
            const sel = document.getElementById('av-filter-level');
            const current = sel.value;
            sel.innerHTML = '<option value="">All Year Levels</option>' +
                levels.map(l => `<option value="${l}"${l === current ? ' selected' : ''}>${l}</option>`).join('');
        },

        // ----------------------------------------------------------------
        // Search filter
        // ----------------------------------------------------------------
        filterSearch() {
            this._applySearch();
            this._renderTable();
        },

        _applySearch() {
            const q = (document.getElementById('av-search').value || '').toLowerCase();
            const level = document.getElementById('av-filter-level').value;

            this._filtered = this._candidates.filter(c => {
                const nameMatch = !q || c.name.toLowerCase().includes(q);
                const levelMatch = !level || c.level === level;
                return nameMatch && levelMatch;
            });

            this._sortCandidates();
        },

        // ----------------------------------------------------------------
        // Sorting
        // ----------------------------------------------------------------
        sortBy(key) {
            if (this._sortKey === key) {
                this._sortAsc = !this._sortAsc;
            } else {
                this._sortKey = key;
                this._sortAsc = key === 'name' || key === 'level';
            }
            this._sortCandidates();
            this._renderTable();
        },

        _sortCandidates() {
            const key = this._sortKey;
            const asc = this._sortAsc ? 1 : -1;
            this._filtered.sort((a, b) => {
                let va = a[key], vb = b[key];
                if (key === 'times_awarded') { va = va || 0; vb = vb || 0; }
                else if (key === 'last_awarded') {
                    va = va || '0000-00-00'; vb = vb || '0000-00-00';
                }
                else { va = (va || '').toString().toLowerCase(); vb = (vb || '').toString().toLowerCase(); }
                if (va < vb) return -1 * asc;
                if (va > vb) return  1 * asc;
                return 0;
            });
        },

        // ----------------------------------------------------------------
        // Render candidate table
        // ----------------------------------------------------------------
        _renderTable() {
            const tbody = document.getElementById('av-candidate-list');
            if (!this._filtered.length) {
                tbody.innerHTML = '<tr><td colspan="7" class="av-no-results">No students found.</td></tr>';
                return;
            }

            const rows = [];
            for (const c of this._filtered) {
                const sel = this._selected.has(c.id);
                const photo = c.image
                    ? `<img src="data:image/png;base64,${c.image}" alt="${this._esc(c.name)}">`
                    : `<div class="av-initials">${this._initials(c.name)}</div>`;
                const lastDate = c.last_awarded
                    ? new Date(c.last_awarded).toLocaleDateString()
                    : '—';

                rows.push(`<tr class="${sel ? 'av-selected' : ''}" data-id="${c.id}" onclick="AwardsVoting.toggleSelect(${c.id})">
                    <td class="av-td-photo">${photo}</td>
                    <td class="av-td-name">${this._esc(c.name)}</td>
                    <td class="av-td-level">${this._esc(c.level)}</td>
                    <td class="av-td-times">${c.times_awarded}</td>
                    <td class="av-td-last">${lastDate}</td>
                    <td class="av-td-select"><div class="av-select-check">${sel ? '\u2713' : ''}</div></td>
                </tr>`);

                if (sel) {
                    const existing = this._esc(this._comments.get(c.id) || '');
                    rows.push(`<tr class="av-comment-row" data-comment-for="${c.id}">
                        <td colspan="7" class="av-td-comment">
                            <textarea class="av-row-comment"
                                      placeholder="Comment for ${this._esc(c.name)} (optional)"
                                      oninput="AwardsVoting.saveComment(${c.id}, this.value)"
                                      onclick="event.stopPropagation()">${existing}</textarea>
                        </td>
                    </tr>`);
                }
            }
            tbody.innerHTML = rows.join('');
        },

        saveComment(id, value) {
            if (value.trim()) {
                this._comments.set(id, value);
            } else {
                this._comments.delete(id);
            }
        },

        // ----------------------------------------------------------------
        // Toggle student selection
        // ----------------------------------------------------------------
        toggleSelect(id) {
            if (this._selected.has(id)) {
                this._selected.delete(id);
                this._comments.delete(id);
            } else {
                this._selected.add(id);
            }
            this._updateSelectionUI();
            this._renderTable();
        },

        _updateSelectionUI() {
            const count = this._selected.size;
            const summary = document.getElementById('av-modal-selection-summary');
            const submitBtn = document.getElementById('av-submit-btn');

            if (count > 0) {
                const names = [...this._selected].map(id => {
                    const c = this._candidates.find(x => x.id === id);
                    return c ? c.name : 'Unknown';
                }).join(', ');

                summary.textContent = `Selected: ${names}`;
                summary.style.display = 'block';
                submitBtn.textContent = count === 1
                    ? `Submit Vote for ${names}`
                    : `Submit ${count} Votes`;
                submitBtn.style.display = 'inline-block';
            } else {
                summary.style.display = 'none';
                submitBtn.style.display = 'none';
            }
        },

        // ----------------------------------------------------------------
        // Submit
        // ----------------------------------------------------------------
        submitVote() {
            if (!this._selected.size) return;

            // Flush any textarea values still in the DOM (in case oninput hasn't fired)
            document.querySelectorAll('.av-row-comment').forEach(ta => {
                const id = parseInt(ta.closest('tr').dataset.commentFor, 10);
                if (ta.value.trim()) this._comments.set(id, ta.value);
            });

            const recipients = [...this._selected].map(id => ({
                id,
                comment: this._comments.get(id) || '',
            }));

            const btn = document.getElementById('av-submit-btn');
            btn.disabled = true;
            btn.textContent = 'Submitting…';

            this._jsonRpc(`/awards/vote/${this._token}/submit`, {
                category_id: this._categoryId,
                recipients,
            }).then(result => {
                if (result.error) {
                    this._showToast('Error: ' + result.error, 'error');
                    btn.disabled = false;
                    this._updateSelectionUI();
                } else {
                    this._showToast('Vote submitted! 🎉', 'success');
                    this.closeModal();
                    // Refresh page stats after short delay
                    setTimeout(() => window.location.reload(), 1800);
                }
            }).catch(() => {
                this._showToast('Submission failed. Please try again.', 'error');
                btn.disabled = false;
                this._updateSelectionUI();
            });
        },

        // ----------------------------------------------------------------
        // JSON-RPC helper
        // ----------------------------------------------------------------
        _jsonRpc(url, params) {
            return fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    id: Date.now(),
                    params: params,
                }),
            }).then(r => r.json()).then(r => r.result !== undefined ? r.result : r);
        },

        // ----------------------------------------------------------------
        // Helpers
        // ----------------------------------------------------------------
        _esc(str) {
            return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        },

        _initials(name) {
            return (name || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
        },

        _showToast(msg, type = 'success') {
            const t = document.createElement('div');
            t.className = `av-toast av-toast--${type}`;
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(() => t.remove(), 3500);
        },

        _showError(msg) {
            document.getElementById('av-candidate-list').innerHTML =
                `<tr><td colspan="6" class="av-no-results">${this._esc(msg)}</td></tr>`;
        },
    };

    window.AwardsVoting = AwardsVoting;
})();
