# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 eNovance
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
"""
Send notifications on request

"""
import os.path
import sys
import traceback as tb

import webob.dec

from nova.openstack.common import context
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging
from nova.openstack.common.middleware import base
from nova.openstack.common.notifier import api

LOG = logging.getLogger(__name__)


def log_and_ignore_error(fn):
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            LOG.exception(_('An exception occurred processing '
                            'the API call: %s ') % e)
    return wrapped


class RequestNotifier(base.Middleware):
    """Send notification on request."""

    @classmethod
    def factory(cls, global_conf, **local_conf):
        """Factory method for paste.deploy."""
        conf = global_conf.copy()
        conf.update(local_conf)

        def _factory(app):
            return cls(app, **conf)
        return _factory

    def __init__(self, app, **conf):
        self.service_name = conf.get('service_name', None)
        self.ignore_req_list = [x.upper().strip() for x in
                                conf.get('ignore_req_list', '').split(',')]
        super(RequestNotifier, self).__init__(app)

    @staticmethod
    def environ_to_dict(environ):
        """Following PEP 333, server variables are lower case, so don't
        include them.

        """
        return dict((k, v) for k, v in environ.iteritems()
                    if k.isupper())

    @log_and_ignore_error
    def process_request(self, request):
        request.environ['HTTP_X_SERVICE_NAME'] = \
            self.service_name or request.host
        payload = {
            'request': self.environ_to_dict(request.environ),
        }

        api.notify(context.get_admin_context(),
                   api.publisher_id(os.path.basename(sys.argv[0])),
                   'http.request',
                   api.INFO,
                   payload)

    @log_and_ignore_error
    def process_response(self, request, response,
                         exception=None, traceback=None):
        payload = {
            'request': self.environ_to_dict(request.environ),
        }

        if response:
            payload['response'] = {
                'status': response.status,
                'headers': response.headers,
            }

        if exception:
            payload['exception'] = {
                'value': repr(exception),
                'traceback': tb.format_tb(traceback)
            }

        api.notify(context.get_admin_context(),
                   api.publisher_id(os.path.basename(sys.argv[0])),
                   'http.response',
                   api.INFO,
                   payload)

    @webob.dec.wsgify
    def __call__(self, req):
        if req.method in self.ignore_req_list:
            return req.get_response(self.application)
        else:
            self.process_request(req)
            try:
                response = req.get_response(self.application)
            except Exception:
                type, value, traceback = sys.exc_info()
                self.process_response(req, None, value, traceback)
                raise
            else:
                self.process_response(req, response)
            return response
