import argparse
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.services.ml_supervised_v2 import (
    MAX_RANDOM_STATE,
    SupervisedV2Error,
    run_supervised_v2,
)


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def random_state_integer(value: str) -> int:
    parsed = non_negative_integer(value)
    if parsed > MAX_RANDOM_STATE:
        raise argparse.ArgumentTypeError(f"must not exceed {MAX_RANDOM_STATE}")
    return parsed


def fold_count(value: str) -> int:
    parsed = positive_integer(value)
    if parsed < 2:
        raise argparse.ArgumentTypeError("must be an integer of at least 2")
    return parsed


class Command(BaseCommand):
    help = "Run the additive corrected supervised-v2 methodology into an explicit directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input-dir",
            required=True,
            help="Directory containing frozen-v1 ml_dataset.csv and feature metadata.",
        )
        parser.add_argument(
            "--output-dir",
            required=True,
            help="Dedicated directory for the additive v2 artifact family.",
        )
        parser.add_argument("--random-state", type=random_state_integer, default=42)
        parser.add_argument("--n-splits", type=fold_count, default=5)
        parser.add_argument("--n-repeats", type=positive_integer, default=3)
        parser.add_argument(
            "--shuffle-permutations", type=positive_integer, default=10
        )

    def handle(self, *args, **options):
        try:
            result = run_supervised_v2(
                Path(options["input_dir"]),
                Path(options["output_dir"]),
                random_state=options["random_state"],
                n_splits=options["n_splits"],
                n_repeats=options["n_repeats"],
                shuffle_permutations=options["shuffle_permutations"],
            )
        except SupervisedV2Error as exc:
            raise CommandError(f"Supervised-v2 analysis failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {len(result.output_filenames)} supervised-v2 artifacts "
                f"for {result.dataset_row_count} rows."
            )
        )
        self.stdout.write(
            "Configuration: "
            f"random_state={result.random_state}, n_splits={result.n_splits}, "
            f"n_repeats={result.n_repeats}, "
            f"shuffle_permutations={result.shuffle_permutations}"
        )
        self.stdout.write(f"Strict split plan: {result.strict_split_plan_sha256}")
        for filename in result.output_filenames:
            self.stdout.write(f"- {filename}")
