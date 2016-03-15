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

import contextlib

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import versionutils

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova.cells import utils as cells_utils
from nova import db
from nova import exception
from nova.i18n import _LE
from nova import notifications
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


# List of fields that can be joined in DB layer.
_INSTANCE_OPTIONAL_JOINED_FIELDS = ['metadata', 'system_metadata',
                                    'info_cache', 'security_groups',
                                    'pci_devices', 'tags', 'services']
# These are fields that are optional but don't translate to db columns
_INSTANCE_OPTIONAL_NON_COLUMN_FIELDS = ['fault', 'flavor', 'old_flavor',
                                        'new_flavor', 'ec2_ids']
# These are fields that are optional and in instance_extra
_INSTANCE_EXTRA_FIELDS = ['numa_topology', 'pci_requests',
                          'flavor', 'vcpu_model', 'migration_context']

# These are fields that can be specified as expected_attrs
INSTANCE_OPTIONAL_ATTRS = (_INSTANCE_OPTIONAL_JOINED_FIELDS +
                           _INSTANCE_OPTIONAL_NON_COLUMN_FIELDS +
                           _INSTANCE_EXTRA_FIELDS)
# These are fields that most query calls load by default
INSTANCE_DEFAULT_FIELDS = ['metadata', 'system_metadata',
                           'info_cache', 'security_groups']


def _expected_cols(expected_attrs):
    """Return expected_attrs that are columns needing joining.

    NB: This function may modify expected_attrs if one
    requested attribute requires another.
    """
    if not expected_attrs:
        return expected_attrs

    simple_cols = [attr for attr in expected_attrs
                   if attr in _INSTANCE_OPTIONAL_JOINED_FIELDS]

    complex_cols = ['extra.%s' % field
                    for field in _INSTANCE_EXTRA_FIELDS
                    if field in expected_attrs]
    if complex_cols:
        simple_cols.append('extra')
    simple_cols = [x for x in simple_cols if x not in _INSTANCE_EXTRA_FIELDS]
    return simple_cols + complex_cols


_NO_DATA_SENTINEL = object()


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class Instance(base.NovaPersistentObject, base.NovaObject,
               base.NovaObjectDictCompat):
    # Version 2.0: Initial version
    # Version 2.1: Added services
    VERSION = '2.1'

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

        'services': fields.ObjectField('ServiceList'),

        'memory_mb': fields.IntegerField(nullable=True),
        'vcpus': fields.IntegerField(nullable=True),
        'root_gb': fields.IntegerField(nullable=True),
        'ephemeral_gb': fields.IntegerField(nullable=True),
        'ephemeral_key_uuid': fields.UUIDField(nullable=True),

        'host': fields.StringField(nullable=True),
        'node': fields.StringField(nullable=True),

        'instance_type_id': fields.IntegerField(nullable=True),

        'user_data': fields.StringField(nullable=True),

        'reservation_id': fields.StringField(nullable=True),

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
        'numa_topology': fields.ObjectField('InstanceNUMATopology',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequests',
                                           nullable=True),
        'tags': fields.ObjectField('TagList'),
        'flavor': fields.ObjectField('Flavor'),
        'old_flavor': fields.ObjectField('Flavor', nullable=True),
        'new_flavor': fields.ObjectField('Flavor', nullable=True),
        'vcpu_model': fields.ObjectField('VirtCPUModel', nullable=True),
        'ec2_ids': fields.ObjectField('EC2Ids'),
        'migration_context': fields.ObjectField('MigrationContext',
                                                nullable=True)
        }

    obj_extra_fields = ['name']

    def obj_make_compatible(self, primitive, target_version):
        super(Instance, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (2, 1) and 'services' in primitive:
            del primitive['services']

    def __init__(self, *args, **kwargs):
        super(Instance, self).__init__(*args, **kwargs)
        self._reset_metadata_tracking()

    @property
    def image_meta(self):
        return objects.ImageMeta.from_instance(self)

    def _reset_metadata_tracking(self, fields=None):
        if fields is None or 'system_metadata' in fields:
            self._orig_system_metadata = (dict(self.system_metadata) if
                                          'system_metadata' in self else {})
        if fields is None or 'metadata' in fields:
            self._orig_metadata = (dict(self.metadata) if
                                   'metadata' in self else {})

    def obj_reset_changes(self, fields=None, recursive=False):
        super(Instance, self).obj_reset_changes(fields,
                                                recursive=recursive)
        self._reset_metadata_tracking(fields=fields)

    def obj_what_changed(self):
        changes = super(Instance, self).obj_what_changed()
        if 'metadata' in self and self.metadata != self._orig_metadata:
            changes.add('metadata')
        if 'system_metadata' in self and (self.system_metadata !=
                                          self._orig_system_metadata):
            changes.add('system_metadata')
        return changes

    @classmethod
    def _obj_from_primitive(cls, context, objver, primitive):
        self = super(Instance, cls)._obj_from_primitive(context, objver,
                                                        primitive)
        self._reset_metadata_tracking()
        return self

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

    def _flavor_from_db(self, db_flavor):
        """Load instance flavor information from instance_extra."""

        flavor_info = jsonutils.loads(db_flavor)

        self.flavor = objects.Flavor.obj_from_primitive(flavor_info['cur'])
        if flavor_info['old']:
            self.old_flavor = objects.Flavor.obj_from_primitive(
                flavor_info['old'])
        else:
            self.old_flavor = None
        if flavor_info['new']:
            self.new_flavor = objects.Flavor.obj_from_primitive(
                flavor_info['new'])
        else:
            self.new_flavor = None
        self.obj_reset_changes(['flavor', 'old_flavor', 'new_flavor'])

    @staticmethod
    def _from_db_object(context, instance, db_inst, expected_attrs=None):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """
        instance._context = context
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

        # NOTE(danms): We can be called with a dict instead of a
        # SQLAlchemy object, so we have to be careful here
        if hasattr(db_inst, '__dict__'):
            have_extra = 'extra' in db_inst.__dict__ and db_inst['extra']
        else:
            have_extra = 'extra' in db_inst and db_inst['extra']

        if 'metadata' in expected_attrs:
            instance['metadata'] = utils.instance_meta(db_inst)
        if 'system_metadata' in expected_attrs:
            instance['system_metadata'] = utils.instance_sys_meta(db_inst)
        if 'fault' in expected_attrs:
            instance['fault'] = (
                objects.InstanceFault.get_latest_for_instance(
                    context, instance.uuid))
        if 'numa_topology' in expected_attrs:
            if have_extra:
                instance._load_numa_topology(
                    db_inst['extra'].get('numa_topology'))
            else:
                instance.numa_topology = None
        if 'pci_requests' in expected_attrs:
            if have_extra:
                instance._load_pci_requests(
                    db_inst['extra'].get('pci_requests'))
            else:
                instance.pci_requests = None
        if 'vcpu_model' in expected_attrs:
            if have_extra:
                instance._load_vcpu_model(
                    db_inst['extra'].get('vcpu_model'))
            else:
                instance.vcpu_model = None
        if 'ec2_ids' in expected_attrs:
            instance._load_ec2_ids()
        if 'migration_context' in expected_attrs:
            if have_extra:
                instance._load_migration_context(
                    db_inst['extra'].get('migration_context'))
            else:
                instance.migration_context = None
        if 'info_cache' in expected_attrs:
            if db_inst.get('info_cache') is None:
                instance.info_cache = None
            elif not instance.obj_attr_is_set('info_cache'):
                # TODO(danms): If this ever happens on a backlevel instance
                # passed to us by a backlevel service, things will break
                instance.info_cache = objects.InstanceInfoCache(context)
            if instance.info_cache is not None:
                instance.info_cache._from_db_object(context,
                                                    instance.info_cache,
                                                    db_inst['info_cache'])

        if any([x in expected_attrs for x in ('flavor',
                                              'old_flavor',
                                              'new_flavor')]):
            if have_extra and db_inst['extra'].get('flavor'):
                instance._flavor_from_db(db_inst['extra']['flavor'])

        # TODO(danms): If we are updating these on a backlevel instance,
        # we'll end up sending back new versions of these objects (see
        # above note for new info_caches
        if 'pci_devices' in expected_attrs:
            pci_devices = base.obj_make_list(
                    context, objects.PciDeviceList(context),
                    objects.PciDevice, db_inst['pci_devices'])
            instance['pci_devices'] = pci_devices
        if 'security_groups' in expected_attrs:
            sec_groups = base.obj_make_list(
                    context, objects.SecurityGroupList(context),
                    objects.SecurityGroup, db_inst.get('security_groups', []))
            instance['security_groups'] = sec_groups

        if 'tags' in expected_attrs:
            tags = base.obj_make_list(
                context, objects.TagList(context),
                objects.Tag, db_inst['tags'])
            instance['tags'] = tags

        if 'services' in expected_attrs:
            services = base.obj_make_list(
                    context, objects.ServiceList(context),
                    objects.Service, db_inst['services'])
            instance['services'] = services

        instance.obj_reset_changes()
        return instance

    @staticmethod
    @db.select_db_reader_mode
    def _db_instance_get_by_uuid(context, uuid, columns_to_join,
                                 use_slave=False):
        return db.instance_get_by_uuid(context, uuid,
                                       columns_to_join=columns_to_join)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid, expected_attrs=None, use_slave=False):
        if expected_attrs is None:
            expected_attrs = ['info_cache', 'security_groups']
        columns_to_join = _expected_cols(expected_attrs)
        db_inst = cls._db_instance_get_by_uuid(context, uuid, columns_to_join,
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
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        expected_attrs = [attr for attr in INSTANCE_DEFAULT_FIELDS
                          if attr in updates]
        if 'security_groups' in updates:
            updates['security_groups'] = [x.name for x in
                                          updates['security_groups']]
        if 'info_cache' in updates:
            updates['info_cache'] = {
                'network_info': updates['info_cache'].network_info.json()
                }
        updates['extra'] = {}
        numa_topology = updates.pop('numa_topology', None)
        expected_attrs.append('numa_topology')
        if numa_topology:
            updates['extra']['numa_topology'] = numa_topology._to_json()
        else:
            updates['extra']['numa_topology'] = None
        pci_requests = updates.pop('pci_requests', None)
        expected_attrs.append('pci_requests')
        if pci_requests:
            updates['extra']['pci_requests'] = (
                pci_requests.to_json())
        else:
            updates['extra']['pci_requests'] = None
        flavor = updates.pop('flavor', None)
        if flavor:
            expected_attrs.append('flavor')
            old = ((self.obj_attr_is_set('old_flavor') and
                    self.old_flavor) and
                   self.old_flavor.obj_to_primitive() or None)
            new = ((self.obj_attr_is_set('new_flavor') and
                    self.new_flavor) and
                   self.new_flavor.obj_to_primitive() or None)
            flavor_info = {
                'cur': self.flavor.obj_to_primitive(),
                'old': old,
                'new': new,
            }
            updates['extra']['flavor'] = jsonutils.dumps(flavor_info)
        vcpu_model = updates.pop('vcpu_model', None)
        expected_attrs.append('vcpu_model')
        if vcpu_model:
            updates['extra']['vcpu_model'] = (
                jsonutils.dumps(vcpu_model.obj_to_primitive()))
        else:
            updates['extra']['vcpu_model'] = None
        db_inst = db.instance_create(self._context, updates)
        self._from_db_object(self._context, self, db_inst, expected_attrs)

        # NOTE(danms): The EC2 ids are created on their first load. In order
        # to avoid them being missing and having to be loaded later, we
        # load them once here on create now that the instance record is
        # created.
        self._load_ec2_ids()
        self.obj_reset_changes(['ec2_ids'])

    @base.remotable
    def destroy(self):
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

        cell_type = cells_opts.get_cell_type()
        if cell_type is not None:
            stale_instance = self.obj_clone()

        try:
            db_inst = db.instance_destroy(self._context, self.uuid,
                                          constraint=constraint)
            self._from_db_object(self._context, self, db_inst)
        except exception.ConstraintNotMet:
            raise exception.ObjectActionError(action='destroy',
                                              reason='host changed')
        if cell_type == 'compute':
            cells_api = cells_rpcapi.CellsAPI()
            cells_api.instance_destroy_at_top(self._context, stale_instance)
        delattr(self, base.get_attrname('id'))

    def _save_info_cache(self, context):
        if self.info_cache:
            with self.info_cache.obj_alternate_context(context):
                self.info_cache.save()

    def _save_security_groups(self, context):
        security_groups = self.security_groups or []
        for secgroup in security_groups:
            with secgroup.obj_alternate_context(context):
                secgroup.save()
        self.security_groups.obj_reset_changes()

    def _save_fault(self, context):
        # NOTE(danms): I don't think we need to worry about this, do we?
        pass

    def _save_numa_topology(self, context):
        if self.numa_topology:
            self.numa_topology.instance_uuid = self.uuid
            with self.numa_topology.obj_alternate_context(context):
                self.numa_topology._save()
        else:
            objects.InstanceNUMATopology.delete_by_instance_uuid(
                    context, self.uuid)

    def _save_pci_requests(self, context):
        # NOTE(danms): No need for this yet.
        pass

    def _save_pci_devices(self, context):
        # NOTE(yjiang5): All devices held by PCI tracker, only PCI tracker
        # permitted to update the DB. all change to devices from here will
        # be dropped.
        pass

    def _save_flavor(self, context):
        if not any([x in self.obj_what_changed() for x in
                    ('flavor', 'old_flavor', 'new_flavor')]):
            return
        # FIXME(danms): We can do this smarterly by updating this
        # with all the other extra things at the same time
        flavor_info = {
            'cur': self.flavor.obj_to_primitive(),
            'old': (self.old_flavor and
                    self.old_flavor.obj_to_primitive() or None),
            'new': (self.new_flavor and
                    self.new_flavor.obj_to_primitive() or None),
        }
        db.instance_extra_update_by_uuid(
            context, self.uuid,
            {'flavor': jsonutils.dumps(flavor_info)})
        self.obj_reset_changes(['flavor', 'old_flavor', 'new_flavor'])

    def _save_old_flavor(self, context):
        if 'old_flavor' in self.obj_what_changed():
            self._save_flavor(context)

    def _save_new_flavor(self, context):
        if 'new_flavor' in self.obj_what_changed():
            self._save_flavor(context)

    def _save_vcpu_model(self, context):
        # TODO(yjiang5): should merge the db accesses for all the extra
        # fields
        if 'vcpu_model' in self.obj_what_changed():
            if self.vcpu_model:
                update = jsonutils.dumps(self.vcpu_model.obj_to_primitive())
            else:
                update = None
            db.instance_extra_update_by_uuid(
                context, self.uuid,
                {'vcpu_model': update})

    def _save_ec2_ids(self, context):
        # NOTE(hanlind): Read-only so no need to save this.
        pass

    def _save_migration_context(self, context):
        if self.migration_context:
            self.migration_context.instance_uuid = self.uuid
            with self.migration_context.obj_alternate_context(context):
                self.migration_context._save()
        else:
            objects.MigrationContext._destroy(context, self.uuid)

    @base.remotable
    def save(self, expected_vm_state=None,
             expected_task_state=None, admin_state_reset=False):
        """Save updates to this instance

        Column-wise updates will be made based on the result of
        self.what_changed(). If expected_task_state is provided,
        it will be checked against the in-database copy of the
        instance before updates are made.

        :param:context: Security context
        :param:expected_task_state: Optional tuple of valid task states
        for the instance to be in
        :param:expected_vm_state: Optional tuple of valid vm states
        for the instance to be in
        :param admin_state_reset: True if admin API is forcing setting
        of task_state/vm_state

        """
        # Store this on the class because _cell_name_blocks_sync is useless
        # after the db update call below.
        self._sync_cells = not self._cell_name_blocks_sync()

        context = self._context
        cell_type = cells_opts.get_cell_type()

        if cell_type is not None:
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

        cells_update_from_api = (cell_type == 'api' and self.cell_name and
                                 self._sync_cells)

        if cells_update_from_api:
            def _handle_cell_update_from_api():
                cells_api = cells_rpcapi.CellsAPI()
                cells_api.instance_update_from_api(context, stale_instance,
                            expected_vm_state,
                            expected_task_state,
                            admin_state_reset)

        updates = {}
        changes = self.obj_what_changed()

        for field in self.fields:
            # NOTE(danms): For object fields, we construct and call a
            # helper method like self._save_$attrname()
            if (self.obj_attr_is_set(field) and
                    isinstance(self.fields[field], fields.ObjectField)):
                try:
                    getattr(self, '_save_%s' % field)(context)
                except AttributeError:
                    LOG.exception(_LE('No save handler for %s'), field,
                                  instance=self)
                except db_exc.DBReferenceError as exp:
                    if exp.key != 'instance_uuid':
                        raise
                    # NOTE(melwitt): This will happen if we instance.save()
                    # before an instance.create() and FK constraint fails.
                    # In practice, this occurs in cells during a delete of
                    # an unscheduled instance. Otherwise, it could happen
                    # as a result of bug.
                    raise exception.InstanceNotFound(instance_id=self.uuid)
            elif field in changes:
                if (field == 'cell_name' and self[field] is not None and
                        self[field].startswith(cells_utils.BLOCK_SYNC_FLAG)):
                    updates[field] = self[field].replace(
                            cells_utils.BLOCK_SYNC_FLAG, '', 1)
                else:
                    updates[field] = self[field]

        if not updates:
            if cells_update_from_api:
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

        expected_attrs = [attr for attr in _INSTANCE_OPTIONAL_JOINED_FIELDS
                               if self.obj_attr_is_set(attr)]
        if 'pci_devices' in expected_attrs:
            # NOTE(danms): We don't refresh pci_devices on save right now
            expected_attrs.remove('pci_devices')

        # NOTE(alaski): We need to pull system_metadata for the
        # notification.send_update() below.  If we don't there's a KeyError
        # when it tries to extract the flavor.
        # NOTE(danms): If we have sysmeta, we need flavor since the caller
        # might be expecting flavor information as a result
        if 'system_metadata' not in expected_attrs:
            expected_attrs.append('system_metadata')
            expected_attrs.append('flavor')
        old_ref, inst_ref = db.instance_update_and_get_original(
                context, self.uuid, updates,
                columns_to_join=_expected_cols(expected_attrs))
        self._from_db_object(context, self, inst_ref,
                             expected_attrs=expected_attrs)

        if cells_update_from_api:
            _handle_cell_update_from_api()
        elif cell_type == 'compute':
            if self._sync_cells:
                cells_api = cells_rpcapi.CellsAPI()
                cells_api.instance_update_at_top(context, stale_instance)

        def _notify():
            # NOTE(danms): We have to be super careful here not to trigger
            # any lazy-loads that will unmigrate or unbackport something. So,
            # make a copy of the instance for notifications first.
            new_ref = self.obj_clone()

            notifications.send_update(context, old_ref, new_ref)

        # NOTE(alaski): If cell synchronization is blocked it means we have
        # already run this block of code in either the parent or child of this
        # cell.  Therefore this notification has already been sent.
        if not self._sync_cells:
            _notify = lambda: None  # noqa: F811

        _notify()

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, use_slave=False):
        extra = [field for field in INSTANCE_OPTIONAL_ATTRS
                       if self.obj_attr_is_set(field)]
        current = self.__class__.get_by_uuid(self._context, uuid=self.uuid,
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
                elif self[field] != current[field]:
                    self[field] = current[field]
        self.obj_reset_changes()

    def _load_generic(self, attrname):
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

    def _load_fault(self):
        self.fault = objects.InstanceFault.get_latest_for_instance(
            self._context, self.uuid)

    def _load_numa_topology(self, db_topology=None):
        if db_topology is not None:
            self.numa_topology = \
                objects.InstanceNUMATopology.obj_from_db_obj(self.uuid,
                                                             db_topology)
        else:
            try:
                self.numa_topology = \
                    objects.InstanceNUMATopology.get_by_instance_uuid(
                        self._context, self.uuid)
            except exception.NumaTopologyNotFound:
                self.numa_topology = None

    def _load_pci_requests(self, db_requests=None):
        # FIXME: also do this if none!
        if db_requests is not None:
            self.pci_requests = objects.InstancePCIRequests.obj_from_db(
                self._context, self.uuid, db_requests)
        else:
            self.pci_requests = \
                objects.InstancePCIRequests.get_by_instance_uuid(
                    self._context, self.uuid)

    def _load_flavor(self):
        instance = self.__class__.get_by_uuid(
            self._context, uuid=self.uuid,
            expected_attrs=['flavor', 'system_metadata'])

        # NOTE(danms): Orphan the instance to make sure we don't lazy-load
        # anything below
        instance._context = None
        self.flavor = instance.flavor
        self.old_flavor = instance.old_flavor
        self.new_flavor = instance.new_flavor

        # NOTE(danms): The query above may have migrated the flavor from
        # system_metadata. Since we have it anyway, go ahead and refresh
        # our system_metadata from it so that a save will be accurate.
        instance.system_metadata.update(self.get('system_metadata', {}))
        self.system_metadata = instance.system_metadata

    def _load_vcpu_model(self, db_vcpu_model=None):
        if db_vcpu_model is None:
            self.vcpu_model = objects.VirtCPUModel.get_by_instance_uuid(
                self._context, self.uuid)
        else:
            db_vcpu_model = jsonutils.loads(db_vcpu_model)
            self.vcpu_model = objects.VirtCPUModel.obj_from_primitive(
                db_vcpu_model)

    def _load_ec2_ids(self):
        self.ec2_ids = objects.EC2Ids.get_by_instance(self._context, self)

    def _load_security_groups(self):
        self.security_groups = objects.SecurityGroupList.get_by_instance(
            self._context, self)

    def _load_pci_devices(self):
        self.pci_devices = objects.PciDeviceList.get_by_instance_uuid(
            self._context, self.uuid)

    def _load_migration_context(self, db_context=_NO_DATA_SENTINEL):
        if db_context is _NO_DATA_SENTINEL:
            try:
                self.migration_context = (
                    objects.MigrationContext.get_by_instance_uuid(
                        self._context, self.uuid))
            except exception.MigrationContextNotFound:
                self.migration_context = None
        elif db_context is None:
            self.migration_context = None
        else:
            self.migration_context = objects.MigrationContext.obj_from_db_obj(
                db_context)

    def apply_migration_context(self):
        if self.migration_context:
            self.numa_topology = self.migration_context.new_numa_topology
        else:
            LOG.debug("Trying to apply a migration context that does not "
                      "seem to be set for this instance", instance=self)

    def revert_migration_context(self):
        if self.migration_context:
            self.numa_topology = self.migration_context.old_numa_topology
        else:
            LOG.debug("Trying to revert a migration context that does not "
                      "seem to be set for this instance", instance=self)

    @contextlib.contextmanager
    def mutated_migration_context(self):
        """Context manager to temporarily apply the migration context.

        Calling .save() from within the context manager means that the mutated
        context will be saved which can cause incorrect resource tracking, and
        should be avoided.
        """
        current_numa_topo = self.numa_topology
        self.apply_migration_context()
        try:
            yield
        finally:
            self.numa_topology = current_numa_topo

    @base.remotable
    def drop_migration_context(self):
        if self.migration_context:
            objects.MigrationContext._destroy(self._context, self.uuid)
            self.migration_context = None

    def clear_numa_topology(self):
        numa_topology = self.numa_topology
        if numa_topology is not None:
            self.numa_topology = numa_topology.clear_host_pinning()

    def obj_load_attr(self, attrname):
        if attrname not in INSTANCE_OPTIONAL_ATTRS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)

        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        LOG.debug("Lazy-loading '%(attr)s' on %(name)s uuid %(uuid)s",
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'uuid': self.uuid,
                   })

        # NOTE(danms): We handle some fields differently here so that we
        # can be more efficient
        if attrname == 'fault':
            self._load_fault()
        elif attrname == 'numa_topology':
            self._load_numa_topology()
        elif attrname == 'pci_requests':
            self._load_pci_requests()
        elif attrname == 'vcpu_model':
            self._load_vcpu_model()
        elif attrname == 'ec2_ids':
            self._load_ec2_ids()
        elif attrname == 'migration_context':
            self._load_migration_context()
        elif attrname == 'security_groups':
            self._load_security_groups()
        elif attrname == 'pci_devices':
            self._load_pci_devices()
        elif 'flavor' in attrname:
            self._load_flavor()
        elif attrname == 'services' and self.deleted:
            # NOTE(mriedem): The join in the data model for instances.services
            # filters on instances.deleted == 0, so if the instance is deleted
            # don't attempt to even load services since we'll fail.
            self.services = objects.ServiceList(self._context)
        else:
            # FIXME(comstud): This should be optimized to only load the attr.
            self._load_generic(attrname)
        self.obj_reset_changes([attrname])

    def get_flavor(self, namespace=None):
        prefix = ('%s_' % namespace) if namespace is not None else ''
        attr = '%sflavor' % prefix
        try:
            return getattr(self, attr)
        except exception.FlavorNotFound:
            # NOTE(danms): This only happens in the case where we don't
            # have flavor information in sysmeta or extra, and doing
            # this triggers a lookup based on our instance_type_id for
            # (very) legacy instances. That legacy code expects a None here,
            # so emulate it for this helper, even though the actual attribute
            # is not nullable.
            return None

    @base.remotable
    def delete_metadata_key(self, key):
        """Optimized metadata delete method.

        This provides a more efficient way to delete a single metadata
        key, instead of just calling instance.save(). This should be called
        with the key still present in self.metadata, which it will update
        after completion.
        """
        db.instance_metadata_delete(self._context, self.uuid, key)
        md_was_changed = 'metadata' in self.obj_what_changed()
        del self.metadata[key]
        self._orig_metadata.pop(key, None)
        notifications.send_update(self._context, self, self)
        if not md_was_changed:
            self.obj_reset_changes(['metadata'])

    def _cell_name_blocks_sync(self):
        if (self.obj_attr_is_set('cell_name') and
                self.cell_name is not None and
                self.cell_name.startswith(cells_utils.BLOCK_SYNC_FLAG)):
            return True
        return False

    def _normalize_cell_name(self):
        """Undo skip_cell_sync()'s cell_name modification if applied"""

        if not self.obj_attr_is_set('cell_name') or self.cell_name is None:
            return
        cn_changed = 'cell_name' in self.obj_what_changed()
        if self.cell_name.startswith(cells_utils.BLOCK_SYNC_FLAG):
            self.cell_name = self.cell_name.replace(
                    cells_utils.BLOCK_SYNC_FLAG, '', 1)
            # cell_name is not normally an empty string, this means it was None
            # or unset before cells_utils.BLOCK_SYNC_FLAG was applied.
            if len(self.cell_name) == 0:
                self.cell_name = None
        if not cn_changed:
            self.obj_reset_changes(['cell_name'])

    @contextlib.contextmanager
    def skip_cells_sync(self):
        """Context manager to save an instance without syncing cells.

        Temporarily disables the cells syncing logic, if enabled.  This should
        only be used when saving an instance that has been passed down/up from
        another cell in order to avoid passing it back to the originator to be
        re-saved.
        """
        cn_changed = 'cell_name' in self.obj_what_changed()
        if not self.obj_attr_is_set('cell_name') or self.cell_name is None:
            self.cell_name = ''
        self.cell_name = '%s%s' % (cells_utils.BLOCK_SYNC_FLAG, self.cell_name)
        if not cn_changed:
            self.obj_reset_changes(['cell_name'])
        try:
            yield
        finally:
            self._normalize_cell_name()


def _make_instance_list(context, inst_list, db_inst_list, expected_attrs):
    get_fault = expected_attrs and 'fault' in expected_attrs
    inst_faults = {}
    if get_fault:
        # Build an instance_uuid:latest-fault mapping
        expected_attrs.remove('fault')
        instance_uuids = [inst['uuid'] for inst in db_inst_list]
        faults = objects.InstanceFaultList.get_by_instance_uuids(
            context, instance_uuids)
        for fault in faults:
            if fault.instance_uuid not in inst_faults:
                inst_faults[fault.instance_uuid] = fault

    inst_cls = objects.Instance

    inst_list.objects = []
    for db_inst in db_inst_list:
        inst_obj = inst_cls._from_db_object(
                context, inst_cls(context), db_inst,
                expected_attrs=expected_attrs)
        if get_fault:
            inst_obj.fault = inst_faults.get(inst_obj.uuid, None)
        inst_list.objects.append(inst_obj)
    inst_list.obj_reset_changes()
    return inst_list


@base.NovaObjectRegistry.register
class InstanceList(base.ObjectListBase, base.NovaObject):
    # Version 2.0: Initial Version
    VERSION = '2.0'

    fields = {
        'objects': fields.ListOfObjectsField('Instance'),
    }

    @classmethod
    @db.select_db_reader_mode
    def _get_by_filters_impl(cls, context, filters,
                       sort_key='created_at', sort_dir='desc', limit=None,
                       marker=None, expected_attrs=None, use_slave=False,
                       sort_keys=None, sort_dirs=None):
        if sort_keys or sort_dirs:
            db_inst_list = db.instance_get_all_by_filters_sort(
                context, filters, limit=limit, marker=marker,
                columns_to_join=_expected_cols(expected_attrs),
                sort_keys=sort_keys, sort_dirs=sort_dirs)
        else:
            db_inst_list = db.instance_get_all_by_filters(
                context, filters, sort_key, sort_dir, limit=limit,
                marker=marker, columns_to_join=_expected_cols(expected_attrs))
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters,
                       sort_key='created_at', sort_dir='desc', limit=None,
                       marker=None, expected_attrs=None, use_slave=False,
                       sort_keys=None, sort_dirs=None):
        return cls._get_by_filters_impl(
            context, filters, sort_key=sort_key, sort_dir=sort_dir,
            limit=limit, marker=marker, expected_attrs=expected_attrs,
            use_slave=use_slave, sort_keys=sort_keys, sort_dirs=sort_dirs)

    @staticmethod
    @db.select_db_reader_mode
    def _db_instance_get_all_by_host(context, host, columns_to_join,
                                     use_slave=False):
        return db.instance_get_all_by_host(context, host,
                                           columns_to_join=columns_to_join)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, expected_attrs=None, use_slave=False):
        db_inst_list = cls._db_instance_get_all_by_host(
            context, host, columns_to_join=_expected_cols(expected_attrs),
            use_slave=use_slave)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_by_host_and_node(cls, context, host, node, expected_attrs=None):
        db_inst_list = db.instance_get_all_by_host_and_node(
            context, host, node,
            columns_to_join=_expected_cols(expected_attrs))
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
    def get_all(cls, context, expected_attrs=None):
        """Returns all instances on all nodes."""
        db_instances = db.instance_get_all(
                context, columns_to_join=_expected_cols(expected_attrs))
        return _make_instance_list(context, cls(), db_instances,
                                   expected_attrs)

    @base.remotable_classmethod
    def get_hung_in_rebooting(cls, context, reboot_window,
                              expected_attrs=None):
        db_inst_list = db.instance_get_all_hung_in_rebooting(context,
                                                             reboot_window)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @staticmethod
    @db.select_db_reader_mode
    def _db_instance_get_active_by_window_joined(
            context, begin, end, project_id, host, columns_to_join,
            use_slave=False):
        return db.instance_get_active_by_window_joined(
            context, begin, end, project_id, host,
            columns_to_join=columns_to_join)

    @base.remotable_classmethod
    def _get_active_by_window_joined(cls, context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None,
                                    use_slave=False):
        # NOTE(mriedem): We need to convert the begin/end timestamp strings
        # to timezone-aware datetime objects for the DB API call.
        begin = timeutils.parse_isotime(begin)
        end = timeutils.parse_isotime(end) if end else None
        db_inst_list = cls._db_instance_get_active_by_window_joined(
            context, begin, end, project_id, host,
            columns_to_join=_expected_cols(expected_attrs),
            use_slave=use_slave)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @classmethod
    def get_active_by_window_joined(cls, context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None,
                                    use_slave=False):
        """Get instances and joins active during a certain time window.

        :param:context: nova request context
        :param:begin: datetime for the start of the time window
        :param:end: datetime for the end of the time window
        :param:project_id: used to filter instances by project
        :param:host: used to filter instances on a given compute host
        :param:expected_attrs: list of related fields that can be joined
        in the database layer when querying for instances
        :param use_slave if True, ship this query off to a DB slave
        :returns: InstanceList

        """
        # NOTE(mriedem): We have to convert the datetime objects to string
        # primitives for the remote call.
        begin = utils.isotime(begin)
        end = utils.isotime(end) if end else None
        return cls._get_active_by_window_joined(context, begin, end,
                                                project_id, host,
                                                expected_attrs,
                                                use_slave=use_slave)

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

    @base.remotable_classmethod
    def get_by_grantee_security_group_ids(cls, context, security_group_ids):
        db_instances = db.instance_get_all_by_grantee_security_groups(
            context, security_group_ids)
        return _make_instance_list(context, cls(), db_instances, [])

    def fill_faults(self):
        """Batch query the database for our instances' faults.

        :returns: A list of instance uuids for which faults were found.
        """
        uuids = [inst.uuid for inst in self]
        faults = objects.InstanceFaultList.get_by_instance_uuids(
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
