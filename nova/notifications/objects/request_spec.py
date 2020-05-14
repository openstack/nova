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
from nova.notifications.objects import server_group as server_group_payload
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class RequestSpecPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 1.1: Add force_hosts, force_nodes, ignore_hosts, image_meta,
    #              instance_group, requested_destination, retry,
    #              scheduler_hints and security_groups fields
    VERSION = '1.1'

    SCHEMA = {
        'ignore_hosts': ('request_spec', 'ignore_hosts'),
        'instance_uuid': ('request_spec', 'instance_uuid'),
        'project_id': ('request_spec', 'project_id'),
        'user_id': ('request_spec', 'user_id'),
        'availability_zone': ('request_spec', 'availability_zone'),
        'num_instances': ('request_spec', 'num_instances'),
        'scheduler_hints': ('request_spec', 'scheduler_hints'),
    }

    fields = {
        'instance_uuid': fields.UUIDField(),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'flavor': fields.ObjectField('FlavorPayload', nullable=True),
        'force_hosts': fields.StringField(nullable=True),
        'force_nodes': fields.StringField(nullable=True),
        'ignore_hosts': fields.ListOfStringsField(nullable=True),
        'image_meta': fields.ObjectField('ImageMetaPayload', nullable=True),
        'instance_group': fields.ObjectField('ServerGroupPayload',
            nullable=True),
        'image': fields.ObjectField('ImageMetaPayload', nullable=True),
        'numa_topology': fields.ObjectField('InstanceNUMATopologyPayload',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequestsPayload',
                                           nullable=True),
        'num_instances': fields.IntegerField(default=1),
        'requested_destination': fields.ObjectField('DestinationPayload',
            nullable=True),
        'retry': fields.ObjectField('SchedulerRetriesPayload', nullable=True),
        'scheduler_hints': fields.DictOfListOfStringsField(nullable=True),
        'security_groups': fields.ListOfStringsField(),
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
        if 'requested_destination' in request_spec \
                and request_spec.requested_destination:
            self.requested_destination = DestinationPayload(
                destination=request_spec.requested_destination)
        else:
            self.requested_destination = None
        if 'retry' in request_spec and request_spec.retry:
            self.retry = SchedulerRetriesPayload(
                retry=request_spec.retry)
        else:
            self.retry = None
        self.security_groups = [
            sec_group.identifier for sec_group in request_spec.security_groups]
        if 'instance_group' in request_spec and request_spec.instance_group:
            self.instance_group = server_group_payload.ServerGroupPayload(
                group=request_spec.instance_group)
        else:
            self.instance_group = None
        if 'force_hosts' in request_spec and request_spec.force_hosts:
            self.force_hosts = request_spec.force_hosts[0]
        else:
            self.force_hosts = None
        if 'force_nodes' in request_spec and request_spec.force_nodes:
            self.force_nodes = request_spec.force_nodes[0]
        else:
            self.force_nodes = None
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
    # Version 1.1: Added pcpuset field
    # Version 1.2: Added 'mixed' to cpu_policy field
    VERSION = '1.2'

    SCHEMA = {
        'id': ('numa_cell', 'id'),
        'cpuset': ('numa_cell', 'cpuset'),
        'pcpuset': ('numa_cell', 'pcpuset'),
        'cpuset_reserved': ('numa_cell', 'cpuset_reserved'),
        'memory': ('numa_cell', 'memory'),
        'pagesize': ('numa_cell', 'pagesize'),
        'cpu_pinning_raw': ('numa_cell', 'cpu_pinning_raw'),
        'cpu_policy': ('numa_cell', 'cpu_policy'),
        'cpu_thread_policy': ('numa_cell', 'cpu_thread_policy'),
    }

    fields = {
        'id': fields.IntegerField(),
        'cpuset': fields.SetOfIntegersField(),
        'pcpuset': fields.SetOfIntegersField(),
        'cpuset_reserved': fields.SetOfIntegersField(nullable=True),
        'memory': fields.IntegerField(),
        'pagesize': fields.IntegerField(nullable=True),
        'cpu_topology': fields.ObjectField('VirtCPUTopologyPayload',
                                           nullable=True),
        'cpu_pinning_raw': fields.DictOfIntegersField(nullable=True),
        'cpu_policy': fields.CPUAllocationPolicyField(nullable=True),
        'cpu_thread_policy': fields.CPUThreadAllocationPolicyField(
            nullable=True),
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


@nova_base.NovaObjectRegistry.register_notification
class DestinationPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'aggregates': ('destination', 'aggregates'),
    }

    fields = {
        'host': fields.StringField(),
        'node': fields.StringField(nullable=True),
        'cell': fields.ObjectField('CellMappingPayload', nullable=True),
        'aggregates': fields.ListOfStringsField(nullable=True,
                                                default=None),
    }

    def __init__(self, destination):
        super(DestinationPayload, self).__init__()
        if (destination.obj_attr_is_set('host') and
                destination.host is not None):
            self.host = destination.host
        if (destination.obj_attr_is_set('node') and
                destination.node is not None):
            self.node = destination.node
        if (destination.obj_attr_is_set('cell') and
                destination.cell is not None):
            self.cell = CellMappingPayload(destination.cell)
        self.populate_schema(destination=destination)


@nova_base.NovaObjectRegistry.register_notification
class SchedulerRetriesPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'num_attempts': ('retry', 'num_attempts'),
    }

    fields = {
        'num_attempts': fields.IntegerField(),
        'hosts': fields.ListOfStringsField(),
    }

    def __init__(self, retry):
        super(SchedulerRetriesPayload, self).__init__()
        self.hosts = []
        for compute_node in retry.hosts:
            self.hosts.append(compute_node.hypervisor_hostname)
        self.populate_schema(retry=retry)


@nova_base.NovaObjectRegistry.register_notification
class CellMappingPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 2.0: Remove transport_url and database_connection fields.
    VERSION = '2.0'

    SCHEMA = {
        'uuid': ('cell', 'uuid'),
        'name': ('cell', 'name'),
        'disabled': ('cell', 'disabled'),
    }

    fields = {
        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'disabled': fields.BooleanField(default=False),
    }

    def __init__(self, cell):
        super(CellMappingPayload, self).__init__()
        self.populate_schema(cell=cell)
