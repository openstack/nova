# Copyright 2018 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures
import mock
import os.path

from oslo_utils import fileutils
from oslo_utils import units

from nova import conf
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier
import nova.tests.unit.image.fake as fake_image
from nova.tests.unit.virt.libvirt import fakelibvirt

CONF = conf.CONF


class _FakeFlat(object):
    def setUp(self):
        super(_FakeFlat, self).setUp()

        def fake_create_image(_self, prepare_template, base, size,
                              *args, **kwargs):
            # Simply ensure the file exists
            open(_self.path, 'a').close()

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.Flat.create_image',
            fake_create_image))


class _FlatTest(_FakeFlat):
    def setUp(self):
        super(_FlatTest, self).setUp()

        self.flags(group='libvirt', images_type='flat')

    def assert_disks_nonshared_instancedir(self, server):
        source_root_disk = os.path.join(self.source_instance_path(server),
                                        'disk')
        dest_root_disk = os.path.join(self.dest_instance_path(server),
                                      'disk')

        self.assertTrue(os.path.exists(source_root_disk),
                        "Source root disk %s does not exist" %
                        source_root_disk)
        self.assertFalse(os.path.exists(dest_root_disk),
                         "Destination root disk %s exists" % dest_root_disk)

    def assert_disks_shared_instancedir(self, server):
        source_root_disk = os.path.join(self.source_instance_path(server),
                                        'disk')

        # FIXME(mdbooth): We should not have deleted a shared root disk
        self.assertFalse(os.path.exists(source_root_disk),
                         "Source root disk %s exists" % source_root_disk)


# NOTE(mdbooth): The Rbd tests also need to mock the flat backend, because the
# image returned by the fake image service may (non-deterministically before
# python3.6 due to dict ordering) include a kernel and ramdisk. The libvirt
# driver forces these to use the flat backend.
class _RbdTest(_FakeFlat):
    def setUp(self):
        super(_RbdTest, self).setUp()

        self.flags(group='libvirt', images_type='rbd')

        self.created = set()

        def fake_create_image(_self, prepare_template, base, size,
                              *args, **kwargs):
            self.created.add(_self.rbd_name)

        def fake_exists(_self):
            return _self.rbd_name in self.created

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.Rbd.create_image',
            fake_create_image))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.Rbd.exists',
            fake_exists))

        # We never want to actually touch rbd
        self.mock_rbd_driver = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.storage.rbd_utils.RBDDriver')).mock.return_value
        self.mock_rbd_driver.get_mon_addrs.return_value = ([], [])
        self.mock_rbd_driver.size.return_value = 10 * units.Gi

        self.mock_cleanup_rbd = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.LibvirtDriver._cleanup_rbd')).mock

    def _assert_disks(self, server):
        # Check that we created a root disk and haven't called _cleanup_rbd at
        # all
        self.assertIn("%s_disk" % server['id'], self.created)
        # FIXME(mdbooth): we should not have deleted shared disks
        self.assertEqual(1, self.mock_cleanup_rbd.call_count)

    # We never want to cleanup rbd disks during evacuate, regardless of
    # instance shared storage
    assert_disks_nonshared_instancedir = _assert_disks
    assert_disks_shared_instancedir = _assert_disks


class _LibvirtEvacuateTest(integrated_helpers.InstanceHelperMixin):
    def _start_compute(self, name):
        # NOTE(mdbooth): fakelibvirt's getHostname currently returns a
        # hardcoded 'compute1', which is undesirable if we want multiple fake
        # computes. There's no good way to pre-initialise get_connection() to
        # return a fake libvirt with a custom return for getHostname.
        #
        # Here we mock the class during service creation to return our custom
        # hostname, but we can't leave this in place because then both computes
        # will still get the same value from their libvirt Connection. Once the
        # service has started, we poke a custom getHostname into the
        # instantiated object to do the same thing, but only for that object.

        with mock.patch.object(fakelibvirt.Connection, 'getHostname',
                               return_value=name):
            compute = self.start_service('compute', host=name)

        compute.driver._host.get_connection().getHostname = lambda: name
        return compute

    def setUp(self):
        super(_LibvirtEvacuateTest, self).setUp()

        self.useFixture(nova_fixtures.NeutronFixture(self))
        fake_network.set_stub_network_methods(self)
        self.useFixture(nova_fixtures.PlacementFixture())

        api_fixture = self.useFixture(
                nova_fixtures.OSAPIFixture(api_version='v2.1'))

        self.api = api_fixture.admin_api
        # force_down and evacuate without onSharedStorage
        self.api.microversion = '2.14'

        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        self.useFixture(fakelibvirt.FakeLibvirtFixture())

        self.start_service('conductor')
        self.start_service('scheduler')

        self.flags(compute_driver='libvirt.LibvirtDriver')
        self.compute0 = self._start_compute('compute0')

        # Choice of image id and flavor are arbitrary. Fixed for consistency.
        self.image_id = fake_image.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID
        self.flavor_id = next(flavor for flavor in self.api.get_flavors()
                              if flavor['name'] == 'm1.tiny')['id']

    @staticmethod
    def source_instance_path(server):
        return os.path.join(CONF.instances_path, server['id'])

    @staticmethod
    def dest_instance_path(server):
        return os.path.join(CONF.instances_path, 'dest', server['id'])

    def _create_server(self):
        create_req = {
            'name': 'server',
            'imageRef': self.image_id,
            'flavorRef': self.flavor_id,
        }
        server = self.api.post_server({'server': create_req})
        self.addCleanup(self.api.delete_server, server['id'])

        self._wait_for_state_change(self.api, server, 'ACTIVE')

        return server

    def _swap_computes(self):
        # Force compute0 down
        self.compute0.stop()
        self.api.force_down_service('compute0', 'nova-compute', True)

        # Start compute1
        self.compute1 = self._start_compute('compute1')

        # Create a 'pass-through' mock for ensure_tree so we can log its calls
        orig_ensure_tree = fileutils.ensure_tree
        self.mock_ensure_tree = self.useFixture(fixtures.MockPatch(
            'oslo_utils.fileutils.ensure_tree',
            side_effect=orig_ensure_tree)).mock

    def _evacuate_with_failure(self, server):
        # Perform an evacuation during which we experience a failure on the
        # destination host
        instance_uuid = server['id']

        with mock.patch.object(self.compute1.driver, 'plug_vifs') as plug_vifs:
            plug_vifs.side_effect = test.TestingException

            self.api.post_server_action(instance_uuid,
                                        {'evacuate': {'host': 'compute1'}})

            # Wait for the rebuild to start, then complete
            fake_notifier.wait_for_versioned_notifications(
                    'instance.rebuild.start')
            self._wait_for_server_parameter(self.api, server,
                                            {'OS-EXT-STS:task_state': None})

            # Meta-test
            plug_vifs.assert_called()

        # Return fresh server state after evacuate
        return self.api.get_server(instance_uuid)

    def test_evacuate_nonshared_instancedir(self):
        # If we fail during evacuate and the instance directory didn't
        # previously exist on the destination, we should delete it

        # Create an instance on compute0
        server = self._create_server()
        self._swap_computes()

        source_instance_path = self.source_instance_path(server)
        dest_instance_path = self.dest_instance_path(server)

        # Check that we've got an instance directory on the source and not on
        # the dest
        self.assertTrue(os.path.exists(source_instance_path),
                        "Source instance directory %s does not exist" %
                        source_instance_path)
        self.assertFalse(os.path.exists(dest_instance_path),
                         "Destination instance directory %s exists" %
                         dest_instance_path)

        # By default our 2 compute hosts share the same instance directory on
        # the test runner. Force a different directory while running evacuate
        # on compute1 so we don't have shared storage.
        def dest_get_instance_path(instance, relative=False):
            if relative:
                return instance.uuid
            return dest_instance_path

        with mock.patch('nova.virt.libvirt.utils.get_instance_path') \
                as get_instance_path:
            get_instance_path.side_effect = dest_get_instance_path
            server = self._evacuate_with_failure(server)

        # Check that we've got an instance directory on the source and not on
        # the dest, but that the dest was created
        self.assertTrue(os.path.exists(source_instance_path),
                        "Source instance directory %s does not exist" %
                        source_instance_path)
        self.assertFalse(os.path.exists(dest_instance_path),
                         "Destination instance directory %s exists" %
                         dest_instance_path)
        self.mock_ensure_tree.assert_called_with(dest_instance_path)

        self.assert_disks_nonshared_instancedir(server)

        # Check we're still on the failed source host
        self.assertEqual('compute0', server['OS-EXT-SRV-ATTR:host'])

    def test_evacuate_shared_instancedir(self):
        # If we fail during evacuate and the instance directory was already
        # present on the destination, we should leave it there

        # By default our 2 compute hosts share the same instance directory on
        # the test runner.

        # Create an instance on compute0
        server = self._create_server()
        self._swap_computes()

        shared_instance_path = self.source_instance_path(server)

        # Check that we've got an instance directory on the source
        self.assertTrue(os.path.exists(shared_instance_path),
                        "Shared instance directory %s does not exist" %
                        shared_instance_path)

        server = self._evacuate_with_failure(server)

        # Check that the instance directory still exists
        # FIXME(mdbooth): the shared instance directory should still exist
        self.assertFalse(os.path.exists(shared_instance_path),
                         "Shared instance directory %s exists" %
                         shared_instance_path)

        self.assert_disks_shared_instancedir(server)

        # Check we're still on the failed source host
        self.assertEqual('compute0', server['OS-EXT-SRV-ATTR:host'])


class LibvirtFlatEvacuateTest(_LibvirtEvacuateTest, _FlatTest, test.TestCase):
    pass


class LibvirtRbdEvacuateTest(_LibvirtEvacuateTest, _RbdTest, test.TestCase):
    pass
