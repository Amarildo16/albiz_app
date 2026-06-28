(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    function readJsonScript(id) {
        var element = byId(id);
        if (!element) {
            return [];
        }
        try {
            return JSON.parse(element.textContent || '[]');
        } catch (error) {
            console.error('Unable to parse ML benchmark page messages.', error);
            return [];
        }
    }

    function hasSwal() {
        return typeof window.Swal !== 'undefined';
    }

    function messageIcon(level) {
        if ((level || '').indexOf('error') !== -1) {
            return 'error';
        }
        if ((level || '').indexOf('warning') !== -1) {
            return 'warning';
        }
        if ((level || '').indexOf('success') !== -1) {
            return 'success';
        }
        return 'info';
    }

    function messageTitle(icon) {
        var form = byId('ml-benchmark-run-form');
        if (form) {
            if (icon === 'success') {
                return form.getAttribute('data-success-title') || 'Benchmark suite refreshed';
            }
            if (icon === 'error') {
                return form.getAttribute('data-error-title') || 'Benchmark run failed';
            }
            if (icon === 'warning') {
                return form.getAttribute('data-warning-title') || 'Benchmark run not started';
            }
            return form.getAttribute('data-info-title') || 'Benchmark suite';
        }
        if (icon === 'success') {
            return 'Benchmark suite refreshed';
        }
        if (icon === 'error') {
            return 'Benchmark run failed';
        }
        if (icon === 'warning') {
            return 'Benchmark run not started';
        }
        return 'Benchmark suite';
    }

    function showPageMessage() {
        if (!hasSwal()) {
            return;
        }
        var messages = readJsonScript('ml-page-messages');
        if (!Array.isArray(messages) || !messages.length) {
            return;
        }
        var message = messages[0];
        var icon = messageIcon(message.level);
        window.Swal.fire({
            title: messageTitle(icon),
            text: message.text || '',
            icon: icon,
            confirmButtonText: (byId('ml-benchmark-run-form') || {}).getAttribute ? (byId('ml-benchmark-run-form').getAttribute('data-ok-button') || 'OK') : 'OK'
        });
    }

    function setRunningState(form) {
        var button = form.querySelector('[data-ml-benchmark-run-button]');
        if (!button) {
            return;
        }
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> ' + (form.getAttribute('data-running-label') || 'Running benchmark suite...');
    }

    function submitWithLoading(form) {
        setRunningState(form);
        if (hasSwal()) {
            window.Swal.fire({
                title: form.getAttribute('data-loading-title') || 'Running benchmark suite',
                text: form.getAttribute('data-loading-text') || 'Please wait while repeated cross-validation benchmarks are generated.',
                allowOutsideClick: false,
                allowEscapeKey: false,
                didOpen: function () {
                    window.Swal.showLoading();
                }
            });
        }
        window.HTMLFormElement.prototype.submit.call(form);
    }

    function bindBenchmarkForm() {
        var form = byId('ml-benchmark-run-form');
        if (!form) {
            return;
        }

        form.addEventListener('submit', function (event) {
            event.preventDefault();

            var title = form.getAttribute('data-confirm-title') || 'Run benchmark suite?';
            var text = form.getAttribute('data-confirm-text') || 'This will run repeated cross-validation benchmarks and may take several minutes. Existing benchmark outputs will be refreshed.';

            if (!hasSwal()) {
                if (window.confirm(text)) {
                    submitWithLoading(form);
                }
                return;
            }

            window.Swal.fire({
                title: title,
                text: text,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: form.getAttribute('data-confirm-button') || 'Yes, run benchmark',
                cancelButtonText: form.getAttribute('data-cancel-button') || 'Cancel',
                reverseButtons: true
            }).then(function (result) {
                if (result.isConfirmed) {
                    submitWithLoading(form);
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        showPageMessage();
        bindBenchmarkForm();
    });
})();
