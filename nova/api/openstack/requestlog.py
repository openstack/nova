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
"""Simple middleware for request logging."""

import time

from oslo_log import log as logging
from oslo_utils import excutils
import webob.dec
import webob.exc

from nova.api.openstack import wsgi
from nova import wsgi as base_wsgi

# TODO(sdague) maybe we can use a better name here for the logger
LOG = logging.getLogger(__name__)


class RequestLog(base_wsgi.Middleware):
    """WSGI Middleware to write a simple request log to.

    Borrowed from Paste Translogger
    """

    # This matches the placement fil
    _log_format = ('%(REMOTE_ADDR)s "%(REQUEST_METHOD)s %(REQUEST_URI)s" '
                   'status: %(status)s len: %(len)s '
                   'microversion: %(microversion)s time: %(time).6f')

    @staticmethod
    def _get_uri(environ):
        req_uri = (environ.get('SCRIPT_NAME', '') +
                   environ.get('PATH_INFO', ''))
        if environ.get('QUERY_STRING'):
            req_uri += '?' + environ['QUERY_STRING']
        return req_uri

    @staticmethod
    def _should_emit(req):
        """Conditions under which we should skip logging.

        If we detect we are running under eventlet wsgi processing, we
        already are logging things, let it go. This is broken out as a
        separate method so that it can be easily adjusted for testing.
        """
        if req.environ.get('eventlet.input', None) is not None:
            return False
        return True

    def _log_req(self, req, res, start):
        if not self._should_emit(req):
            return

        # in the event that things exploded really badly deeper in the
        # wsgi stack, res is going to be an empty dict for the
        # fallback logging. So never count on it having attributes.
        status = getattr(res, "status", "500 Error").split(None, 1)[0]
        data = {
            'REMOTE_ADDR': req.environ.get('REMOTE_ADDR', '-'),
            'REQUEST_METHOD': req.environ['REQUEST_METHOD'],
            'REQUEST_URI': self._get_uri(req.environ),
            'status': status,
            'len': getattr(res, "content_length", 0),
            'time': time.time() - start,
            'microversion': '-'
        }
        # set microversion if it exists
        if not req.api_version_request.is_null():
            data["microversion"] = req.api_version_request.get_string()
        LOG.info(self._log_format, data)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        res = {}
        start = time.time()
        try:
            res = req.get_response(self.application)
            self._log_req(req, res, start)
            return res
        except Exception:
            with excutils.save_and_reraise_exception():
                self._log_req(req, res, start)
