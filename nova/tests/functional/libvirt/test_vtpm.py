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

from unittest import mock

from castellan.common import exception as castellan_exc
from castellan.common.objects import passphrase
from castellan.key_manager import key_manager
import ddt
import fixtures
from oslo_log import log as logging
from oslo_utils import uuidutils

import nova.conf
from nova import context as nova_context
from nova import crypto
from nova import exception
from nova import objects
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova import utils

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

        #: A mapping of UUIDs to RequestContext objects.
        self._contexts = {}

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
        self._contexts[uuid] = context

        return uuid

    def get(self, context, managed_object_id):
        """Retrieves the key identified by the specified id.

        This implementation returns the key that is associated with the
        specified UUID. A Forbidden exception is raised if the specified
        context is None; a KeyError is raised if the UUID is invalid.
        """
        if context is None:
            raise exception.Forbidden()

        if context.user_id != self._contexts[managed_object_id].user_id:
            raise castellan_exc.KeyManagerError(
                'Key manager error: Forbidden: Secret payload retrieval '
                'attempt not allowed - please review your user/project '
                'privileges')

        if managed_object_id not in self._passphrases:
            raise KeyError('cannot retrieve non-existent secret')

        return self._passphrases[managed_object_id]

    def delete(self, context, managed_object_id):
        """Represents deleting the key.

        Simply delete the key from our list of keys.
        """
        if context is None:
            raise exception.Forbidden()

        if context.user_id != self._contexts[managed_object_id].user_id:
            raise castellan_exc.KeyManagerError(
                'Key manager error: Forbidden: Secret payload retrieval '
                'attempt not allowed - please review your user/project '
                'privileges')

        if managed_object_id not in self._passphrases:
            raise exception.KeyManagerError(
                reason="cannot delete non-existent secret")

        del self._passphrases[managed_object_id]
        del self._contexts[managed_object_id]

    def add_consumer(self, context, managed_object_id, consumer_data):
        raise NotImplementedError(
            'FakeKeyManager does not implement adding consumers'
        )

    def remove_consumer(self, context, managed_object_id, consumer_data):
        raise NotImplementedError(
            'FakeKeyManager does not implement removing consumers'
        )


@ddt.ddt
class VTPMServersTest(base.ServersTestBase):

    # NOTE: ADMIN_API is intentionally not set to True in order to catch key
    # manager service secret ownership issues.

    # Reflect reality more for async API requests like migration
    CAST_AS_CALL = False

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
        _p.start()
        self.addCleanup(_p.stop)

        self.key_mgr = crypto._get_key_manager()

    def _create_server_with_vtpm(self, secret_security=None,
                                 expected_state='ACTIVE'):
        extra_specs = {'hw:tpm_model': 'tpm-tis', 'hw:tpm_version': '1.2'}
        if secret_security:
            extra_specs.update({'hw:tpm_secret_security': secret_security})
        flavor_id = self._create_flavor(extra_spec=extra_specs)
        server = self._create_server(flavor_id=flavor_id,
                                     expected_state=expected_state)

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
        return instance.system_metadata['vtpm_secret_uuid']

    def assertInstanceHasNoSecret(self, server):
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        self.assertNotIn('vtpm_secret_uuid', instance.system_metadata)
        self.assertEqual(0, len(self.key_mgr._passphrases))

    def _assert_libvirt_has_secret(self, host, instance_uuid):
        s = host.driver._host.find_secret('vtpm', instance_uuid)
        self.assertIsNotNone(s)
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, instance_uuid)
        secret_uuid = instance.system_metadata['vtpm_secret_uuid']
        self.assertEqual(secret_uuid, s.UUIDString())

    def _assert_libvirt_had_secret(self, compute, secret_uuid):
        # This assert is for ephemeral private libvirt secrets that we
        # undefine immediately after guest creation. Examples include 'user'
        # and 'deployment' TPM secret security modes and legacy servers.
        # The LibvirtFixture tracks secrets that existed before they were
        # removed, so we can assert this.
        conn = compute.driver._host.get_connection()
        self.assertIn(secret_uuid, conn._removed_secrets)

    def _assert_libvirt_secret_missing(self, host, instance_uuid):
        s = host.driver._host.find_secret('vtpm', instance_uuid)
        self.assertIsNone(s)

    def test_tpm_secret_security_user(self):
        self.flags(supported_tpm_secret_security=['user'], group='libvirt')
        host = self.start_compute(hostname='tpm-host')
        compute = self.computes['tpm-host']

        # ensure we are reporting the correct traits
        traits = self._get_provider_traits(self.compute_rp_uuids[host])
        self.assertIn('COMPUTE_SECURITY_TPM_SECRET_SECURITY_USER', traits)

        server = self._create_server_with_vtpm(secret_security='user')

        # The server should have a secret in the key manager service.
        secret_uuid = self.assertInstanceHasSecret(server)

        # And it should have had a libvirt secret created and undefined.
        self._assert_libvirt_had_secret(compute, secret_uuid)

    def test_tpm_secret_security_user_negative(self):
        self.flags(supported_tpm_secret_security=['deployment'],
                   group='libvirt')
        self.start_compute(hostname='tpm-host')
        self._create_server_with_vtpm(secret_security='user',
                                      expected_state='ERROR')

    def test_create_server(self):
        compute = self.start_compute()

        # ensure we are reporting the correct traits
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
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

    def test_create_server_secret_security_host(self):
        self.flags(supported_tpm_secret_security=['host'], group='libvirt')
        compute = self.start_compute()

        # ensure we are reporting the correct traits
        traits = self._get_provider_traits(self.compute_rp_uuids[compute])
        self.assertIn('COMPUTE_SECURITY_TPM_SECRET_SECURITY_HOST', traits)

        # create a server with vTPM
        server = self._create_server_with_vtpm(secret_security='host')

        # ensure our instance's system_metadata field and key manager inventory
        # is correct
        self.assertInstanceHasSecret(server)

        # ensure the libvirt secret is defined correctly
        ctx = nova_context.get_admin_context()
        instance = objects.Instance.get_by_uuid(ctx, server['id'])
        conn = self.computes[compute].driver._host.get_connection()
        secret = conn._secrets[instance.system_metadata['vtpm_secret_uuid']]
        self.assertFalse(secret._ephemeral)
        self.assertFalse(secret._private)

        # now delete the server
        self._delete_server(server)

        # ensure we deleted the key and undefined the secret now that we no
        # longer need it
        self.assertEqual(0, len(self.key_mgr._passphrases))
        self.assertNotIn(instance.system_metadata['vtpm_secret_uuid'],
                         conn._secrets)

    def test_suspend_resume_server(self):
        self.start_compute()

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
        self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm()

        # soft reboot the server
        server = self._reboot_server(server, hard=False)
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field and key manager inventory
        # is still correct
        self.assertInstanceHasSecret(server)

    def test_hard_reboot_server(self):
        self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # hard reboot the server
        server = self._reboot_server(server, hard=True)

        # ensure our instance's system_metadata field and key manager inventory
        # is still correct
        self.assertInstanceHasSecret(server)

    @ddt.data(None, 'user', 'host')
    def test_hard_reboot_server_as_admin(self, secret_security):
        """Test hard rebooting a non-admin user's instance as admin.

        This should only work for the 'host' TPM secret security policy.
        """
        self.start_compute()

        # create a server with vTPM
        server = self._create_server_with_vtpm(secret_security=secret_security)

        # Attempt to reboot the server as admin, should only work for 'host'.
        if secret_security == 'host':
            self._reboot_server(server, hard=True, api=self.admin_api)
        else:
            self._reboot_server(server, hard=True, expected_state='ERROR',
                                api=self.admin_api)

    def _test_resize_revert_server__vtpm_to_vtpm(self, extra_specs=None):
        """Test behavior of revert when a vTPM is retained across a resize.

        Other tests cover going from no vTPM => vTPM and vice versa.
        """
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

        server = self._create_server_with_vtpm()

        # Create a different flavor with a vTPM.
        extra_specs = extra_specs or {
            'hw:tpm_model': 'tpm-tis', 'hw:tpm_version': '1.2'}
        flavor_id = self._create_flavor(extra_spec=extra_specs)

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._resize_server(server, flavor_id=flavor_id)

        # ensure our instance's system_metadata field and key manager inventory
        # is updated to reflect the new vTPM requirement
        self.assertInstanceHasSecret(server)

        # revert the instance rather than confirming it, and ensure the secret
        # is correctly cleaned up

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._revert_resize(server)

        # Should still have a secret because we had a vTPM before too.
        self.assertInstanceHasSecret(server)

    def test_resize_revert_server__vtpm_to_vtpm_same_config(self):
        self._test_resize_revert_server__vtpm_to_vtpm()

    def test_resize_revert_server__vtpm_to_vtpm_different_config(self):
        extra_specs = {'hw:tpm_model': 'tpm-tis', 'hw:tpm_version': '2.0'}
        self._test_resize_revert_server__vtpm_to_vtpm(
            extra_specs=extra_specs)

    def test_resize_server__no_vtpm_to_vtpm(self):
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

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
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

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

    def test_create_server_secret_security_unsupported(self):
        """Test when a not supported TPM secret security mode is requested

        We expect the create to fail for NoValidHost.
        """
        # Start a compute host which supports no modes.
        self.flags(supported_tpm_secret_security=[], group='libvirt')
        self.start_compute('test_compute0')

        # Try to create an instance on that host defaulting to 'user'.
        server = self._create_server_with_vtpm(expected_state='ERROR')

        # The create should have failed for NoValidHost.
        event = self._wait_for_instance_action_event(
            server, 'create', 'conductor_schedule_and_build_instances',
            'Error')
        self.assertIn('NoValidHost', event['traceback'])

    def test_migrate_server(self):
        """Test cold migrate as a non-admin user.

        Cold migrate policy defaults to admin-only but this will not currently
        work as admin due to key manager service secret ownership.
        """
        # Allow non-admin to cold migrate a server.
        rules = {
            'os_compute_api:os-migrate-server:migrate': 'rule:admin_or_owner'}
        self.policy.set_rules(rules, overwrite=False)

        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

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

    def test_migrate_server_as_admin(self):
        """Test cold migrate as an admin user.

        Cold migrate policy defaults to admin-only but this will not currently
        work as admin due to key manager service secret ownership.
        """
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # cold migrate the server
            self._migrate_server(
                    server, expected_state='ERROR', api=self.admin_api)

        # Migration should have failed due to permissions error.
        # Need microversion 2.84 to get events.details field.
        with utils.temporary_mutation(self.admin_api, microversion='2.84'):
            event = self._wait_for_instance_action_event(
                server, 'migrate', 'compute_finish_resize', 'Error')
            msg = ('Key manager error: Forbidden: Secret payload retrieval '
                   'attempt not allowed - please review your user/project '
                   'privileges')
            self.assertIn(msg, event['details'])

    def test_live_migrate_server(self):
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

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
        for host in ('test_compute0', 'test_compute1'):
            self.start_compute(host)

        # create a server with vTPM
        server = self._create_server_with_vtpm()
        self.addCleanup(self._delete_server, server)

        # ensure our instance's system_metadata field is correct
        self.assertInstanceHasSecret(server)

        # attempt to shelve the server
        self.assertRaises(
            client.OpenStackApiException,
            self._shelve_server, server)


class VTPMServersTestNonShared(VTPMServersTest):

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.MockPatch(
            'nova.compute.manager.ComputeManager._is_instance_storage_shared',
            return_value=False))
