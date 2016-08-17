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
from oslo_middleware import request_id

from nova.api.openstack.placement import auth
from nova.api.openstack.placement import handler
from nova.api.openstack.placement import microversion
from nova import objects


# TODO(cdent): NAME points to the config project being used, so for
# now this is "nova" but we probably want "placement" eventually.
NAME = "nova"


# Make sure that objects are registered for this running of the
# placement API.
objects.register_all()


def deploy(conf, project_name):
    """Assemble the middleware pipeline leading to the placement app."""
    if conf.auth_strategy == 'noauth2':
        auth_middleware = auth.NoAuthMiddleware
    else:
        # Do not provide global conf to middleware here.
        auth_middleware = auth_token.filter_factory(
            {}, olso_config_project=project_name)

    context_middleware = auth.PlacementKeystoneContext
    req_id_middleware = request_id.RequestId
    microversion_middleware = microversion.MicroversionMiddleware

    application = handler.PlacementHandler()

    for middleware in (context_middleware,
                       auth_middleware,
                       microversion_middleware,
                       req_id_middleware):
        application = middleware(application)

    return application


def loadapp(config, project_name=NAME):
    application = deploy(config, project_name)
    return application
