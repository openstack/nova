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

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import context
from nova import objects
from nova.tests.unit import fake_flavor
from nova.tests import uuidsentinel as uuids


INSTANCE_NUMA_TOPOLOGY = objects.InstanceNUMATopology(
        cells=[objects.InstanceNUMACell(id=0, cpuset=set([1, 2]), memory=512),
              objects.InstanceNUMACell(id=1, cpuset=set([3, 4]), memory=512)])
INSTANCE_NUMA_TOPOLOGY.obj_reset_changes(recursive=True)

IMAGE_META = objects.ImageMeta.from_dict(
        {'status': 'active',
         'container_format': 'bare',
         'min_ram': 0,
         'updated_at': '2014-12-12T11:16:36.000000',
         'min_disk': 0,
         'owner': '2d8b9502858c406ebee60f0849486222',
         'protected': 'yes',
         'properties': {
             'os_type': 'Linux',
             'hw_video_model': 'vga',
             'hw_video_ram': '512',
             'hw_qemu_guest_agent': 'yes',
             'hw_scsi_model': 'virtio-scsi',
         },
         'size': 213581824,
         'name': 'f16-x86_64-openstack-sda',
         'checksum': '755122332caeb9f661d5c978adb8b45f',
         'created_at': '2014-12-10T16:23:14.000000',
         'disk_format': 'qcow2',
         'id': 'c8b1790e-a07d-4971-b137-44f2432936cd',
        }
    )
IMAGE_META.obj_reset_changes(recursive=True)

PCI_REQUESTS = objects.InstancePCIRequests(
        requests=[objects.InstancePCIRequest(count=1),
                  objects.InstancePCIRequest(count=2)])
PCI_REQUESTS.obj_reset_changes(recursive=True)


def fake_db_spec():
    req_obj = fake_spec_obj()
    # NOTE(takashin): There is not 'retry' information in the DB table.
    del req_obj.retry
    db_request_spec = {
            'id': 1,
            'instance_uuid': req_obj.instance_uuid,
            'spec': jsonutils.dumps(req_obj.obj_to_primitive()),
    }

    return db_request_spec


def fake_spec_obj(remove_id=False):
    ctxt = context.RequestContext('fake', 'fake')
    req_obj = objects.RequestSpec(ctxt)
    if not remove_id:
        req_obj.id = 42
    req_obj.instance_uuid = uuidutils.generate_uuid()
    req_obj.image = IMAGE_META
    req_obj.numa_topology = INSTANCE_NUMA_TOPOLOGY
    req_obj.pci_requests = PCI_REQUESTS
    req_obj.flavor = fake_flavor.fake_flavor_obj(ctxt)
    req_obj.retry = objects.SchedulerRetries()
    req_obj.limits = objects.SchedulerLimits()
    req_obj.instance_group = objects.InstanceGroup(uuid=uuids.instgroup)
    req_obj.project_id = 'fake'
    req_obj.user_id = 'fake-user'
    req_obj.num_instances = 1
    req_obj.availability_zone = None
    req_obj.ignore_hosts = ['host2', 'host4']
    req_obj.force_hosts = ['host1', 'host3']
    req_obj.force_nodes = ['node1', 'node2']
    req_obj.scheduler_hints = {'hint': ['over-there']}
    req_obj.requested_destination = None
    # This should never be a changed field
    req_obj.obj_reset_changes(['id'])
    return req_obj
