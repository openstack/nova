#    Copyright 2018 NTT Corporation
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

from nova.notifications.objects import base
from nova.notifications.objects import flavor as flavor_payload
from nova.notifications.objects import image as image_payload
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class RequestSpecPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'instance_uuid': ('request_spec', 'instance_uuid'),
        'project_id': ('request_spec', 'project_id'),
        'user_id': ('request_spec', 'user_id'),
        'availability_zone': ('request_spec', 'availability_zone'),
        'num_instances': ('request_spec', 'num_instances')
    }

    fields = {
        'instance_uuid': fields.UUIDField(),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'flavor': fields.ObjectField('FlavorPayload', nullable=True),
        'image': fields.ObjectField('ImageMetaPayload', nullable=True),
        'numa_topology': fields.ObjectField('InstanceNUMATopologyPayload',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequestsPayload',
                                           nullable=True),
        'num_instances': fields.IntegerField(default=1)
    }

    def __init__(self, request_spec):
        super(RequestSpecPayload, self).__init__()
        self.flavor = flavor_payload.FlavorPayload(
            request_spec.flavor) if request_spec.obj_attr_is_set(
                'flavor') else None
        self.image = image_payload.ImageMetaPayload(
            request_spec.image) if request_spec.image else None
        if request_spec.numa_topology is not None:
            if not request_spec.numa_topology.obj_attr_is_set('instance_uuid'):
                request_spec.numa_topology.instance_uuid = (
                    request_spec.instance_uuid)
            self.numa_topology = InstanceNUMATopologyPayload(
                request_spec.numa_topology)
        else:
            self.numa_topology = None
        if request_spec.pci_requests is not None:
            if not request_spec.pci_requests.obj_attr_is_set('instance_uuid'):
                request_spec.pci_requests.instance_uuid = (
                    request_spec.instance_uuid)
            self.pci_requests = InstancePCIRequestsPayload(
                request_spec.pci_requests)
        else:
            self.pci_requests = None
        self.populate_schema(request_spec=request_spec)


@nova_base.NovaObjectRegistry.register_notification
class InstanceNUMATopologyPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'instance_uuid': ('numa_topology', 'instance_uuid'),
        'emulator_threads_policy': ('numa_topology',
                                    'emulator_threads_policy')
    }

    fields = {
        'instance_uuid': fields.UUIDField(),
        'cells': fields.ListOfObjectsField('InstanceNUMACellPayload'),
        'emulator_threads_policy': fields.CPUEmulatorThreadsPolicyField(
            nullable=True)
    }

    def __init__(self, numa_topology):
        super(InstanceNUMATopologyPayload, self).__init__()
        self.cells = InstanceNUMACellPayload.from_numa_cell_list_obj(
            numa_topology.cells)
        self.populate_schema(numa_topology=numa_topology)


@nova_base.NovaObjectRegistry.register_notification
class InstanceNUMACellPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'id': ('numa_cell', 'id'),
        'cpuset': ('numa_cell', 'cpuset'),
        'memory': ('numa_cell', 'memory'),
        'pagesize': ('numa_cell', 'pagesize'),
        'cpu_pinning_raw': ('numa_cell', 'cpu_pinning_raw'),
        'cpu_policy': ('numa_cell', 'cpu_policy'),
        'cpu_thread_policy': ('numa_cell', 'cpu_thread_policy'),
        'cpuset_reserved': ('numa_cell', 'cpuset_reserved'),
    }

    fields = {
        'id': fields.IntegerField(),
        'cpuset': fields.SetOfIntegersField(),
        'memory': fields.IntegerField(),
        'pagesize': fields.IntegerField(nullable=True),
        'cpu_topology': fields.ObjectField('VirtCPUTopologyPayload',
                                           nullable=True),
        'cpu_pinning_raw': fields.DictOfIntegersField(nullable=True),
        'cpu_policy': fields.CPUAllocationPolicyField(nullable=True),
        'cpu_thread_policy': fields.CPUThreadAllocationPolicyField(
            nullable=True),
        'cpuset_reserved': fields.SetOfIntegersField(nullable=True)
    }

    def __init__(self, numa_cell):
        super(InstanceNUMACellPayload, self).__init__()
        if (numa_cell.obj_attr_is_set('cpu_topology') and
                numa_cell.cpu_topology is not None):
            self.cpu_topology = VirtCPUTopologyPayload(numa_cell.cpu_topology)
        else:
            self.cpu_topology = None
        self.populate_schema(numa_cell=numa_cell)

    @classmethod
    def from_numa_cell_list_obj(cls, numa_cell_list):
        """Returns a list of InstanceNUMACellPayload objects
        based on the passed list of InstanceNUMACell objects.
        """
        payloads = []
        for numa_cell in numa_cell_list:
            payloads.append(cls(numa_cell))
        return payloads


@nova_base.NovaObjectRegistry.register_notification
class VirtCPUTopologyPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'sockets': ('virt_cpu_topology', 'sockets'),
        'cores': ('virt_cpu_topology', 'cores'),
        'threads': ('virt_cpu_topology', 'threads'),
    }

    fields = {
        'sockets': fields.IntegerField(nullable=True, default=1),
        'cores': fields.IntegerField(nullable=True, default=1),
        'threads': fields.IntegerField(nullable=True, default=1),
    }

    def __init__(self, virt_cpu_topology):
        super(VirtCPUTopologyPayload, self).__init__()
        self.populate_schema(virt_cpu_topology=virt_cpu_topology)


@nova_base.NovaObjectRegistry.register_notification
class InstancePCIRequestsPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'instance_uuid': ('pci_requests', 'instance_uuid')
    }

    fields = {
        'instance_uuid': fields.UUIDField(),
        'requests': fields.ListOfObjectsField('InstancePCIRequestPayload')
    }

    def __init__(self, pci_requests):
        super(InstancePCIRequestsPayload, self).__init__()
        self.requests = InstancePCIRequestPayload.from_pci_request_list_obj(
            pci_requests.requests)
        self.populate_schema(pci_requests=pci_requests)


@nova_base.NovaObjectRegistry.register_notification
class InstancePCIRequestPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'count': ('pci_request', 'count'),
        'spec': ('pci_request', 'spec'),
        'alias_name': ('pci_request', 'alias_name'),
        'request_id': ('pci_request', 'request_id'),
        'numa_policy': ('pci_request', 'numa_policy')
    }

    fields = {
        'count': fields.IntegerField(),
        'spec': fields.ListOfDictOfNullableStringsField(),
        'alias_name': fields.StringField(nullable=True),
        'request_id': fields.UUIDField(nullable=True),
        'numa_policy': fields.PCINUMAAffinityPolicyField(nullable=True)
    }

    def __init__(self, pci_request):
        super(InstancePCIRequestPayload, self).__init__()
        self.populate_schema(pci_request=pci_request)

    @classmethod
    def from_pci_request_list_obj(cls, pci_request_list):
        """Returns a list of InstancePCIRequestPayload objects
        based on the passed list of InstancePCIRequest objects.
        """
        payloads = []
        for pci_request in pci_request_list:
            payloads.append(cls(pci_request))
        return payloads
