# Copyright (c) 2013 NEC Corporation
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

"""Middleware that provides high-level error handling.

It catches all exceptions from subsequent applications in WSGI pipeline
to hide internal errors from API response.
"""
import logging

import webob.dec
import webob.exc

from nova.openstack.common._i18n import _LE
from nova.openstack.common.middleware import base
from nova.openstack.common import versionutils


LOG = logging.getLogger(__name__)


@versionutils.deprecated(as_of=versionutils.deprecated.JUNO,
                         in_favor_of='oslo.middleware.CatchErrors')
class CatchErrorsMiddleware(base.Middleware):

    @webob.dec.wsgify
    def __call__(self, req):
        try:
            response = req.get_response(self.application)
        except Exception:
            LOG.exception(_LE('An error occurred during '
                              'processing the request: %s'))
            response = webob.exc.HTTPInternalServerError()
        return response
