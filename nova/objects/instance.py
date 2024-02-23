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

import collections
import contextlib

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import versionutils
import sqlalchemy as sa
from sqlalchemy.orm import joinedload
from sqlalchemy import sql
from sqlalchemy.sql import func

from nova import availability_zones as avail_zone
from nova.compute import task_states
from nova.compute import vm_states
from nova.db.main import api as db
from nova.db.main import models
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
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
                                    'pci_devices', 'tags', 'services',
                                    'fault']
# These are fields that are optional but don't translate to db columns
_INSTANCE_OPTIONAL_NON_COLUMN_FIELDS = ['flavor', 'old_flavor',
                                        'new_flavor', 'ec2_ids']
# These are fields that are optional and in instance_extra
_INSTANCE_EXTRA_FIELDS = ['numa_topology', 'pci_requests',
                          'flavor', 'vcpu_model', 'migration_context',
                          'keypairs', 'device_metadata', 'trusted_certs',
                          'resources']
# These are fields that applied/drooped by migration_context
_MIGRATION_CONTEXT_ATTRS = ['numa_topology', 'pci_requests',
                            'pci_devices', 'resources']

# These are fields that can be specified as expected_attrs
INSTANCE_OPTIONAL_ATTRS = (_INSTANCE_OPTIONAL_JOINED_FIELDS +
                           _INSTANCE_OPTIONAL_NON_COLUMN_FIELDS +
                           _INSTANCE_EXTRA_FIELDS)
# These are fields that most query calls load by default
INSTANCE_DEFAULT_FIELDS = ['metadata', 'system_metadata',
                           'info_cache', 'security_groups']

# Maximum count of tags to one instance
MAX_TAG_COUNT = 50


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
    expected_cols = simple_cols + complex_cols
    # NOTE(pumaranikar): expected_cols list can contain duplicates since
    # caller appends column attributes to expected_attr without checking if
    # it is already present in the list or not. Hence, we remove duplicates
    # here, if any. The resultant list is sorted based on list index to
    # maintain the insertion order.
    return sorted(list(set(expected_cols)), key=expected_cols.index)


_NO_DATA_SENTINEL = object()


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class Instance(base.NovaPersistentObject, base.NovaObject,
               base.NovaObjectDictCompat):
    # Version 2.0: Initial version
    # Version 2.1: Added services
    # Version 2.2: Added keypairs
    # Version 2.3: Added device_metadata
    # Version 2.4: Added trusted_certs
    # Version 2.5: Added hard_delete kwarg in destroy
    # Version 2.6: Added hidden
    # Version 2.7: Added resources
    VERSION = '2.7'

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

        # TODO(stephenfin): Remove this in version 3.0 of the object as it has
        # been replaced by 'flavor'
        'instance_type_id': fields.IntegerField(nullable=True),

        'user_data': fields.StringField(nullable=True),

        'reservation_id': fields.StringField(nullable=True),

        'launched_at': fields.DateTimeField(nullable=True),
        'terminated_at': fields.DateTimeField(nullable=True),

        'availability_zone': fields.StringField(nullable=True),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        'launched_on': fields.StringField(nullable=True),

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

        # TODO(stephenfin): Remove this in version 3.0 of the object
        'cell_name': fields.StringField(nullable=True),

        'metadata': fields.DictOfStringsField(),
        'system_metadata': fields.DictOfNullableStringsField(),

        'info_cache': fields.ObjectField('InstanceInfoCache',
                                         nullable=True),

        # TODO(stephenfin): Remove this in version 3.0 of the object as it's
        # related to nova-network
        'security_groups': fields.ObjectField('SecurityGroupList'),

        'fault': fields.ObjectField('InstanceFault', nullable=True),

        'cleaned': fields.BooleanField(default=False),

        'pci_devices': fields.ObjectField('PciDeviceList', nullable=True),
        'numa_topology': fields.ObjectField('InstanceNUMATopology',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequests',
                                           nullable=True),
        'device_metadata': fields.ObjectField('InstanceDeviceMetadata',
                                              nullable=True),
        'tags': fields.ObjectField('TagList'),
        'flavor': fields.ObjectField('Flavor'),
        'old_flavor': fields.ObjectField('Flavor', nullable=True),
        'new_flavor': fields.ObjectField('Flavor', nullable=True),
        'vcpu_model': fields.ObjectField('VirtCPUModel', nullable=True),
        'ec2_ids': fields.ObjectField('EC2Ids'),
        'migration_context': fields.ObjectField('MigrationContext',
                                                nullable=True),
        'keypairs': fields.ObjectField('KeyPairList'),
        'trusted_certs': fields.ObjectField('TrustedCerts', nullable=True),
        'hidden': fields.BooleanField(default=False),
        'resources': fields.ObjectField('ResourceList', nullable=True),
        }

    obj_extra_fields = ['name']

    def obj_make_compatible(self, primitive, target_version):
        super(Instance, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (2, 7) and 'resources' in primitive:
            del primitive['resources']
        if target_version < (2, 6) and 'hidden' in primitive:
            del primitive['hidden']
        if target_version < (2, 4) and 'trusted_certs' in primitive:
            del primitive['trusted_certs']
        if target_version < (2, 3) and 'device_metadata' in primitive:
            del primitive['device_metadata']
        if target_version < (2, 2) and 'keypairs' in primitive:
            del primitive['keypairs']
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

    def obj_clone(self):
        """Create a copy of this instance object."""
        nobj = super(Instance, self).obj_clone()
        # Since the base object only does a deep copy of the defined fields,
        # need to make sure to also copy the additional tracking metadata
        # attributes so they don't show as changed and cause the metadata
        # to always be updated even when stale information.
        if hasattr(self, '_orig_metadata'):
            nobj._orig_metadata = dict(self._orig_metadata)
        if hasattr(self, '_orig_system_metadata'):
            nobj._orig_system_metadata = dict(self._orig_system_metadata)
        return nobj

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
        except (exception.ObjectActionError,
                exception.OrphanedObjectError):
            # This indicates self.id was not set and/or could not be
            # lazy loaded.  What this means is the instance has not
            # been persisted to a db yet, which should indicate it has
            # not been scheduled yet. In this situation it will have a
            # blank name.
            if (self.vm_state == vm_states.BUILDING and
                    self.task_state == task_states.SCHEDULING):
                base_name = ''
            else:
                # If the vm/task states don't indicate that it's being booted
                # then we have a bug here. Log an error and attempt to return
                # the uuid which is what an error above would return.
                LOG.error('Could not lazy-load instance.id while '
                          'attempting to generate the instance name.')
                base_name = self.uuid
        return base_name

    def _flavor_from_db(self, db_flavor):
        """Load instance flavor information from instance_extra."""

        # Before we stored flavors in instance_extra, certain fields, defined
        # in nova.compute.flavors.system_metadata_flavor_props, were stored
        # in the instance.system_metadata for the embedded instance.flavor.
        # The "disabled" and "is_public" fields weren't one of those keys,
        # however, so really old instances that had their embedded flavor
        # converted to the serialized instance_extra form won't have the
        # disabled attribute set and we need to default those here so callers
        # don't explode trying to load instance.flavor.disabled.
        def _default_flavor_values(flavor):
            if 'disabled' not in flavor:
                flavor.disabled = False
            if 'is_public' not in flavor:
                flavor.is_public = True

        flavor_info = jsonutils.loads(db_flavor)

        self.flavor = objects.Flavor.obj_from_primitive(flavor_info['cur'])
        _default_flavor_values(self.flavor)
        if flavor_info['old']:
            self.old_flavor = objects.Flavor.obj_from_primitive(
                flavor_info['old'])
            _default_flavor_values(self.old_flavor)
        else:
            self.old_flavor = None
        if flavor_info['new']:
            self.new_flavor = objects.Flavor.obj_from_primitive(
                flavor_info['new'])
            _default_flavor_values(self.new_flavor)
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

        if 'metadata' in expected_attrs:
            instance['metadata'] = utils.instance_meta(db_inst)
        if 'system_metadata' in expected_attrs:
            instance['system_metadata'] = utils.instance_sys_meta(db_inst)
        if 'fault' in expected_attrs:
            instance['fault'] = (
                objects.InstanceFault.get_latest_for_instance(
                    context, instance.uuid))
        if 'ec2_ids' in expected_attrs:
            instance._load_ec2_ids()
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

        # TODO(danms): If we are updating these on a backlevel instance,
        # we'll end up sending back new versions of these objects (see
        # above note for new info_caches
        if 'pci_devices' in expected_attrs:
            pci_devices = base.obj_make_list(
                    context, objects.PciDeviceList(context),
                    objects.PciDevice, db_inst['pci_devices'])
            instance['pci_devices'] = pci_devices

        # TODO(stephenfin): Remove this as it's related to nova-network
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

        instance._extra_attributes_from_db_object(instance, db_inst,
                                                  expected_attrs)

        instance.obj_reset_changes()
        return instance

    @staticmethod
    def _extra_attributes_from_db_object(instance, db_inst,
                                         expected_attrs=None):
        """Method to help with migration of extra attributes to objects.
        """
        if expected_attrs is None:
            expected_attrs = []
        # NOTE(danms): We can be called with a dict instead of a
        # SQLAlchemy object, so we have to be careful here
        if hasattr(db_inst, '__dict__'):
            have_extra = 'extra' in db_inst.__dict__ and db_inst['extra']
        else:
            have_extra = 'extra' in db_inst and db_inst['extra']

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
        if 'device_metadata' in expected_attrs:
            if have_extra:
                instance._load_device_metadata(
                    db_inst['extra'].get('device_metadata'))
            else:
                instance.device_metadata = None
        if 'vcpu_model' in expected_attrs:
            if have_extra:
                instance._load_vcpu_model(
                    db_inst['extra'].get('vcpu_model'))
            else:
                instance.vcpu_model = None
        if 'migration_context' in expected_attrs:
            if have_extra:
                instance._load_migration_context(
                    db_inst['extra'].get('migration_context'))
            else:
                instance.migration_context = None
        if 'keypairs' in expected_attrs:
            if have_extra:
                instance._load_keypairs(db_inst['extra'].get('keypairs'))
        if 'trusted_certs' in expected_attrs:
            if have_extra:
                instance._load_trusted_certs(
                    db_inst['extra'].get('trusted_certs'))
            else:
                instance.trusted_certs = None
        if 'resources' in expected_attrs:
            if have_extra:
                instance._load_resources(
                    db_inst['extra'].get('resources'))
            else:
                instance.resources = None
        if any([x in expected_attrs for x in ('flavor',
                                              'old_flavor',
                                              'new_flavor')]):
            if have_extra and db_inst['extra'].get('flavor'):
                instance._flavor_from_db(db_inst['extra']['flavor'])

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
        if self.obj_attr_is_set('deleted') and self.deleted:
            raise exception.ObjectActionError(action='create',
                                              reason='already deleted')
        updates = self.obj_get_changes()

        # NOTE(danms): We know because of the check above that deleted
        # is either unset or false. Since we need to avoid passing False
        # down to the DB layer (which uses an integer), we can always
        # default it to zero here.
        updates['deleted'] = 0

        expected_attrs = [attr for attr in INSTANCE_DEFAULT_FIELDS
                          if attr in updates]

        # TODO(stephenfin): Remove this as it's related to nova-network
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
        device_metadata = updates.pop('device_metadata', None)
        expected_attrs.append('device_metadata')
        if device_metadata:
            updates['extra']['device_metadata'] = (
                device_metadata._to_json())
        else:
            updates['extra']['device_metadata'] = None
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
            self._nullify_flavor_description(flavor_info)
            updates['extra']['flavor'] = jsonutils.dumps(flavor_info)
        keypairs = updates.pop('keypairs', None)
        if keypairs is not None:
            expected_attrs.append('keypairs')
            updates['extra']['keypairs'] = jsonutils.dumps(
                keypairs.obj_to_primitive())
        vcpu_model = updates.pop('vcpu_model', None)
        expected_attrs.append('vcpu_model')
        if vcpu_model:
            updates['extra']['vcpu_model'] = (
                jsonutils.dumps(vcpu_model.obj_to_primitive()))
        else:
            updates['extra']['vcpu_model'] = None
        trusted_certs = updates.pop('trusted_certs', None)
        expected_attrs.append('trusted_certs')
        if trusted_certs:
            updates['extra']['trusted_certs'] = jsonutils.dumps(
                trusted_certs.obj_to_primitive())
        else:
            updates['extra']['trusted_certs'] = None
        resources = updates.pop('resources', None)
        expected_attrs.append('resources')
        if resources:
            updates['extra']['resources'] = jsonutils.dumps(
                resources.obj_to_primitive())
        else:
            updates['extra']['resources'] = None
        db_inst = db.instance_create(self._context, updates)
        self._from_db_object(self._context, self, db_inst, expected_attrs)

        # NOTE(danms): The EC2 ids are created on their first load. In order
        # to avoid them being missing and having to be loaded later, we
        # load them once here on create now that the instance record is
        # created.
        self._load_ec2_ids()
        self.obj_reset_changes(['ec2_ids'])

    @base.remotable
    def destroy(self, hard_delete=False):
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
            db_inst = db.instance_destroy(self._context, self.uuid,
                                          constraint=constraint,
                                          hard_delete=hard_delete)
            self._from_db_object(self._context, self, db_inst)
        except exception.ConstraintNotMet:
            raise exception.ObjectActionError(action='destroy',
                                              reason='host changed')
        delattr(self, base.get_attrname('id'))

    def _save_info_cache(self, context):
        if self.info_cache:
            with self.info_cache.obj_alternate_context(context):
                self.info_cache.save()

    # TODO(stephenfin): Remove this as it's related to nova-network
    def _save_security_groups(self, context):
        security_groups = self.security_groups or []
        for secgroup in security_groups:
            with secgroup.obj_alternate_context(context):
                secgroup.save()
        self.security_groups.obj_reset_changes()

    def _save_fault(self, context):
        # NOTE(danms): I don't think we need to worry about this, do we?
        pass

    def _save_pci_requests(self, context):
        # TODO(danms): Unfortunately, extra.pci_requests is not a serialized
        # PciRequests object (!), so we have to handle it specially here.
        # That should definitely be fixed!
        self._extra_values_to_save['pci_requests'] = (
            self.pci_requests.to_json())

    def _save_pci_devices(self, context):
        # NOTE(yjiang5): All devices held by PCI tracker, only PCI tracker
        # permitted to update the DB. all change to devices from here will
        # be dropped.
        pass

    def _save_tags(self, context):
        # NOTE(gibi): tags are not saved through the instance
        pass

    def _save_services(self, context):
        # NOTE(mriedem): services are not saved through the instance
        pass

    @staticmethod
    def _nullify_flavor_description(flavor_info):
        """Helper method to nullify descriptions from a set of primitive
        flavors.

        Note that we don't remove the flavor description since that would
        make the versioned notification FlavorPayload have to handle the field
        not being set on the embedded instance.flavor.

        :param dict: dict of primitive flavor objects where the values are the
            flavors which get persisted in the instance_extra.flavor table.
        """
        for flavor in flavor_info.values():
            if flavor and 'description' in flavor['nova_object.data']:
                flavor['nova_object.data']['description'] = None

    def _save_flavor(self, context):
        if not any([x in self.obj_what_changed() for x in
                    ('flavor', 'old_flavor', 'new_flavor')]):
            return
        flavor_info = {
            'cur': self.flavor.obj_to_primitive(),
            'old': (self.old_flavor and
                    self.old_flavor.obj_to_primitive() or None),
            'new': (self.new_flavor and
                    self.new_flavor.obj_to_primitive() or None),
        }
        self._nullify_flavor_description(flavor_info)
        self._extra_values_to_save['flavor'] = jsonutils.dumps(flavor_info)
        self.obj_reset_changes(['flavor', 'old_flavor', 'new_flavor'])

    def _save_old_flavor(self, context):
        if 'old_flavor' in self.obj_what_changed():
            self._save_flavor(context)

    def _save_new_flavor(self, context):
        if 'new_flavor' in self.obj_what_changed():
            self._save_flavor(context)

    def _save_ec2_ids(self, context):
        # NOTE(hanlind): Read-only so no need to save this.
        pass

    def _save_keypairs(self, context):
        if 'keypairs' in self.obj_what_changed():
            self._save_extra_generic('keypairs')
            self.obj_reset_changes(['keypairs'], recursive=True)

    def _save_extra_generic(self, field):
        if field in self.obj_what_changed():
            obj = getattr(self, field)
            value = None
            if obj is not None:
                value = jsonutils.dumps(obj.obj_to_primitive())
            self._extra_values_to_save[field] = value

    # TODO(stephenfin): Remove the 'admin_state_reset' field in version 3.0 of
    # the object
    @base.remotable
    def save(self, expected_vm_state=None,
             expected_task_state=None, admin_state_reset=False):
        """Save updates to this instance

        Column-wise updates will be made based on the result of
        self.obj_what_changed(). If expected_task_state is provided,
        it will be checked against the in-database copy of the
        instance before updates are made.

        :param expected_vm_state: Optional tuple of valid vm states
                                  for the instance to be in
        :param expected_task_state: Optional tuple of valid task states
                                    for the instance to be in
        :param admin_state_reset: True if admin API is forcing setting
                                  of task_state/vm_state
        """
        context = self._context

        self._extra_values_to_save = {}
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
                    if field in _INSTANCE_EXTRA_FIELDS:
                        self._save_extra_generic(field)
                        continue
                    LOG.exception('No save handler for %s', field,
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
                updates[field] = self[field]

        if self._extra_values_to_save:
            db.instance_extra_update_by_uuid(context, self.uuid,
                                             self._extra_values_to_save)

        if not updates:
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
        if 'system_metadata' not in expected_attrs:
            expected_attrs.append('system_metadata')
        old_ref, inst_ref = db.instance_update_and_get_original(
                context, self.uuid, updates,
                columns_to_join=_expected_cols(expected_attrs))
        self._from_db_object(context, self, inst_ref,
                             expected_attrs=expected_attrs)

        # NOTE(danms): We have to be super careful here not to trigger
        # any lazy-loads that will unmigrate or unbackport something. So,
        # make a copy of the instance for notifications first.
        new_ref = self.obj_clone()
        notifications.send_update(context, old_ref, new_ref)

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
            if field not in self:
                continue
            if field not in current:
                # If the field isn't in current we should not
                # touch it, triggering a likely-recursive lazy load.
                # Log it so we can see it happening though, as it
                # probably isn't expected in most cases.
                LOG.debug('Field %s is set but not in refreshed '
                          'instance, skipping', field)
                continue
            if field == 'info_cache':
                self.info_cache.refresh()
            elif self[field] != current[field]:
                self[field] = current[field]
        self.obj_reset_changes()

    def _load_generic(self, attrname):
        instance = self.__class__.get_by_uuid(self._context,
                                              uuid=self.uuid,
                                              expected_attrs=[attrname])

        if attrname not in instance:
            # NOTE(danms): Never allow us to recursively-load
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('loading %s requires recursion') % attrname)

        # NOTE(danms): load anything we don't already have from the
        # instance we got from the database to make the most of the
        # performance hit.
        for field in self.fields:
            if field in instance and field not in self:
                setattr(self, field, getattr(instance, field))

    def _load_fault(self):
        self.fault = objects.InstanceFault.get_latest_for_instance(
            self._context, self.uuid)

    def _load_numa_topology(self, db_topology=_NO_DATA_SENTINEL):
        if db_topology is None:
            self.numa_topology = None
        elif db_topology is not _NO_DATA_SENTINEL:
            self.numa_topology = objects.InstanceNUMATopology.obj_from_db_obj(
                self._context, self.uuid, db_topology)
        else:
            try:
                self.numa_topology = \
                    objects.InstanceNUMATopology.get_by_instance_uuid(
                        self._context, self.uuid)
            except exception.NumaTopologyNotFound:
                self.numa_topology = None

    def _load_pci_requests(self, db_requests=_NO_DATA_SENTINEL):
        if db_requests is not _NO_DATA_SENTINEL:
            self.pci_requests = objects.InstancePCIRequests.obj_from_db(
                self._context, self.uuid, db_requests)
        else:
            self.pci_requests = \
                objects.InstancePCIRequests.get_by_instance_uuid(
                    self._context, self.uuid)

    def _load_device_metadata(self, db_dev_meta=_NO_DATA_SENTINEL):
        if db_dev_meta is None:
            self.device_metadata = None
        elif db_dev_meta is not _NO_DATA_SENTINEL:
            self.device_metadata = \
                objects.InstanceDeviceMetadata.obj_from_db(
                self._context, db_dev_meta)
        else:
            self.device_metadata = \
                objects.InstanceDeviceMetadata.get_by_instance_uuid(
                    self._context, self.uuid)

    def _load_flavor(self):
        instance = self.__class__.get_by_uuid(
            self._context, uuid=self.uuid,
            expected_attrs=['flavor'])

        # NOTE(danms): Orphan the instance to make sure we don't lazy-load
        # anything below
        instance._context = None
        self.flavor = instance.flavor
        self.old_flavor = instance.old_flavor
        self.new_flavor = instance.new_flavor

    def _load_vcpu_model(self, db_vcpu_model=_NO_DATA_SENTINEL):
        if db_vcpu_model is None:
            self.vcpu_model = None
        elif db_vcpu_model is _NO_DATA_SENTINEL:
            self.vcpu_model = objects.VirtCPUModel.get_by_instance_uuid(
                self._context, self.uuid)
        else:
            db_vcpu_model = jsonutils.loads(db_vcpu_model)
            self.vcpu_model = objects.VirtCPUModel.obj_from_primitive(
                db_vcpu_model)

    def _load_ec2_ids(self):
        self.ec2_ids = objects.EC2Ids.get_by_instance(self._context, self)

    # TODO(stephenfin): Remove this as it's related to nova-network
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

    def _load_keypairs(self, db_keypairs=_NO_DATA_SENTINEL):
        if db_keypairs is _NO_DATA_SENTINEL:
            inst = objects.Instance.get_by_uuid(self._context, self.uuid,
                                                expected_attrs=['keypairs'])
            if 'keypairs' in inst:
                self.keypairs = inst.keypairs
                self.keypairs.obj_reset_changes(recursive=True)
                self.obj_reset_changes(['keypairs'])
            else:
                self.keypairs = objects.KeyPairList(objects=[])
                # NOTE(danms): We leave the keypairs attribute dirty in hopes
                # someone else will save it for us
        elif db_keypairs:
            self.keypairs = objects.KeyPairList.obj_from_primitive(
                jsonutils.loads(db_keypairs))
            self.obj_reset_changes(['keypairs'])

    def _load_tags(self):
        self.tags = objects.TagList.get_by_resource_id(
            self._context, self.uuid)

    def _load_trusted_certs(self, db_trusted_certs=_NO_DATA_SENTINEL):
        if db_trusted_certs is None:
            self.trusted_certs = None
        elif db_trusted_certs is _NO_DATA_SENTINEL:
            self.trusted_certs = objects.TrustedCerts.get_by_instance_uuid(
                self._context, self.uuid)
        else:
            self.trusted_certs = objects.TrustedCerts.obj_from_primitive(
                jsonutils.loads(db_trusted_certs))

    def _load_resources(self, db_resources=_NO_DATA_SENTINEL):
        if db_resources is None:
            self.resources = None
        elif db_resources is _NO_DATA_SENTINEL:
            self.resources = objects.ResourceList.get_by_instance_uuid(
                self._context, self.uuid)
        else:
            self.resources = objects.ResourceList.obj_from_primitive(
                jsonutils.loads(db_resources))

    def apply_migration_context(self):
        if self.migration_context:
            self._set_migration_context_to_instance(prefix='new_')
        else:
            LOG.debug("Trying to apply a migration context that does not "
                      "seem to be set for this instance", instance=self)

    def revert_migration_context(self):
        if self.migration_context:
            self._set_migration_context_to_instance(prefix='old_')
        else:
            LOG.debug("Trying to revert a migration context that does not "
                      "seem to be set for this instance", instance=self)

    def _set_migration_context_to_instance(self, prefix):
        for inst_attr_name in _MIGRATION_CONTEXT_ATTRS:
            setattr(self, inst_attr_name, None)
            attr_name = prefix + inst_attr_name
            if attr_name in self.migration_context:
                attr_value = getattr(
                    self.migration_context, attr_name)
                setattr(self, inst_attr_name, attr_value)

    @contextlib.contextmanager
    def mutated_migration_context(self, revert=False):
        """Context manager to temporarily apply/revert the migration context.

        Calling .save() from within the context manager means that the mutated
        context will be saved which can cause incorrect resource tracking, and
        should be avoided.
        """
        # First check to see if we even have a migration context set and if not
        # we can exit early without lazy-loading other attributes.
        if 'migration_context' in self and self.migration_context is None:
            yield
            return

        current_values = {}
        for attr_name in _MIGRATION_CONTEXT_ATTRS:
            current_values[attr_name] = getattr(self, attr_name)
        if revert:
            self.revert_migration_context()
        else:
            self.apply_migration_context()
        try:
            yield
        finally:
            for attr_name in _MIGRATION_CONTEXT_ATTRS:
                setattr(self, attr_name, current_values[attr_name])

    @base.remotable
    def drop_migration_context(self):
        if self.migration_context:
            db.instance_extra_update_by_uuid(self._context, self.uuid,
                                             {'migration_context': None})
            self.migration_context = None

    def clear_numa_topology(self):
        numa_topology = self.numa_topology
        if numa_topology is not None:
            self.numa_topology = numa_topology.clear_host_pinning()

    def obj_load_attr(self, attrname):
        # NOTE(danms): We can't lazy-load anything without a context and a uuid
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())
        if 'uuid' not in self:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)

        LOG.debug("Lazy-loading '%(attr)s' on %(name)s uuid %(uuid)s",
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'uuid': self.uuid,
                   })

        with utils.temporary_mutation(self._context, read_deleted='yes'):
            self._obj_load_attr(attrname)

    def _obj_load_attr(self, attrname):
        """Internal method for loading attributes from instances.

        NOTE: Do not use this directly.

        This method contains the implementation of lazy-loading attributes
        from Instance object, minus some massaging of the context and
        error-checking. This should always be called with the object-local
        context set for reading deleted instances and with uuid set. All
        of the code below depends on those two things. Thus, this should
        only be called from obj_load_attr() itself.

        :param attrname: The name of the attribute to be loaded
        """

        # NOTE(danms): We handle some fields differently here so that we
        # can be more efficient
        if attrname == 'fault':
            self._load_fault()
        elif attrname == 'numa_topology':
            self._load_numa_topology()
        elif attrname == 'device_metadata':
            self._load_device_metadata()
        elif attrname == 'pci_requests':
            self._load_pci_requests()
        elif attrname == 'vcpu_model':
            self._load_vcpu_model()
        elif attrname == 'ec2_ids':
            self._load_ec2_ids()
        elif attrname == 'migration_context':
            self._load_migration_context()
        elif attrname == 'keypairs':
            # NOTE(danms): Let keypairs control its own destiny for
            # resetting changes.
            return self._load_keypairs()
        elif attrname == 'trusted_certs':
            return self._load_trusted_certs()
        elif attrname == 'resources':
            return self._load_resources()
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
        elif attrname == 'tags':
            if self.deleted:
                # NOTE(mriedem): Same story as services, the DB API query
                # in instance_tag_get_by_instance_uuid will fail if the
                # instance has been deleted so just return an empty tag list.
                self.tags = objects.TagList(self._context)
            else:
                self._load_tags()
        elif attrname in self.fields and attrname != 'id':
            # NOTE(danms): We've never let 'id' be lazy-loaded, and use its
            # absence as a sentinel that it hasn't been created in the database
            # yet, so refuse to do so here.
            self._load_generic(attrname)
        else:
            # NOTE(danms): This is historically what we did for
            # something not in a field that was force-loaded. So, just
            # do this for consistency.
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)

        self.obj_reset_changes([attrname])

    def get_flavor(self, namespace=None):
        prefix = ('%s_' % namespace) if namespace is not None else ''
        attr = '%sflavor' % prefix
        try:
            return getattr(self, attr)
        except exception.FlavorNotFound:
            # NOTE(danms): This only happens in the case where we don't
            # have flavor information in instance_extra, and doing
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

    def get_network_info(self):
        if self.info_cache is None:
            return network_model.NetworkInfo.hydrate([])
        return self.info_cache.network_info

    def get_bdms(self):
        return objects.BlockDeviceMappingList.get_by_instance_uuid(
            self._context, self.uuid)

    def remove_pci_device_and_request(self, pci_device):
        """Remove the PciDevice and the related InstancePciRequest"""
        if pci_device in self.pci_devices.objects:
            self.pci_devices.objects.remove(pci_device)
        self.pci_requests.requests = [
            pci_req for pci_req in self.pci_requests.requests
            if pci_req.request_id != pci_device.request_id]


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


@db.pick_context_manager_writer
def populate_missing_availability_zones(context, count):
    # instances without host have no reasonable AZ to set
    not_empty_host = models.Instance.host != None  # noqa E711
    instances = (context.session.query(models.Instance).
        filter(not_empty_host).
        filter_by(availability_zone=None).limit(count).all())
    count_all = len(instances)
    count_hit = 0
    for instance in instances:
        az = avail_zone.get_instance_availability_zone(context, instance)
        instance.availability_zone = az
        instance.save(context.session)
        count_hit += 1
    return count_all, count_hit


@base.NovaObjectRegistry.register
class InstanceList(base.ObjectListBase, base.NovaObject):
    # Version 2.0: Initial Version
    # Version 2.1: Add get_uuids_by_host()
    # Version 2.2: Pagination for get_active_by_window_joined()
    # Version 2.3: Add get_count_by_vm_state()
    # Version 2.4: Add get_counts()
    # Version 2.5: Add get_uuids_by_host_and_node()
    # Version 2.6: Add get_uuids_by_hosts()
    VERSION = '2.6'

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
        return db_inst_list

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters,
                       sort_key='created_at', sort_dir='desc', limit=None,
                       marker=None, expected_attrs=None, use_slave=False,
                       sort_keys=None, sort_dirs=None):
        db_inst_list = cls._get_by_filters_impl(
            context, filters, sort_key=sort_key, sort_dir=sort_dir,
            limit=limit, marker=marker, expected_attrs=expected_attrs,
            use_slave=use_slave, sort_keys=sort_keys, sort_dirs=sort_dirs)
        # NOTE(melwitt): _make_instance_list could result in joined objects'
        # (from expected_attrs) _from_db_object methods being called during
        # Instance._from_db_object, each of which might choose to perform
        # database writes. So, we call this outside of _get_by_filters_impl to
        # avoid being nested inside a 'reader' database transaction context.
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

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

    @staticmethod
    @db.pick_context_manager_reader
    def _get_uuids_by_host_and_node(context, host, node):
        return context.session.query(
            models.Instance.uuid).filter_by(
            host=host).filter_by(node=node).filter_by(deleted=0).all()

    @base.remotable_classmethod
    def get_uuids_by_host_and_node(cls, context, host, node):
        """Return non-deleted instance UUIDs for the given host and node.

        :param context: nova auth request context
        :param host: Filter instances on this host.
        :param node: Filter instances on this node.
        :returns: list of non-deleted instance UUIDs on the given host and node
        """
        return cls._get_uuids_by_host_and_node(context, host, node)

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
            use_slave=False, limit=None, marker=None):
        return db.instance_get_active_by_window_joined(
            context, begin, end, project_id, host,
            columns_to_join=columns_to_join, limit=limit, marker=marker)

    @base.remotable_classmethod
    def _get_active_by_window_joined(cls, context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None, use_slave=False,
                                    limit=None, marker=None):
        # NOTE(mriedem): We need to convert the begin/end timestamp strings
        # to timezone-aware datetime objects for the DB API call.
        begin = timeutils.parse_isotime(begin)
        end = timeutils.parse_isotime(end) if end else None
        db_inst_list = cls._db_instance_get_active_by_window_joined(
            context, begin, end, project_id, host,
            columns_to_join=_expected_cols(expected_attrs),
            use_slave=use_slave, limit=limit, marker=marker)
        return _make_instance_list(context, cls(), db_inst_list,
                                   expected_attrs)

    @classmethod
    def get_active_by_window_joined(cls, context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None, use_slave=False,
                                    limit=None, marker=None):
        """Get instances and joins active during a certain time window.

        :param:context: nova request context
        :param:begin: datetime for the start of the time window
        :param:end: datetime for the end of the time window
        :param:project_id: used to filter instances by project
        :param:host: used to filter instances on a given compute host
        :param:expected_attrs: list of related fields that can be joined
        in the database layer when querying for instances
        :param use_slave if True, ship this query off to a DB slave
        :param limit: maximum number of instances to return per page
        :param marker: last instance uuid from the previous page
        :returns: InstanceList

        """
        # NOTE(mriedem): We have to convert the datetime objects to string
        # primitives for the remote call.
        begin = utils.isotime(begin)
        end = utils.isotime(end) if end else None
        return cls._get_active_by_window_joined(context, begin, end,
                                                project_id, host,
                                                expected_attrs,
                                                use_slave=use_slave,
                                                limit=limit, marker=marker)

    # TODO(stephenfin): Remove this as it's related to nova-network
    @base.remotable_classmethod
    def get_by_security_group_id(cls, context, security_group_id):
        db_secgroup = db.security_group_get(
            context, security_group_id,
            columns_to_join=['instances.info_cache',
                             'instances.system_metadata'])
        return _make_instance_list(context, cls(), db_secgroup['instances'],
                                   ['info_cache', 'system_metadata'])

    # TODO(stephenfin): Remove this as it's related to nova-network
    @classmethod
    def get_by_security_group(cls, context, security_group):
        return cls.get_by_security_group_id(context, security_group.id)

    # TODO(stephenfin): Remove this as it's related to nova-network
    @base.remotable_classmethod
    def get_by_grantee_security_group_ids(cls, context, security_group_ids):
        raise NotImplementedError()

    def fill_faults(self):
        """Batch query the database for our instances' faults.

        :returns: A list of instance uuids for which faults were found.
        """
        uuids = [inst.uuid for inst in self]
        faults = objects.InstanceFaultList.get_latest_by_instance_uuids(
            self._context, uuids)
        faults_by_uuid = {}
        for fault in faults:
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

    @base.remotable_classmethod
    def get_uuids_by_host(cls, context, host):
        return db.instance_get_all_uuids_by_hosts(context, [host])[host]

    @base.remotable_classmethod
    def get_uuids_by_hosts(cls, context, hosts):
        """Returns a dict, keyed by hypervisor hostname, of a list of instance
        UUIDs associated with that compute node.
        """
        return db.instance_get_all_uuids_by_hosts(context, hosts)

    @staticmethod
    @db.pick_context_manager_reader
    def _get_count_by_vm_state_in_db(context, project_id, user_id, vm_state):
        return context.session.query(models.Instance.id).\
            filter_by(deleted=0).\
            filter_by(project_id=project_id).\
            filter_by(user_id=user_id).\
            filter_by(vm_state=vm_state).\
            count()

    @base.remotable_classmethod
    def get_count_by_vm_state(cls, context, project_id, user_id, vm_state):
        return cls._get_count_by_vm_state_in_db(context, project_id, user_id,
                                                vm_state)

    @staticmethod
    @db.pick_context_manager_reader
    def _get_counts_in_db(context, project_id, user_id=None):
        # NOTE(melwitt): Copied from nova/db/main/api.py:
        # It would be better to have vm_state not be nullable
        # but until then we test it explicitly as a workaround.
        not_soft_deleted = sa.or_(
            models.Instance.vm_state != vm_states.SOFT_DELETED,
            models.Instance.vm_state == sql.null()
            )
        project_query = context.session.query(
            func.count(models.Instance.id),
            func.sum(models.Instance.vcpus),
            func.sum(models.Instance.memory_mb)).\
            filter_by(deleted=0).\
            filter(not_soft_deleted).\
            filter_by(project_id=project_id)
        # NOTE(mriedem): Filter out hidden instances since there should be a
        # non-hidden version of the instance in another cell database and the
        # API will only show one of them, so we don't count the hidden copy.
        project_query = project_query.filter(
            sa.or_(
                models.Instance.hidden == sql.false(),
                models.Instance.hidden == sql.null(),
            ))

        project_result = project_query.first()
        fields = ('instances', 'cores', 'ram')
        project_counts = {field: int(project_result[idx] or 0)
                          for idx, field in enumerate(fields)}
        counts = {'project': project_counts}
        if user_id:
            user_result = project_query.filter_by(user_id=user_id).first()
            user_counts = {field: int(user_result[idx] or 0)
                           for idx, field in enumerate(fields)}
            counts['user'] = user_counts
        return counts

    @staticmethod
    def _recover_flavor_from_instance_extras(context, instance_types,
                                             missing_itypes):
        # Not found in flavor db. might be deleted. get it from the
        # saved info
        # We first get a list of instance UUIDs - one per flavor -
        # that use this flavor. Then we do a query against the
        # instance_extra table with those uuids. This is faster
        # than a subquery-JOIN, subquery with WHERE, a JOIN, a CTE
        # with WHERE or a CTE with JOIN.
        missing_itypes_instance_uuids = [
            x[0] for x in context.session.query(
                models.Instance.uuid
            ).filter(
                models.Instance.instance_type_id.
                in_(missing_itypes)
            ).group_by(
                models.Instance.instance_type_id
            ).all()]

        db_flavors = context.session.query(
                models.InstanceExtra.flavor
            ).filter(
                models.InstanceExtra.instance_uuid.
                in_(missing_itypes_instance_uuids)
            )

        for db_flavor in db_flavors:
            flavor_info = jsonutils.loads(db_flavor[0])
            flavor = objects.Flavor.obj_from_primitive(
                                                flavor_info['cur'])
            separate = flavor.extra_specs.get('quota:separate')
            instance_types[flavor.id] = {
                'name': flavor.name,
                'separate': separate == 'true'
            }

    @staticmethod
    def _recover_flavor_from_cell_instance_types(context, instance_types,
                                                  missing_itypes):
        # Not found in flavor db of upstream api, searching locally
        # This is probably not necessary anymore, because every
        # instance we have should have saved flavor information.
        msg = 'flavor(s) with ref id %s not found in flavor db'
        LOG.warning(msg, ', '.join(str(x) for x in missing_itypes))

        flavor_query = context.session.query(
            models.InstanceTypes). \
            filter(models.InstanceTypes.id.in_(missing_itypes)). \
            options(joinedload('extra_specs'))
        for old_flavor in flavor_query:
            # Bad hack, but works
            instance_types[old_flavor.id] = {
                'name': old_flavor.name,
                'separate': len(old_flavor.extra_specs) > 0
            }

    @staticmethod
    @db.pick_context_manager_reader
    def _get_instance_types(context, wanted_itypes):
        # TODO(xxx): cache flavor_ids
        if not wanted_itypes:
            return {}

        instance_types = objects.FlavorList.get_by_id(
            context, wanted_itypes)
        missing_itypes = wanted_itypes - set(instance_types.keys())

        if not missing_itypes:
            return instance_types

        InstanceList._recover_flavor_from_instance_extras(context,
                                                          instance_types,
                                                          missing_itypes)

        missing_itypes = wanted_itypes - set(instance_types.keys())

        if not missing_itypes:
            return instance_types

        InstanceList._recover_flavor_from_cell_instance_types(context,
                                                              instance_types,
                                                              missing_itypes)
        return instance_types

    @staticmethod
    def _sum_counts(instances, instance_types):
        return InstanceList._sum_counts_by_extra_group_keys(instances,
                                                            instance_types)[()]

    @staticmethod
    def _sum_counts_by_az(instances, instance_types):
        counts = InstanceList._sum_counts_by_extra_group_keys(instances,
                                                              instance_types)
        return {az: values for (az,), values in counts.items()}

    @staticmethod
    def _sum_counts_by_extra_group_keys(instances, instance_types):
        counts_by_extra_group_keys = collections.defaultdict(
            lambda: {'instances': 0, 'cores': 0, 'ram': 0})

        if not instances:
            return counts_by_extra_group_keys

        for type_id, instance_count, cores, ram, *xtra_group_keys in instances:
            counts = counts_by_extra_group_keys[tuple(xtra_group_keys)]
            itype = instance_types.get(type_id)
            if itype is None:
                # log an error, but continue. We need the rest of the
                # function to work. We'll just add it to non-separate
                # instances, so the overall number is correct at least.
                # Also this should not happen.
                LOG.error('Unknown instance type id %s', type_id)
            if itype and itype.get('separate', False):
                t_name = f"instances_{itype['name']}"
                counts[t_name] = counts.get(t_name, 0) + instance_count
            else:
                counts['instances'] += instance_count
                counts['cores'] += int(cores)
                counts['ram'] += int(ram)

        return counts_by_extra_group_keys

    @staticmethod
    def _build_instance_usage_query(context, project_id):
        not_soft_deleted = sa.or_(
            models.Instance.vm_state != vm_states.SOFT_DELETED,
            models.Instance.vm_state == sql.null()
            )
        return context.session.query(
            models.Instance.instance_type_id,
            func.count(models.Instance.id),
            func.sum(models.Instance.vcpus),
            func.sum(models.Instance.memory_mb)).\
            filter_by(deleted=0).\
            filter(not_soft_deleted).\
            filter_by(project_id=project_id).\
            group_by(models.Instance.instance_type_id)

    @staticmethod
    @db.pick_context_manager_reader
    def _get_counts_in_db_separateaware(context, project_id, user_id=None):
        project_query = InstanceList._build_instance_usage_query(context,
                                                                 project_id)

        project_result = project_query.all()
        instance_types = InstanceList._get_instance_types(
            context, set(x[0] for x in project_result))

        project_counts = InstanceList._sum_counts(project_result,
                                                  instance_types)

        counts = {'project': project_counts}
        if user_id:
            user_result = project_query.filter_by(user_id=user_id).all()
            # We can re-use the instance_types, as the instances for the user
            # in the project are a subset of all instances in the project.
            # Therefore the instance types are as well.
            user_counts = InstanceList._sum_counts(user_result, instance_types)
            counts['user'] = user_counts

        return counts

    @staticmethod
    @db.pick_context_manager_reader
    def _get_counts_in_db_by_az(context, project_id):
        query = InstanceList._build_instance_usage_query(context, project_id)

        result = (query.
            add_columns(models.Instance.availability_zone).
            filter(models.Instance.availability_zone != sql.null()).
            group_by(models.Instance.availability_zone).all())

        instance_types = InstanceList._get_instance_types(
            context, set(x[0] for x in result))

        project_counts = InstanceList._sum_counts_by_az(result, instance_types)

        counts = {'project': project_counts}
        return counts

    @base.remotable_classmethod
    def get_counts(cls, context, project_id, user_id=None):
        """Get the counts of Instance objects in the database.

        :param context: The request context for database access
        :param project_id: The project_id to count across
        :param user_id: The user_id to count across
        :returns: A dict containing the project-scoped counts and user-scoped
                  counts if user_id is specified. For example:

                    {'project': {'instances': <count across project>,
                                 'cores': <count across project>,
                                 'ram': <count across project},
                     'user': {'instances': <count across user>,
                              'cores': <count across user>,
                              'ram': <count across user>}}
        """
        return cls._get_counts_in_db_separateaware(context, project_id,
                                                    user_id=user_id)

    @base.remotable_classmethod
    def get_counts_by_az(cls, context, project_id):
        """Get the counts of Instance objects in the database.

        :param context: The request context for database access
        :returns: A dict containing the project-scoped counts. For example:
                    {'project': {
                        '<availability-zone>: {
                            'instances': <count across project in az>,
                            'cores': <count across project in az>,
                            'ram': <count across project in az>
                            'instances_<flavor_name>: <count across...>,
                            ...
                            },

                     ...}
        """
        return cls._get_counts_in_db_by_az(context, project_id)

    @staticmethod
    @db.pick_context_manager_reader
    def _get_count_by_hosts(context, hosts):
        return context.session.query(models.Instance).\
            filter_by(deleted=0).\
            filter(models.Instance.host.in_(hosts)).count()

    @classmethod
    def get_count_by_hosts(cls, context, hosts):
        return cls._get_count_by_hosts(context, hosts)
