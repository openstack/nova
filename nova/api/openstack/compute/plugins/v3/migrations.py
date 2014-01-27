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

from nova.api.openstack import extensions
from nova import compute


ALIAS = "os-migrations"


def authorize(context, action_name):
    action = 'v3:%s:%s' % (ALIAS, action_name)
    extensions.extension_authorizer('compute', action)(context)


class MigrationsController(object):
    """Controller for accessing migrations in OpenStack API."""
    def __init__(self):
        self.compute_api = compute.API()

    @extensions.expected_errors(())
    def index(self, req):
        """Return all migrations in progress."""
        context = req.environ['nova.context']
        authorize(context, "index")
        migrations = self.compute_api.get_migrations(context, req.GET)
        return {'migrations': migrations}


class Migrations(extensions.V3APIExtensionBase):
    """Provide data on migrations."""
    name = "Migrations"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-migrations',
                                                MigrationsController())
        resources.append(resource)
        return resources

    def get_controller_extensions(self):
        return []
