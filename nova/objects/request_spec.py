#    Copyright 2015 Red Hat, Inc.
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

from oslo_serialization import jsonutils
from oslo_utils import versionutils


from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import instance as obj_instance
from nova.scheduler import utils as scheduler_utils
from nova.virt import hardware

REQUEST_SPEC_OPTIONAL_ATTRS = ['requested_destination',
                               'security_groups']


@base.NovaObjectRegistry.register
class RequestSpec(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: ImageMeta version 1.6
    # Version 1.2: SchedulerRetries version 1.1
    # Version 1.3: InstanceGroup version 1.10
    # Version 1.4: ImageMeta version 1.7
    # Version 1.5: Added get_by_instance_uuid(), create(), save()
    # Version 1.6: Added requested_destination
    # Version 1.7: Added destroy()
    # Version 1.8: Added security_groups
    VERSION = '1.8'

    fields = {
        'id': fields.IntegerField(),
        'image': fields.ObjectField('ImageMeta', nullable=True),
        'numa_topology': fields.ObjectField('InstanceNUMATopology',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequests',
                                           nullable=True),
        # TODO(mriedem): The project_id shouldn't be nullable since the
        # scheduler relies on it being set.
        'project_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'flavor': fields.ObjectField('Flavor', nullable=False),
        'num_instances': fields.IntegerField(default=1),
        'ignore_hosts': fields.ListOfStringsField(nullable=True),
        # NOTE(mriedem): In reality, you can only ever have one
        # host in the force_hosts list. The fact this is a list
        # is a mistake perpetuated over time.
        'force_hosts': fields.ListOfStringsField(nullable=True),
        # NOTE(mriedem): In reality, you can only ever have one
        # node in the force_nodes list. The fact this is a list
        # is a mistake perpetuated over time.
        'force_nodes': fields.ListOfStringsField(nullable=True),
        'requested_destination': fields.ObjectField('Destination',
                                                    nullable=True,
                                                    default=None),
        'retry': fields.ObjectField('SchedulerRetries', nullable=True),
        'limits': fields.ObjectField('SchedulerLimits', nullable=True),
        'instance_group': fields.ObjectField('InstanceGroup', nullable=True),
        # NOTE(sbauza): Since hints are depending on running filters, we prefer
        # to leave the API correctly validating the hints per the filters and
        # just provide to the RequestSpec object a free-form dictionary
        'scheduler_hints': fields.DictOfListOfStringsField(nullable=True),
        'instance_uuid': fields.UUIDField(),
        'security_groups': fields.ObjectField('SecurityGroupList'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(RequestSpec, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 8):
            if 'security_groups' in primitive:
                del primitive['security_groups']
        if target_version < (1, 6):
            if 'requested_destination' in primitive:
                del primitive['requested_destination']

    def obj_load_attr(self, attrname):
        if attrname not in REQUEST_SPEC_OPTIONAL_ATTRS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)

        if attrname == 'security_groups':
            self.security_groups = objects.SecurityGroupList(objects=[])
            return

        # NOTE(sbauza): In case the primitive was not providing that field
        # because of a previous RequestSpec version, we want to default
        # that field in order to have the same behaviour.
        self.obj_set_defaults(attrname)

    @property
    def vcpus(self):
        return self.flavor.vcpus

    @property
    def memory_mb(self):
        return self.flavor.memory_mb

    @property
    def root_gb(self):
        return self.flavor.root_gb

    @property
    def ephemeral_gb(self):
        return self.flavor.ephemeral_gb

    @property
    def swap(self):
        return self.flavor.swap

    def _image_meta_from_image(self, image):
        if isinstance(image, objects.ImageMeta):
            self.image = image
        elif isinstance(image, dict):
            # NOTE(sbauza): Until Nova is fully providing an ImageMeta object
            # for getting properties, we still need to hydrate it here
            # TODO(sbauza): To be removed once all RequestSpec hydrations are
            # done on the conductor side and if the image is an ImageMeta
            self.image = objects.ImageMeta.from_dict(image)
        else:
            self.image = None

    def _from_instance(self, instance):
        if isinstance(instance, obj_instance.Instance):
            # NOTE(sbauza): Instance should normally be a NovaObject...
            getter = getattr
        elif isinstance(instance, dict):
            # NOTE(sbauza): ... but there are some cases where request_spec
            # has an instance key as a dictionary, just because
            # select_destinations() is getting a request_spec dict made by
            # sched_utils.build_request_spec()
            # TODO(sbauza): To be removed once all RequestSpec hydrations are
            # done on the conductor side
            getter = lambda x, y: x.get(y)
        else:
            # If the instance is None, there is no reason to set the fields
            return

        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'availability_zone']
        for field in instance_fields:
            if field == 'uuid':
                setattr(self, 'instance_uuid', getter(instance, field))
            elif field == 'pci_requests':
                self._from_instance_pci_requests(getter(instance, field))
            elif field == 'numa_topology':
                self._from_instance_numa_topology(getter(instance, field))
            else:
                setattr(self, field, getter(instance, field))

    def _from_instance_pci_requests(self, pci_requests):
        if isinstance(pci_requests, dict):
            pci_req_cls = objects.InstancePCIRequests
            self.pci_requests = pci_req_cls.from_request_spec_instance_props(
                pci_requests)
        else:
            self.pci_requests = pci_requests

    def _from_instance_numa_topology(self, numa_topology):
        if isinstance(numa_topology, dict):
            self.numa_topology = hardware.instance_topology_from_instance(
                dict(numa_topology=numa_topology))
        else:
            self.numa_topology = numa_topology

    def _from_flavor(self, flavor):
        if isinstance(flavor, objects.Flavor):
            self.flavor = flavor
        elif isinstance(flavor, dict):
            # NOTE(sbauza): Again, request_spec is primitived by
            # sched_utils.build_request_spec() and passed to
            # select_destinations() like this
            # TODO(sbauza): To be removed once all RequestSpec hydrations are
            # done on the conductor side
            self.flavor = objects.Flavor(**flavor)

    def _from_retry(self, retry_dict):
        self.retry = (SchedulerRetries.from_dict(self._context, retry_dict)
                      if retry_dict else None)

    def _populate_group_info(self, filter_properties):
        if filter_properties.get('instance_group'):
            # New-style group information as a NovaObject, we can directly set
            # the field
            self.instance_group = filter_properties.get('instance_group')
        elif filter_properties.get('group_updated') is True:
            # Old-style group information having ugly dict keys containing sets
            # NOTE(sbauza): Can be dropped once select_destinations is removed
            policies = list(filter_properties.get('group_policies'))
            hosts = list(filter_properties.get('group_hosts'))
            members = list(filter_properties.get('group_members'))
            self.instance_group = objects.InstanceGroup(policies=policies,
                                                        hosts=hosts,
                                                        members=members)
            # hosts has to be not part of the updates for saving the object
            self.instance_group.obj_reset_changes(['hosts'])
        else:
            # Set the value anyway to avoid any call to obj_attr_is_set for it
            self.instance_group = None

    def _from_limits(self, limits_dict):
        self.limits = SchedulerLimits.from_dict(limits_dict)

    def _from_hints(self, hints_dict):
        if hints_dict is None:
            self.scheduler_hints = None
            return
        self.scheduler_hints = {
            hint: value if isinstance(value, list) else [value]
            for hint, value in hints_dict.items()}

    @classmethod
    def from_primitives(cls, context, request_spec, filter_properties):
        """Returns a new RequestSpec object by hydrating it from legacy dicts.

        Deprecated.  A RequestSpec object is created early in the boot process
        using the from_components method.  That object will either be passed to
        places that require it, or it can be looked up with
        get_by_instance_uuid.  This method can be removed when there are no
        longer any callers.  Because the method is not remotable it is not tied
        to object versioning.

        That helper is not intended to leave the legacy dicts kept in the nova
        codebase, but is rather just for giving a temporary solution for
        populating the Spec object until we get rid of scheduler_utils'
        build_request_spec() and the filter_properties hydratation in the
        conductor.

        :param context: a context object
        :param request_spec: An old-style request_spec dictionary
        :param filter_properties: An old-style filter_properties dictionary
        """
        num_instances = request_spec.get('num_instances', 1)
        spec = cls(context, num_instances=num_instances)
        # Hydrate from request_spec first
        image = request_spec.get('image')
        spec._image_meta_from_image(image)
        instance = request_spec.get('instance_properties')
        spec._from_instance(instance)
        flavor = request_spec.get('instance_type')
        spec._from_flavor(flavor)
        # Hydrate now from filter_properties
        spec.ignore_hosts = filter_properties.get('ignore_hosts')
        spec.force_hosts = filter_properties.get('force_hosts')
        spec.force_nodes = filter_properties.get('force_nodes')
        retry = filter_properties.get('retry', {})
        spec._from_retry(retry)
        limits = filter_properties.get('limits', {})
        spec._from_limits(limits)
        spec._populate_group_info(filter_properties)
        scheduler_hints = filter_properties.get('scheduler_hints', {})
        spec._from_hints(scheduler_hints)
        spec.requested_destination = filter_properties.get(
            'requested_destination')

        # NOTE(sbauza): Default the other fields that are not part of the
        # original contract
        spec.obj_set_defaults()

        return spec

    def get_scheduler_hint(self, hint_name, default=None):
        """Convenient helper for accessing a particular scheduler hint since
        it is hydrated by putting a single item into a list.

        In order to reduce the complexity, that helper returns a string if the
        requested hint is a list of only one value, and if not, returns the
        value directly (ie. the list). If the hint is not existing (or
        scheduler_hints is None), then it returns the default value.

        :param hint_name: name of the hint
        :param default: the default value if the hint is not there
        """
        if (not self.obj_attr_is_set('scheduler_hints')
                or self.scheduler_hints is None):
            return default
        hint_val = self.scheduler_hints.get(hint_name, default)
        return (hint_val[0] if isinstance(hint_val, list)
                and len(hint_val) == 1 else hint_val)

    def _to_legacy_image(self):
        return base.obj_to_primitive(self.image) if (
            self.obj_attr_is_set('image') and self.image) else {}

    def _to_legacy_instance(self):
        # NOTE(sbauza): Since the RequestSpec only persists a few Instance
        # fields, we can only return a dict.
        instance = {}
        instance_fields = ['numa_topology', 'pci_requests',
                           'project_id', 'availability_zone', 'instance_uuid']
        for field in instance_fields:
            if not self.obj_attr_is_set(field):
                continue
            if field == 'instance_uuid':
                instance['uuid'] = getattr(self, field)
            else:
                instance[field] = getattr(self, field)
        flavor_fields = ['root_gb', 'ephemeral_gb', 'memory_mb', 'vcpus']
        if not self.obj_attr_is_set('flavor'):
            return instance
        for field in flavor_fields:
            instance[field] = getattr(self.flavor, field)
        return instance

    def _to_legacy_group_info(self):
        # NOTE(sbauza): Since this is only needed until the AffinityFilters are
        # modified by using directly the RequestSpec object, we need to keep
        # the existing dictionary as a primitive.
        return {'group_updated': True,
                'group_hosts': set(self.instance_group.hosts),
                'group_policies': set(self.instance_group.policies),
                'group_members': set(self.instance_group.members)}

    def to_legacy_request_spec_dict(self):
        """Returns a legacy request_spec dict from the RequestSpec object.

        Since we need to manage backwards compatibility and rolling upgrades
        within our RPC API, we need to accept to provide an helper for
        primitiving the right RequestSpec object into a legacy dict until we
        drop support for old Scheduler RPC API versions.
        If you don't understand why this method is needed, please don't use it.
        """
        req_spec = {}
        if not self.obj_attr_is_set('num_instances'):
            req_spec['num_instances'] = self.fields['num_instances'].default
        else:
            req_spec['num_instances'] = self.num_instances
        req_spec['image'] = self._to_legacy_image()
        req_spec['instance_properties'] = self._to_legacy_instance()
        if self.obj_attr_is_set('flavor'):
            req_spec['instance_type'] = self.flavor
        else:
            req_spec['instance_type'] = {}
        return req_spec

    def to_legacy_filter_properties_dict(self):
        """Returns a legacy filter_properties dict from the RequestSpec object.

        Since we need to manage backwards compatibility and rolling upgrades
        within our RPC API, we need to accept to provide an helper for
        primitiving the right RequestSpec object into a legacy dict until we
        drop support for old Scheduler RPC API versions.
        If you don't understand why this method is needed, please don't use it.
        """
        filt_props = {}
        if self.obj_attr_is_set('ignore_hosts') and self.ignore_hosts:
            filt_props['ignore_hosts'] = self.ignore_hosts
        if self.obj_attr_is_set('force_hosts') and self.force_hosts:
            filt_props['force_hosts'] = self.force_hosts
        if self.obj_attr_is_set('force_nodes') and self.force_nodes:
            filt_props['force_nodes'] = self.force_nodes
        if self.obj_attr_is_set('retry') and self.retry:
            filt_props['retry'] = self.retry.to_dict()
        if self.obj_attr_is_set('limits') and self.limits:
            filt_props['limits'] = self.limits.to_dict()
        if self.obj_attr_is_set('instance_group') and self.instance_group:
            filt_props.update(self._to_legacy_group_info())
        if self.obj_attr_is_set('scheduler_hints') and self.scheduler_hints:
            # NOTE(sbauza): We need to backport all the hints correctly since
            # we had to hydrate the field by putting a single item into a list.
            filt_props['scheduler_hints'] = {hint: self.get_scheduler_hint(
                hint) for hint in self.scheduler_hints}
        if self.obj_attr_is_set('requested_destination'
                                ) and self.requested_destination:
            filt_props['requested_destination'] = self.requested_destination
        return filt_props

    @classmethod
    def from_components(cls, context, instance_uuid, image, flavor,
            numa_topology, pci_requests, filter_properties, instance_group,
            availability_zone, security_groups=None, project_id=None):
        """Returns a new RequestSpec object hydrated by various components.

        This helper is useful in creating the RequestSpec from the various
        objects that are assembled early in the boot process.  This method
        creates a complete RequestSpec object with all properties set or
        intentionally left blank.

        :param context: a context object
        :param instance_uuid: the uuid of the instance to schedule
        :param image: a dict of properties for an image or volume
        :param flavor: a flavor NovaObject
        :param numa_topology: InstanceNUMATopology or None
        :param pci_requests: InstancePCIRequests
        :param filter_properties: a dict of properties for scheduling
        :param instance_group: None or an instance group NovaObject
        :param availability_zone: an availability_zone string
        :param security_groups: A SecurityGroupList object. If None, don't
                                set security_groups on the resulting object.
        :param project_id: The project_id for the requestspec (should match
                           the instance project_id).
        """
        spec_obj = cls(context)
        spec_obj.num_instances = 1
        spec_obj.instance_uuid = instance_uuid
        spec_obj.instance_group = instance_group
        if spec_obj.instance_group is None and filter_properties:
            spec_obj._populate_group_info(filter_properties)
        spec_obj.project_id = project_id or context.project_id
        spec_obj._image_meta_from_image(image)
        spec_obj._from_flavor(flavor)
        spec_obj._from_instance_pci_requests(pci_requests)
        spec_obj._from_instance_numa_topology(numa_topology)
        spec_obj.ignore_hosts = filter_properties.get('ignore_hosts')
        spec_obj.force_hosts = filter_properties.get('force_hosts')
        spec_obj.force_nodes = filter_properties.get('force_nodes')
        spec_obj._from_retry(filter_properties.get('retry', {}))
        spec_obj._from_limits(filter_properties.get('limits', {}))
        spec_obj._from_hints(filter_properties.get('scheduler_hints', {}))
        spec_obj.availability_zone = availability_zone
        if security_groups is not None:
            spec_obj.security_groups = security_groups
        spec_obj.requested_destination = filter_properties.get(
            'requested_destination')

        # NOTE(sbauza): Default the other fields that are not part of the
        # original contract
        spec_obj.obj_set_defaults()
        return spec_obj

    def ensure_project_id(self, instance):
        if 'project_id' not in self or self.project_id is None:
            self.project_id = instance.project_id

    @staticmethod
    def _from_db_object(context, spec, db_spec):
        spec_obj = spec.obj_from_primitive(jsonutils.loads(db_spec['spec']))
        for key in spec.fields:
            # Load these from the db model not the serialized object within,
            # though they should match.
            if key in ['id', 'instance_uuid']:
                setattr(spec, key, db_spec[key])
            elif key == 'ignore_hosts':
                # NOTE(mriedem): Do not override the 'ignore_hosts'
                # field which is not persisted. It is not a lazy-loadable
                # field. If it is not set, set None.
                if not spec.obj_attr_is_set(key):
                    setattr(spec, key, None)
            elif key in spec_obj:
                setattr(spec, key, getattr(spec_obj, key))
        spec._context = context

        if 'instance_group' in spec and spec.instance_group:
            # NOTE(danms): We don't store the full instance group in
            # the reqspec since it would be stale almost immediately.
            # Instead, load it by uuid here so it's up-to-date.
            try:
                spec.instance_group = objects.InstanceGroup.get_by_uuid(
                    context, spec.instance_group.uuid)
            except exception.InstanceGroupNotFound:
                # NOTE(danms): Instance group may have been deleted
                spec.instance_group = None

        spec.obj_reset_changes()
        return spec

    @staticmethod
    @db.api_context_manager.reader
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        db_spec = context.session.query(api_models.RequestSpec).filter_by(
            instance_uuid=instance_uuid).first()
        if not db_spec:
            raise exception.RequestSpecNotFound(
                    instance_uuid=instance_uuid)
        return db_spec

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_spec = cls._get_by_instance_uuid_from_db(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_spec)

    @staticmethod
    @db.api_context_manager.writer
    def _create_in_db(context, updates):
        db_spec = api_models.RequestSpec()
        db_spec.update(updates)
        db_spec.save(context.session)
        return db_spec

    def _get_update_primitives(self):
        """Serialize object to match the db model.

        We store copies of embedded objects rather than
        references to these objects because we want a snapshot of the request
        at this point.  If the references changed or were deleted we would
        not be able to reschedule this instance under the same conditions as
        it was originally scheduled with.
        """
        updates = self.obj_get_changes()
        db_updates = None
        # NOTE(alaski): The db schema is the full serialized object in a
        # 'spec' column.  If anything has changed we rewrite the full thing.
        if updates:
            # NOTE(danms): Don't persist the could-be-large and could-be-stale
            # properties of InstanceGroup
            spec = self.obj_clone()
            if 'instance_group' in spec and spec.instance_group:
                spec.instance_group.members = None
                spec.instance_group.hosts = None
            # NOTE(mriedem): Don't persist retries or ignored hosts since
            # those are per-request
            for excluded in ('retry', 'ignore_hosts'):
                if excluded in spec and getattr(spec, excluded):
                    setattr(spec, excluded, None)

            db_updates = {'spec': jsonutils.dumps(spec.obj_to_primitive())}
            if 'instance_uuid' in updates:
                db_updates['instance_uuid'] = updates['instance_uuid']
        return db_updates

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        updates = self._get_update_primitives()
        if not updates:
            raise exception.ObjectActionError(action='create',
                                              reason='no fields are set')
        db_spec = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_spec)

    @staticmethod
    @db.api_context_manager.writer
    def _save_in_db(context, instance_uuid, updates):
        # FIXME(sbauza): Provide a classmethod when oslo.db bug #1520195 is
        # fixed and released
        db_spec = RequestSpec._get_by_instance_uuid_from_db(context,
                                                            instance_uuid)
        db_spec.update(updates)
        db_spec.save(context.session)
        return db_spec

    @base.remotable
    def save(self):
        updates = self._get_update_primitives()
        if updates:
            db_spec = self._save_in_db(self._context, self.instance_uuid,
                                       updates)
            self._from_db_object(self._context, self, db_spec)
            self.obj_reset_changes()

    @staticmethod
    @db.api_context_manager.writer
    def _destroy_in_db(context, instance_uuid):
        result = context.session.query(api_models.RequestSpec).filter_by(
            instance_uuid=instance_uuid).delete()
        if not result:
            raise exception.RequestSpecNotFound(instance_uuid=instance_uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.instance_uuid)

    @staticmethod
    @db.api_context_manager.writer
    def _destroy_bulk_in_db(context, instance_uuids):
        return context.session.query(api_models.RequestSpec).filter(
                api_models.RequestSpec.instance_uuid.in_(instance_uuids)).\
                delete(synchronize_session=False)

    @classmethod
    def destroy_bulk(cls, context, instance_uuids):
        return cls._destroy_bulk_in_db(context, instance_uuids)

    def reset_forced_destinations(self):
        """Clears the forced destination fields from the RequestSpec object.

        This method is for making sure we don't ask the scheduler to give us
        again the same destination(s) without persisting the modifications.
        """
        self.force_hosts = None
        self.force_nodes = None
        # NOTE(sbauza): Make sure we don't persist this, we need to keep the
        # original request for the forced hosts
        self.obj_reset_changes(['force_hosts', 'force_nodes'])


# NOTE(sbauza): Since verifying a huge list of instances can be a performance
# impact, we need to use a marker for only checking a set of them.
# As the current model doesn't expose a way to persist that marker, we propose
# here to use the request_specs table with a fake (and impossible) instance
# UUID where the related spec field (which is Text) would be the marker, ie.
# the last instance UUID we checked.
# TODO(sbauza): Remove the CRUD helpers and the migration script in Ocata.

# NOTE(sbauza): RFC4122 (4.1.7) allows a Nil UUID to be semantically accepted.
FAKE_UUID = '00000000-0000-0000-0000-000000000000'


@db.api_context_manager.reader
def _get_marker_for_migrate_instances(context):
    req_spec = (context.session.query(api_models.RequestSpec).filter_by(
                instance_uuid=FAKE_UUID)).first()
    marker = req_spec['spec'] if req_spec else None
    return marker


@db.api_context_manager.writer
def _set_or_delete_marker_for_migrate_instances(context, marker=None):
    # We need to delete the old marker anyway, which no longer corresponds to
    # the last instance we checked (if there was a marker)...
    # NOTE(sbauza): delete() deletes rows that match the query and if none
    # are found, returns 0 hits.
    context.session.query(api_models.RequestSpec).filter_by(
        instance_uuid=FAKE_UUID).delete()
    if marker is not None:
        # ... but there can be a new marker to set
        db_mapping = api_models.RequestSpec()
        db_mapping.update({'instance_uuid': FAKE_UUID, 'spec': marker})
        db_mapping.save(context.session)


def _create_minimal_request_spec(context, instance):
    image = instance.image_meta
    # This is an old instance. Let's try to populate a RequestSpec
    # object using the existing information we have previously saved.
    request_spec = objects.RequestSpec.from_components(
        context, instance.uuid, image,
        instance.flavor, instance.numa_topology,
        instance.pci_requests,
        {}, None, instance.availability_zone,
        project_id=instance.project_id
    )
    scheduler_utils.setup_instance_group(context, request_spec)
    request_spec.create()


def migrate_instances_add_request_spec(context, max_count):
    """Creates and persists a RequestSpec per instance not yet having it."""
    marker = _get_marker_for_migrate_instances(context)
    # Prevent lazy-load of those fields for every instance later.
    attrs = ['system_metadata', 'flavor', 'pci_requests', 'numa_topology',
             'availability_zone']
    try:
        instances = objects.InstanceList.get_by_filters(
            context, filters={'deleted': False}, sort_key='created_at',
            sort_dir='asc', limit=max_count, marker=marker,
            expected_attrs=attrs)
    except exception.MarkerNotFound:
        # Instance referenced by marker may have been purged.
        # Try again but get all instances.
        instances = objects.InstanceList.get_by_filters(
            context, filters={'deleted': False}, sort_key='created_at',
            sort_dir='asc', limit=max_count, expected_attrs=attrs)
    count_all = len(instances)
    count_hit = 0
    for instance in instances:
        try:
            RequestSpec.get_by_instance_uuid(context, instance.uuid)
        except exception.RequestSpecNotFound:
            _create_minimal_request_spec(context, instance)
            count_hit += 1
    if count_all > 0:
        # We want to persist which last instance was checked in order to make
        # sure we don't review it again in a next call.
        marker = instances[-1].uuid

    _set_or_delete_marker_for_migrate_instances(context, marker)
    return count_all, count_hit


@base.NovaObjectRegistry.register
class Destination(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add cell field
    VERSION = '1.1'

    fields = {
        'host': fields.StringField(),
        # NOTE(sbauza): Given we want to split the host/node relationship later
        # and also remove the possibility to have multiple nodes per service,
        # let's provide a possible nullable node here.
        'node': fields.StringField(nullable=True),
        'cell': fields.ObjectField('CellMapping', nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(Destination, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            if 'cell' in primitive:
                del primitive['cell']


@base.NovaObjectRegistry.register
class SchedulerRetries(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: ComputeNodeList version 1.14
    VERSION = '1.1'

    fields = {
        'num_attempts': fields.IntegerField(),
        # NOTE(sbauza): Even if we are only using host/node strings, we need to
        # know which compute nodes were tried
        'hosts': fields.ObjectField('ComputeNodeList'),
    }

    @classmethod
    def from_dict(cls, context, retry_dict):
        # NOTE(sbauza): We are not persisting the user context since it's only
        # needed for hydrating the Retry object
        retry_obj = cls()
        if not ('num_attempts' and 'hosts') in retry_dict:
            # NOTE(sbauza): We prefer to return an empty object if the
            # primitive is not good enough
            return retry_obj
        retry_obj.num_attempts = retry_dict.get('num_attempts')
        # NOTE(sbauza): each retry_dict['hosts'] item is a list of [host, node]
        computes = [objects.ComputeNode(context=context, host=host,
                                        hypervisor_hostname=node)
                    for host, node in retry_dict.get('hosts')]
        retry_obj.hosts = objects.ComputeNodeList(objects=computes)
        return retry_obj

    def to_dict(self):
        legacy_hosts = [[cn.host, cn.hypervisor_hostname] for cn in self.hosts]
        return {'num_attempts': self.num_attempts,
                'hosts': legacy_hosts}


@base.NovaObjectRegistry.register
class SchedulerLimits(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'numa_topology': fields.ObjectField('NUMATopologyLimits',
                                            nullable=True,
                                            default=None),
        'vcpu': fields.IntegerField(nullable=True, default=None),
        'disk_gb': fields.IntegerField(nullable=True, default=None),
        'memory_mb': fields.IntegerField(nullable=True, default=None),
    }

    @classmethod
    def from_dict(cls, limits_dict):
        limits = cls(**limits_dict)
        # NOTE(sbauza): Since the limits can be set for each field or not, we
        # prefer to have the fields nullable, but default the value to None.
        # Here we accept that the object is always generated from a primitive
        # hence the use of obj_set_defaults exceptionally.
        limits.obj_set_defaults()
        return limits

    def to_dict(self):
        limits = {}
        for field in self.fields:
            if getattr(self, field) is not None:
                limits[field] = getattr(self, field)
        return limits
