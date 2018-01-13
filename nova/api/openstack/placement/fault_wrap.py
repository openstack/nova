# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Simple middleware for safely catching unexpected exceptions."""

# NOTE(cdent): This is a super simplified replacement for the nova
# FaultWrapper, which does more than placement needs.

from oslo_log import log as logging
import six
from webob import exc

from nova.api.openstack.placement import util

LOG = logging.getLogger(__name__)


class FaultWrapper(object):
    """Turn an uncaught exception into a status 500.

    Uncaught exceptions usually shouldn't happen, if it does it
    means there is a bug in the placement service, which should be
    fixed.
    """

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        try:
            return self.application(environ, start_response)
        except Exception as unexpected_exception:
            LOG.exception('Placement API unexpected error: %s',
                          unexpected_exception)
            formatted_exception = exc.HTTPInternalServerError(
                six.text_type(unexpected_exception))
            formatted_exception.json_formatter = util.json_error_formatter
            return formatted_exception.generate_response(
                environ, start_response)
