import io
import os
import time

from django.core.management import call_command
from django.utils import timezone

from analytics.services.ml_results import ML_OUTPUT_DIR, ML_OUTPUT_FILES


ML_RUN_LOCK_NAME = '.ml_run.lock'
WEB_ML_COMMANDS = ['build_ml_dataset', 'run_ml_analysis']


def run_ml_pipeline_from_web():
    """Run the local ML export pipeline from an explicit web POST request."""
    ML_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ML_OUTPUT_DIR / ML_RUN_LOCK_NAME
    start_time = timezone.now()
    started_at = time.perf_counter()
    lock_acquired = False
    lock_fd = None
    command_outputs = []

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        lock_acquired = True
        with os.fdopen(lock_fd, 'w', encoding='utf-8') as lock_file:
            lock_fd = None
            lock_file.write(f'started_at={start_time.isoformat()}\n')
            lock_file.write(f'pid={os.getpid()}\n')

        for command_name in WEB_ML_COMMANDS:
            stdout = io.StringIO()
            stderr = io.StringIO()
            call_command(command_name, stdout=stdout, stderr=stderr)
            command_outputs.append(
                {
                    'command': command_name,
                    'stdout': stdout.getvalue(),
                    'stderr': stderr.getvalue(),
                }
            )

        duration_seconds = round(time.perf_counter() - started_at, 2)
        return {
            'success': True,
            'locked': False,
            'message': 'ML results were generated successfully.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': duration_seconds,
            'commands_run': WEB_ML_COMMANDS,
            'generated_files_count': generated_files_count(),
            'command_outputs': command_outputs,
            'error_details': '',
        }
    except FileExistsError:
        return {
            'success': False,
            'locked': True,
            'message': 'ML analysis is already running. Please wait for it to finish.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': [],
            'generated_files_count': generated_files_count(),
            'command_outputs': [],
            'error_details': '',
        }
    except Exception as exc:
        return {
            'success': False,
            'locked': False,
            'message': 'ML results could not be generated.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': WEB_ML_COMMANDS,
            'generated_files_count': generated_files_count(),
            'command_outputs': command_outputs,
            'error_details': f'{exc.__class__.__name__}: {exc}',
        }
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def generated_files_count():
    return sum(
        1
        for filename in ML_OUTPUT_FILES
        if (ML_OUTPUT_DIR / filename).exists()
    )
