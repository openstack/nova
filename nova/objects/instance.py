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

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova.compute import flavors
from nova import db
from nova import exception
from nova import notifications
from nova.objects import base
from nova.objects import fields
from nova.objects import flavor as flavor_obj
from nova.objects import instance_fault
from nova.objects import instance_info_cache
from nova.objects import pci_device
from nova.objects import security_group
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import utils

from oslo.config import cfg


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


# List of fields that can be joined in DB layer.
_INSTANCE_OPTIONAL_JOINED_FIELDS = ['metadata', 'system_metadata',
                                    'info_cache', 'security_groups',
                                    'pci_devices']
# These are fields that are optional but don't translate to db columns
_INSTANCE_OPTIONAL_NON_COLUMN_FIELDS = ['fault']

# These are fields that can be specified as expected_attrs
INSTANCE_OPTIONAL_ATTRS = (_INSTANCE_OPTIONAL_JOINED_FIELDS +
                           _INSTANCE_OPTIONAL_NON_COLUMN_FIELDS)
# These are fields that most query calls load by default
INSTANCE_DEFAULT_FIELDS = ['metadata', 'system_metadata',
                           'info_cache', 'security_groups']


def _expected_cols(expected_attrs):
    """Return expected_attrs that are columns needing joining."""
    if not expected_attrs:
        return expected_attrs
    return [attr for attr in expected_attrs
                 if attr in _INSTANCE_OPTIONAL_JOINED_FIELDS]


class Instance(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added info_cache
    # Version 1.2: Added security_groups
    # Version 1.3: Added expected_vm_state and admin_state_reset to
    #              save()
    # Version 1.4: Added locked_by and deprecated locked
    # Version 1.5: Added cleaned
    # Version 1.6: Added pci_devices
    # Version 1.7: String attributes updated to support unicode
    # Version 1.8: 'security_groups' and 'pci_devices' cannot be None
    # Version 1.9: Make uuid a non-None real string
    # Version 1.10: Added use_slave to refresh and get_by_uuid
    # Version 1.11: Update instance from database during destroy
    VERSION = '1.11'

    fields = {
        'id': fields.IntegerField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        'image_ref': fields.StringField(nullable=True),
        'kernel_id': fields.StringField(nullable=True),
        'ramdisk_id': fields.StringField(nullable=True),
        'hostname': fields.StringField(nullable=True),

        'launch_index': fields.IntegerField(nullable=True),
        'key_name': fields.StringField(nullable=True),
        'key_data': fields.StringField(nullable=True),

        'power_state': fields.IntegerField(nullable=True),
        'vm_state': fields.StringField(nullable=True),
        'task_state': fields.StringField(nullable=True),

        'memory_mb': fields.IntegerField(nullable=True),
        'vcpus': fields.IntegerField(nullable=True),
        'root_gb': fields.IntegerField(nullable=True),
        'ephemeral_gb': fields.IntegerField(nullable=True),

        'host': fields.StringField(nullable=True),
        'node': fields.StringField(nullable=True),

        'instance_type_id': fields.IntegerField(nullable=True),

        'user_data': fields.StringField(nullable=True),

        'reservation_id': fields.StringField(nullable=True),

        'scheduled_at': fields.DateTimeField(nullable=True),
        'launched_at': fields.DateTimeField(nullable=True),
        'terminated_at': fields.DateTimeField(nullable=True),

        'availability_zone': fields.StringField(nullable=True),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        'launched_on': fields.StringField(nullable=True),

        # NOTE(jdillaman): locked deprecated in favor of locked_by,
        # to be removed in Icehouse
        'locked': fields.BooleanField(default=False),
        'locked_by': fields.StringField(nullable=True),

        'os_type': fields.StringField(nullable=True),
        'architecture': fields.StringField(nullable=True),
        'vm_mode': fields.StringField(nullable=True),
        'uuid': fields.UUIDField(),

        'root_device_name': fields.StringField(nullable=True),
        'default_ephemeral_device': fields.StringField(nullable=True),
        'default_swap_device': fields.StringField(nullable=True),
        'config_drive': fields.StringField(nullable=True),

        'access_ip_v4': fields.IPV4AddressField(nullable=True),
        'access_ip_v6': fields.IPV6AddressField(nullable=True),

        'auto_disk_config': fields.BooleanField(default=False),
        'progress': fields.IntegerField(nullable=True),

        'shutdown_terminate': fields.BooleanField(default=False),
        'disable_terminate': fields.BooleanField(default=False),

        'cell_name': fields.StringField(nullable=True),

        'metadata': fields.DictOfStringsField(),
        'system_metadata': fields.DictOfNullableStringsField(),

        'info_cache': fields.ObjectField('InstanceInfoCache',
                                         nullable=True),

        'security_groups': fields.ObjectField('SecurityGroupList'),

        'fault': fields.ObjectField('InstanceFault', nullable=True),

        'cleaned': fields.BooleanField(default=False),

        'pci_devices': fields.ObjectField('PciDeviceList', nullable=True),
        }

    obj_extra_fields = ['name']

    def __init__(self, *args, **kwargs):
        super(Instance, self).__init__(*args, **kwargs)
        self._reset_metadata_tracking()

    def _reset_metadata_tracking(self):
        self._orig_system_metadata = (dict(self.system_metadata) if
                                      'system_metadata' in self else {})
        self._orig_metadata = (dict(self.metadata) if
                               'metadata' in self else {})

    def obj_reset_changes(self, fields=None):
        super(Instance, self).obj_reset_changes(fields)
        self._reset_metadata_tracking()

    def obj_what_changed(self):
        changes = super(Instance, self).obj_what_changed()
        if 'metadata' in self and self.metadata != self._orig_metadata:
            changes.add('metadata')
        if 'system_metadata' in self and (self.system_metadata !=
                                          self._orig_system_metadata):
            changes.add('system_metadata')
        return changes

    def obj_make_compatible(self, primitive, target_version):
        target_version = (int(target_version.split('.')[0]),
                          int(target_version.split('.')[1]))
        unicode_attributes = ['user_id', 'project_id', 'image_ref',
                              'kernel_id', 'ramdisk_id', 'hostname',
                              'key_name', 'key_data', 'host', 'node',
                              'user_data', 'availability_zone',
                              'display_name', 'display_description',
                              'launched_on', 'locked_by', 'os_type',
                              'architecture', 'vm_mode', 'root_device_name',
                              'default_ephemeral_device',
                              'default_swap_device', 'config_drive',
                              'cell_name']
        if target_version < (1, 10) and 'info_cache' in primitive:
            # NOTE(danms): Instance <= 1.9 (havana) had info_cache 1.4
            self.info_cache.obj_make_compatible(primitive['info_cache'],
                                                '1.4')
            primitive['info_cache']['nova_object.version'] = '1.4'
        if target_version < (1, 7):
            # NOTE(danms): Before 1.7, we couldn't handle unicode in
            # string fields, so squash it here
            for field in [x for x in unicode_attributes if x in primitive
                          and primitive[x] is not None]:
                primitive[field] = primitive[field].encode('ascii', 'replace')
        if target_version < (1, 6):
            # NOTE(danms): Before 1.6 there was no pci_devices list
            if 'pci_devices' in primitive:
                del primitive['pci_devices']

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
                if key == 'name':
                    # NOTE(danms): prevent recursion
                    continue
                elif not self.obj_attr_is_set(key):
                    # NOTE(danms): Don't trigger lazy-loads
                    continue
                info[key] = self[key]
            try:
                base_name = CONF.instance_name_template % info
            except KeyError:
                base_name = self.uuid
        return base_name

    @staticmethod
    def _from_db_object(context, instance, db_inst, expected_attrs=None):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """
        if expected_attrs is None:
            expected_attrs = []
        # Most of the field names match right now, so be quick
        for field in instance.fields:
            if field in INSTANCE_OPTIONAL_ATTRS:
                continue
            elif field == 'deleted':
                instance.deleted = db_inst['deleted'] == db_inst['id']
            elif field == 'cleaned':
                instance.cleaned = db_inst['cleaned'] == 1
            else:
                instance[field] = db_inst[field]

        if 'metadata' in expected_attrs:
            instance['metadata'] = utils.instance_meta(db_inst)
        if 'system_metadata' in expected_attrs:
            instance['system_metadata'] = utils.instance_sys_meta(db_inst)
        if 'fault' in expected_attrs:
            instance['fault'] = (
                instance_fault.InstanceFault.get_latest_for_instance(
                    context, instance.uuid))

        if 'pci_devices' in expected_attrs:
            pci_devices = pci_device._make_pci_list(
                    context, pci_device.PciDeviceList(),
                    db_inst['pci_devices'])
            instance['pci_devices'] = pci_devices
        if 'info_cache' in expected_attrs:
            if db_inst['info_cache'] is None:
                instance.info_cache = None
            elif not instance.obj_attr_is_set('info_cache'):
                # TODO(danms): If this ever happens on a backlevel instance
                # passed to us by a backlevel service, things will break
                instance.info_cache = instance_info_cache.InstanceInfoCache()
            if instance.info_cache is not None:
                instance_info_cache.InstanceInfoCache._from_db_object(
                    context, instance.info_cache, db_inst['info_cache'])
        if 'security_groups' in expected_attrs:
            sec_groups = security_group._make_secgroup_list(
                    context, security_group.SecurityGroupList(),
                    db_inst['security_groups'])
            instance['security_groups'] = sec_groups

        instance._context = context
        instance.obj_reset_changes()
        return instance

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid, expected_attrs=None, use_slave=False):
        if expected_attrs is None:
            expected_attrs = ['info_cache', 'security_groups']
        columns_to_join = _expected_cols(expected_attrs)
        db_inst = db.instance_get_by_uuid(context, uuid,
                                          columns_to_join=columns_to_join,
                                          use_slave=use_slave)
        return cls._from_db_object(context, cls(), db_inst,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_id(cls, context, inst_id, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = ['info_cache', 'security_groups']
        columns_to_join = _expected_cols(expected_attrs)
        db_inst = db.instance_get(context, inst_id,
                                  columns_to_join=columns_to_join)
        return cls._from_db_object(context, cls(), db_inst,
                                   expected_attrs)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        updates.pop('id', None)
        expected_attrs = [attr for attr in INSTANCE_DEFAULT_FIELDS
                          if attr in updates]
        if 'security_groups' in updates:
            updates['security_groups'] = [x.name for x in
                                          updates['security_groups']]
        if 'info_cache' in updates:
            updates['info_cache'] = {
                'network_info': updates['info_cache'].network_info.json()
                }
        db_inst = db.instance_create(context, updates)
        Instance._from_db_object(context, self, db_inst, expected_attrs)

    @base.remotable
    def destroy(self, context):
        if not self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='destroy',
                                              reason='already destroyed')
        if not self.obj_attr_is_set('uuid'):
            raise exception.ObjectActionError(action='destroy',
                                              reason='no uuid')
        if not self.obj_attr_is_set('host') or not self.host:
            # NOTE(danms): If our host is not set, avoid a race
            constraint = db.constraint(host=db.equal_any(None))
        else:
            constraint = None

        try:
            db_inst = db.instance_destroy(context, self.uuid,
                                          constraint=constraint)
            Instance._from_db_object(context, self, db_inst)
        except exception.ConstraintNotMet:
            raise exception.ObjectActionError(action='destroy',
                                              reason='host changed')
        delattr(self, base.get_attrname('id'))

    def _save_info_cache(self, context):
        self.info_cache.save(context)

    def _save_security_groups(self, context):
        for secgroup in self.security_groups:
            secgroup.save(context)

    def _save_fault(self, context):
        # NOTE(danms): I don't think we need to worry about this, do we?
        pass

    def _save_pci_devices(self, context):
        # NOTE(yjiang5): All devices held by PCI tracker, only PCI tracker
        # permitted to update the DB. all change to devices from here will
        # be dropped.
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
            stale_instance = self.obj_clone()

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
            if (self.obj_attr_is_set(field) and
                    isinstance(self[field], base.NovaObject)):
                try:
                    getattr(self, '_save_%s' % field)(context)
                except AttributeError:
                    LOG.exception(_('No save handler for %s') % field,
                                  instance=self)
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
            if (self.VERSION == '1.9' and
                    expected_task_state == 'image_snapshot'):
                # NOTE(danms): Icehouse introduced a pending state which
                # Havana doesn't know about. If we're an old instance,
                # tolerate the pending state as well
                expected_task_state = [
                    expected_task_state, 'image_snapshot_pending']
            updates['expected_task_state'] = expected_task_state
        if expected_vm_state is not None:
            updates['expected_vm_state'] = expected_vm_state

        expected_attrs = [attr for attr in _INSTANCE_OPTIONAL_JOINED_FIELDS
                               if self.obj_attr_is_set(attr)]
        # NOTE(alaski): We need to pull system_metadata for the
        # notification.send_update() below.  If we don't there's a KeyError
        # when it tries to extract the flavor.
        if 'system_metadata' not in expected_attrs:
            expected_attrs.append('system_metadata')
        old_ref, inst_ref = db.instance_update_and_get_original(
                context, self.uuid, updates, update_cells=False,
                columns_to_join=_expected_cols(expected_attrs))

        if stale_instance:
            _handle_cell_update_from_api()
        elif cell_type == 'compute':
            cells_api = cells_rpcapi.CellsAPI()
            cells_api.instance_update_at_top(context, inst_ref)

        self._from_db_object(context, self, inst_ref, expected_attrs)
        notifications.send_update(context, old_ref, inst_ref)
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context, use_slave=False):
        extra = [field for field in INSTANCE_OPTIONAL_ATTRS
                       if self.obj_attr_is_set(field)]
        current = self.__class__.get_by_uuid(context, uuid=self.uuid,
                                             expected_attrs=extra,
                                             use_slave=use_slave)
        # NOTE(danms): We orphan the instance copy so we do not unexpectedly
        # trigger a lazy-load (which would mean we failed to calculate the
        # expected_attrs properly)
        current._context = None

        for field in self.fields:
            if self.obj_attr_is_set(field):
                if field == 'info_cache':
                    self.info_cache.refresh()
                    # NOTE(danms): Make sure this shows up as touched
                    self.info_cache = self.info_cache
                elif self[field] != current[field]:
                    self[field] = current[field]
        self.obj_reset_changes()

    def obj_load_attr(self, attrname):
        if attrname not in INSTANCE_OPTIONAL_ATTRS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        LOG.debug(_("Lazy-loading `%(attr)s' on %(name)s uuid %(uuid)s"),
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'uuid': self.uuid,
                   })
        # FIXME(comstud): This should be optimized to only load the attr.
        instance = self.__class__.get_by_uuid(self._context,
                                              uuid=self.uuid,
                                              expected_attrs=[attrname])

        # NOTE(danms): Never allow us to recursively-load
        if instance.obj_attr_is_set(attrname):
            self[attrname] = instance[attrname]
        else:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='loading %s requires recursion' % attrname)

    def get_flavor(self, namespace=None):
        prefix = ('%s_' % namespace) if namespace is not None else ''

        db_flavor = flavors.extract_flavor(self, prefix)
        flavor = flavor_obj.Flavor()
        for key in flavors.system_metadata_flavor_props:
            flavor[key] = db_flavor[key]
        return flavor

    def set_flavor(self, flavor, namespace=None):
        prefix = ('%s_' % namespace) if namespace is not None else ''

        self.system_metadata = flavors.save_flavor_info(
            self.system_metadata, flavor, prefix)
        self.save()

    def delete_flavor(self, namespace):
        self.system_metadata = flavors.delete_flavor_info(
            self.system_metadata, "%s_" % namespace)
        self.save()


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


class InstanceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added use_slave to get_by_host
    #              Instance <= version 1.9
    # Version 1.2: Instance <= version 1.11
    # Version 1.3: Added use_slave to get_by_filters
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('Instance'),
    }
    child_versions = {
        '1.1': '1.9',
        # NOTE(danms): Instance was at 1.9 before we added this
        '1.2': '1.11',
        '1.3': '1.11',
        }

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters,
                       sort_key='created_at', sort_dir='desc', limit=None,
                       marker=None, expected_attrs=None, use_slave=False):
        db_inst_list = db.instance_get_all_by_filters(
            context, filters, sort_key, sort_dir, limit=limit, marker=marker,
            columns_to_join=_expected_cols(expected_attrs),
            use_slave=use_slave)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, expected_attrs=None, use_slave=False):
        db_inst_list = db.instance_get_all_by_host(
            context, host, columns_to_join=_expected_cols(expected_attrs),
            use_slave=use_slave)
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

    @base.remotable_classmethod
    def get_by_security_group_id(cls, context, security_group_id):
        db_secgroup = db.security_group_get(
            context, security_group_id,
            columns_to_join=['instances.info_cache',
                             'instances.system_metadata'])
        return _make_instance_list(context, cls(), db_secgroup['instances'],
                                   ['info_cache', 'system_metadata'])

    @classmethod
    def get_by_security_group(cls, context, security_group):
        return cls.get_by_security_group_id(context, security_group.id)

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
