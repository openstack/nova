#    Copyright 2013 IBM Corp.
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

import copy

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova import notifications
from nova.objects import base
from nova.objects import instance_fault
from nova.objects import instance_info_cache
from nova.objects import security_group
from nova.objects import utils as obj_utils
from nova import utils

from oslo.config import cfg


CONF = cfg.CONF


# These are fields that can be specified as expected_attrs
INSTANCE_OPTIONAL_FIELDS = ['metadata', 'system_metadata', 'fault']
# These are fields that are always joined by the db right now
INSTANCE_IMPLIED_FIELDS = ['info_cache', 'security_groups']
# These are fields that are optional but don't translate to db columns
INSTANCE_OPTIONAL_NON_COLUMNS = ['fault']
# These are all fields that most query calls load by default
INSTANCE_DEFAULT_FIELDS = INSTANCE_OPTIONAL_FIELDS + INSTANCE_IMPLIED_FIELDS


class Instance(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added info_cache
    # Version 1.2: Added security_groups
    # Version 1.3: Added expected_vm_state and admin_state_reset to
    #              save()
    # Version 1.4: Added locked_by and deprecated locked
    # Version 1.5: Added cleaned
    VERSION = '1.5'

    fields = {
        'id': int,

        'user_id': obj_utils.str_or_none,
        'project_id': obj_utils.str_or_none,

        'image_ref': obj_utils.str_or_none,
        'kernel_id': obj_utils.str_or_none,
        'ramdisk_id': obj_utils.str_or_none,
        'hostname': obj_utils.str_or_none,

        'launch_index': obj_utils.int_or_none,
        'key_name': obj_utils.str_or_none,
        'key_data': obj_utils.str_or_none,

        'power_state': obj_utils.int_or_none,
        'vm_state': obj_utils.str_or_none,
        'task_state': obj_utils.str_or_none,

        'memory_mb': obj_utils.int_or_none,
        'vcpus': obj_utils.int_or_none,
        'root_gb': obj_utils.int_or_none,
        'ephemeral_gb': obj_utils.int_or_none,

        'host': obj_utils.str_or_none,
        'node': obj_utils.str_or_none,

        'instance_type_id': obj_utils.int_or_none,

        'user_data': obj_utils.str_or_none,

        'reservation_id': obj_utils.str_or_none,

        'scheduled_at': obj_utils.datetime_or_str_or_none,
        'launched_at': obj_utils.datetime_or_str_or_none,
        'terminated_at': obj_utils.datetime_or_str_or_none,

        'availability_zone': obj_utils.str_or_none,

        'display_name': obj_utils.str_or_none,
        'display_description': obj_utils.str_or_none,

        'launched_on': obj_utils.str_or_none,

        # NOTE(jdillaman): locked deprecated in favor of locked_by,
        # to be removed in Icehouse
        'locked': bool,
        'locked_by': obj_utils.str_or_none,

        'os_type': obj_utils.str_or_none,
        'architecture': obj_utils.str_or_none,
        'vm_mode': obj_utils.str_or_none,
        'uuid': obj_utils.str_or_none,

        'root_device_name': obj_utils.str_or_none,
        'default_ephemeral_device': obj_utils.str_or_none,
        'default_swap_device': obj_utils.str_or_none,
        'config_drive': obj_utils.str_or_none,

        'access_ip_v4': obj_utils.ip_or_none(4),
        'access_ip_v6': obj_utils.ip_or_none(6),

        'auto_disk_config': bool,
        'progress': obj_utils.int_or_none,

        'shutdown_terminate': bool,
        'disable_terminate': bool,

        'cell_name': obj_utils.str_or_none,

        'metadata': dict,
        'system_metadata': dict,

        'info_cache': obj_utils.nested_object_or_none(
            instance_info_cache.InstanceInfoCache),

        'security_groups': obj_utils.nested_object_or_none(
            security_group.SecurityGroupList),

        'fault': obj_utils.nested_object_or_none(
            instance_fault.InstanceFault),

        'cleaned': bool,

        }

    obj_extra_fields = ['name']

    def __init__(self, *args, **kwargs):
        super(Instance, self).__init__(*args, **kwargs)
        self.obj_reset_changes()

    def obj_reset_changes(self, fields=None):
        super(Instance, self).obj_reset_changes(fields)
        self._orig_system_metadata = (dict(self.system_metadata) if
                                      'system_metadata' in self else {})
        self._orig_metadata = (dict(self.metadata) if
                               'metadata' in self else {})

    def obj_what_changed(self):
        changes = super(Instance, self).obj_what_changed()
        if 'metadata' in self and self.metadata != self._orig_metadata:
            changes.add('metadata')
        if 'system_metadata' in self and (self.system_metadata !=
                                          self._orig_system_metadata):
            changes.add('system_metadata')
        return changes

    @property
    def name(self):
        try:
            base_name = CONF.instance_name_template % self.id
        except TypeError:
            # Support templates like "uuid-%(uuid)s", etc.
            info = {}
            # NOTE(russellb): Don't use self.iteritems() here, as it will
            # result in infinite recursion on the name property.
            for key in self.fields:
                # prevent recursion if someone specifies %(name)s
                # %(name)s will not be valid.
                if key == 'name':
                    continue
                info[key] = self[key]
            try:
                base_name = CONF.instance_name_template % info
            except KeyError:
                base_name = self.uuid
        return base_name

    def _attr_access_ip_v4_to_primitive(self):
        if self.access_ip_v4 is not None:
            return str(self.access_ip_v4)
        else:
            return None

    def _attr_access_ip_v6_to_primitive(self):
        if self.access_ip_v6 is not None:
            return str(self.access_ip_v6)
        else:
            return None

    _attr_scheduled_at_to_primitive = obj_utils.dt_serializer('scheduled_at')
    _attr_launched_at_to_primitive = obj_utils.dt_serializer('launched_at')
    _attr_terminated_at_to_primitive = obj_utils.dt_serializer('terminated_at')
    _attr_info_cache_to_primitive = obj_utils.obj_serializer('info_cache')
    _attr_security_groups_to_primitive = obj_utils.obj_serializer(
        'security_groups')

    _attr_scheduled_at_from_primitive = obj_utils.dt_deserializer
    _attr_launched_at_from_primitive = obj_utils.dt_deserializer
    _attr_terminated_at_from_primitive = obj_utils.dt_deserializer

    def _attr_info_cache_from_primitive(self, val):
        return base.NovaObject.obj_from_primitive(val)

    def _attr_security_groups_from_primitive(self, val):
        return base.NovaObject.obj_from_primitive(val)

    @staticmethod
    def _from_db_object(context, instance, db_inst, expected_attrs=None):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """
        if expected_attrs is None:
            expected_attrs = []
        # Most of the field names match right now, so be quick
        for field in instance.fields:
            if field in INSTANCE_OPTIONAL_FIELDS + INSTANCE_IMPLIED_FIELDS:
                continue
            elif field == 'deleted':
                instance.deleted = db_inst['deleted'] == db_inst['id']
            elif field == 'cleaned':
                instance.cleaned = db_inst['cleaned'] == 1
            else:
                instance[field] = db_inst[field]

        if 'metadata' in expected_attrs:
            instance['metadata'] = utils.metadata_to_dict(db_inst['metadata'])
        if 'system_metadata' in expected_attrs:
            instance['system_metadata'] = utils.metadata_to_dict(
                db_inst['system_metadata'])
        if 'fault' in expected_attrs:
            instance['fault'] = (
                instance_fault.InstanceFault.get_latest_for_instance(
                    context, instance.uuid))
        # NOTE(danms): info_cache and security_groups are almost
        # always joined in the DB layer right now, so check to see if
        # they are asked for and are present in the resulting object
        if 'info_cache' in expected_attrs and db_inst.get('info_cache'):
            instance['info_cache'] = instance_info_cache.InstanceInfoCache()
            instance_info_cache.InstanceInfoCache._from_db_object(
                    context, instance['info_cache'], db_inst['info_cache'])
        if ('security_groups' in expected_attrs and
                db_inst.get('security_groups')):
            instance['security_groups'] = security_group.SecurityGroupList()
            security_group._make_secgroup_list(context,
                                               instance['security_groups'],
                                               db_inst['security_groups'])

        instance._context = context
        instance.obj_reset_changes()
        return instance

    @staticmethod
    def _attrs_to_columns(attrs):
        """Translate instance attributes into columns needing joining."""
        columns_to_join = []
        if 'metadata' in attrs:
            columns_to_join.append('metadata')
        if 'system_metadata' in attrs:
            columns_to_join.append('system_metadata')
        # NOTE(danms): The DB API currently always joins info_cache and
        # security_groups for get operations, so don't add them to the
        # list of columns
        return columns_to_join

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = ['info_cache', 'security_groups']
        columns_to_join = cls._attrs_to_columns(expected_attrs)
        db_inst = db.instance_get_by_uuid(context, uuid,
                                          columns_to_join=columns_to_join)
        return cls._from_db_object(context, cls(), db_inst,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_id(cls, context, inst_id, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = ['info_cache', 'security_groups']
        columns_to_join = cls._attrs_to_columns(expected_attrs)
        db_inst = db.instance_get(context, inst_id,
                                  columns_to_join=columns_to_join)
        return cls._from_db_object(context, cls(), db_inst,
                                   expected_attrs)

    def _save_info_cache(self, context):
        self.info_cache.save(context)

    def _save_security_groups(self, context):
        for secgroup in self.security_groups:
            secgroup.save(context)

    def _save_instance_fault(self, context):
        # NOTE(danms): I don't think we need to worry about this, do we?
        pass

    @base.remotable
    def save(self, context, expected_vm_state=None,
             expected_task_state=None, admin_state_reset=False):
        """Save updates to this instance

        Column-wise updates will be made based on the result of
        self.what_changed(). If expected_task_state is provided,
        it will be checked against the in-database copy of the
        instance before updates are made.
        :param context: Security context
        :param expected_task_state: Optional tuple of valid task states
                                    for the instance to be in.
        :param expected_vm_state: Optional tuple of valid vm states
                                  for the instance to be in.
        :param admin_state_reset: True if admin API is forcing setting
                                  of task_state/vm_state.
        """

        cell_type = cells_opts.get_cell_type()
        if cell_type == 'api' and self.cell_name:
            # NOTE(comstud): We need to stash a copy of ourselves
            # before any updates are applied.  When we call the save
            # methods on nested objects, we will lose any changes to
            # them.  But we need to make sure child cells can tell
            # what is changed.
            #
            # We also need to nuke any updates to vm_state and task_state
            # unless admin_state_reset is True.  compute cells are
            # authoritative for their view of vm_state and task_state.
            stale_instance = copy.deepcopy(self)

            def _handle_cell_update_from_api():
                cells_api = cells_rpcapi.CellsAPI()
                cells_api.instance_update_from_api(context, stale_instance,
                        expected_vm_state,
                        expected_task_state,
                        admin_state_reset)
        else:
            stale_instance = None

        updates = {}
        changes = self.obj_what_changed()
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    isinstance(self[field], base.NovaObject)):
                getattr(self, '_save_%s' % field)(context)
            elif field in changes:
                updates[field] = self[field]

        if not updates:
            if stale_instance:
                _handle_cell_update_from_api()
            return

        # Cleaned needs to be turned back into an int here
        if 'cleaned' in updates:
            if updates['cleaned']:
                updates['cleaned'] = 1
            else:
                updates['cleaned'] = 0

        if expected_task_state is not None:
            updates['expected_task_state'] = expected_task_state
        if expected_vm_state is not None:
            updates['expected_vm_state'] = expected_vm_state

        old_ref, inst_ref = db.instance_update_and_get_original(
                context, self.uuid, updates, update_cells=False)

        if stale_instance:
            _handle_cell_update_from_api()
        elif cell_type == 'compute':
            cells_api = cells_rpcapi.CellsAPI()
            cells_api.instance_update_at_top(context, inst_ref)

        expected_attrs = []
        for attr in INSTANCE_OPTIONAL_FIELDS:
            if hasattr(self, base.get_attrname(attr)):
                expected_attrs.append(attr)
        self._from_db_object(context, self, inst_ref, expected_attrs)
        if 'vm_state' in changes or 'task_state' in changes:
            notifications.send_update(context, old_ref, inst_ref)
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        extra = []
        for field in INSTANCE_DEFAULT_FIELDS:
            if hasattr(self, base.get_attrname(field)):
                extra.append(field)
        current = self.__class__.get_by_uuid(context, uuid=self.uuid,
                                             expected_attrs=extra)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
        self.obj_reset_changes()

    def obj_load_attr(self, attrname):
        extra = []
        if attrname == 'system_metadata':
            extra.append('system_metadata')
        elif attrname == 'metadata':
            extra.append('metadata')
        elif attrname == 'info_cache':
            extra.append('info_cache')
        elif attrname == 'security_groups':
            extra.append('security_groups')
        elif attrname == 'fault':
            extra.append('fault')

        if not extra:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)

        # NOTE(danms): This could be optimized to just load the bits we need
        instance = self.__class__.get_by_uuid(self._context,
                                              uuid=self.uuid,
                                              expected_attrs=extra)

        # NOTE(danms): Never allow us to recursively-load
        if hasattr(instance, base.get_attrname(attrname)):
            self[attrname] = instance[attrname]
        else:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='loading %s requires recursion' % attrname)


def _make_instance_list(context, inst_list, db_inst_list, expected_attrs):
    get_fault = expected_attrs and 'fault' in expected_attrs
    inst_faults = {}
    if get_fault:
        # Build an instance_uuid:latest-fault mapping
        expected_attrs.remove('fault')
        instance_uuids = [inst['uuid'] for inst in db_inst_list]
        faults = instance_fault.InstanceFaultList.get_by_instance_uuids(
            context, instance_uuids)
        for fault in faults:
            if fault.instance_uuid not in inst_faults:
                inst_faults[fault.instance_uuid] = fault

    inst_list.objects = []
    for db_inst in db_inst_list:
        inst_obj = Instance._from_db_object(context, Instance(), db_inst,
                                            expected_attrs=expected_attrs)
        if get_fault:
            inst_obj.fault = inst_faults.get(inst_obj.uuid, None)
        inst_list.objects.append(inst_obj)
    inst_list.obj_reset_changes()
    return inst_list


def expected_cols(expected_attrs):
    """Return expected_attrs that are columns needing joining."""
    if expected_attrs:
        return list(set(expected_attrs) - set(INSTANCE_OPTIONAL_NON_COLUMNS))
    else:
        return expected_attrs


class InstanceList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_filters(cls, context, filters,
                       sort_key='created_at', sort_dir='desc', limit=None,
                       marker=None, expected_attrs=None):
        db_inst_list = db.instance_get_all_by_filters(
            context, filters, sort_key, sort_dir, limit=limit, marker=marker,
            columns_to_join=expected_cols(expected_attrs))
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, expected_attrs=None):
        db_inst_list = db.instance_get_all_by_host(
            context, host, columns_to_join=expected_cols(expected_attrs))
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_host_and_node(cls, context, host, node, expected_attrs=None):
        db_inst_list = db.instance_get_all_by_host_and_node(
            context, host, node)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_host_and_not_type(cls, context, host, type_id=None,
                                 expected_attrs=None):
        db_inst_list = db.instance_get_all_by_host_and_not_type(
            context, host, type_id=type_id)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_hung_in_rebooting(cls, context, reboot_window,
                              expected_attrs=None):
        db_inst_list = db.instance_get_all_hung_in_rebooting(context,
                                                             reboot_window)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    def fill_faults(self):
        """Batch query the database for our instances' faults.

        :returns: A list of instance uuids for which faults were found.
        """
        uuids = [inst.uuid for inst in self]
        faults = instance_fault.InstanceFaultList.get_by_instance_uuids(
            self._context, uuids)
        faults_by_uuid = {}
        for fault in faults:
            if fault.instance_uuid not in faults_by_uuid:
                faults_by_uuid[fault.instance_uuid] = fault

        for instance in self:
            if instance.uuid in faults_by_uuid:
                instance.fault = faults_by_uuid[instance.uuid]
            else:
                # NOTE(danms): Otherwise the caller will cause a lazy-load
                # when checking it, and we know there are none
                instance.fault = None
            instance.obj_reset_changes(['fault'])

        return faults_by_uuid.keys()
