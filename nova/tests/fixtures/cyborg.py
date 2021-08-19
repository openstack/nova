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

import copy

import fixtures
from oslo_config import cfg
from oslo_log import log as logging

from nova import exception


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _get_device_profile(dp_name, trait):
    dp = {
        'fakedev-dp': [
            {
                'name': 'fakedev-dp',
                'uuid': 'cbec22f3-ac29-444e-b4bb-98509f32faae',
                'groups': [
                    {
                        'resources:FPGA': 1,
                        'trait:' + trait: 'required',
                    },
                ],
                # Skipping links key in Cyborg API return value
            },
            ],
        'fakedev-dp-port': [
            {
                'name': 'fakedev-dp',
                'uuid': 'cbec22f3-ac29-444e-b4bb-98509f32faae',
                'groups': [
                    {
                        'resources:FPGA': 1,
                        'trait:' + trait: 'required',
                    },
                ],
                # Skipping links key in Cyborg API return value
            },
         ],
         'fakedev-dp-multi': [
            {
                'name': 'fakedev-dp-multi',
                'uuid': 'cbec22f3-ac29-444e-b4bb-98509f32faae',
                'groups': [
                    {
                        'resources:FPGA': 2,
                        'resources:FPGA2': 1,
                        'trait:' + trait: 'required',
                    },
                ],
                # Skipping links key in Cyborg API return value
            },
          ],
        }
    return dp[dp_name]


def get_arqs(dp_name):
    # prepare fixture arqs and bound info
    arqs = [
        {
        'uuid': 'b59d34d3-787b-4fb0-a6b9-019cd81172f8',
        'device_profile_name': dp_name,
        'device_profile_group_id': 0,
        'state': 'Initial',
        'device_rp_uuid': None,
        'hostname': None,
        'instance_uuid': None,
        'attach_handle_info': {},
        'attach_handle_type': '',
        },
        {'uuid': '73d5f9f3-23e9-4b45-909a-e8a1db4cf24c',
        'device_profile_name': dp_name,
        'device_profile_group_id': 0,
        'state': 'Initial',
        'device_rp_uuid': None,
        'hostname': None,
        'instance_uuid': None,
        'attach_handle_info': {},
        'attach_handle_type': '',
        },
        {'uuid': '69b83caf-dd1c-493d-8796-40af5a16e3f6',
        'device_profile_name': dp_name,
        'device_profile_group_id': 0,
        'state': 'Initial',
        'device_rp_uuid': None,
        'hostname': None,
        'instance_uuid': None,
        'attach_handle_info': {},
        'attach_handle_type': '',
        },
        {'uuid': 'e5fc1da7-216b-4102-a50d-43ba77bcacf7',
        'device_profile_name': dp_name,
        'device_profile_group_id': 0,
        'state': 'Initial',
        'device_rp_uuid': None,
        'hostname': None,
        'instance_uuid': None,
        'attach_handle_info': {},
        'attach_handle_type': '',
        }
    ]
    # arqs bound info
    attach_handle_list = [
        {
            'bus': '0c',
            'device': '0',
            'domain': '0000',
            'function': '1',
            'physical_network': 'PHYNET1'
        },
        {
            'bus': '0c',
            'device': '0',
            'domain': '0000',
            'function': '2',
            'physical_network': 'PHYNET1'
        },
        {
            'bus': '0c',
            'device': '0',
            'domain': '0000',
            'function': '3',
            'physical_network': 'PHYNET1'
        },
        {
            'bus': '0c',
            'device': '0',
            'domain': '0000',
            'function': '4',
            'physical_network': 'PHYNET1'
        }
    ]

    bound_arqs = []
    # combine bond info to arq generating a bonded arqs list
    for idx, arq in enumerate(arqs):
        bound_arq = copy.deepcopy(arq)
        bound_arq.update(
            {'state': 'Bound',
            'attach_handle_type': 'TEST_PCI',
            'attach_handle_info': attach_handle_list[idx]},
            )
        bound_arqs.append(bound_arq)
    return arqs, bound_arqs


class CyborgFixture(fixtures.Fixture):
    """Fixture that mocks Cyborg APIs used by nova/accelerator/cyborg.py"""

    dp_name = 'fakedev-dp'
    trait = 'CUSTOM_FAKE_DEVICE'
    arq_list, bound_arq_list = copy.deepcopy(get_arqs(dp_name))
    arq_uuids = []
    for arq in arq_list:
        arq_uuids.append(arq["uuid"])
    call_create_arq_count = 0

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

    def setUp(self):
        super().setUp()
        self.mock_get_dp = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient._get_device_profile_list',
            side_effect=self.fake_get_device_profile_list)).mock
        self.mock_create_arqs = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.create_arqs',
            side_effect=self.fake_create_arqs)).mock
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
        self.mock_get_arq_by_uuid = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.'
            'get_arq_by_uuid',
            side_effect=self.fake_get_arq_by_uuid)).mock
        self.mock_get_arq_device_rp_uuid = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.'
            'get_arq_device_rp_uuid',
            side_effect=self.fake_get_arq_device_rp_uuid)).mock
        self.mock_create_arq_and_match_rp = self.useFixture(fixtures.MockPatch(
            'nova.accelerator.cyborg._CyborgClient.'
            'create_arqs_and_match_resource_providers',
            side_effect=self.fake_create_arq_and_match_rp)).mock
        self.mock_fake_delete_arqs_by_uuid = self.useFixture(
            fixtures.MockPatch(
                'nova.accelerator.cyborg._CyborgClient.'
                'delete_arqs_by_uuid',
                side_effect=self.fake_delete_arqs_by_uuid)).mock

    def fake_get_device_profile_list(self, dp_name):
        return _get_device_profile(dp_name, self.trait)

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
        if bindings.keys() and CyborgFixture.arq_uuids is None:
            LOG.error("ARQ not found")
            raise exception.AcceleratorRequestOpFailed()
        for arq_uuid, binding in bindings.items():
            for bound_arq in CyborgFixture.bound_arq_list:
                if arq_uuid == bound_arq["uuid"]:
                    bound_arq["hostname"] = binding["hostname"]
                    bound_arq["instance_uuid"] = binding["instance_uuid"]
                    bound_arq["device_rp_uuid"] = binding["device_rp_uuid"]
                    break

    @staticmethod
    def fake_get_arqs_for_instance(instance_uuid, only_resolved=False):
        """Get list of bound ARQs for this instance.

           This function uses bindings indexed by instance UUID to
           populate the bound ARQ templates in CyborgFixture.bound_arq_list.
        """
        bound_arq_list = copy.deepcopy(CyborgFixture.bound_arq_list)
        instance_bound_arqs = []
        for arq in bound_arq_list:
            if arq["instance_uuid"] == instance_uuid:
                instance_bound_arqs.append(arq)
        return instance_bound_arqs

    def fake_get_arq_by_uuid(self, uuid):
        for arq in self.arq_list:
            if uuid == arq['uuid']:
                return arq
        return None

    def fake_delete_arqs_for_instance(self, instance_uuid):
        # clean up arq binding info while delete arqs
        for arq in self.bound_arq_list:
            if arq["instance_uuid"] == instance_uuid:
                arq["instance_uuid"] = None
                arq["hostname"] = None
                arq["device_rp_uuid"] = None

    def fake_create_arq_and_match_rp(self,
        dp_name, rg_rp_map=None, owner=None):
        # sync the device_rp_uuid to fake arq
        arqs = self.fake_create_arqs(dp_name)
        for arq in arqs:
            dp_group_id = arq['device_profile_group_id']
            requester_id = ("device_profile_" + str(dp_group_id) +
                (str(owner) if owner else ""))
            arq["device_rp_uuid"] = rg_rp_map[requester_id][0]
        return arqs

    def fake_create_arqs(self, dp_name):
        index = self.call_create_arq_count
        self.call_create_arq_count += 1
        if index < len(self.arq_list):
            return [self.arq_list[index]]
        else:
            return None

    def fake_get_arq_device_rp_uuid(self,
        arq_arg, rg_rp_map=None, port_id=None):
        # sync the device_rp_uuid to fake arq
        for arq in self.arq_list:
            if arq["uuid"] == arq_arg['uuid']:
                dp_group_id = arq['device_profile_group_id']
                requester_id = ("device_profile_" +
                    str(dp_group_id) + str(port_id))
                arq["device_rp_uuid"] = rg_rp_map[requester_id][0]
                return arq["device_rp_uuid"]
        return None

    def fake_delete_arqs_by_uuid(self, arq_uuids):
        # clean up arq binding info while delete arqs
        for arq_uuid in arq_uuids:
            for arq in self.bound_arq_list:
                if arq["uuid"] == arq_uuid:
                    arq["instance_uuid"] = None
                    arq["hostname"] = None
                    arq["device_rp_uuid"] = None
