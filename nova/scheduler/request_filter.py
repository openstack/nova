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

from oslo_log import log as logging

import nova.conf


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


ALL_REQUEST_FILTERS = [
]


def process_reqspec(ctxt, request_spec):
    """Process an objects.ReqestSpec before calling placement.

    :param ctxt: A RequestContext
    :param request_spec: An objects.RequestSpec to be inspected/modified
    """
    for filter in ALL_REQUEST_FILTERS:
        filter(ctxt, request_spec)
