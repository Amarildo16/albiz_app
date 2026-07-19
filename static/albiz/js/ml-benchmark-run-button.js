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

    function supervisedV2Button(form) {
        return form.querySelector('[data-ml-supervised-v2-run-button]');
    }

    function supervisedV2StatusElement() {
        return byId('ml-supervised-v2-run-status');
    }

    function setSupervisedV2RunningState(form, isRunning) {
        var button = supervisedV2Button(form);
        if (button && !button.getAttribute('data-original-html')) {
            button.setAttribute('data-original-html', button.innerHTML);
        }
        if (button) {
            button.disabled = isRunning;
            button.innerHTML = isRunning
                ? '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> ' + (form.getAttribute('data-running-label') || 'Running corrected benchmark...')
                : button.getAttribute('data-original-html');
        }
    }

    function updateSupervisedV2StatusText(status) {
        var element = supervisedV2StatusElement();
        if (!element) {
            return;
        }
        var text = status && status.message ? status.message : '';
        if (status && status.error_details) {
            text += ' ' + status.error_details;
        }
        element.textContent = text || '';
    }

    function parseJsonResponse(response) {
        return response.json().catch(function () {
            return {
                state: 'failure',
                running: false,
                success: false,
                message: 'The corrected benchmark status response could not be read.'
            };
        }).then(function (payload) {
            payload.httpOk = response.ok;
            return payload;
        });
    }

    function csrfToken(form) {
        var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : '';
    }

    function showSupervisedV2Failure(form, status) {
        setSupervisedV2RunningState(form, false);
        updateSupervisedV2StatusText(status);
        var message = status && status.message ? status.message : 'Corrected benchmark failed.';
        if (status && status.error_details) {
            message += ' ' + status.error_details;
        }
        if (hasSwal()) {
            window.Swal.fire({
                title: form.getAttribute('data-error-title') || 'Corrected benchmark failed',
                text: message,
                icon: 'error',
                confirmButtonText: form.getAttribute('data-ok-button') || 'OK'
            });
        } else {
            window.alert(message);
        }
    }

    function showSupervisedV2Warning(form, status) {
        setSupervisedV2RunningState(form, false);
        updateSupervisedV2StatusText(status);
        var message = status && status.message ? status.message : 'Corrected benchmark was not started.';
        if (hasSwal()) {
            window.Swal.fire({
                title: form.getAttribute('data-warning-title') || 'Corrected benchmark not started',
                text: message,
                icon: 'warning',
                confirmButtonText: form.getAttribute('data-ok-button') || 'OK'
            });
        } else {
            window.alert(message);
        }
    }

    function showSupervisedV2Success(form, status) {
        updateSupervisedV2StatusText(status);
        var message = status && status.message ? status.message : 'Corrected benchmark completed successfully.';
        if (hasSwal()) {
            window.Swal.fire({
                title: form.getAttribute('data-success-title') || 'Corrected benchmark completed',
                text: message,
                icon: 'success',
                timer: 1200,
                showConfirmButton: false
            }).then(function () {
                window.location.reload();
            });
            return;
        }
        window.setTimeout(function () {
            window.location.reload();
        }, 900);
    }

    function pollSupervisedV2Status(form) {
        var statusUrl = form.getAttribute('data-status-url');
        if (!statusUrl) {
            showSupervisedV2Failure(form, {
                message: 'Corrected benchmark status endpoint is unavailable.'
            });
            return;
        }

        window.fetch(statusUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(parseJsonResponse).then(function (status) {
            updateSupervisedV2StatusText(status);
            if (status.running || status.state === 'running') {
                setSupervisedV2RunningState(form, true);
                window.setTimeout(function () {
                    pollSupervisedV2Status(form);
                }, 2500);
                return;
            }
            if (status.success || status.state === 'success') {
                showSupervisedV2Success(form, status);
                return;
            }
            if (status.state === 'failure') {
                showSupervisedV2Failure(form, status);
                return;
            }
            setSupervisedV2RunningState(form, false);
        }).catch(function () {
            showSupervisedV2Failure(form, {
                message: 'Corrected benchmark status could not be reached.'
            });
        });
    }

    function startSupervisedV2Run(form) {
        var startUrl = form.getAttribute('data-start-url');
        if (!startUrl) {
            showSupervisedV2Failure(form, {
                message: 'Corrected benchmark start endpoint is unavailable.'
            });
            return;
        }

        setSupervisedV2RunningState(form, true);
        updateSupervisedV2StatusText({ message: form.getAttribute('data-loading-text') || 'Running corrected benchmark.' });
        if (hasSwal()) {
            window.Swal.fire({
                title: form.getAttribute('data-loading-title') || 'Running corrected benchmark',
                text: form.getAttribute('data-loading-text') || 'Please wait while the supervised-v2 benchmark is generated.',
                allowOutsideClick: false,
                allowEscapeKey: false,
                didOpen: function () {
                    window.Swal.showLoading();
                }
            });
        }

        var headers = { 'X-Requested-With': 'XMLHttpRequest' };
        var token = csrfToken(form);
        if (token) {
            headers['X-CSRFToken'] = token;
        }

        window.fetch(startUrl, {
            method: 'POST',
            body: new window.FormData(form),
            credentials: 'same-origin',
            headers: headers
        }).then(parseJsonResponse).then(function (status) {
            updateSupervisedV2StatusText(status);
            if (status.locked && !status.running) {
                showSupervisedV2Warning(form, status);
                return;
            }
            if (!status.httpOk && !status.running && !status.locked) {
                showSupervisedV2Failure(form, status);
                return;
            }
            pollSupervisedV2Status(form);
        }).catch(function () {
            showSupervisedV2Failure(form, {
                message: 'Corrected benchmark could not be started.'
            });
        });
    }

    function bindSupervisedV2Form() {
        var form = byId('ml-supervised-v2-run-form');
        if (!form) {
            return;
        }
        var button = supervisedV2Button(form);
        if (!button) {
            return;
        }

        if (form.getAttribute('data-initial-running') === 'true') {
            setSupervisedV2RunningState(form, true);
            pollSupervisedV2Status(form);
        }

        button.addEventListener('click', function (event) {
            event.preventDefault();
            if (button.disabled) {
                return;
            }

            var title = form.getAttribute('data-confirm-title') || 'Run Corrected Benchmark?';
            var text = form.getAttribute('data-confirm-text') || 'This will run the corrected supervised benchmark using the current ML dataset. The operation may take several minutes.';

            if (!hasSwal()) {
                if (window.confirm(text)) {
                    startSupervisedV2Run(form);
                }
                return;
            }

            window.Swal.fire({
                title: title,
                text: text,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: form.getAttribute('data-confirm-button') || 'Run Benchmark',
                cancelButtonText: form.getAttribute('data-cancel-button') || 'Cancel',
                reverseButtons: true
            }).then(function (result) {
                if (result.isConfirmed) {
                    startSupervisedV2Run(form);
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        showPageMessage();
        bindBenchmarkForm();
        bindSupervisedV2Form();
    });
})();
