# Copyright 2016-2019 Dirk Thomas
# Licensed under the Apache License, Version 2.0

import argparse
import os

from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.verb import VerbExtensionPoint
from colcon_test_result.test_result import get_test_results
from colcon_test_result.test_result import Result

logger = colcon_logger.getChild(__name__)


class TestResultVerb(VerbExtensionPoint):
    """Show the test results generated when testing a set of packages."""

    __test__ = False  # prevent the class to falsely be identified as a test

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(VerbExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    def add_arguments(self, *, parser):  # noqa: D102
        parser.add_argument(
            '--test-result-base',
            type=_argparse_existing_dir,
            default='build',
            help='The base path for all test results (default: build)')
        parser.add_argument(
            '--all',
            action='store_true',
            help='Show all test result file (even without errors / failures)')
        parser.add_argument(
            '--result-files-only',
            action='store_true',
            help='Print only the path to the result files. '
                 'Use with --all to get files without errors / failures')
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show additional information for errors / failures')

    def main(self, *, context):  # noqa: D102
        all_results = list(get_test_results(
            context.args.test_result_base,
            collect_details=context.args.verbose))

        results = [
            r for r in all_results
            if r.error_count or r.failure_count or context.args.all]
        results.sort(key=lambda r: r.path)

        if context.args.result_files_only:
            for result in results:
                print(result.path)
        else:
            for result in results:
                print(result)
                if context.args.verbose:
                    for detail in result.details:
                        for i, line in enumerate(detail.splitlines()):
                            print('-' if i == 0 else ' ', line)

        summary = Result('Summary')
        for result in all_results:
            summary.add_result(result)

        if not context.args.result_files_only:
            if results:
                print()
            print(summary)

        return 1 if summary.error_count or summary.failure_count else 0


def _argparse_existing_dir(path):
    if not os.path.exists(path):
        raise argparse.ArgumentTypeError("Path '%s' does not exist" % path)
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError("Path '%s' is not a directory" % path)
    return path
