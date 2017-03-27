# Copyright 2017 IBM
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from keystoneauth1 import exceptions as kse
from keystoneauth1 import session
from oslo_log import log as logging
import webob

from nova.i18n import _

LOG = logging.getLogger(__name__)


def verify_project_id(context, project_id):
    """verify that a project_id exists.

    This attempts to verify that a project id exists. If it does not,
    an HTTPBadRequest is emitted.

    """
    sess = session.Session(auth=context.get_auth_plugin())
    try:
        resp = sess.get('/v3/projects/%s' % project_id,
                        endpoint_filter={'service_type': 'identity'},
                        raise_exc=False)
    except kse.ClientException:
        # something is wrong, like there isn't a keystone v3 endpoint,
        # we'll take the pass and default to everything being ok.
        LOG.exception("Unable to contact keystone to verify project_id")
        return True

    if resp:
        # All is good with this 20x status
        return True
    elif resp.status_code == 404:
        # we got access, and we know this project is not there
        raise webob.exc.HTTPBadRequest(
            explanation=_("Project ID %s is not a valid project.") %
            project_id)
    elif resp.status_code == 403:
        # we don't have enough permission to verify this, so default
        # to "it's ok".
        LOG.info(
            "Insufficient permissions for user %(user)s to verify "
            "existence of project_id %(pid)s",
            {"user": context.user_id, "pid": project_id})
        return True
    else:
        LOG.warning(
            "Unexpected response from keystone trying to "
            "verify project_id %(pid)s - resp: %(code)s %(content)s",
            {"pid": project_id,
             "code": resp.status_code,
             "content": resp.content})
        # realize we did something wrong, but move on with a warning
        return True
