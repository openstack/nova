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

import collections
import copy

import fixtures


def _get_device_profile(dp_name, trait):
    dp = [
        {
            'name': dp_name,
            'uuid': 'cbec22f3-ac29-444e-b4bb-98509f32faae',
            'groups': [
                {
                    'resources:FPGA': '1',
                    'trait:' + trait: 'required',
                },
            ],
            # Skipping links key in Cyborg API return value
        },
    ]
    return dp


def get_arqs(dp_name):
    arq = {
        'uuid': 'b59d34d3-787b-4fb0-a6b9-019cd81172f8',
        'device_profile_name': dp_name,
        'device_profile_group_id': 0,
        'state': 'Initial',
        'device_rp_uuid': None,
        'hostname': None,
        'instance_uuid': None,
        'attach_handle_info': {},
        'attach_handle_type': '',
    }
    bound_arq = copy.deepcopy(arq)
    bound_arq.update({
        'state': 'Bound',
        'attach_handle_type': 'TEST_PCI',
        'attach_handle_info': {
            'bus': '0c',
            'device': '0',
            'domain': '0000',
            'function': '0'
        },
    })
    return [arq], [bound_arq]


class CyborgFixture(fixtures.Fixture):
    """Fixture that mocks Cyborg APIs used by nova/accelerator/cyborg.py"""

    dp_name = 'fakedev-dp'
    trait = 'CUSTOM_FAKE_DEVICE'
    arq_list, bound_arq_list = get_arqs(dp_name)

    # NOTE(Sundar): The bindings passed to the fake_bind_arqs() from the
    # conductor are indexed by ARQ UUID and include the host name, device
    # RP UUID and instance UUID. (See params to fake_bind_arqs below.)
    #
    # Later, when the compute manager calls fake_get_arqs_for_instance() with
    # the instance UUID, the returned ARQs must contain the host name and
    # device RP UUID. But these can vary from test to test.
    #
    # So, fake_bind_arqs() below takes bindings indexed by ARQ UUID and
    # converts them to bindings indexed by instance UUID, which are then
    # stored in the dict below. This dict looks like:
    # { $instance_uuid: [
    #      {'hostname': $hostname,
    #       'device_rp_uuid': $device_rp_uuid,
    #       'arq_uuid': $arq_uuid
    #      }
    #   ]
    # }
    # Since it is indexed by instance UUID, and that is presumably unique
    # across concurrently executing tests, this should be safe for
    # concurrent access.
    bindings_by_instance = {}

    def setUp(self):
        super().setUp()
        self.mock_get_dp = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient._get_device_profile_list',
            return_value=_get_device_profile(self.dp_name, self.trait))).mock
        self.mock_create_arqs = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient._create_arqs',
            return_value=self.arq_list)).mock
        self.mock_bind_arqs = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.bind_arqs',
            side_effect=self.fake_bind_arqs)).mock
        self.mock_get_arqs = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.'
            'get_arqs_for_instance',
            side_effect=self.fake_get_arqs_for_instance)).mock
        self.mock_del_arqs = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.'
            'delete_arqs_for_instance',
            side_effect=self.fake_delete_arqs_for_instance)).mock

    @staticmethod
    def fake_bind_arqs(bindings):
        """Simulate Cyborg ARQ bindings.

        Since Nova calls Cyborg for binding on per-instance basis, the
        instance UUIDs would be the same for all ARQs in a single call.

        This function converts bindings indexed by ARQ UUID to bindings
        indexed by instance UUID, so that fake_get_arqs_for_instance can
        retrieve them later.

        :param bindings:
               { "$arq_uuid": {
                     "hostname": STRING
                     "device_rp_uuid": UUID
                     "instance_uuid": UUID
                  },
                  ...
                }
        :returns: None
        """
        binding_by_instance = collections.defaultdict(list)
        for index, arq_uuid in enumerate(bindings):
            arq_binding = bindings[arq_uuid]
            # instance_uuid is same for all ARQs in a single call.
            instance_uuid = arq_binding['instance_uuid']
            newbinding = {
                'hostname': arq_binding['hostname'],
                'device_rp_uuid': arq_binding['device_rp_uuid'],
                'arq_uuid': arq_uuid,
            }
            binding_by_instance[instance_uuid].append(newbinding)

        CyborgFixture.bindings_by_instance.update(binding_by_instance)

    @staticmethod
    def fake_get_arqs_for_instance(instance_uuid, only_resolved=False):
        """Get list of bound ARQs for this instance.

           This function uses bindings indexed by instance UUID to
           populate the bound ARQ templates in CyborgFixture.bound_arq_list.
        """
        arq_host_rp_list = CyborgFixture.bindings_by_instance.get(
            instance_uuid)
        if not arq_host_rp_list:
            return []

        # The above looks like:
        # [{'hostname': $hostname,
        #   'device_rp_uuid': $device_rp_uuid,
        #   'arq_uuid': $arq_uuid
        #  }]

        bound_arq_list = copy.deepcopy(CyborgFixture.bound_arq_list)
        for arq in bound_arq_list:
            match = [
                (
                    arq_host_rp['hostname'],
                    arq_host_rp['device_rp_uuid'],
                    instance_uuid,
                )
                for arq_host_rp in arq_host_rp_list
                if arq_host_rp['arq_uuid'] == arq['uuid']
            ]
            # Only 1 ARQ UUID would match, so len(match) == 1
            arq['hostname'], arq['device_rp_uuid'], arq['instance_uuid'] = (
                match[0][0], match[0][1], match[0][2],
            )
        return bound_arq_list

    @staticmethod
    def fake_delete_arqs_for_instance(instance_uuid):
        CyborgFixture.bindings_by_instance.pop(instance_uuid, None)
