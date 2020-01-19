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

import copy
import itertools

import os_resource_classes as orc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils
import six

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import instance as obj_instance

LOG = logging.getLogger(__name__)

REQUEST_SPEC_OPTIONAL_ATTRS = ['requested_destination',
                               'security_groups',
                               'network_metadata',
                               'requested_resources',
                               'request_level_params']


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
    # Version 1.9: Added user_id
    # Version 1.10: Added network_metadata
    # Version 1.11: Added is_bfv
    # Version 1.12: Added requested_resources
    # Version 1.13: Added request_level_params
    VERSION = '1.13'

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
        'user_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'flavor': fields.ObjectField('Flavor', nullable=False),
        'num_instances': fields.IntegerField(default=1),
        # NOTE(alex_xu): This field won't be persisted.
        'ignore_hosts': fields.ListOfStringsField(nullable=True),
        # NOTE(mriedem): In reality, you can only ever have one
        # host in the force_hosts list. The fact this is a list
        # is a mistake perpetuated over time.
        'force_hosts': fields.ListOfStringsField(nullable=True),
        # NOTE(mriedem): In reality, you can only ever have one
        # node in the force_nodes list. The fact this is a list
        # is a mistake perpetuated over time.
        'force_nodes': fields.ListOfStringsField(nullable=True),
        # NOTE(alex_xu): This field won't be persisted.
        'requested_destination': fields.ObjectField('Destination',
                                                    nullable=True,
                                                    default=None),
        # NOTE(alex_xu): This field won't be persisted.
        'retry': fields.ObjectField('SchedulerRetries', nullable=True),
        'limits': fields.ObjectField('SchedulerLimits', nullable=True),
        'instance_group': fields.ObjectField('InstanceGroup', nullable=True),
        # NOTE(sbauza): Since hints are depending on running filters, we prefer
        # to leave the API correctly validating the hints per the filters and
        # just provide to the RequestSpec object a free-form dictionary
        'scheduler_hints': fields.DictOfListOfStringsField(nullable=True),
        'instance_uuid': fields.UUIDField(),
        # TODO(stephenfin): Remove this as it's related to nova-network
        'security_groups': fields.ObjectField('SecurityGroupList'),
        # NOTE(alex_xu): This field won't be persisted.
        'network_metadata': fields.ObjectField('NetworkMetadata'),
        'is_bfv': fields.BooleanField(),
        # NOTE(gibi): Eventually we want to store every resource request as
        # RequestGroup objects here. However currently the flavor based
        # resources like vcpu, ram, disk, and flavor.extra_spec based resources
        # are not handled this way. See the Todo in from_components() where
        # requested_resources are set.
        # NOTE(alex_xu): This field won't be persisted.
        'requested_resources': fields.ListOfObjectsField('RequestGroup',
                                                         nullable=True,
                                                         default=None),
        # NOTE(efried): This field won't be persisted.
        'request_level_params': fields.ObjectField('RequestLevelParams'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(RequestSpec, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 13) and 'request_level_params' in primitive:
            del primitive['request_level_params']
        if target_version < (1, 12):
            if 'requested_resources' in primitive:
                del primitive['requested_resources']
        if target_version < (1, 11) and 'is_bfv' in primitive:
            del primitive['is_bfv']
        if target_version < (1, 10):
            if 'network_metadata' in primitive:
                del primitive['network_metadata']
        if target_version < (1, 9):
            if 'user_id' in primitive:
                del primitive['user_id']
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

        if attrname == 'network_metadata':
            self.network_metadata = objects.NetworkMetadata(
                physnets=set(), tunneled=False)
            return

        if attrname == 'request_level_params':
            self.request_level_params = RequestLevelParams()
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

    @property
    def root_required(self):
        # self.request_level_params and .root_required lazy-default via their
        # respective obj_load_attr methods.
        return self.request_level_params.root_required

    @property
    def root_forbidden(self):
        # self.request_level_params and .root_forbidden lazy-default via their
        # respective obj_load_attr methods.
        return self.request_level_params.root_forbidden

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
                           'project_id', 'user_id', 'availability_zone']
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
        if isinstance(numa_topology, six.string_types):
            numa_topology = objects.InstanceNUMATopology.obj_from_primitive(
                jsonutils.loads(numa_topology))

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
            self.instance_group = objects.InstanceGroup(policy=policies[0],
                                                        hosts=hosts,
                                                        members=members)
            # InstanceGroup.uuid is not nullable so only set it if we got it.
            group_uuid = filter_properties.get('group_uuid')
            if group_uuid:
                self.instance_group.uuid = group_uuid
            # hosts has to be not part of the updates for saving the object
            self.instance_group.obj_reset_changes(['hosts'])
        else:
            # Set the value anyway to avoid any call to obj_attr_is_set for it
            self.instance_group = None

    def _from_limits(self, limits):
        if isinstance(limits, dict):
            self.limits = SchedulerLimits.from_dict(limits)
        else:
            # Already a SchedulerLimits object.
            self.limits = limits

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
        if (not self.obj_attr_is_set('scheduler_hints') or
                self.scheduler_hints is None):
            return default
        hint_val = self.scheduler_hints.get(hint_name, default)
        return (hint_val[0] if isinstance(hint_val, list) and
                len(hint_val) == 1 else hint_val)

    def _to_legacy_image(self):
        return base.obj_to_primitive(self.image) if (
            self.obj_attr_is_set('image') and self.image) else {}

    def _to_legacy_instance(self):
        # NOTE(sbauza): Since the RequestSpec only persists a few Instance
        # fields, we can only return a dict.
        instance = {}
        instance_fields = ['numa_topology', 'pci_requests',
                           'project_id', 'user_id', 'availability_zone',
                           'instance_uuid']
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
                'group_policies': set([self.instance_group.policy]),
                'group_members': set(self.instance_group.members),
                'group_uuid': self.instance_group.uuid}

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
            availability_zone, security_groups=None, project_id=None,
            user_id=None, port_resource_requests=None):
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
        :param user_id: The user_id for the requestspec (should match
                           the instance user_id).
        :param port_resource_requests: a list of RequestGroup objects
                                       representing the resource needs of the
                                       neutron ports
        """
        spec_obj = cls(context)
        spec_obj.num_instances = 1
        spec_obj.instance_uuid = instance_uuid
        spec_obj.instance_group = instance_group
        if spec_obj.instance_group is None and filter_properties:
            spec_obj._populate_group_info(filter_properties)
        spec_obj.project_id = project_id or context.project_id
        spec_obj.user_id = user_id or context.user_id
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

        # TODO(gibi): do the creation of the unnumbered group and any
        # numbered group from the flavor by moving the logic from
        # nova.scheduler.utils.resources_from_request_spec() here. See also
        # the comment in the definition of requested_resources field.
        spec_obj.requested_resources = []
        if port_resource_requests:
            spec_obj.requested_resources.extend(port_resource_requests)

        # NOTE(efried): We don't need to handle request_level_params here yet
        #  because they're set dynamically by the scheduler. That could change
        #  in the future.

        # NOTE(sbauza): Default the other fields that are not part of the
        # original contract
        spec_obj.obj_set_defaults()
        return spec_obj

    def ensure_project_and_user_id(self, instance):
        if 'project_id' not in self or self.project_id is None:
            self.project_id = instance.project_id
        if 'user_id' not in self or self.user_id is None:
            self.user_id = instance.user_id

    def ensure_network_metadata(self, instance):
        if not (instance.info_cache and instance.info_cache.network_info):
            return

        physnets = set([])
        tunneled = True

        # physical_network and tunneled might not be in the cache for old
        # instances that haven't had their info_cache healed yet
        for vif in instance.info_cache.network_info:
            physnet = vif.get('network', {}).get('meta', {}).get(
                'physical_network', None)
            if physnet:
                physnets.add(physnet)
            tunneled |= vif.get('network', {}).get('meta', {}).get(
                'tunneled', False)

        self.network_metadata = objects.NetworkMetadata(
            physnets=physnets, tunneled=tunneled)

    @staticmethod
    def _from_db_object(context, spec, db_spec):
        spec_obj = spec.obj_from_primitive(jsonutils.loads(db_spec['spec']))
        for key in spec.fields:
            # Load these from the db model not the serialized object within,
            # though they should match.
            if key in ['id', 'instance_uuid']:
                setattr(spec, key, db_spec[key])
            elif key in ('requested_destination', 'requested_resources',
                         'network_metadata', 'request_level_params'):
                # Do not override what we already have in the object as this
                # field is not persisted. If save() is called after
                # one of these fields is populated, it will reset the field to
                # None and we'll lose what is set (but not persisted) on the
                # object.
                continue
            elif key in ('retry', 'ignore_hosts'):
                # NOTE(takashin): Do not override the 'retry' or 'ignore_hosts'
                # fields which are not persisted. They are not lazy-loadable
                # fields. If they are not set, set None.
                if not spec.obj_attr_is_set(key):
                    setattr(spec, key, None)
            elif key in spec_obj:
                setattr(spec, key, getattr(spec_obj, key))
        spec._context = context

        if 'instance_group' in spec and spec.instance_group:
            # NOTE(mriedem): We could have a half-baked instance group with no
            # uuid if some legacy translation was performed on this spec in the
            # past. In that case, try to workaround the issue by getting the
            # group uuid from the scheduler hint.
            if 'uuid' not in spec.instance_group:
                spec.instance_group.uuid = spec.get_scheduler_hint('group')
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
            # NOTE(mriedem): Don't persist these since they are per-request
            for excluded in ('retry', 'requested_destination',
                             'requested_resources', 'ignore_hosts',
                             'request_level_params'):
                if excluded in spec and getattr(spec, excluded):
                    setattr(spec, excluded, None)
            # NOTE(stephenfin): Don't persist network metadata since we have
            # no need for it after scheduling
            if 'network_metadata' in spec and spec.network_metadata:
                del spec.network_metadata

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

    @property
    def maps_requested_resources(self):
        """Returns True if this RequestSpec needs to map requested_resources
        to resource providers, False otherwise.
        """
        return 'requested_resources' in self and self.requested_resources

    def _is_valid_group_rp_mapping(
            self, group_rp_mapping, placement_allocations, provider_traits):
        """Decides if the mapping is valid from resources and traits
        perspective.

        :param group_rp_mapping: A list of RequestGroup - RP UUID two tuples
                                representing a mapping between request groups
                                in this RequestSpec and RPs from the
                                allocation. It contains every RequestGroup in
                                this RequestSpec but the mapping might not be
                                valid from resources and traits perspective.
        :param placement_allocations: The overall allocation made by the
                                      scheduler for this RequestSpec
        :param provider_traits: A dict keyed by resource provider uuids
                                containing the list of traits the given RP has.
                                This dict contains info only about RPs
                                appearing in the placement_allocations param.
        :return: True if each group's resource and trait request can be
                 fulfilled from the RP it is mapped to. False otherwise.
        """

        # Check that traits are matching for each group - rp pair in
        # this mapping
        for group, rp_uuid in group_rp_mapping:
            if not group.required_traits.issubset(provider_traits[rp_uuid]):
                return False

        # TODO(gibi): add support for groups with forbidden_traits and
        # aggregates

        # Check that each group can consume the requested resources from the rp
        # that it is mapped to in the current mapping. Consume each group's
        # request from the allocation, if anything drops below zero, then this
        # is not a solution
        rcs = set()
        allocs = copy.deepcopy(placement_allocations)
        for group, rp_uuid in group_rp_mapping:
            rp_allocs = allocs[rp_uuid]['resources']
            for rc, amount in group.resources.items():
                rcs.add(rc)
                if rc in rp_allocs:
                    rp_allocs[rc] -= amount
                    if rp_allocs[rc] < 0:
                        return False
                else:
                    return False

        # Check that all the allocations are consumed from the resource
        # classes that appear in the request groups. It should never happen
        # that we have a match but also have some leftover if placement returns
        # valid allocation candidates. Except if the leftover in the allocation
        # are due to the RC requested in the unnumbered group.
        for rp_uuid in allocs:
            rp_allocs = allocs[rp_uuid]['resources']
            for rc, amount in group.resources.items():
                if rc in rcs and rc in rp_allocs:
                    if rp_allocs[rc] != 0:
                        LOG.debug(
                            'Found valid group - RP mapping %s but there are '
                            'allocations leftover in %s from resource class '
                            '%s', group_rp_mapping, allocs, rc)
                        return False

        # If both the traits and the allocations are OK then mapping is valid
        return True

    def map_requested_resources_to_providers(
            self, placement_allocations, provider_traits):
        """Fill the provider_uuids field in each RequestGroup objects in the
        requested_resources field.

        The mapping is generated based on the overall allocation made for this
        RequestSpec, the request in each RequestGroup, and the traits of the
        RPs in the allocation.

        Limitations:
        * only groups with use_same_provider = True is mapped, the un-numbered
          group are not supported.
        * mapping is generated only based on the resource request and the
          required traits, aggregate membership and forbidden traits are not
          supported.
        * requesting the same resource class in numbered and un-numbered group
          is not supported

        We can live with these limitations today as Neutron does not use
        forbidden traits and aggregates in the request and each Neutron port is
        mapped to a numbered group and the resources class used by neutron
        ports are never requested through the flavor extra_spec.

        This is a workaround as placement does not return which RP fulfills
        which granular request group in the allocation candidate request. There
        is a spec proposing a solution in placement:
        https://review.opendev.org/#/c/597601/

        :param placement_allocations: The overall allocation made by the
                                      scheduler for this RequestSpec
        :param provider_traits: A dict keyed by resource provider uuids
                                containing the list of traits the given RP has.
                                This dict contains info only about RPs
                                appearing in the placement_allocations param.
        """
        if not self.maps_requested_resources:
            # Nothing to do, so let's return early
            return

        for group in self.requested_resources:
            # See the limitations in the func doc above
            if (not group.use_same_provider or
                    group.aggregates or
                    group.forbidden_traits):
                raise NotImplementedError()

        # Iterate through every possible group - RP mappings and try to find a
        # valid one. If there are more than one possible solution then it is
        # enough to find one as these solutions are interchangeable from
        # backend (e.g. Neutron) perspective.
        LOG.debug('Trying to find a valid group - RP mapping for groups %s to '
                  'allocations %s with traits %s', self.requested_resources,
                  placement_allocations, provider_traits)

        # This generator first creates permutations with repetition of the RPs
        # with length of the number of groups we have. So if there is
        #   2 RPs (rp1, rp2) and
        #   3 groups (g1, g2, g3).
        # Then the itertools.product(('rp1', 'rp2'), repeat=3)) will be:
        #  (rp1, rp1, rp1)
        #  (rp1, rp1, rp2)
        #  (rp1, rp2, rp1)
        #  ...
        #  (rp2, rp2, rp2)
        # Then we zip each of this permutations to our group list resulting in
        # a list of list of group - rp pairs:
        # [[('g1', 'rp1'), ('g2', 'rp1'), ('g3', 'rp1')],
        #  [('g1', 'rp1'), ('g2', 'rp1'), ('g3', 'rp2')],
        #  [('g1', 'rp1'), ('g2', 'rp2'), ('g3', 'rp1')],
        #  ...
        #  [('g1', 'rp2'), ('g2', 'rp2'), ('g3', 'rp2')]]
        # NOTE(gibi): the list() around the zip() below is needed as the
        # algorithm looks into the mapping more than once and zip returns an
        # iterator in py3.x. Still we need to generate a mapping once hence the
        # generator expression.
        every_possible_mapping = (list(zip(self.requested_resources, rps))
                                  for rps in itertools.product(
                                      placement_allocations.keys(),
                                      repeat=len(self.requested_resources)))
        for mapping in every_possible_mapping:
            if self._is_valid_group_rp_mapping(
                    mapping, placement_allocations, provider_traits):
                for group, rp in mapping:
                    # NOTE(gibi): un-numbered group might be mapped to more
                    # than one RP but we do not support that yet here.
                    group.provider_uuids = [rp]
                LOG.debug('Found valid group - RP mapping %s', mapping)
                return

        # if we reached this point then none of the possible mappings was
        # valid. This should never happen as Placement returns allocation
        # candidates based on the overall resource request of the server
        # including the request of the groups.
        raise ValueError('No valid group - RP mapping is found for '
                         'groups %s, allocation %s and provider traits %s' %
                         (self.requested_resources, placement_allocations,
                          provider_traits))

    def get_request_group_mapping(self):
        """Return request group resource - provider mapping. This is currently
        used for Neutron ports that have resource request due to the port
        having QoS minimum bandwidth policy rule attached.

        :returns: A dict keyed by RequestGroup requester_id, currently Neutron
        port_id, to a list of resource provider UUIDs which provide resource
        for that RequestGroup.
        """

        if ('requested_resources' in self and
                self.requested_resources is not None):
            return {
                group.requester_id: group.provider_uuids
                for group in self.requested_resources
            }


@base.NovaObjectRegistry.register
class Destination(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add cell field
    # Version 1.2: Add aggregates field
    # Version 1.3: Add allow_cross_cell_move field.
    # Version 1.4: Add forbidden_aggregates field
    VERSION = '1.4'

    fields = {
        'host': fields.StringField(),
        # NOTE(sbauza): Given we want to split the host/node relationship later
        # and also remove the possibility to have multiple nodes per service,
        # let's provide a possible nullable node here.
        'node': fields.StringField(nullable=True),
        'cell': fields.ObjectField('CellMapping', nullable=True),

        # NOTE(dansmith): These are required aggregates (or sets) and
        # are passed to placement.  See require_aggregates() below.
        'aggregates': fields.ListOfStringsField(nullable=True,
                                                default=None),
        # NOTE(mriedem): allow_cross_cell_move defaults to False so that the
        # scheduler by default selects hosts from the cell specified in the
        # cell field.
        'allow_cross_cell_move': fields.BooleanField(default=False),
        # NOTE(vrushali): These are forbidden aggregates passed to placement as
        # query params to the allocation candidates API. Nova uses this field
        # to implement the isolate_aggregates request filter.
        'forbidden_aggregates': fields.SetOfStringsField(nullable=True,
                                                         default=None),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(Destination, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4):
            if 'forbidden_aggregates' in primitive:
                del primitive['forbidden_aggregates']
        if target_version < (1, 3) and 'allow_cross_cell_move' in primitive:
            del primitive['allow_cross_cell_move']
        if target_version < (1, 2):
            if 'aggregates' in primitive:
                del primitive['aggregates']
        if target_version < (1, 1):
            if 'cell' in primitive:
                del primitive['cell']

    def obj_load_attr(self, attrname):
        self.obj_set_defaults(attrname)

    def require_aggregates(self, aggregates):
        """Add a set of aggregates to the list of required aggregates.

        This will take a list of aggregates, which are to be logically OR'd
        together and add them to the list of required aggregates that will
        be used to query placement. Aggregate sets provided in sequential calls
        to this method will be AND'd together.

        For example, the following set of calls:
            dest.require_aggregates(['foo', 'bar'])
            dest.require_aggregates(['baz'])
        will generate the following logical query to placement:
            "Candidates should be in 'foo' OR 'bar', but definitely in 'baz'"

        :param aggregates: A list of aggregates, at least one of which
                           must contain the destination host.

        """
        if self.aggregates is None:
            self.aggregates = []
        self.aggregates.append(','.join(aggregates))

    def append_forbidden_aggregates(self, forbidden_aggregates):
        """Add a set of aggregates to the forbidden aggregates.

        This will take a set of forbidden aggregates that should be
        ignored by the placement service.

        :param forbidden_aggregates: A set of aggregates which should be
                                    ignored by the placement service.

        """
        if self.forbidden_aggregates is None:
            self.forbidden_aggregates = set([])
        self.forbidden_aggregates |= forbidden_aggregates


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


@base.NovaObjectRegistry.register
class RequestGroup(base.NovaEphemeralObject):
    """Versioned object based on the unversioned
    nova.api.openstack.placement.lib.RequestGroup object.
    """
    # Version 1.0: Initial version
    # Version 1.1: add requester_id and provider_uuids fields
    # Version 1.2: add in_tree field
    # Version 1.3: Add forbidden_aggregates field
    VERSION = '1.3'

    fields = {
        'use_same_provider': fields.BooleanField(default=True),
        'resources': fields.DictOfIntegersField(default={}),
        'required_traits': fields.SetOfStringsField(default=set()),
        'forbidden_traits': fields.SetOfStringsField(default=set()),
        # The aggregates field has a form of
        #     [[aggregate_UUID1],
        #      [aggregate_UUID2, aggregate_UUID3]]
        # meaning that the request should be fulfilled from an RP that is a
        # member of the aggregate aggregate_UUID1 and member of the aggregate
        # aggregate_UUID2 or aggregate_UUID3 .
        'aggregates': fields.ListOfListsOfStringsField(default=[]),
        # The forbidden_aggregates field has a form of
        #     set(['aggregate_UUID1', 'aggregate_UUID12', 'aggregate_UUID3'])
        # meaning that the request should not be fulfilled from an RP
        # belonging to any of the aggregates in forbidden_aggregates field.
        'forbidden_aggregates': fields.SetOfStringsField(default=set()),
        # The entity the request is coming from (e.g. the Neutron port uuid)
        # which may not always be a UUID.
        'requester_id': fields.StringField(nullable=True, default=None),
        # The resource provider UUIDs that together fulfill the request
        # NOTE(gibi): this can be more than one if this is the unnumbered
        # request group (i.e. use_same_provider=False)
        'provider_uuids': fields.ListOfUUIDField(default=[]),
        'in_tree': fields.UUIDField(nullable=True, default=None),
    }

    @classmethod
    def from_port_request(cls, context, port_uuid, port_resource_request):
        """Init the group from the resource request of a neutron port

        :param context: the request context
        :param port_uuid: the port requesting the resources
        :param port_resource_request: the resource_request attribute of the
                                      neutron port
        For example:

            port_resource_request = {
                "resources": {
                    "NET_BW_IGR_KILOBIT_PER_SEC": 1000,
                    "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
                "required": ["CUSTOM_PHYSNET_2",
                             "CUSTOM_VNIC_TYPE_NORMAL"]
            }
        """

        # NOTE(gibi): Assumptions:
        # * a port requests resource from a single provider.
        # * a port only specifies resources and required traits
        # NOTE(gibi): Placement rejects allocation candidates where a request
        # group has traits but no resources specified. This is why resources
        # are handled as mandatory below but not traits.
        obj = cls(context=context,
                  use_same_provider=True,
                  resources=port_resource_request['resources'],
                  required_traits=set(port_resource_request.get(
                      'required', [])),
                  requester_id=port_uuid)
        obj.obj_set_defaults()
        return obj

    def obj_make_compatible(self, primitive, target_version):
        super(RequestGroup, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 3):
            if 'forbidden_aggregates' in primitive:
                del primitive['forbidden_aggregates']
        if target_version < (1, 2):
            if 'in_tree' in primitive:
                del primitive['in_tree']
        if target_version < (1, 1):
            if 'requester_id' in primitive:
                del primitive['requester_id']
            if 'provider_uuids' in primitive:
                del primitive['provider_uuids']

    def add_resource(self, rclass, amount):
        # Validate the class.
        if not (rclass.startswith(orc.CUSTOM_NAMESPACE) or
                        rclass in orc.STANDARDS):
            LOG.warning(
                "Received an invalid ResourceClass '%(key)s' in extra_specs.",
                {"key": rclass})
            return
        # val represents the amount.  Convert to int, or warn and skip.
        try:
            amount = int(amount)
            if amount < 0:
                raise ValueError()
        except ValueError:
            LOG.warning(
                "Resource amounts must be nonnegative integers. Received '%s'",
                amount)
            return
        self.resources[rclass] = amount

    def add_trait(self, trait_name, trait_type):
        # Currently the only valid values for a trait entry are 'required'
        # and 'forbidden'
        trait_vals = ('required', 'forbidden')
        if trait_type == 'required':
            self.required_traits.add(trait_name)
        elif trait_type == 'forbidden':
            self.forbidden_traits.add(trait_name)
        else:
            LOG.warning(
                "Only (%(tvals)s) traits are supported. Received '%(val)s'.",
                {"tvals": ', '.join(trait_vals), "val": trait_type})

    def is_empty(self):
        return not any((
            self.resources,
            self.required_traits, self.forbidden_traits,
            self.aggregates, self.forbidden_aggregates))

    def strip_zeros(self):
        """Remove any resources whose amount is zero."""
        for rclass in list(self.resources):
            if self.resources[rclass] == 0:
                self.resources.pop(rclass)


@base.NovaObjectRegistry.register
class RequestLevelParams(base.NovaObject):
    """Options destined for the "top level" of the placement allocation
    candidates query (parallel to, but not including, the list of
    RequestGroup).
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        # Traits required on the root provider
        'root_required': fields.SetOfStringsField(default=set()),
        # Traits forbidden on the root provider
        'root_forbidden': fields.SetOfStringsField(default=set()),
        # NOTE(efried): group_policy would be appropriate to include here, once
        # we have a use case for it.
    }

    def obj_load_attr(self, attrname):
        self.obj_set_defaults(attrname)
