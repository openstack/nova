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
"""Deployment handling for Placmenent API."""

from keystonemiddleware import auth_token
import oslo_middleware
from oslo_middleware import cors

from nova.api import openstack as common_api
from nova.api.openstack.placement import auth
from nova.api.openstack.placement import handler
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import requestlog
from nova import objects


# TODO(cdent): NAME points to the config project being used, so for
# now this is "nova" but we probably want "placement" eventually.
NAME = "nova"


# Make sure that objects are registered for this running of the
# placement API.
objects.register_all()


def deploy(conf, project_name):
    """Assemble the middleware pipeline leading to the placement app."""
    if conf.api.auth_strategy == 'noauth2':
        auth_middleware = auth.NoAuthMiddleware
    else:
        # Do not use 'oslo_config_project' param here as the conf
        # location may have been overridden earlier in the deployment
        # process with OS_PLACEMENT_CONFIG_DIR in wsgi.py.
        auth_middleware = auth_token.filter_factory(
            {}, oslo_config_config=conf)

    # Pass in our CORS config, if any, manually as that's a)
    # explicit, b) makes testing more straightfoward, c) let's
    # us control the use of cors by the presence of its config.
    conf.register_opts(cors.CORS_OPTS, 'cors')
    if conf.cors.allowed_origin:
        cors_middleware = oslo_middleware.CORS.factory(
            {}, **conf.cors)
    else:
        cors_middleware = None

    context_middleware = auth.PlacementKeystoneContext
    req_id_middleware = oslo_middleware.RequestId
    microversion_middleware = microversion.MicroversionMiddleware
    fault_wrap = common_api.FaultWrapper
    request_log = requestlog.RequestLog

    application = handler.PlacementHandler()

    # NOTE(cdent): The ordering here is important. The list is ordered
    # from the inside out. For a single request req_id_middleware is called
    # first and microversion_middleware last. Then the request is finally
    # passed to the application (the PlacementHandler). At that point
    # the response ascends the middleware in the reverse of the
    # order the request went in. This order ensures that log messages
    # all see the same contextual information including request id and
    # authentication information.
    for middleware in (microversion_middleware,
                       fault_wrap,
                       request_log,
                       context_middleware,
                       auth_middleware,
                       cors_middleware,
                       req_id_middleware,
                       ):
        if middleware:
            application = middleware(application)

    return application


def loadapp(config, project_name=NAME):
    application = deploy(config, project_name)
    return application
