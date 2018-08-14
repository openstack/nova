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

from microversion_parse import middleware as mp_middleware
import oslo_middleware
from oslo_middleware import cors

from nova.api.openstack.placement import auth
from nova.api.openstack.placement import db_api
from nova.api.openstack.placement import fault_wrap
from nova.api.openstack.placement import handler
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider
from nova.api.openstack.placement import requestlog
from nova.api.openstack.placement import util


# TODO(cdent): NAME points to the config project being used, so for
# now this is "nova" but we probably want "placement" eventually.
NAME = "nova"


def deploy(conf):
    """Assemble the middleware pipeline leading to the placement app."""
    if conf.api.auth_strategy == 'noauth2':
        auth_middleware = auth.NoAuthMiddleware
    else:
        # Do not use 'oslo_config_project' param here as the conf
        # location may have been overridden earlier in the deployment
        # process with OS_PLACEMENT_CONFIG_DIR in wsgi.py.
        auth_middleware = auth.filter_factory(
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
    microversion_middleware = mp_middleware.MicroversionMiddleware
    fault_middleware = fault_wrap.FaultWrapper
    request_log = requestlog.RequestLog

    application = handler.PlacementHandler()
    # configure microversion middleware in the old school way
    application = microversion_middleware(
        application, microversion.SERVICE_TYPE, microversion.VERSIONS,
        json_error_formatter=util.json_error_formatter)

    # NOTE(cdent): The ordering here is important. The list is ordered
    # from the inside out. For a single request req_id_middleware is called
    # first and microversion_middleware last. Then the request is finally
    # passed to the application (the PlacementHandler). At that point
    # the response ascends the middleware in the reverse of the
    # order the request went in. This order ensures that log messages
    # all see the same contextual information including request id and
    # authentication information.
    for middleware in (fault_middleware,
                       request_log,
                       context_middleware,
                       auth_middleware,
                       cors_middleware,
                       req_id_middleware,
                       ):
        if middleware:
            application = middleware(application)

    # NOTE(mriedem): Ignore scope check UserWarnings from oslo.policy.
    if not conf.oslo_policy.enforce_scope:
        import warnings
        warnings.filterwarnings('ignore',
                                message="Policy .* failed scope check",
                                category=UserWarning)

    return application


def update_database():
    """Do any database updates required at process boot time, such as
    updating the traits table.
    """
    ctx = db_api.DbContext()
    resource_provider.ensure_trait_sync(ctx)
    resource_provider.ensure_rc_cache(ctx)


# NOTE(cdent): Althought project_name is no longer used because of the
# resolution of https://bugs.launchpad.net/nova/+bug/1734491, loadapp()
# is considered a public interface for the creation of a placement
# WSGI app so must maintain its interface. The canonical placement WSGI
# app is created by init_application in wsgi.py, but this is not
# required and in fact can be limiting. loadapp() may be used from
# fixtures or arbitrary WSGI frameworks and loaders.
def loadapp(config, project_name=NAME):
    """WSGI application creator for placement.

    :param config: An olso_config.cfg.ConfigOpts containing placement
                   configuration.
    :param project_name: oslo_config project name. Ignored, preserved for
                         backwards compatibility
    """
    application = deploy(config)
    update_database()
    return application
