(function () {
    'use strict';

    var modalIds = {
        sm: 'main_modal_sm',
        md: 'main_modal_md',
        default: 'main_modal',
        lg: 'main_modal_lg',
        xl: 'main_modal_xl',
        fs: 'main_modal_fs'
    };

    function normalizeSize(size) {
        if (!size) {
            return 'default';
        }

        var normalized = String(size).toLowerCase();
        if (normalized === 'full' || normalized === 'fullscreen') {
            return 'fs';
        }

        return modalIds[normalized] ? normalized : 'default';
    }

    function getModal(size) {
        return document.getElementById(modalIds[normalizeSize(size)]);
    }

    function getBootstrapModal(modal, options) {
        if (!modal || !window.bootstrap || !window.bootstrap.Modal) {
            return null;
        }

        return window.bootstrap.Modal.getOrCreateInstance(modal, options || {});
    }

    function setHtml(element, html) {
        if (element) {
            element.innerHTML = html || '';
        }
    }

    function setAlert(modal, type, html) {
        var alert = modal.querySelector('[data-albiz-alert="' + type + '"]');
        if (!alert) {
            return;
        }

        setHtml(alert, html);
        alert.classList.toggle('d-none', !html);
    }

    function restoreSubmitButtons(modal) {
        modal.querySelectorAll('[data-albiz-original-html], [data-albiz-original-value]').forEach(function (button) {
            if (button.dataset.albizOriginalHtml !== undefined) {
                button.innerHTML = button.dataset.albizOriginalHtml;
                delete button.dataset.albizOriginalHtml;
            }

            if (button.dataset.albizOriginalValue !== undefined) {
                button.value = button.dataset.albizOriginalValue;
                delete button.dataset.albizOriginalValue;
            }

            button.disabled = false;
        });

        modal.querySelectorAll('form.ajax-submit.is-submitting').forEach(function (form) {
            form.classList.remove('is-submitting');
        });
    }

    function resetModal(modal) {
        if (!modal) {
            return;
        }

        restoreSubmitButtons(modal);
        setHtml(modal.querySelector('[data-albiz-modal-title]'), '');
        setHtml(modal.querySelector('[data-albiz-modal-body]'), '');
        setAlert(modal, 'danger', '');
        setAlert(modal, 'info', '');
    }

    function setModalContent(modal, options) {
        setHtml(modal.querySelector('[data-albiz-modal-title]'), options.title || '');
        setHtml(modal.querySelector('[data-albiz-modal-body]'), options.body || '');
        setAlert(modal, 'danger', options.danger || '');
        setAlert(modal, 'info', options.info || options.primary || '');
    }

    function open(sizeOrOptions, maybeOptions) {
        var options = typeof sizeOrOptions === 'object' && sizeOrOptions !== null
            ? sizeOrOptions
            : Object.assign({}, maybeOptions || {}, { size: sizeOrOptions });
        var modal = getModal(options.size);
        var instance = getBootstrapModal(modal, options.bootstrapOptions);

        if (!modal || !instance) {
            return null;
        }

        resetModal(modal);
        setModalContent(modal, options);
        instance.show();
        return instance;
    }

    function close(size) {
        var modal = getModal(size);
        var instance = getBootstrapModal(modal);

        if (instance) {
            instance.hide();
        }
    }

    function showButtonLoading(button) {
        button.disabled = true;

        if (button.tagName === 'INPUT') {
            button.dataset.albizOriginalValue = button.value;
            button.value = 'Submitting...';
            return;
        }

        button.dataset.albizOriginalHtml = button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Submitting...';
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.classList.contains('ajax-submit')) {
            return;
        }

        var modal = form.closest('.modal');
        if (!modal) {
            return;
        }

        if (form.classList.contains('is-submitting')) {
            event.preventDefault();
            return;
        }

        form.classList.add('is-submitting');
        var submitter = event.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
        if (submitter) {
            showButtonLoading(submitter);
        }
    });

    document.addEventListener('hidden.bs.modal', function (event) {
        if (event.target && event.target.classList.contains('albiz-modal')) {
            resetModal(event.target);
        }
    });

    window.AlbizModal = {
        open: open,
        close: close,
        reset: function (size) {
            resetModal(getModal(size));
        },
        get: getModal
    };
})();
