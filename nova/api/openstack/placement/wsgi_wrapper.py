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
"""Extend functionality from webob.dec.wsgify for Placement API."""

import webob

from oslo_log import log as logging
from webob.dec import wsgify

from nova.api.openstack.placement import util

LOG = logging.getLogger(__name__)


class PlacementWsgify(wsgify):

    def call_func(self, req, *args, **kwargs):
        """Add json_error_formatter to any webob HTTPExceptions."""
        try:
            super(PlacementWsgify, self).call_func(req, *args, **kwargs)
        except webob.exc.HTTPException as exc:
            LOG.debug("Placement API returning an error response: %s", exc)
            exc.json_formatter = util.json_error_formatter
            raise
