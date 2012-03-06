# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
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
"""
Fakes For Scheduler tests.
"""

import mox

from nova import db
from nova.compute import instance_types
from nova.compute import vm_states
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager


COMPUTE_NODES = [
        dict(id=1, local_gb=1024, memory_mb=1024, vcpus=1,
                service=dict(host='host1', disabled=False)),
        dict(id=2, local_gb=2048, memory_mb=2048, vcpus=2,
                service=dict(host='host2', disabled=True)),
        dict(id=3, local_gb=4096, memory_mb=4096, vcpus=4,
                service=dict(host='host3', disabled=False)),
        dict(id=4, local_gb=8192, memory_mb=8192, vcpus=8,
                service=dict(host='host4', disabled=False)),
        # Broken entry
        dict(id=5, local_gb=1024, memory_mb=1024, vcpus=1, service=None),
]

INSTANCES = [
        dict(root_gb=512, ephemeral_gb=0, memory_mb=512, vcpus=1,
             host='host1'),
        dict(root_gb=512, ephemeral_gb=0, memory_mb=512, vcpus=1,
             host='host2'),
        dict(root_gb=512, ephemeral_gb=0, memory_mb=512, vcpus=1,
             host='host2'),
        dict(root_gb=1024, ephemeral_gb=0, memory_mb=1024, vcpus=1,
             host='host3'),
        # Broken host
        dict(root_gb=1024, ephemeral_gb=0, memory_mb=1024, vcpus=1,
             host=None),
        # No matching host
        dict(root_gb=1024, ephemeral_gb=0, memory_mb=1024, vcpus=1,
             host='host5'),
]


class FakeFilterScheduler(filter_scheduler.FilterScheduler):
    def __init__(self, *args, **kwargs):
        super(FakeFilterScheduler, self).__init__(*args, **kwargs)
        self.host_manager = host_manager.HostManager()


class FakeHostManager(host_manager.HostManager):
    """host1: free_ram_mb=1024-512-512=0, free_disk_gb=1024-512-512=0
       host2: free_ram_mb=2048-512=1536  free_disk_gb=2048-512=1536
       host3: free_ram_mb=4096-1024=3072  free_disk_gb=4096-1024=3072
       host4: free_ram_mb=8192  free_disk_gb=8192"""

    def __init__(self):
        super(FakeHostManager, self).__init__()

        self.service_states = {
            'host1': {
                'compute': {'host_memory_free': 1073741824},
            },
            'host2': {
                'compute': {'host_memory_free': 2147483648},
            },
            'host3': {
                'compute': {'host_memory_free': 3221225472},
            },
            'host4': {
                'compute': {'host_memory_free': 999999999},
            },
        }

    def get_host_list_from_db(self, context):
        return [
            ('host1', dict(free_disk_gb=1024, free_ram_mb=1024)),
            ('host2', dict(free_disk_gb=2048, free_ram_mb=2048)),
            ('host3', dict(free_disk_gb=4096, free_ram_mb=4096)),
            ('host4', dict(free_disk_gb=8192, free_ram_mb=8192)),
        ]


class FakeHostState(host_manager.HostState):
    def __init__(self, host, topic, attribute_dict):
        super(FakeHostState, self).__init__(host, topic)
        for (key, val) in attribute_dict.iteritems():
            setattr(self, key, val)


class FakeInstance(object):
    def __init__(self, context=None, params=None, type_name='m1.tiny'):
        """Create a test instance. Returns uuid"""
        self.context = context

        i = self._create_fake_instance(params, type_name=type_name)
        self.uuid = i['uuid']

    def _create_fake_instance(self, params=None, type_name='m1.tiny'):
        """Create a test instance"""
        if not params:
            params = {}

        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        type_id = instance_types.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst.update(params)
        return db.instance_create(self.context, inst)


class FakeComputeAPI(object):
    def create_db_entry_for_new_instance(self, *args, **kwargs):
        pass


def mox_host_manager_db_calls(mock, context):
    mock.StubOutWithMock(db, 'compute_node_get_all')
    mock.StubOutWithMock(db, 'instance_get_all')

    db.compute_node_get_all(mox.IgnoreArg()).AndReturn(COMPUTE_NODES)
    db.instance_get_all(mox.IgnoreArg()).AndReturn(INSTANCES)
