import io
import os
import time

from django.core.management import call_command
from django.utils import timezone

from analytics.services.ml_results import (
    BENCHMARK_LOCK_FILENAME,
    BENCHMARK_REQUIRED_FILES,
    ML_OUTPUT_DIR,
)


WEB_ML_BENCHMARK_COMMANDS = ['run_ml_benchmark']


def run_ml_benchmark_from_web():
    """Run the benchmark suite from an explicit web POST request."""
    ML_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ML_OUTPUT_DIR / BENCHMARK_LOCK_FILENAME
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

        stdout = io.StringIO()
        stderr = io.StringIO()
        call_command('run_ml_benchmark', stdout=stdout, stderr=stderr)
        command_outputs.append(
            {
                'command': 'run_ml_benchmark',
                'stdout': stdout.getvalue(),
                'stderr': stderr.getvalue(),
            }
        )

        return {
            'success': True,
            'locked': False,
            'message': 'Benchmark suite was generated successfully.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': WEB_ML_BENCHMARK_COMMANDS,
            'generated_files_count': generated_benchmark_files_count(),
            'expected_output_files': BENCHMARK_REQUIRED_FILES,
            'command_outputs': command_outputs,
            'error_details': '',
        }
    except FileExistsError:
        return {
            'success': False,
            'locked': True,
            'message': 'Benchmark suite is already running. Please wait for it to finish.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': [],
            'generated_files_count': generated_benchmark_files_count(),
            'expected_output_files': BENCHMARK_REQUIRED_FILES,
            'command_outputs': [],
            'error_details': '',
        }
    except Exception as exc:
        return {
            'success': False,
            'locked': False,
            'message': 'Benchmark suite could not be generated.',
            'start_time': start_time,
            'end_time': timezone.now(),
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'commands_run': WEB_ML_BENCHMARK_COMMANDS,
            'generated_files_count': generated_benchmark_files_count(),
            'expected_output_files': BENCHMARK_REQUIRED_FILES,
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


def generated_benchmark_files_count():
    return sum(
        1
        for filename in BENCHMARK_REQUIRED_FILES
        if (ML_OUTPUT_DIR / filename).exists()
    )
