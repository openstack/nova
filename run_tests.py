#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


import os
import unittest
import sys

from nose import config
from nose import result
from nose import core


class NovaTestResult(result.TextTestResult):
    def __init__(self, *args, **kw):
        result.TextTestResult.__init__(self, *args, **kw)
        self._last_case = None

    def getDescription(self, test):
        return str(test)

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        current_case = test.test.__class__.__name__

        if self.showAll:
            if current_case != self._last_case:
                self.stream.writeln(current_case)
                self._last_case = current_case

            self.stream.write(
                '    %s' % str(test.test._testMethodName).ljust(60))
            self.stream.flush()


class NovaTestRunner(core.TextTestRunner):
    def _makeResult(self):
        return NovaTestResult(self.stream,
                              self.descriptions,
                              self.verbosity,
                              self.config)


if __name__ == '__main__':
    c = config.Config(stream=sys.stdout,
                      env=os.environ,
                      verbosity=3)

    runner = NovaTestRunner(stream=c.stream,
                            verbosity=c.verbosity,
                            config=c)
    sys.exit(not core.run(config=c, testRunner=runner))
