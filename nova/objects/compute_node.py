#    Copyright 2013 IBM Corp
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

from oslo.serialization import jsonutils

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import pci_device_pool
from nova import utils


# TODO(berrange): Remove NovaObjectDictCompat
class ComputeNode(base.NovaPersistentObject, base.NovaObject,
                  base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added get_by_service_id()
    # Version 1.2: String attributes updated to support unicode
    # Version 1.3: Added stats field
    # Version 1.4: Added host ip field
    # Version 1.5: Added numa_topology field
    # Version 1.6: Added supported_hv_specs
    # Version 1.7: Added host field
    # Version 1.8: Added get_by_host_and_nodename()
    # Version 1.9: Added pci_device_pools
    VERSION = '1.9'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'service_id': fields.IntegerField(),
        'host': fields.StringField(nullable=True),
        'vcpus': fields.IntegerField(),
        'memory_mb': fields.IntegerField(),
        'local_gb': fields.IntegerField(),
        'vcpus_used': fields.IntegerField(),
        'memory_mb_used': fields.IntegerField(),
        'local_gb_used': fields.IntegerField(),
        'hypervisor_type': fields.StringField(),
        'hypervisor_version': fields.IntegerField(),
        'hypervisor_hostname': fields.StringField(nullable=True),
        'free_ram_mb': fields.IntegerField(nullable=True),
        'free_disk_gb': fields.IntegerField(nullable=True),
        'current_workload': fields.IntegerField(nullable=True),
        'running_vms': fields.IntegerField(nullable=True),
        'cpu_info': fields.StringField(nullable=True),
        'disk_available_least': fields.IntegerField(nullable=True),
        'metrics': fields.StringField(nullable=True),
        'stats': fields.DictOfNullableStringsField(nullable=True),
        'host_ip': fields.IPAddressField(nullable=True),
        'numa_topology': fields.StringField(nullable=True),
        # NOTE(pmurray): the supported_hv_specs field maps to the
        # supported_instances field in the database
        'supported_hv_specs': fields.ListOfObjectsField('HVSpec'),
        # NOTE(pmurray): the pci_device_pools field maps to the
        # pci_stats field in the database
        'pci_device_pools': fields.ObjectField('PciDevicePoolList',
                                               nullable=True),
        }

    obj_relationships = {
        'pci_device_pools': [('1.9', '1.0')],
        'supported_hv_specs': [('1.6', '1.0')],
    }

    def obj_make_compatible(self, primitive, target_version):
        super(ComputeNode, self).obj_make_compatible(primitive, target_version)
        target_version = utils.convert_version_to_tuple(target_version)
        if target_version < (1, 7) and 'host' in primitive:
            del primitive['host']
        if target_version < (1, 5) and 'numa_topology' in primitive:
            del primitive['numa_topology']
        if target_version < (1, 4) and 'host_ip' in primitive:
            del primitive['host_ip']
        if target_version < (1, 3) and 'stats' in primitive:
            # pre 1.3 version does not have a stats field
            del primitive['stats']

    @staticmethod
    def _host_from_db_object(compute, db_compute):
        if (('host' not in db_compute or db_compute['host'] is None)
                and 'service_id' in db_compute
                and db_compute['service_id'] is not None):
            # FIXME(sbauza) : Unconverted compute record, provide compatibility
            # This has to stay until we can be sure that any/all compute nodes
            # in the database have been converted to use the host field

            # Service field of ComputeNode could be deprecated in a next patch,
            # so let's use directly the Service object
            try:
                service = objects.Service.get_by_id(
                    compute._context, db_compute['service_id'])
            except exception.ServiceNotFound:
                compute['host'] = None
                return
            try:
                compute['host'] = service.host
            except (AttributeError, exception.OrphanedObjectError):
                # Host can be nullable in Service
                compute['host'] = None
        elif 'host' in db_compute and db_compute['host'] is not None:
            # New-style DB having host as a field
            compute['host'] = db_compute['host']
        else:
            # We assume it should not happen but in case, let's set it to None
            compute['host'] = None

    @staticmethod
    def _from_db_object(context, compute, db_compute):
        special_cases = set([
            'stats',
            'supported_hv_specs',
            'host',
            'pci_device_pools',
            ])
        fields = set(compute.fields) - special_cases
        for key in fields:
            compute[key] = db_compute[key]

        stats = db_compute['stats']
        if stats:
            compute['stats'] = jsonutils.loads(stats)

        sup_insts = db_compute.get('supported_instances')
        if sup_insts:
            hv_specs = jsonutils.loads(sup_insts)
            hv_specs = [objects.HVSpec.from_list(hv_spec)
                        for hv_spec in hv_specs]
            compute['supported_hv_specs'] = hv_specs

        pci_stats = db_compute.get('pci_stats')
        compute.pci_device_pools = pci_device_pool.from_pci_stats(pci_stats)
        compute._context = context

        # Make sure that we correctly set the host field depending on either
        # host column is present in the table or not
        compute._host_from_db_object(compute, db_compute)

        compute.obj_reset_changes()
        return compute

    @base.remotable_classmethod
    def get_by_id(cls, context, compute_id):
        db_compute = db.compute_node_get(context, compute_id)
        return cls._from_db_object(context, cls(), db_compute)

    @base.remotable_classmethod
    def get_by_service_id(cls, context, service_id):
        db_compute = db.compute_node_get_by_service_id(context, service_id)
        return cls._from_db_object(context, cls(), db_compute)

    @base.remotable_classmethod
    def get_by_host_and_nodename(cls, context, host, nodename):
        try:
            db_compute = db.compute_node_get_by_host_and_nodename(
                context, host, nodename)
        except exception.ComputeHostNotFound:
            # FIXME(sbauza): Some old computes can still have no host record
            # We need to provide compatibility by using the old service_id
            # record.
            # We assume the compatibility as an extra penalty of one more DB
            # call but that's necessary until all nodes are upgraded.
            service = objects.Service.get_by_compute_host(context, host)
            # NOTE(sbauza): Here, the old model is buggy because there can only
            # be one compute node per service_id
            db_compute = db.compute_node_get_by_service_id(context, service.id)
            # We can avoid an extra call to Service object in _from_db_object
            db_compute['host'] = service.host
        return cls._from_db_object(context, cls(), db_compute)

    @staticmethod
    def _convert_stats_to_db_format(updates):
        stats = updates.pop('stats', None)
        if stats is not None:
            updates['stats'] = jsonutils.dumps(stats)

    @staticmethod
    def _convert_host_ip_to_db_format(updates):
        host_ip = updates.pop('host_ip', None)
        if host_ip:
            updates['host_ip'] = str(host_ip)

    @staticmethod
    def _convert_supported_instances_to_db_format(updates):
        hv_specs = updates.pop('supported_hv_specs', None)
        if hv_specs is not None:
            hv_specs = [hv_spec.to_list() for hv_spec in hv_specs]
            updates['supported_instances'] = jsonutils.dumps(hv_specs)

    @staticmethod
    def _convert_pci_stats_to_db_format(updates):
        pools = updates.pop('pci_device_pools', None)
        if pools:
            updates['pci_stats'] = jsonutils.dumps(pools.obj_to_primitive())

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        self._convert_stats_to_db_format(updates)
        self._convert_host_ip_to_db_format(updates)
        self._convert_supported_instances_to_db_format(updates)
        self._convert_pci_stats_to_db_format(updates)

        db_compute = db.compute_node_create(context, updates)
        self._from_db_object(context, self, db_compute)

    @base.remotable
    def save(self, context, prune_stats=False):
        # NOTE(belliott) ignore prune_stats param, no longer relevant

        updates = self.obj_get_changes()
        updates.pop('id', None)
        self._convert_stats_to_db_format(updates)
        self._convert_host_ip_to_db_format(updates)
        self._convert_supported_instances_to_db_format(updates)
        self._convert_pci_stats_to_db_format(updates)

        db_compute = db.compute_node_update(context, self.id, updates)
        self._from_db_object(context, self, db_compute)

    @base.remotable
    def destroy(self, context):
        db.compute_node_delete(context, self.id)

    @property
    def service(self):
        if not hasattr(self, '_cached_service'):
            self._cached_service = objects.Service.get_by_id(self._context,
                                                             self.service_id)
        return self._cached_service


class ComputeNodeList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              ComputeNode <= version 1.2
    # Version 1.1 ComputeNode version 1.3
    # Version 1.2 Add get_by_service()
    # Version 1.3 ComputeNode version 1.4
    # Version 1.4 ComputeNode version 1.5
    # Version 1.5 Add use_slave to get_by_service
    # Version 1.6 ComputeNode version 1.6
    # Version 1.7 ComputeNode version 1.7
    # Version 1.8 ComputeNode version 1.8 + add get_all_by_host()
    # Version 1.9 ComputeNode version 1.9
    VERSION = '1.9'
    fields = {
        'objects': fields.ListOfObjectsField('ComputeNode'),
        }
    child_versions = {
        '1.0': '1.2',
        # NOTE(danms): ComputeNode was at 1.2 before we added this
        '1.1': '1.3',
        '1.2': '1.3',
        '1.3': '1.4',
        '1.4': '1.5',
        '1.5': '1.5',
        '1.6': '1.6',
        '1.7': '1.7',
        '1.8': '1.8',
        '1.9': '1.9',
        }

    @base.remotable_classmethod
    def get_all(cls, context):
        db_computes = db.compute_node_get_all(context)
        return base.obj_make_list(context, cls(context), objects.ComputeNode,
                                  db_computes)

    @base.remotable_classmethod
    def get_by_hypervisor(cls, context, hypervisor_match):
        db_computes = db.compute_node_search_by_hypervisor(context,
                                                           hypervisor_match)
        return base.obj_make_list(context, cls(context), objects.ComputeNode,
                                  db_computes)

    @base.remotable_classmethod
    def _get_by_service(cls, context, service_id, use_slave=False):
        db_service = db.service_get(context, service_id,
                                    with_compute_node=True,
                                    use_slave=use_slave)
        return base.obj_make_list(context, cls(context), objects.ComputeNode,
                                  db_service['compute_node'])

    @classmethod
    def get_by_service(cls, context, service, use_slave=False):
        return cls._get_by_service(context, service.id, use_slave=use_slave)

    @base.remotable_classmethod
    def get_all_by_host(cls, context, host, use_slave=False):
        try:
            db_computes = db.compute_node_get_all_by_host(context, host,
                                                          use_slave)
        except exception.ComputeHostNotFound:
            # FIXME(sbauza): Some old computes can still have no host record
            # We need to provide compatibility by using the old service_id
            # record.
            # We assume the compatibility as an extra penalty of one more DB
            # call but that's necessary until all nodes are upgraded.
            service = objects.Service.get_by_compute_host(context, host,
                                                          use_slave)
            db_compute = db.compute_node_get_by_service_id(context,
                                                           service.id)
            # We can avoid an extra call to Service object in _from_db_object
            db_compute['host'] = service.host
            # NOTE(sbauza): Yeah, the old model sucks, because there can only
            # be one node per host...
            db_computes = [db_compute]
        return base.obj_make_list(context, cls(context), objects.ComputeNode,
                                  db_computes)
