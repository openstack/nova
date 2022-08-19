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

from oslo_utils.fixture import uuidsentinel

from nova import context
from nova import objects
from nova.tests.functional import integrated_helpers


class _TestEphemeralEncryptionBase(
    integrated_helpers.ProviderUsageBaseTestCase
):
    # NOTE(lyarwood): A dict of test flavors defined per test class,
    # keyed by flavor name and providing an additional dict containing an 'id'
    # and optional 'extra_specs' dict. For example:
    #   {
    #       'name': {
    #           'id': uuidsentinel.flavor_id
    #           'extra_specs': {
    #               'hw:foo': 'bar'
    #           }
    #       }
    #   }
    flavors = {}

    def setUp(self):
        super().setUp()

        self.ctxt = context.get_admin_context()

        # Create the required test flavors
        for name, details in self.flavors.items():
            flavor = self.admin_api.post_flavor({
                'flavor': {
                    'name': name,
                    'id': details['id'],
                    'ram': 512,
                    'vcpus': 1,
                    'disk': 1024,
                }
            })
            # Add the optional extra_specs
            if details.get('extra_specs'):
                self.admin_api.post_extra_spec(
                    flavor['id'], {'extra_specs': details['extra_specs']})

        # We only need a single compute for these tests
        self._start_compute(host='compute1')

    def _assert_ephemeral_encryption_enabled(
            self, server_id, encryption_format=None):
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.ctxt, server_id)
        for bdm in bdms:
            if bdm.is_local:
                self.assertTrue(bdm.encrypted)
                if encryption_format:
                    self.assertEqual(
                        encryption_format, bdm.encryption_format)

    def _assert_ephemeral_encryption_disabled(self, server_id):
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.ctxt, server_id)
        for bdm in bdms:
            if bdm.is_local:
                self.assertFalse(bdm.encrypted)


class TestEphemeralEncryptionAvailable(_TestEphemeralEncryptionBase):

    compute_driver = 'fake.EphEncryptionDriver'
    flavors = {
        'no_eph_encryption': {
            'id': uuidsentinel.no_eph_encryption
        },
        'eph_encryption': {
            'id': uuidsentinel.eph_encryption_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True'
            }
        },
        'eph_encryption_disabled': {
            'id': uuidsentinel.eph_encryption_disabled_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'False'
            }
        },
    }

    def test_image_requested(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(server_id)

    def test_image_disabled(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption_disabled,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_disabled(server_id)

    def test_flavor_requested(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_flavor,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(server_id)

    def test_flavor_disabled(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_disabled_flavor,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_disabled(server_id)

    def test_flavor_and_image_requested(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_flavor,
            image_uuid=uuidsentinel.eph_encryption,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(server_id)

    def test_flavor_and_image_disabled(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_disabled_flavor,
            image_uuid=uuidsentinel.eph_encryption_disabled,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_disabled(server_id)

    def test_flavor_requested_and_image_disabled(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_flavor,
            image_uuid=uuidsentinel.eph_encryption_disabled,
            networks=[])
        self._assert_bad_build_request_error(server_request)

    def test_flavor_disabled_and_image_requested(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_disabled_flavor,
            image_uuid=uuidsentinel.eph_encryption,
            networks=[])
        self._assert_bad_build_request_error(server_request)


class TestEphemeralEncryptionUnavailable(_TestEphemeralEncryptionBase):

    compute_driver = 'fake.MediumFakeDriver'
    flavors = {
        'no_eph_encryption': {
            'id': uuidsentinel.no_eph_encryption
        },
        'eph_encryption': {
            'id': uuidsentinel.eph_encryption_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True'
            }
        },
        'eph_encryption_disabled': {
            'id': uuidsentinel.eph_encryption_disabled_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'False'
            }
        },
    }

    def test_requested_but_unavailable(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_flavor,
            image_uuid=uuidsentinel.eph_encryption,
            networks=[])
        self._assert_build_request_schedule_failure(server_request)

    def test_image_disabled(self):
        server_request = self._build_server(
            image_uuid=uuidsentinel.eph_encryption_disabled,
            flavor_id=uuidsentinel.no_eph_encryption,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_disabled(server_id)

    def test_flavor_disabled(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_disabled_flavor,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_disabled(server_id)


class TestEphemeralEncryptionLUKS(TestEphemeralEncryptionAvailable):

    compute_driver = 'fake.EphEncryptionDriverLUKS'
    flavors = {
        'no_eph_encryption': {
            'id': uuidsentinel.no_eph_encryption
        },
        'eph_encryption': {
            'id': uuidsentinel.eph_encryption_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True'
            }
        },
        'eph_encryption_disabled': {
            'id': uuidsentinel.eph_encryption_disabled_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'False'
            }
        },
        'eph_encryption_luks': {
            'id': uuidsentinel.eph_encryption_luks_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True',
                'hw:ephemeral_encryption_format': 'luks'
            }
        },
        'eph_encryption_plain': {
            'id': uuidsentinel.eph_encryption_plain_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True',
                'hw:ephemeral_encryption_format': 'plain'
            }
        },

    }

    def test_image_requested_luks(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption_luks,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='luks')

    def test_flavor_requested_luks(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_luks_flavor,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='luks')

    def test_flavor_and_image_requested_luks(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_luks_flavor,
            image_uuid=uuidsentinel.eph_encryption_luks,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='luks')

    def test_image_requested_plain(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption_plain,
            networks=[])
        self._assert_build_request_schedule_failure(server_request)

    def test_flavor_requested_plain(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_plain_flavor,
            networks=[])
        self._assert_build_request_schedule_failure(server_request)

    def test_image_requested_luks_flavor_requested_plain(self):
        server_request = self._build_server(
            image_uuid=uuidsentinel.eph_encryption_luks,
            flavor_id=uuidsentinel.eph_encryption_plain_flavor,
            networks=[])
        self._assert_bad_build_request_error(server_request)

    def test_image_requested_plain_flavor_requested_luks(self):
        server_request = self._build_server(
            image_uuid=uuidsentinel.eph_encryption_plain,
            flavor_id=uuidsentinel.eph_encryption_luks_flavor,
            networks=[])
        self._assert_bad_build_request_error(server_request)


class TestEphemeralEncryptionPLAIN(_TestEphemeralEncryptionBase):

    compute_driver = 'fake.EphEncryptionDriverPLAIN'
    flavors = {
        'no_eph_encryption': {
            'id': uuidsentinel.no_eph_encryption
        },
        'eph_encryption': {
            'id': uuidsentinel.eph_encryption_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True'
            }
        },
        'eph_encryption_disabled': {
            'id': uuidsentinel.eph_encryption_disabled_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'False'
            }
        },
        'eph_encryption_luks': {
            'id': uuidsentinel.eph_encryption_luks_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True',
                'hw:ephemeral_encryption_format': 'luks'
            }
        },
        'eph_encryption_plain': {
            'id': uuidsentinel.eph_encryption_plain_flavor,
            'extra_specs': {
                'hw:ephemeral_encryption': 'True',
                'hw:ephemeral_encryption_format': 'plain'
            }
        },
    }

    def test_image_requested_plain(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption_plain,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='plain')

    def test_flavor_requested_plain(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_plain_flavor,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='plain')

    def test_flavor_and_image_requested_plain(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_plain_flavor,
            image_uuid=uuidsentinel.eph_encryption_plain,
            networks=[])
        server_id = self._assert_build_request_success(server_request)
        self._assert_ephemeral_encryption_enabled(
            server_id, encryption_format='plain')

    def test_image_requested_luks(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.no_eph_encryption,
            image_uuid=uuidsentinel.eph_encryption_luks,
            networks=[])
        self._assert_build_request_schedule_failure(server_request)

    def test_flavor_requested_luks(self):
        server_request = self._build_server(
            flavor_id=uuidsentinel.eph_encryption_luks_flavor,
            networks=[])
        self._assert_build_request_schedule_failure(server_request)

    def test_image_requested_plain_flavor_requested_luks(self):
        server_request = self._build_server(
            image_uuid=uuidsentinel.eph_encryption_plain,
            flavor_id=uuidsentinel.eph_encryption_luks_flavor,
            networks=[])
        self._assert_bad_build_request_error(server_request)

    def test_image_requested_luks_flavor_requested_plain(self):
        server_request = self._build_server(
            image_uuid=uuidsentinel.eph_encryption_luks,
            flavor_id=uuidsentinel.eph_encryption_plain_flavor,
            networks=[])
        self._assert_bad_build_request_error(server_request)
