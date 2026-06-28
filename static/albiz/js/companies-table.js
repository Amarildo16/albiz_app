(function () {
    'use strict';

    var columns = [
        { data: 'company_nipt' },
        { data: 'business_name' },
        { data: 'legal_form' },
        { data: 'subject_status' },
        { data: 'city' },
        { data: 'registration_year', className: 'text-end' },
        { data: 'active_procurement_count', className: 'text-end' },
        { data: 'winner_value_amount', className: 'text-end' },
        { data: 'safe_winner_to_budget_ratio_avg', className: 'text-end' },
        { data: 'qkb_flag' },
        { data: 'risk_indicators', orderable: false, searchable: false },
        { data: 'actions', orderable: false, searchable: false }
    ];

    function getFilterValue(name) {
        var element = document.querySelector('[data-company-filter="' + name + '"]');
        return element ? element.value.trim() : '';
    }

    function collectFilters() {
        return {
            search: getFilterValue('search'),
            legal_form: getFilterValue('legal_form'),
            subject_status: getFilterValue('subject_status'),
            city: getFilterValue('city'),
            has_red_flags: getFilterValue('has_red_flags'),
            risk_indicator: getFilterValue('risk_indicator'),
            min_active_procurement_count: getFilterValue('min_active_procurement_count'),
            max_active_procurement_count: getFilterValue('max_active_procurement_count')
        };
    }

    function escapeHtml(value) {
        if (value === null || value === undefined || value === '') {
            return '';
        }

        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function t(key, fallback) {
        return (window.AlbizI18n && window.AlbizI18n[key]) || fallback;
    }

    function renderMutedDash(value) {
        var escaped = escapeHtml(value);
        return escaped || '<span class="text-muted">-</span>';
    }

    function formatInteger(value) {
        if (value === null || value === undefined || value === '') {
            return '0';
        }

        var numberValue = Number(value);
        if (!Number.isFinite(numberValue)) {
            return escapeHtml(value);
        }

        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(numberValue);
    }

    function formatMoney(value) {
        if (value === null || value === undefined || value === '') {
            return '<span class="text-muted">-</span>';
        }

        var numberValue = Number(value);
        if (!Number.isFinite(numberValue)) {
            return escapeHtml(value);
        }

        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(numberValue);
    }

    function formatRatio(value) {
        if (value === null || value === undefined || value === '') {
            return '<span class="text-muted">-</span>';
        }

        var numberValue = Number(value);
        if (!Number.isFinite(numberValue)) {
            return escapeHtml(value);
        }

        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(numberValue);
    }

    function renderTextBadge(value, colorClass) {
        var text = escapeHtml(value);
        if (!text) {
            return '<span class="text-muted">-</span>';
        }

        return '<span class="badge ' + colorClass + '">' + text + '</span>';
    }

    function renderQkbFlag(value) {
        if (value === true || value === 'true' || value === 1 || value === '1') {
            return '<span class="badge bg-danger-subtle text-danger">' + escapeHtml(t('qkbFlag', 'QKB flag')) + '</span>';
        }

        if (value === false || value === 'false' || value === 0 || value === '0') {
            return '<span class="badge bg-success-subtle text-success">' + escapeHtml(t('noQkbFlag', 'No QKB flag')) + '</span>';
        }

        return '<span class="badge bg-secondary-subtle text-secondary">' + escapeHtml(t('unknown', 'Unknown')) + '</span>';
    }

    function getIndicatorBadgeClass(level) {
        if (level === 'danger') {
            return 'bg-danger-subtle text-danger';
        }
        if (level === 'warning') {
            return 'bg-warning-subtle text-warning';
        }
        if (level === 'info') {
            return 'bg-info-subtle text-info';
        }
        return 'bg-secondary-subtle text-secondary';
    }

    function renderRiskIndicators(indicators) {
        if (!Array.isArray(indicators) || indicators.length === 0) {
            return '<span class="badge bg-secondary-subtle text-secondary">' + escapeHtml(t('noIndicators', 'No indicators')) + '</span>';
        }

        return '<div class="d-flex flex-wrap gap-1">' + indicators.map(function (indicator) {
            var label = indicator && indicator.label ? indicator.label : '';
            var level = indicator && indicator.level ? indicator.level : '';
            return '<span class="badge ' + getIndicatorBadgeClass(level) + '">' + escapeHtml(label) + '</span>';
        }).join('') + '</div>';
    }

    function renderActions(row) {
        var detailUrl = row && row.detail_url ? row.detail_url : '#';
        return '<a href="' + escapeHtml(detailUrl) + '" class="btn btn-sm btn-soft-primary">' + escapeHtml(t('view', 'View')) + '</a>';
    }

    function showError(message) {
        var errorElement = document.getElementById('companies-table-error');
        if (!errorElement) {
            return;
        }

        if (message) {
            errorElement.textContent = message;
            errorElement.classList.remove('d-none');
        } else {
            errorElement.textContent = '';
            errorElement.classList.add('d-none');
        }
    }

    function debounce(fn, wait) {
        var timeoutId;
        return function () {
            var args = arguments;
            window.clearTimeout(timeoutId);
            timeoutId = window.setTimeout(function () {
                fn.apply(null, args);
            }, wait);
        };
    }

    function bindFilterReload(reload) {
        var debouncedReload = debounce(reload, 350);
        document.querySelectorAll('[data-company-filter]').forEach(function (element) {
            var eventName = element.tagName === 'SELECT' ? 'change' : 'input';
            element.addEventListener(eventName, eventName === 'change' ? reload : debouncedReload);
        });

        var resetButton = document.getElementById('companies-reset-filters');
        if (resetButton) {
            resetButton.addEventListener('click', function () {
                document.querySelectorAll('[data-company-filter]').forEach(function (element) {
                    element.value = '';
                });
                reload();
            });
        }
    }

    function initDataTables(tableElement) {
        if (!window.jQuery || !window.jQuery.fn || !window.jQuery.fn.DataTable) {
            return null;
        }

        var fallbackControls = document.getElementById('companies-fallback-controls');
        if (fallbackControls) {
            fallbackControls.classList.add('d-none');
        }

        var dataTable = window.jQuery(tableElement).DataTable({
            ajax: {
                url: tableElement.dataset.ajaxUrl,
                data: function (data) {
                    var filters = collectFilters();
                    data.search = data.search || {};
                    data.search.value = filters.search;
                    data.legal_form = filters.legal_form;
                    data.subject_status = filters.subject_status;
                    data.city = filters.city;
                    data.has_red_flags = filters.has_red_flags;
                    data.risk_indicator = filters.risk_indicator;
                    data.min_active_procurement_count = filters.min_active_procurement_count;
                    data.max_active_procurement_count = filters.max_active_procurement_count;
                },
                dataSrc: function (json) {
                    showError(json.error || '');
                    return json.data || [];
                },
                error: function () {
                    showError(t('unableLoadCompanies', 'Unable to load companies from the collector database.'));
                }
            },
            autoWidth: false,
            columns: [
                { data: 'company_nipt', render: renderMutedDash },
                { data: 'business_name', render: renderMutedDash },
                { data: 'legal_form', render: function (value) { return renderTextBadge(value, 'bg-primary-subtle text-primary'); } },
                { data: 'subject_status', render: function (value) { return renderTextBadge(value, 'bg-secondary-subtle text-secondary'); } },
                { data: 'city', render: renderMutedDash },
                { data: 'registration_year', className: 'text-end', render: renderMutedDash },
                { data: 'active_procurement_count', className: 'text-end', render: formatInteger },
                { data: 'winner_value_amount', className: 'text-end', render: formatMoney },
                { data: 'safe_winner_to_budget_ratio_avg', className: 'text-end', render: formatRatio },
                { data: 'qkb_flag', render: renderQkbFlag },
                { data: 'risk_indicators', orderable: false, searchable: false, render: renderRiskIndicators },
                {
                    data: 'actions',
                    orderable: false,
                    searchable: false,
                    render: function (value, type, row) {
                        return renderActions(row);
                    }
                }
            ],
            lengthMenu: [10, 25, 50, 100],
            order: [[1, 'asc']],
            pageLength: 25,
            processing: true,
            searching: false,
            serverSide: true
        });

        bindFilterReload(function () {
            dataTable.ajax.reload();
        });

        return dataTable;
    }

    function setTableBody(tableElement, html) {
        var body = tableElement.querySelector('tbody');
        if (body) {
            body.innerHTML = html;
        }
    }

    function renderFallbackRows(tableElement, rows) {
        if (!rows.length) {
            setTableBody(tableElement, '<tr><td colspan="12" class="text-center text-muted py-4">' + escapeHtml(t('noCompaniesFound', 'No companies found.')) + '</td></tr>');
            return;
        }

        setTableBody(tableElement, rows.map(function (row) {
            return '<tr>' +
                '<td class="fw-medium">' + renderMutedDash(row.company_nipt) + '</td>' +
                '<td>' + renderMutedDash(row.business_name) + '</td>' +
                '<td>' + renderTextBadge(row.legal_form, 'bg-primary-subtle text-primary') + '</td>' +
                '<td>' + renderTextBadge(row.subject_status, 'bg-secondary-subtle text-secondary') + '</td>' +
                '<td>' + renderMutedDash(row.city) + '</td>' +
                '<td class="text-end">' + renderMutedDash(row.registration_year) + '</td>' +
                '<td class="text-end">' + formatInteger(row.active_procurement_count) + '</td>' +
                '<td class="text-end">' + formatMoney(row.winner_value_amount) + '</td>' +
                '<td class="text-end">' + formatRatio(row.safe_winner_to_budget_ratio_avg) + '</td>' +
                '<td>' + renderQkbFlag(row.qkb_flag) + '</td>' +
                '<td>' + renderRiskIndicators(row.risk_indicators) + '</td>' +
                '<td>' + renderActions(row) + '</td>' +
            '</tr>';
        }).join(''));
    }

    function initFallbackTable(tableElement) {
        console.warn('DataTables assets are not available locally; using Albiz AJAX table fallback.');

        var state = {
            draw: 0,
            start: 0,
            length: 25,
            orderColumn: 1,
            orderDir: 'asc',
            recordsFiltered: 0
        };

        var lengthElement = document.getElementById('companies-page-length');
        var infoElement = document.getElementById('companies-table-info');
        var previousButton = document.getElementById('companies-prev-page');
        var nextButton = document.getElementById('companies-next-page');

        function buildUrl() {
            var filters = collectFilters();
            var params = new URLSearchParams();
            params.set('draw', String(state.draw));
            params.set('start', String(state.start));
            params.set('length', String(state.length));
            params.set('search[value]', filters.search);
            params.set('order[0][column]', String(state.orderColumn));
            params.set('order[0][dir]', state.orderDir);
            params.set('legal_form', filters.legal_form);
            params.set('subject_status', filters.subject_status);
            params.set('city', filters.city);
            params.set('has_red_flags', filters.has_red_flags);
            params.set('risk_indicator', filters.risk_indicator);
            params.set('min_active_procurement_count', filters.min_active_procurement_count);
            params.set('max_active_procurement_count', filters.max_active_procurement_count);
            return tableElement.dataset.ajaxUrl + '?' + params.toString();
        }

        function updateInfo(rowCount) {
            var total = state.recordsFiltered;
            var first = total === 0 ? 0 : state.start + 1;
            var last = state.start + rowCount;

            if (infoElement) {
                infoElement.textContent = t('showingRows', 'Showing {first} to {last} of {total} rows')
                    .replace('{first}', first)
                    .replace('{last}', last)
                    .replace('{total}', total);
            }
            if (previousButton) {
                previousButton.disabled = state.start <= 0;
            }
            if (nextButton) {
                nextButton.disabled = state.start + state.length >= total;
            }
        }

        function reload(resetPage) {
            if (resetPage) {
                state.start = 0;
            }

            state.draw += 1;
            setTableBody(tableElement, '<tr><td colspan="12" class="text-center text-muted py-4">' + escapeHtml(t('loadingCompanies', 'Loading companies...')) + '</td></tr>');

            fetch(buildUrl(), {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' }
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error('HTTP ' + response.status);
                    }
                    return response.json();
                })
                .then(function (payload) {
                    showError(payload.error || '');
                    state.recordsFiltered = Number(payload.recordsFiltered || 0);
                    renderFallbackRows(tableElement, payload.data || []);
                    updateInfo((payload.data || []).length);
                })
                .catch(function (error) {
                    showError(t('unableLoadCompaniesPrefix', 'Unable to load companies from the collector database:') + ' ' + error.message);
                    setTableBody(tableElement, '<tr><td colspan="12" class="text-center text-muted py-4">No companies available.</td></tr>');
                    state.recordsFiltered = 0;
                    updateInfo(0);
                });
        }

        bindFilterReload(function () {
            reload(true);
        });

        if (lengthElement) {
            lengthElement.addEventListener('change', function () {
                state.length = Number(lengthElement.value) || 25;
                reload(true);
            });
        }

        if (previousButton) {
            previousButton.addEventListener('click', function () {
                state.start = Math.max(0, state.start - state.length);
                reload(false);
            });
        }

        if (nextButton) {
            nextButton.addEventListener('click', function () {
                if (state.start + state.length < state.recordsFiltered) {
                    state.start += state.length;
                    reload(false);
                }
            });
        }

        tableElement.querySelectorAll('thead th[data-column-index]').forEach(function (header) {
            if (header.dataset.orderable === 'false') {
                return;
            }

            header.classList.add('cursor-pointer');
            header.addEventListener('click', function () {
                var columnIndex = Number(header.dataset.columnIndex);
                if (state.orderColumn === columnIndex) {
                    state.orderDir = state.orderDir === 'asc' ? 'desc' : 'asc';
                } else {
                    state.orderColumn = columnIndex;
                    state.orderDir = 'asc';
                }
                reload(true);
            });
        });

        reload(true);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var tableElement = document.getElementById('companies-table');
        if (!tableElement || !tableElement.dataset.ajaxUrl) {
            return;
        }

        if (!initDataTables(tableElement)) {
            initFallbackTable(tableElement);
        }
    });
})();
