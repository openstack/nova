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


import typing as ty

if ty.TYPE_CHECKING:
    import keystoneauth1.plugin

from keystoneauth1 import loading as ks_loading
from keystoneauth1 import service_token
from oslo_log import log as logging

import nova.conf


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

# Auth plugins and auth sessions keyed by configuration group name
_AUTHS = {}
_SESSIONS = {}


def reset_globals():
    """For async unit test consistency."""
    global _AUTHS, _SESSIONS
    _AUTHS = {}
    _SESSIONS = {}


def get_service_auth_plugin(
    conf_group: str,
) -> 'keystoneauth1.plugin.BaseAuthPlugin':
    """Get an auth plugin for authentication as the service user."""
    auth = _AUTHS.get(conf_group)
    if not auth:
        auth = ks_loading.load_auth_from_conf_options(CONF, conf_group)
        _AUTHS[conf_group] = auth
    return auth


def get_service_auth_session(
    conf_group: str,
    auth: ty.Optional['keystoneauth1.plugin.BaseAuthPlugin'] = None,
) -> 'keystoneauth1.session.Session':
    """Get a session for authentication as the service user.

    An auth plugin can be optionally passed in to use to authenticate the
    session.
    """
    session = _SESSIONS.get(conf_group)
    if not session:
        session = ks_loading.load_session_from_conf_options(
                CONF, conf_group, auth=auth)
        _SESSIONS[conf_group] = session
    return session


def get_service_user_token_auth_plugin(context, user_auth=None):
    """Dynamically get an auth plugin based on service user token config.

    This function will use [service_user]send_service_user_token configuration
    to determine whether to return either:

        * The user's auth from the RequestContext
    or
        * A wrapper around both the user's auth and the service user's auth

    The user's auth may be optionally passed in to use instead grabbing it
    from the RequestContext. This comes up in cases where we have an anonymous
    RequestContext such as using get_admin_context() in nova-manage commands to
    call other service APIs.

    This function should only be used for passing service user tokens to APIs.
    """
    # user_auth may be passed in when the RequestContext is anonymous, such as
    # when get_admin_context() is used for API calls by nova-manage.
    user_auth = user_auth or context.get_auth_plugin()

    if CONF.service_user.send_service_user_token:
        service_auth = get_service_auth_plugin(
                nova.conf.service_token.SERVICE_USER_GROUP)

        if service_auth is None:
            # This indicates a misconfiguration so log a warning and
            # return the user_auth.
            LOG.warning('Unable to load auth from [service_user] '
                        'configuration. Ensure "auth_type" is set.')
            return user_auth

        return service_token.ServiceTokenAuthWrapper(
                   user_auth=user_auth, service_auth=service_auth)
    return user_auth
