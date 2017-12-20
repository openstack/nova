# Copyright 2011 OpenStack Foundation
# Copyright 2011 Justin Santa Barbara
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

import functools

from oslo_log import log as logging
import webob.dec
import webob.exc

from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)


def expected_errors(errors):
    """Decorator for v2.1 API methods which specifies expected exceptions.

    Specify which exceptions may occur when an API method is called. If an
    unexpected exception occurs then return a 500 instead and ask the user
    of the API to file a bug report.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as exc:
                if isinstance(exc, webob.exc.WSGIHTTPException):
                    if isinstance(errors, int):
                        t_errors = (errors,)
                    else:
                        t_errors = errors
                    if exc.code in t_errors:
                        raise
                elif isinstance(exc, exception.Forbidden):
                    # Note(cyeoh): Special case to handle
                    # Forbidden exceptions so every
                    # extension method does not need to wrap authorize
                    # calls. ResourceExceptionHandler silently
                    # converts NotAuthorized to HTTPForbidden
                    raise
                elif isinstance(exc, exception.ValidationError):
                    # Note(oomichi): Handle a validation error, which
                    # happens due to invalid API parameters, as an
                    # expected error.
                    raise
                elif isinstance(exc, exception.Unauthorized):
                    # Handle an authorized exception, will be
                    # automatically converted to a HTTP 401, clients
                    # like python-novaclient handle this error to
                    # generate new token and do another attempt.
                    raise

                LOG.exception("Unexpected exception in API method")
                msg = _('Unexpected API Error. Please report this at '
                    'http://bugs.launchpad.net/nova/ and attach the Nova '
                    'API log if possible.\n%s') % type(exc)
                raise webob.exc.HTTPInternalServerError(explanation=msg)

        return wrapped

    return decorator
