# Copyright 2016-2018 Dirk Thomas
# Licensed under the Apache License, Version 2.0

import argparse
import os
import traceback
from xml.etree.ElementTree import ElementTree
from xml.etree.ElementTree import ParseError

from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.verb import VerbExtensionPoint

logger = colcon_logger.getChild(__name__)


class TestResultVerb(VerbExtensionPoint):
    """
    Collect the jUnit results generated when testing a set of packages.

    It recursively crawls for XML files under the passed build base.
    Each XML file is being parsed and if it has the structure of a jUnit result
    file the statistics are being extracted.
    """

    __test__ = False  # prevent the class to falsely be identified as a test

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(VerbExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    def add_arguments(self, *, parser):  # noqa: D102
        parser.add_argument(
            '--build-base',
            type=_argparse_existing_dir,
            default='build',
            help='The base path for all build directories (default: build)')
        parser.add_argument(
            '--all',
            action='store_true',
            help='Show all test result file (even without errors / failures)')
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show additional information for errors / failures')

    def main(self, *, context):  # noqa: D102
        results = collect_test_results(
            context.args.build_base,
            get_testcases=context.args.verbose)

        # output stats from individual result files
        for result in results:
            if result.error_count or result.failure_count or context.args.all:
                print(result)
                if not context.args.verbose:
                    continue

                for testcase in result.testcases:
                    if (
                        not testcase.error_messages and
                        not testcase.failure_messages
                    ):
                        continue

                    # print label of testcase
                    msg_parts = []
                    if testcase.classname:
                        msg_parts.append(testcase.classname)
                    if testcase.name:
                        msg_parts.append(testcase.name)
                    if testcase.file:
                        suffix = ':' + testcase.line if testcase.line else ''
                        msg_parts.append(
                            '({testcase.file}{suffix})'.format_map(locals()))
                    print('-', ' '.join(msg_parts))

                    # print more information
                    _output_messages('error message', testcase.error_messages)
                    _output_messages(
                        'failure message', testcase.failure_messages)
                    _output_messages('stdout output', testcase.system_outs)
                    _output_messages('stderr output', testcase.system_errs)

        if (
            any(r.error_count or r.failure_count for r in results) or
            (context.args.all and results)
        ):
            print()

        summary = Result('Summary')
        for result in results:
            summary.add_result_counts(result)

        print(summary)

        return 1 if summary.error_count or summary.failure_count else 0


def _argparse_existing_dir(path):
    if not os.path.exists(path):
        raise argparse.ArgumentTypeError("Path '%s' does not exist" % path)
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError("Path '%s' is not a directory" % path)
    return path


def collect_test_results(basepath, *, get_testcases=False):
    """
    Collect test results by parsing all XML files in a given path.

    Each file is interpreted as a JUnit result file.

    :param str basepath: the basepath to recursively crawl
    :returns: list of test results
    :rtype: list of :py:class:`colcon_core.verb.test_results.Result`
    """
    results = []
    for dirpath, dirnames, filenames in os.walk(str(basepath)):
        # skip subdirectories starting with a dot
        dirnames[:] = filter(lambda d: not d.startswith('.'), dirnames)
        dirnames.sort()

        for filename in sorted(filenames):
            if not filename.endswith('.xml'):
                continue

            path = os.path.join(dirpath, filename)
            try:
                result = parse_junit_xml(path, get_testcases=get_testcases)
            except ParseError as e:
                logger.warn("Skipping '{path}': {e}".format_map(locals()))
                continue
            except ValueError as e:
                logger.debug("Skipping '{path}': {e}".format_map(locals()))
                continue
            except Exception as e:
                exc = traceback.format_exc()
                logger.error(
                    "Skipping '{path}': {e}\n{exc}".format_map(locals()))
                continue
            results.append(result)
    return results


def parse_junit_xml(path, *, get_testcases=False):
    """
    Parse an XML file and interpret it as a jUnit result file.

    See
    https://github.com/google/googletest/blob/master/googletest/docs/AdvancedGuide.md#generating-an-xml-report
    for an example of the format.

    :param str path: the path of the XML file
    :param parse_testcases: the flag if more information from each test case
      should be extracted
    :type parse_testcases: bool
    :returns: a result containing the stats
    :rtype: :py:class:`colcon_core.verb.test_results.Result`
    :raises ParseError: if the XML is not well-formed
    :raises TypeError: if the root node is neither named 'testsuite' nor
      'testsuites'
    """
    tree = ElementTree()
    root = tree.parse(path)

    # check if the root tag looks like a jUnit file
    if root.tag not in ['testsuite', 'testsuites']:
        raise ValueError(
            "the root tag is neither 'testsuite' nor 'testsuites'")

    # extract the integer values from various attributes
    result = Result(path)
    for slot, attribute, default in (
        ('test_count', 'tests', None),
        ('error_count', 'errors', 0),
        ('failure_count', 'failures', None),
        ('skipped_count', 'skip', 0),
        ('skipped_count', 'disabled', 0),
    ):
        try:
            value = root.attrib[attribute]
        except KeyError:
            if default is None:
                raise ValueError(
                    "the '{attribute}' attribute is required"
                    .format_map(locals()))
            value = default
        try:
            value = int(value)
        except ValueError as e:
            raise ValueError(
                "the '{attribute}' attribute should be an integer"
                .format_map(locals()))
        if value < 0:
            raise ValueError(
                "the '{attribute}' attribute should be a positive integer"
                .format_map(locals()))
        setattr(result, slot, getattr(result, slot) + value)

    if get_testcases:
        result.testcases = parse_testcases(root)

    return result


def parse_testcases(node):
    """
    Parse the statistics of all recursive testcases.

    :param node: The XML node
    :returns: The testcases
    :rtype: list
    """
    testcases = []
    # recursively process test suites
    if node.tag == 'testsuites':
        for child in node:
            testcases += parse_testcases(child)
        return testcases

    if node.tag != 'testsuite':
        return testcases

    # extract information
    for child in node:
        if child.tag != 'testcase':
            continue

        # extract information from test case
        testcase = Testcase(
            classname=child.attrib.get('classname'),
            file_=child.attrib.get('file'),
            line=child.attrib.get('line'),
            name=child.attrib.get('name'),
            time=child.attrib.get('time'))
        for child2 in child:
            if child2.tag == 'error':
                testcase.error_messages.append(
                    child2.attrib.get('message', ''))
            elif child2.tag == 'failure':
                testcase.failure_messages.append(
                    child2.attrib.get('message', ''))
            elif child2.tag == 'system-out':
                testcase.system_outs.append(child2.text)
            elif child2.tag == 'system-err':
                testcase.system_errs.append(child2.text)
        testcases.append(testcase)
    return testcases


def _output_messages(label, messages):
    if messages:
        print(' ', '<<<', label)
        for message in messages:
            for line in message.strip('\n\r').splitlines():
                print(' ', ' ', line)
        print(' ', '>>>')


class Result:
    """Aggregated statistics from a set of test cases."""

    __slots__ = (
        'path',
        'test_count',
        'error_count',
        'failure_count',
        'skipped_count',
        'testcases',
    )

    def __init__(self, path):  # noqa: D107
        self.path = path
        self.test_count = 0
        self.error_count = 0
        self.failure_count = 0
        self.skipped_count = 0
        self.testcases = None

    def add_result_counts(self, result):
        """
        Add the statistics from another result to this one.

        The `path` and the `testcases` are not changed.

        :param result: The other result
        """
        self.test_count += result.test_count
        self.error_count += result.error_count
        self.failure_count += result.failure_count
        self.skipped_count += result.skipped_count

    def __str__(self):  # noqa: D105
        data = {}
        for slot in self.__slots__:
            data[slot] = getattr(self, slot)
            if slot in ('test_count', 'error_count', 'failure_count'):
                data[slot + '_plural'] = 's' if data[slot] != 1 else ''
        return \
            '{path}: ' \
            '{test_count} test{test_count_plural}, ' \
            '{error_count} error{error_count_plural}, ' \
            '{failure_count} failure{failure_count_plural}, ' \
            '{skipped_count} skipped' \
            .format(**data)


class Testcase:
    """Information from a `testcase` tag."""

    __slots__ = (
        'classname',
        'file',
        'line',
        'name',
        'time',
        'error_messages',
        'failure_messages',
        'system_outs',
        'system_errs',
    )

    __test__ = False  # prevent the class to falsely be identified as a test

    def __init__(
        self, *, classname=None, file_=None, line=None, name=None, time=None
    ):  # noqa: D107
        self.classname = classname
        self.file = file_
        self.line = line
        self.name = name
        self.time = float(time) if time is not None else None
        self.error_messages = []
        self.failure_messages = []
        self.system_outs = []
        self.system_errs = []
