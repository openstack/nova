# Copyright (C) 2020 Red Hat, Inc.
# All Rights Reserved.
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

import mock

from castellan.common.objects import passphrase
from castellan.key_manager import key_manager
from oslo_log import log as logging
from oslo_utils import uuidutils
from oslo_utils import versionutils

import nova.conf
from nova import context as nova_context
from nova import crypto
from nova import exception
from nova import objects
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class FakeKeyManager(key_manager.KeyManager):
    """A fake key manager.

    This key manager implementation supports a minimum subset of methods
    specified by the key manager interface that are required for vTPM. Side
    effects (e.g., raising exceptions) for each method are handled as specified
    by the key manager interface.
    """

    def __init__(self, configuration):
        super().__init__(configuration)

        #: A mapping of UUIDs to passphrases.
        self._passphrases = {}

    def create_key(self, context, algorithm, length, **kwargs):
        """Creates a symmetric key.

        This is not implemented as it's unnecessary here.
        """
        raise NotImplementedError(
            "FakeKeyManager does not support symmetric keys"
        )

    def create_key_pair(self, context, **kwargs):
        """Creates an asymmetric keypair.

        This is not implemented as it's unnecessary here.
        """
        raise NotImplementedError(
            "FakeKeyManager does not support asymmetric keys"
        )

    def store(self, context, managed_object, **kwargs):
        """Stores (i.e., registers) a passphrase with the key manager."""
        if context is None:
            raise exception.Forbidden()

        if not isinstance(managed_object, passphrase.Passphrase):
            raise exception.KeyManagerError(
                reason='cannot store anything except passphrases')

        uuid = uuidutils.generate_uuid()
        managed_object._id = uuid  # set the id to simulate persistence
        self._passphrases[uuid] = managed_object

        return uuid

    def get(self, context, managed_object_id):
        """Retrieves the key identified by the specified id.

        This implementation returns the key that is associated with the
        specified UUID. A Forbidden exception is raised if the specified
        context is None; a KeyError is raised if the UUID is invalid.
        """
        if context is None:
            raise exception.Forbidden()

        if managed_object_id not in self._passphrases:
            raise KeyError('cannot retrieve non-existent secret')

        return self._passphrases[managed_object_id]

    def delete(self, context, managed_object_id):
        """Represents deleting the key.

        Simply delete the key from our list of keys.
        """
        if context is None:
            raise exception.Forbidden()

        if managed_object_id not in self._passphrases:
            raise exception.KeyManagerError(
                reason="cannot delete non-existent secret")

        del self._passphrases[managed_object_id]


class VTPMServersTest(base.ServersTestBase):

    # many move operations are admin-only
    ADMIN_API = True

    def setUp(self):
        # enable vTPM and use our own fake key service
        self.flags(swtpm_enabled=True, group='libvirt')
        self.flags(
            backend='nova.tests.functional.libvirt.test_vtpm.FakeKeyManager',
            group='key_manager')

        super().setUp()

        # mock the '_check_vtpm_support' function which validates things like
        # the presence of users on the host, none of which makes sense here
        _p = mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver._check_vtpm_support')
        self.mock_conn = _p.start()
        self.addCleanup(_p.stop)

        self.key_mgr = crypto._get_key_manager()

    # TODO(stephenfin): This should be moved to the base class
    def start_compute(self, hostname='compute1'):
        libvirt_version = versionutils.convert_version_to_int(
            driver.MIN_LIBVIRT_VTPM)
        fake_connection = self._get_connection(
            libvirt_version=libvirt_version, hostname=hostname)

        # This is fun. Firstly we need to do a global'ish mock so we can
        # actually start the service.
        with mock.patch(
            'nova.virt.libvirt.host.Host.get_connection',
            return_value=fake_connection,
        ):
            compute = self.start_service('compute', host=hostname)
            # Once that's done, we need to tweak the compute "service" to
            # make sure it returns unique objects. We do this inside the
            # mock context to avoid a small window between the end of the
            # context and the tweaking where get_connection would revert to
            # being an autospec mock.
            compute.driver._host.get_connection = lambda: fake_connection

        return compute

    def _create_server_with_vtpm(self):
        extra_specs = {'hw:tpm_model': 'tpm-tis', 'hw:tpm_version': '1.2'}
        flavor_id = self._create_flavor(extra_spec=extra_specs)
        server = self._create_server(flavor_id=flavor_id)

        return server

    def _create_server_without_vtpm(self):
        # use the default flavor (i.e. one without vTPM extra specs)
        return self._create_server()

    def assertInstanceHasSecret(self, server):
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertIn('vtpm_secret_uuid', instance.system_metadata)
        self.assertEqual(1, len(self.key_mgr._passphrases))
        self.assertIn(
            instance.system_metadata['vtpm_secret_uuid'],
            self.key_mgr._passphrases)

    def assertInstanceHasNoSecret(self, server):
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertNotIn('vtpm_secret_uuid', instance.system_metadata)
        self.assertEqual(0, len(self.key_mgr._passphrases))

    def test_create_server(self):
        self.compute = self.start_compute()

        # ensure we are reporting the correct traits
        root_rp_uuid = self._get_provider_uuid_by_name(self.compute.host)
        traits = self._get_provider_traits(root_rp_uuid)
        for trait in ('COMPUTE_SECURITY_TPM_1_2', 'COMPUTE_SECURITY_TPM_2_0'):
            self.assertIn(trait, traits)

        # create a server with vTPM
        server = self._create_server_with_vtpm()

        # ensure our instance's system_metadata field and key manager inventory
        # is correct
        self.assertInstanceHasSecret(server)

        # now delete the server
        self._delete_server(server)

        # ensure we deleted the key now that we no longer need it
        self.assertEqual(0, len(self.key_mgr._passphrases))

    def test_suspend_resume_server(self):
        self.compute = self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # suspend the server
        server = self._suspend_server(server)

        # ensure our instance's system_metadata field and key manager inventory
        # is correct
        self.assertInstanceHasSecret(server)

        # resume the server
        server = self._resume_server(server)

        # ensure our instance's system_metadata field and key manager inventory
        # is still correct
        self.assertInstanceHasSecret(server)

    def test_soft_reboot_server(self):
        self.compute = self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm()

        # soft reboot the server
        server = self._reboot_server(server, hard=False)
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field and key manager inventory
        # is still correct
        self.assertInstanceHasSecret(server)

    def test_hard_reboot_server(self):
        self.compute = self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # hard reboot the server
        server = self._reboot_server(server, hard=True)

        # ensure our instance's system_metadata field and key manager inventory
        # is still correct
        self.assertInstanceHasSecret(server)

    def test_resize_server__no_vtpm_to_vtpm(self):
        self.computes = {}
        for host in ('test_compute0', 'test_compute1'):
            self.computes[host] = self.start_compute(host)

        # create a server without vTPM
        server = self._create_server_without_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field and key manager inventory
        # is correct
        self.assertInstanceHasNoSecret(server)

        # create a flavor with vTPM
        extra_specs = {'hw:tpm_model': 'tpm-tis', 'hw:tpm_version': '1.2'}
        flavor_id = self._create_flavor(extra_spec=extra_specs)

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # resize the server to a new flavor *with* vTPM
            server = self._resize_server(server, flavor_id=flavor_id)

        # ensure our instance's system_metadata field and key manager inventory
        # is updated to reflect the new vTPM requirement
        self.assertInstanceHasSecret(server)

        # revert the instance rather than confirming it, and ensure the secret
        # is correctly cleaned up

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # revert back to the old flavor *without* vTPM
            server = self._revert_resize(server)

        # ensure we delete the new key since we no longer need it
        self.assertInstanceHasNoSecret(server)

    def test_resize_server__vtpm_to_no_vtpm(self):
        self.computes = {}
        for host in ('test_compute0', 'test_compute1'):
            self.computes[host] = self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        # create a flavor without vTPM
        flavor_id = self._create_flavor()

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # resize the server to a new flavor *without* vTPM
            server = self._resize_server(server, flavor_id=flavor_id)

        # ensure we still have the key for the vTPM device in storage in case
        # we revert
        self.assertInstanceHasSecret(server)

        # confirm the instance and ensure the secret is correctly cleaned up

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # revert back to the old flavor *with* vTPM
            server = self._confirm_resize(server)

        # ensure we have finally deleted the key for the vTPM device since
        # there is no going back now
        self.assertInstanceHasNoSecret(server)

    def test_migrate_server(self):
        self.computes = {}
        for host in ('test_compute0', 'test_compute1'):
            self.computes[host] = self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # cold migrate the server
            self._migrate_server(server)

        # ensure nothing has changed
        self.assertInstanceHasSecret(server)

    def test_live_migrate_server(self):
        self.computes = {}
        for host in ('test_compute0', 'test_compute1'):
            self.computes[host] = self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        # live migrate the server
        self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate_server, server)

    def test_shelve_server(self):
        self.computes = {}
        for host in ('test_compute0', 'test_compute1'):
            self.computes[host] = self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        # attempt to shelve the server
        self.assertRaises(
            client.OpenStackApiException,
            self._shelve_server, server)
