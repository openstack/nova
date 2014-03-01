# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures


def get_logging_handle_error_fixture():
    """returns a fixture to make logging raise formatting exceptions.

    Usage:
    self.useFixture(logging.get_logging_handle_error_fixture())
    """
    return fixtures.MonkeyPatch('logging.Handler.handleError',
                                _handleError)


def _handleError(self, record):
    """Monkey patch for logging.Handler.handleError.

    The default handleError just logs the error to stderr but we want
    the option of actually raising an exception.
    """
    raise
