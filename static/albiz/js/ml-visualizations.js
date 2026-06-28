(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    function readChartData() {
        var element = byId('ml-chart-data');
        if (!element) {
            return {};
        }
        try {
            return JSON.parse(element.textContent || '{}');
        } catch (error) {
            console.error('Unable to parse ML chart data.', error);
            return {};
        }
    }

    function hasApexCharts() {
        return typeof window.ApexCharts !== 'undefined';
    }

    function renderApexChart(containerId, options) {
        var container = byId(containerId);
        if (!container || !hasApexCharts()) {
            return null;
        }
        var chart = new window.ApexCharts(container, options);
        chart.render();
        return chart;
    }

    function numberValue(value, fallback) {
        if (value === null || value === '' || typeof value === 'undefined') {
            return fallback;
        }
        var parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function groupedByCluster(rows) {
        return rows.reduce(function (groups, row) {
            var cluster = row.cluster_id === '' || row.cluster_id === null || typeof row.cluster_id === 'undefined'
                ? 'Unknown'
                : String(row.cluster_id);
            if (!groups[cluster]) {
                groups[cluster] = [];
            }
            groups[cluster].push(row);
            return groups;
        }, {});
    }

    function groupedForCube(rows) {
        var hasCluster = rows.some(function (row) {
            return row.cluster_id !== '' && row.cluster_id !== null && typeof row.cluster_id !== 'undefined';
        });
        return rows.reduce(function (groups, row) {
            var groupName;
            if (hasCluster) {
                groupName = row.cluster_id === '' || row.cluster_id === null || typeof row.cluster_id === 'undefined'
                    ? 'Cluster unknown'
                    : 'Cluster ' + String(row.cluster_id);
            } else {
                groupName = row.strict_weak_risk_label === '' || row.strict_weak_risk_label === null || typeof row.strict_weak_risk_label === 'undefined'
                    ? 'Strict label unknown'
                    : 'Strict label ' + String(row.strict_weak_risk_label);
            }
            if (!groups[groupName]) {
                groups[groupName] = [];
            }
            groups[groupName].push(row);
            return groups;
        }, {});
    }

    function pointName(row) {
        return [
            row.company_nipt || 'N/A',
            row.business_name || 'N/A',
            'Cluster: ' + (row.cluster_id || 'N/A'),
            'Performance: ' + formatNumber(row.performance_score, 4),
            'Isolation score: ' + formatNumber(row.anomaly_score, 4),
            'LOF score: ' + formatNumber(row.lof_score, 4)
        ].join('<br>');
    }

    function cubePointName(row) {
        return [
            row.company_nipt || 'N/A',
            row.business_name || 'N/A',
            'Active procurement count: ' + formatCount(row.active_procurement_count),
            'Active winner value: ' + formatMoney(row.active_total_winner_value_amount),
            'Performance score: ' + formatNumber(row.performance_score, 4),
            'Isolation score: ' + formatNumber(row.anomaly_score, 4),
            'LOF score: ' + formatNumber(row.lof_score, 4),
            'Cluster: ' + (row.cluster_id || 'N/A'),
            'Strict weak label: ' + (row.strict_weak_risk_label || 'N/A')
        ].join('<br>');
    }

    function formatNumber(value, places) {
        if (value === null || value === '' || typeof value === 'undefined') {
            return 'N/A';
        }
        var parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 'N/A';
        }
        return parsed.toFixed(places);
    }

    function formatCount(value) {
        var parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 'N/A';
        }
        return Math.round(parsed).toLocaleString();
    }

    function formatMoney(value) {
        var parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 'N/A';
        }
        return parsed.toLocaleString(undefined, {
            maximumFractionDigits: 0
        });
    }

    function markerSizeFromPerformance(value) {
        var parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 4;
        }
        return Math.max(3, Math.min(11, 3 + parsed / 14));
    }

    function renderModelComparison(data) {
        if (!data || !Array.isArray(data.models) || !data.models.length) {
            return;
        }
        renderApexChart('ml-model-comparison-chart', {
            chart: {
                type: 'bar',
                height: 320,
                toolbar: { show: false }
            },
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '45%'
                }
            },
            dataLabels: { enabled: false },
            series: [
                { name: 'F1', data: data.f1 || [] },
                { name: 'ROC AUC', data: data.roc_auc || [] }
            ],
            xaxis: {
                categories: data.models,
                labels: { rotate: -25, trim: true }
            },
            yaxis: {
                min: 0,
                max: 1,
                labels: {
                    formatter: function (value) {
                        return value.toFixed(2);
                    }
                }
            },
            colors: ['#405189', '#0ab39c'],
            legend: { position: 'top' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatNumber(value, 4);
                    }
                }
            }
        });
    }

    function renderFullModelComparison(data) {
        if (!data || !Array.isArray(data.models) || !data.models.length) {
            return;
        }
        renderApexChart('ml-full-model-comparison-chart', {
            chart: {
                type: 'bar',
                height: 320,
                toolbar: { show: false }
            },
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '45%'
                }
            },
            dataLabels: { enabled: false },
            series: [
                { name: 'F1', data: data.f1 || [] },
                { name: 'ROC AUC', data: data.roc_auc || [] }
            ],
            xaxis: {
                categories: data.models,
                labels: { rotate: -25, trim: true }
            },
            yaxis: {
                min: 0,
                max: 1,
                labels: {
                    formatter: function (value) {
                        return value.toFixed(2);
                    }
                }
            },
            colors: ['#f7b84b', '#f06548'],
            legend: { position: 'top' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatNumber(value, 4);
                    }
                }
            }
        });
    }

    function renderPcaVariance(data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length) {
            return;
        }
        renderApexChart('ml-pca-variance-chart', {
            chart: {
                type: 'bar',
                height: 280,
                toolbar: { show: false }
            },
            series: [{
                name: 'Explained variance',
                data: data.values || []
            }],
            xaxis: { categories: data.labels },
            yaxis: {
                min: 0,
                labels: {
                    formatter: function (value) {
                        return (value * 100).toFixed(1) + '%';
                    }
                }
            },
            colors: ['#299cdb'],
            dataLabels: {
                enabled: true,
                formatter: function (value) {
                    return (value * 100).toFixed(1) + '%';
                }
            },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return (value * 100).toFixed(2) + '%';
                    }
                }
            }
        });
    }

    function renderPca2d(rows) {
        if (!Array.isArray(rows) || !rows.length) {
            return;
        }
        var groups = groupedByCluster(rows);
        var series = Object.keys(groups).sort().map(function (cluster) {
            return {
                name: 'Cluster ' + cluster,
                data: groups[cluster].map(function (row) {
                    return {
                        x: numberValue(row.pc1, 0),
                        y: numberValue(row.pc2, 0),
                        meta: row
                    };
                })
            };
        });

        renderApexChart('ml-pca-2d-chart', {
            chart: {
                type: 'scatter',
                height: 420,
                zoom: { enabled: true, type: 'xy' },
                toolbar: { show: true }
            },
            series: series,
            xaxis: {
                title: { text: 'PC1' },
                tickAmount: 8,
                labels: {
                    formatter: function (value) {
                        return formatNumber(value, 2);
                    }
                }
            },
            yaxis: {
                title: { text: 'PC2' },
                tickAmount: 8,
                labels: {
                    formatter: function (value) {
                        return formatNumber(value, 2);
                    }
                }
            },
            legend: { position: 'top' },
            markers: {
                size: 4,
                strokeWidth: 0,
                opacity: 0.75
            },
            tooltip: {
                custom: function (context) {
                    var row = context.w.config.series[context.seriesIndex].data[context.dataPointIndex].meta;
                    return '<div class="p-2 small">' + pointName(row) + '</div>';
                }
            }
        });
    }

    function renderPca3d(rows) {
        var container = byId('ml-pca-3d-chart');
        var warning = byId('ml-pca-3d-warning');
        if (!container || !Array.isArray(rows) || !rows.length) {
            return;
        }
        if (typeof window.Plotly === 'undefined') {
            if (warning) {
                warning.classList.remove('d-none');
            }
            return;
        }

        var groups = groupedByCluster(rows);
        var traces = Object.keys(groups).sort().map(function (cluster) {
            var groupRows = groups[cluster];
            return {
                type: 'scatter3d',
                mode: 'markers',
                name: 'Cluster ' + cluster,
                x: groupRows.map(function (row) { return numberValue(row.pc1, 0); }),
                y: groupRows.map(function (row) { return numberValue(row.pc2, 0); }),
                z: groupRows.map(function (row) { return numberValue(row.pc3, 0); }),
                text: groupRows.map(pointName),
                hovertemplate: '%{text}<extra></extra>',
                marker: {
                    size: 3,
                    opacity: 0.72
                }
            };
        });

        window.Plotly.newPlot(container, traces, {
            margin: { l: 0, r: 0, b: 0, t: 0 },
            height: 520,
            legend: { orientation: 'h' },
            scene: {
                xaxis: { title: 'PC1' },
                yaxis: { title: 'PC2' },
                zaxis: { title: 'PC3' },
                camera: {
                    eye: { x: 1.45, y: 1.45, z: 1.1 }
                }
            }
        }, {
            responsive: true,
            displaylogo: false,
            scrollZoom: true
        });
    }

    function renderProcurementAnomalyCube(rows) {
        var container = byId('ml-procurement-anomaly-cube-chart');
        var warning = byId('ml-procurement-anomaly-cube-warning');
        if (!container) {
            return;
        }
        if (!Array.isArray(rows) || !rows.length) {
            if (warning) {
                warning.classList.remove('d-none');
            }
            return;
        }
        if (typeof window.Plotly === 'undefined') {
            if (warning) {
                warning.classList.remove('d-none');
            }
            return;
        }

        var groups = groupedForCube(rows);
        var traces = Object.keys(groups).sort().map(function (groupName) {
            var groupRows = groups[groupName];
            return {
                type: 'scatter3d',
                mode: 'markers',
                name: groupName,
                x: groupRows.map(function (row) { return numberValue(row.log_procurement_count, 0); }),
                y: groupRows.map(function (row) { return numberValue(row.log_winner_value, 0); }),
                z: groupRows.map(function (row) { return numberValue(row.anomaly_score, 0); }),
                text: groupRows.map(cubePointName),
                hovertemplate: '%{text}<extra></extra>',
                marker: {
                    size: groupRows.map(function (row) {
                        return markerSizeFromPerformance(row.performance_score);
                    }),
                    opacity: 0.78
                }
            };
        });

        window.Plotly.newPlot(container, traces, {
            margin: { l: 0, r: 0, b: 0, t: 0 },
            height: 540,
            legend: { orientation: 'h' },
            scene: {
                xaxis: { title: 'log(1 + Active Procurement Count)' },
                yaxis: { title: 'log(1 + Active Winner Value)' },
                zaxis: { title: 'Isolation Forest Anomaly Score' },
                camera: {
                    eye: { x: 1.55, y: 1.45, z: 1.1 }
                }
            }
        }, {
            responsive: true,
            displaylogo: false,
            scrollZoom: true
        });
    }

    function renderClusterDistribution(data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length) {
            return;
        }
        renderApexChart('ml-cluster-distribution-chart', {
            chart: {
                type: 'donut',
                height: 320
            },
            labels: data.labels,
            series: data.counts || [],
            legend: { position: 'bottom' },
            dataLabels: {
                formatter: function (value) {
                    return value.toFixed(1) + '%';
                }
            }
        });
    }

    function renderFeatureImportance(data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length) {
            return;
        }
        renderApexChart('ml-feature-importance-chart', {
            chart: {
                type: 'bar',
                height: 420,
                toolbar: { show: false }
            },
            plotOptions: {
                bar: { horizontal: true }
            },
            series: [{
                name: 'Importance',
                data: data.values || []
            }],
            xaxis: {
                labels: {
                    formatter: function (value) {
                        return formatNumber(value, 2);
                    }
                }
            },
            yaxis: { labels: { maxWidth: 260 } },
            colors: ['#f7b84b'],
            dataLabels: { enabled: false },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatNumber(value, 6);
                    }
                }
            }
        });
    }

    function renderFinancialComparison(data) {
        if (!data || !Array.isArray(data.models) || !data.models.length) {
            return;
        }
        renderApexChart('ml-financial-comparison-chart', {
            chart: {
                type: 'bar',
                height: 360,
                toolbar: { show: false }
            },
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '52%'
                }
            },
            dataLabels: { enabled: false },
            series: [
                { name: 'Procurement-only F1', data: data.baselineF1 || [] },
                { name: 'Procurement + financial F1', data: data.enrichedF1 || [] },
                { name: 'Procurement-only ROC AUC', data: data.baselineRocAuc || [] },
                { name: 'Procurement + financial ROC AUC', data: data.enrichedRocAuc || [] }
            ],
            xaxis: {
                categories: data.models,
                labels: { rotate: -25, trim: true }
            },
            yaxis: {
                min: 0,
                max: 1,
                labels: {
                    formatter: function (value) {
                        return value.toFixed(2);
                    }
                }
            },
            colors: ['#405189', '#0ab39c', '#f7b84b', '#299cdb'],
            legend: { position: 'top' },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatNumber(value, 4);
                    }
                }
            }
        });
    }

    function renderFinancialCoverage(data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length) {
            return;
        }
        renderApexChart('ml-financial-coverage-chart', {
            chart: {
                type: 'donut',
                height: 300,
                toolbar: { show: false }
            },
            labels: data.labels || [],
            series: data.series || [],
            colors: ['#0ab39c', '#6c757d'],
            legend: { position: 'bottom' },
            dataLabels: { enabled: false },
            tooltip: {
                y: {
                    formatter: formatCount
                }
            }
        });
    }

    function renderFinancialFeatureImportance(data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length) {
            return;
        }
        renderApexChart('ml-financial-feature-importance-chart', {
            chart: {
                type: 'bar',
                height: 420,
                toolbar: { show: false }
            },
            plotOptions: {
                bar: { horizontal: true }
            },
            series: [{
                name: 'Importance',
                data: data.values || []
            }],
            xaxis: {
                labels: {
                    formatter: function (value) {
                        return formatNumber(value, 2);
                    }
                }
            },
            yaxis: { labels: { maxWidth: 280 } },
            colors: ['#0ab39c'],
            dataLabels: { enabled: false },
            tooltip: {
                y: {
                    formatter: function (value) {
                        return formatNumber(value, 6);
                    }
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var data = readChartData();
        renderFullModelComparison(data.fullModelComparison);
        renderModelComparison(data.modelComparison);
        renderPcaVariance(data.pcaVariance);
        renderPca2d(data.pca2d);
        renderPca3d(data.pca3d);
        renderProcurementAnomalyCube(data.procurementAnomalyCube);
        renderClusterDistribution(data.clusterDistribution);
        renderFeatureImportance(data.featureImportance);
        renderFinancialComparison(data.financialComparison);
        renderFinancialCoverage(data.financialCoverage);
        renderFinancialFeatureImportance(data.financialFeatureImportance);
    });
})();
