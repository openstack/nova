#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013, Nebula, Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Colorizer Code is borrowed from Twisted:
# Copyright (c) 2001-2010 Twisted Matrix Laboratories.
#
#    Permission is hereby granted, free of charge, to any person obtaining
#    a copy of this software and associated documentation files (the
#    "Software"), to deal in the Software without restriction, including
#    without limitation the rights to use, copy, modify, merge, publish,
#    distribute, sublicense, and/or sell copies of the Software, and to
#    permit persons to whom the Software is furnished to do so, subject to
#    the following conditions:
#
#    The above copyright notice and this permission notice shall be
#    included in all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
#    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
#    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
#    LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
#    OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
#    WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""Display a subunit stream through a colorized unittest test runner."""

import heapq
import subunit
import sys
import unittest

import testtools


class _AnsiColorizer(object):
    """
    A colorizer is an object that loosely wraps around a stream, allowing
    callers to write text to the stream in a particular color.

    Colorizer classes must implement C{supported()} and C{write(text, color)}.
    """
    _colors = dict(black=30, red=31, green=32, yellow=33,
                   blue=34, magenta=35, cyan=36, white=37)

    def __init__(self, stream):
        self.stream = stream

    def supported(cls, stream=sys.stdout):
        """
        A class method that returns True if the current platform supports
        coloring terminal output using this method. Returns False otherwise.
        """
        if not stream.isatty():
            return False  # auto color only on TTYs
        try:
            import curses
        except ImportError:
            return False
        else:
            try:
                try:
                    return curses.tigetnum("colors") > 2
                except curses.error:
                    curses.setupterm()
                    return curses.tigetnum("colors") > 2
            except Exception:
                # guess false in case of error
                return False
    supported = classmethod(supported)

    def write(self, text, color):
        """
        Write the given text to the stream in the given color.

        @param text: Text to be written to the stream.

        @param color: A string label for a color. e.g. 'red', 'white'.
        """
        color = self._colors[color]
        self.stream.write('\x1b[%s;1m%s\x1b[0m' % (color, text))


class _Win32Colorizer(object):
    """
    See _AnsiColorizer docstring.
    """
    def __init__(self, stream):
        import win32console
        red, green, blue, bold = (win32console.FOREGROUND_RED,
                                  win32console.FOREGROUND_GREEN,
                                  win32console.FOREGROUND_BLUE,
                                  win32console.FOREGROUND_INTENSITY)
        self.stream = stream
        self.screenBuffer = win32console.GetStdHandle(
                win32console.STD_OUT_HANDLE)
        self._colors = {
            'normal': red | green | blue,
            'red': red | bold,
            'green': green | bold,
            'blue': blue | bold,
            'yellow': red | green | bold,
            'magenta': red | blue | bold,
            'cyan': green | blue | bold,
            'white': red | green | blue | bold
            }

    def supported(cls, stream=sys.stdout):
        try:
            import win32console
            screenBuffer = win32console.GetStdHandle(
                win32console.STD_OUT_HANDLE)
        except ImportError:
            return False
        import pywintypes
        try:
            screenBuffer.SetConsoleTextAttribute(
                win32console.FOREGROUND_RED |
                win32console.FOREGROUND_GREEN |
                win32console.FOREGROUND_BLUE)
        except pywintypes.error:
            return False
        else:
            return True
    supported = classmethod(supported)

    def write(self, text, color):
        color = self._colors[color]
        self.screenBuffer.SetConsoleTextAttribute(color)
        self.stream.write(text)
        self.screenBuffer.SetConsoleTextAttribute(self._colors['normal'])


class _NullColorizer(object):
    """
    See _AnsiColorizer docstring.
    """
    def __init__(self, stream):
        self.stream = stream

    def supported(cls, stream=sys.stdout):
        return True
    supported = classmethod(supported)

    def write(self, text, color):
        self.stream.write(text)


def get_elapsed_time_color(elapsed_time):
    if elapsed_time > 1.0:
        return 'red'
    elif elapsed_time > 0.25:
        return 'yellow'
    else:
        return 'green'


class NovaTestResult(testtools.TestResult):
    def __init__(self, stream, descriptions, verbosity):
        super(NovaTestResult, self).__init__()
        self.stream = stream
        self.showAll = verbosity > 1
        self.num_slow_tests = 10
        self.slow_tests = []  # this is a fixed-sized heap
        self.colorizer = None
        # NOTE(vish): reset stdout for the terminal check
        stdout = sys.stdout
        sys.stdout = sys.__stdout__
        for colorizer in [_Win32Colorizer, _AnsiColorizer, _NullColorizer]:
            if colorizer.supported():
                self.colorizer = colorizer(self.stream)
                break
        sys.stdout = stdout
        self.start_time = None
        self.last_time = {}
        self.results = {}
        self.last_written = None

    def _writeElapsedTime(self, elapsed):
        color = get_elapsed_time_color(elapsed)
        self.colorizer.write("  %.2f" % elapsed, color)

    def _addResult(self, test, *args):
        try:
            name = test.id()
        except AttributeError:
            name = 'Unknown.unknown'
        test_class, test_name = name.rsplit('.', 1)

        elapsed = (self._now() - self.start_time).total_seconds()
        item = (elapsed, test_class, test_name)
        if len(self.slow_tests) >= self.num_slow_tests:
            heapq.heappushpop(self.slow_tests, item)
        else:
            heapq.heappush(self.slow_tests, item)

        self.results.setdefault(test_class, [])
        self.results[test_class].append((test_name, elapsed) + args)
        self.last_time[test_class] = self._now()
        self.writeTests()

    def _writeResult(self, test_name, elapsed, long_result, color,
                     short_result, success):
        if self.showAll:
            self.stream.write('    %s' % str(test_name).ljust(66))
            self.colorizer.write(long_result, color)
            if success:
                self._writeElapsedTime(elapsed)
            self.stream.writeln()
        else:
            self.colorizer.write(short_result, color)

    def addSuccess(self, test):
        super(NovaTestResult, self).addSuccess(test)
        self._addResult(test, 'OK', 'green', '.', True)

    def addFailure(self, test, err):
        if test.id() == 'process-returncode':
            return
        super(NovaTestResult, self).addFailure(test, err)
        self._addResult(test, 'FAIL', 'red', 'F', False)

    def addError(self, test, err):
        super(NovaTestResult, self).addFailure(test, err)
        self._addResult(test, 'ERROR', 'red', 'E', False)

    def addSkip(self, test, reason=None, details=None):
        super(NovaTestResult, self).addSkip(test, reason, details)
        self._addResult(test, 'SKIP', 'blue', 'S', True)

    def startTest(self, test):
        self.start_time = self._now()
        super(NovaTestResult, self).startTest(test)

    def writeTestCase(self, cls):
        if not self.results.get(cls):
            return
        if cls != self.last_written:
            self.colorizer.write(cls, 'white')
            self.stream.writeln()
        for result in self.results[cls]:
            self._writeResult(*result)
        del self.results[cls]
        self.stream.flush()
        self.last_written = cls

    def writeTests(self):
        time = self.last_time.get(self.last_written, self._now())
        if not self.last_written or (self._now() - time).total_seconds() > 2.0:
            diff = 3.0
            while diff > 2.0:
                classes = self.results.keys()
                oldest = min(classes, key=lambda x: self.last_time[x])
                diff = (self._now() - self.last_time[oldest]).total_seconds()
                self.writeTestCase(oldest)
        else:
            self.writeTestCase(self.last_written)

    def done(self):
        self.stopTestRun()

    def stopTestRun(self):
        for cls in list(self.results.iterkeys()):
            self.writeTestCase(cls)
        self.stream.writeln()
        self.writeSlowTests()

    def writeSlowTests(self):
        # Pare out 'fast' tests
        slow_tests = [item for item in self.slow_tests
                      if get_elapsed_time_color(item[0]) != 'green']
        if slow_tests:
            slow_total_time = sum(item[0] for item in slow_tests)
            slow = ("Slowest %i tests took %.2f secs:"
                    % (len(slow_tests), slow_total_time))
            self.colorizer.write(slow, 'yellow')
            self.stream.writeln()
            last_cls = None
            # sort by name
            for elapsed, cls, name in sorted(slow_tests,
                                             key=lambda x: x[1] + x[2]):
                if cls != last_cls:
                    self.colorizer.write(cls, 'white')
                    self.stream.writeln()
                last_cls = cls
                self.stream.write('    %s' % str(name).ljust(68))
                self._writeElapsedTime(elapsed)
                self.stream.writeln()

    def printErrors(self):
        if self.showAll:
            self.stream.writeln()
        self.printErrorList('ERROR', self.errors)
        self.printErrorList('FAIL', self.failures)

    def printErrorList(self, flavor, errors):
        for test, err in errors:
            self.colorizer.write("=" * 70, 'red')
            self.stream.writeln()
            self.colorizer.write(flavor, 'red')
            self.stream.writeln(": %s" % test.id())
            self.colorizer.write("-" * 70, 'red')
            self.stream.writeln()
            self.stream.writeln("%s" % err)


test = subunit.ProtocolTestCase(sys.stdin, passthrough=None)

if sys.version_info[0:2] <= (2, 6):
    runner = unittest.TextTestRunner(verbosity=2)
else:
    runner = unittest.TextTestRunner(verbosity=2, resultclass=NovaTestResult)

if runner.run(test).wasSuccessful():
    exit_code = 0
else:
    exit_code = 1
sys.exit(exit_code)
