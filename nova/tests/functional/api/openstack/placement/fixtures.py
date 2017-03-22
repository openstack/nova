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

import os

from gabbi import fixture
from oslo_middleware import cors
from oslo_utils import uuidutils

from nova.api.openstack.placement import deploy
from nova import conf
from nova import config
from nova import context
from nova import objects
from nova.tests import fixtures


CONF = conf.CONF


def setup_app():
    return deploy.loadapp(CONF)


class APIFixture(fixture.GabbiFixture):
    """Setup the required backend fixtures for a basic placement service."""

    def __init__(self):
        self.conf = None

    def start_fixture(self):
        # Set up stderr and stdout captures by directly driving the
        # existing nova fixtures that do that. This captures the
        # output that happens outside individual tests (for
        # example database migrations).
        self.standard_logging_fixture = fixtures.StandardLogging()
        self.standard_logging_fixture.setUp()
        self.output_stream_fixture = fixtures.OutputStreamCapture()
        self.output_stream_fixture.setUp()

        self.conf = CONF
        self.conf.set_override('auth_strategy', 'noauth2', group='api')
        # Be explicit about all three database connections to avoid
        # potential conflicts with config on disk.
        self.conf.set_override('connection', "sqlite://", group='database')
        self.conf.set_override('connection', "sqlite://",
                               group='api_database')

        # Register CORS opts, but do not set config. This has the
        # effect of exercising the "don't use cors" path in
        # deploy.py. Without setting some config the group will not
        # be present.
        self.conf.register_opts(cors.CORS_OPTS, 'cors')

        # Make sure default_config_files is an empty list, not None.
        # If None /etc/nova/nova.conf is read and confuses results.
        config.parse_args([], default_config_files=[], configure_db=False,
                          init_rpc=False)

        # NOTE(cdent): api and main database are not used but we still need
        # to manage them to make the fixtures work correctly and not cause
        # conflicts with other tests in the same process.
        self.api_db_fixture = fixtures.Database('api')
        self.main_db_fixture = fixtures.Database('main')
        self.api_db_fixture.reset()
        self.main_db_fixture.reset()

        os.environ['RP_UUID'] = uuidutils.generate_uuid()
        os.environ['RP_NAME'] = uuidutils.generate_uuid()
        os.environ['CUSTOM_RES_CLASS'] = 'CUSTOM_IRON_NFV'

    def stop_fixture(self):
        self.api_db_fixture.cleanup()
        self.main_db_fixture.cleanup()
        self.output_stream_fixture.cleanUp()
        self.standard_logging_fixture.cleanUp()
        if self.conf:
            self.conf.reset()


class AllocationFixture(APIFixture):
    """An APIFixture that has some pre-made Allocations."""

    def start_fixture(self):
        super(AllocationFixture, self).start_fixture()
        self.context = context.get_admin_context()
        # Stealing from the super
        rp_name = os.environ['RP_NAME']
        rp_uuid = os.environ['RP_UUID']
        rp = objects.ResourceProvider(
            self.context, name=rp_name, uuid=rp_uuid)
        rp.create()

        # Create some DISK_GB inventory and allocations.
        inventory = objects.Inventory(
            self.context, resource_provider=rp,
            resource_class='DISK_GB', total=2048,
            step_size=10, min_unit=10, max_unit=600)
        inventory.obj_set_defaults()
        rp.add_inventory(inventory)
        alloc1 = objects.Allocation(
            self.context, resource_provider=rp,
            resource_class='DISK_GB',
            consumer_id=uuidutils.generate_uuid(),
            used=500)
        alloc2 = objects.Allocation(
            self.context, resource_provider=rp,
            resource_class='DISK_GB',
            consumer_id=uuidutils.generate_uuid(),
            used=500)
        alloc_list = objects.AllocationList(self.context,
                objects=[alloc1, alloc2])
        alloc_list.create_all()

        # Create some VCPU inventory and allocations.
        inventory = objects.Inventory(
            self.context, resource_provider=rp,
            resource_class='VCPU', total=8,
            max_unit=4)
        inventory.obj_set_defaults()
        rp.add_inventory(inventory)
        alloc1 = objects.Allocation(
            self.context, resource_provider=rp,
            resource_class='VCPU',
            consumer_id=uuidutils.generate_uuid(),
            used=2)
        alloc2 = objects.Allocation(
            self.context, resource_provider=rp,
            resource_class='VCPU',
            consumer_id=uuidutils.generate_uuid(),
            used=4)
        alloc_list = objects.AllocationList(self.context,
                objects=[alloc1, alloc2])
        alloc_list.create_all()

        # The ALT_RP_XXX variables are for a resource provider that has
        # not been created in the Allocation fixture
        os.environ['ALT_RP_UUID'] = uuidutils.generate_uuid()
        os.environ['ALT_RP_NAME'] = uuidutils.generate_uuid()


class CORSFixture(APIFixture):
    """An APIFixture that turns on CORS."""

    def start_fixture(self):
        super(CORSFixture, self).start_fixture()
        # NOTE(cdent): If we remove this override, then the cors
        # group ends up not existing in the conf, so when deploy.py
        # wants to load the CORS middleware, it will not.
        self.conf.set_override('allowed_origin', 'http://valid.example.com',
                               group='cors')
