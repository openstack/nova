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

import logging
import warnings

import fixtures
from oslotest import log


class NullHandler(logging.Handler):
    """custom default NullHandler to attempt to format the record.

    Used in conjunction with Logging below to detect formatting errors
    in debug logs.
    """
    def handle(self, record):
        self.format(record)

    def emit(self, record):
        pass

    def createLock(self):
        self.lock = None


class Logging(log.ConfigureLogging):
    """A logging fixture providing two important fixtures.

    One is to capture logs for later inspection.

    The other is to make sure that DEBUG logs, even if not captured,
    are formatted.
    """

    def __init__(self):
        super(Logging, self).__init__()
        # If level was not otherwise set, default to INFO.
        if self.level is None:
            self.level = logging.INFO
        # Always capture logs, unlike the parent.
        self.capture_logs = True

    def setUp(self):
        super(Logging, self).setUp()
        if self.level > logging.DEBUG:
            handler = NullHandler()
            self.useFixture(fixtures.LogHandler(handler, nuke_handlers=False))
            handler.setLevel(logging.DEBUG)


class WarningsFixture(fixtures.Fixture):
    """Filter or escalates certain warnings during test runs.

    Add additional entries as required. Remove when obsolete.
    """

    def setUp(self):
        super(WarningsFixture, self).setUp()

        # Ignore policy scope warnings.
        warnings.filterwarnings('ignore',
                                message="Policy .* failed scope check",
                                category=UserWarning)
        # The UUIDFields emits a warning if the value is not a  valid UUID.
        # Let's escalate that to an exception in the test to prevent adding
        # violations.
        warnings.filterwarnings('error', message=".*invalid UUID.*")

        self.addCleanup(warnings.resetwarnings)
