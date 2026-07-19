import io
import json
import os
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from analytics.services.ml_results import (
    BENCHMARK_LOCK_FILENAME,
    ML_OUTPUT_DIR,
    ML_SUPERVISED_V2_OUTPUT_DIR,
    SUPERVISED_V2_RUN_LOCK_FILENAME,
    SUPERVISED_V2_RUN_STATUS_FILENAME,
)


WEB_ML_SUPERVISED_V2_COMMANDS = ['run_ml_supervised_v2']
ML_ANALYSIS_LOCK_FILENAME = '.ml_run.lock'


def start_ml_supervised_v2_from_web():
    """Start the corrected supervised-v2 benchmark from an explicit web POST."""
    if conflicting_legacy_ml_lock_exists():
        return public_status(
            {
                'state': 'locked',
                'running': False,
                'success': False,
                'locked': True,
                'message': 'Another ML run is already running. Please wait for it to finish.',
                'start_time': '',
                'end_time': '',
                'duration_seconds': 0,
                'commands_run': [],
                'generated_files_count': generated_supervised_v2_files_count(),
                'command_outputs': [],
                'error_details': '',
            }
        )

    ML_SUPERVISED_V2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ML_SUPERVISED_V2_OUTPUT_DIR / SUPERVISED_V2_RUN_LOCK_FILENAME
    status_path = ML_SUPERVISED_V2_OUTPUT_DIR / SUPERVISED_V2_RUN_STATUS_FILENAME
    start_time = timezone.now()
    started_at = time.perf_counter()
    lock_fd = None

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(lock_fd, 'w', encoding='utf-8') as lock_file:
            lock_fd = None
            lock_file.write(f'started_at={start_time.isoformat()}\n')
            lock_file.write(f'pid={os.getpid()}\n')

        running_status = {
            'state': 'running',
            'running': True,
            'success': False,
            'locked': False,
            'message': 'Corrected supervised benchmark is running.',
            'start_time': start_time.isoformat(),
            'end_time': '',
            'duration_seconds': 0,
            'commands_run': WEB_ML_SUPERVISED_V2_COMMANDS,
            'generated_files_count': generated_supervised_v2_files_count(),
            'command_outputs': [],
            'error_details': '',
        }
        write_status(status_path, running_status)

        thread = threading.Thread(
            target=run_ml_supervised_v2_worker,
            args=(lock_path, status_path, start_time, started_at),
            name='ml-supervised-v2-web-runner',
            daemon=True,
        )
        thread.start()
        return public_status(running_status)
    except FileExistsError:
        status = get_ml_supervised_v2_status()
        status.update(
            {
                'locked': True,
                'running': True,
                'state': 'running',
                'success': False,
                'message': 'Corrected supervised benchmark is already running.',
            }
        )
        return public_status(status)
    except Exception as exc:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        failed = {
            'state': 'failure',
            'running': False,
            'success': False,
            'locked': False,
            'message': 'Corrected supervised benchmark could not be started.',
            'start_time': start_time.isoformat(),
            'end_time': timezone.now().isoformat(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': WEB_ML_SUPERVISED_V2_COMMANDS,
            'generated_files_count': generated_supervised_v2_files_count(),
            'command_outputs': [],
            'error_details': clean_text(f'{exc.__class__.__name__}: {exc}'),
        }
        write_status(status_path, failed)
        return public_status(failed)


def run_ml_supervised_v2_worker(lock_path, status_path, start_time, started_at):
    command_outputs = []
    try:
        stdout = io.StringIO()
        stderr = io.StringIO()
        call_command(
            'run_ml_supervised_v2',
            input_dir=str(ML_OUTPUT_DIR),
            output_dir=str(ML_SUPERVISED_V2_OUTPUT_DIR),
            stdout=stdout,
            stderr=stderr,
        )
        command_outputs.append(
            {
                'command': 'run_ml_supervised_v2',
                'stdout': clean_text(stdout.getvalue()),
                'stderr': clean_text(stderr.getvalue()),
            }
        )
        write_status(
            status_path,
            {
                'state': 'success',
                'running': False,
                'success': True,
                'locked': False,
                'message': 'Corrected supervised benchmark completed successfully.',
                'start_time': start_time.isoformat(),
                'end_time': timezone.now().isoformat(),
                'duration_seconds': round(time.perf_counter() - started_at, 2),
                'commands_run': WEB_ML_SUPERVISED_V2_COMMANDS,
                'generated_files_count': generated_supervised_v2_files_count(),
                'command_outputs': command_outputs,
                'error_details': '',
            },
        )
    except Exception as exc:
        write_status(
            status_path,
            {
                'state': 'failure',
                'running': False,
                'success': False,
                'locked': False,
                'message': 'Corrected supervised benchmark failed.',
                'start_time': start_time.isoformat(),
                'end_time': timezone.now().isoformat(),
                'duration_seconds': round(time.perf_counter() - started_at, 2),
                'commands_run': WEB_ML_SUPERVISED_V2_COMMANDS,
                'generated_files_count': generated_supervised_v2_files_count(),
                'command_outputs': command_outputs,
                'error_details': clean_text(f'{exc.__class__.__name__}: {exc}'),
            },
        )
    finally:
        try:
            Path(lock_path).unlink()
        except FileNotFoundError:
            pass


def get_ml_supervised_v2_status():
    status_path = ML_SUPERVISED_V2_OUTPUT_DIR / SUPERVISED_V2_RUN_STATUS_FILENAME
    lock_path = ML_SUPERVISED_V2_OUTPUT_DIR / SUPERVISED_V2_RUN_LOCK_FILENAME
    status = {}
    if status_path.exists() and status_path.is_file():
        try:
            status = json.loads(status_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            status = {
                'state': 'failure',
                'success': False,
                'message': 'Corrected supervised benchmark status could not be read.',
                'error_details': '',
            }

    if lock_path.exists():
        status.update(
            {
                'state': 'running',
                'running': True,
                'success': False,
                'locked': False,
            }
        )
        status.setdefault('message', 'Corrected supervised benchmark is running.')
    elif not status:
        status = {
            'state': 'idle',
            'running': False,
            'success': False,
            'locked': False,
            'message': 'Corrected supervised benchmark has not been run yet.',
            'start_time': '',
            'end_time': '',
            'duration_seconds': 0,
            'commands_run': [],
            'generated_files_count': generated_supervised_v2_files_count(),
            'command_outputs': [],
            'error_details': '',
        }
    else:
        status['running'] = False
        status.setdefault('locked', False)
        status['generated_files_count'] = generated_supervised_v2_files_count()

    return public_status(status)


def write_status(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f'.{path.name}.tmp')
    temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temporary_path, path)


def generated_supervised_v2_files_count():
    try:
        from analytics.services.ml_supervised_v2 import OUTPUT_FILENAMES
    except Exception:
        return 0
    return sum(
        1
        for filename in OUTPUT_FILENAMES
        if (ML_SUPERVISED_V2_OUTPUT_DIR / filename).exists()
    )


def conflicting_legacy_ml_lock_exists():
    return any(
        (ML_OUTPUT_DIR / filename).exists()
        for filename in (ML_ANALYSIS_LOCK_FILENAME, BENCHMARK_LOCK_FILENAME)
    )


def public_status(status):
    command_outputs = []
    for item in status.get('command_outputs', []):
        command_outputs.append(
            {
                'command': item.get('command', ''),
                'stdout': clean_text(item.get('stdout', '')),
                'stderr': clean_text(item.get('stderr', '')),
            }
        )

    return {
        'state': status.get('state', 'idle'),
        'running': bool(status.get('running')),
        'success': bool(status.get('success')),
        'locked': bool(status.get('locked')),
        'message': clean_text(status.get('message', '')),
        'start_time': status.get('start_time', ''),
        'end_time': status.get('end_time', ''),
        'duration_seconds': status.get('duration_seconds', 0),
        'commands_run': list(status.get('commands_run', [])),
        'generated_files_count': status.get('generated_files_count', 0),
        'command_outputs': command_outputs,
        'error_details': clean_text(status.get('error_details', '')),
    }


def clean_text(value, limit=4000):
    text = str(value or '')
    replacements = {
        str(settings.BASE_DIR): '<BASE_DIR>',
        str(ML_OUTPUT_DIR): '<ML_OUTPUT_DIR>',
        str(ML_SUPERVISED_V2_OUTPUT_DIR): '<ML_SUPERVISED_V2_OUTPUT_DIR>',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text[:limit]
