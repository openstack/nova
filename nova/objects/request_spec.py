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

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import instance as obj_instance
from nova.virt import hardware

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class RequestSpec(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: ImageMeta version 1.6
    # Version 1.2: SchedulerRetries version 1.1
    # Version 1.3: InstanceGroup version 1.10
    # Version 1.4: ImageMeta version 1.7
    # Version 1.5: Added get_by_instance_uuid(), create(), save()
    VERSION = '1.5'

    fields = {
        'id': fields.IntegerField(),
        'image': fields.ObjectField('ImageMeta', nullable=True),
        'numa_topology': fields.ObjectField('InstanceNUMATopology',
                                            nullable=True),
        'pci_requests': fields.ObjectField('InstancePCIRequests',
                                           nullable=True),
        'project_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'flavor': fields.ObjectField('Flavor', nullable=False),
        'num_instances': fields.IntegerField(default=1),
        'ignore_hosts': fields.ListOfStringsField(nullable=True),
        'force_hosts': fields.ListOfStringsField(nullable=True),
        'force_nodes': fields.ListOfStringsField(nullable=True),
        'retry': fields.ObjectField('SchedulerRetries', nullable=True),
        'limits': fields.ObjectField('SchedulerLimits', nullable=True),
        'instance_group': fields.ObjectField('InstanceGroup', nullable=True),
        # NOTE(sbauza): Since hints are depending on running filters, we prefer
        # to leave the API correctly validating the hints per the filters and
        # just provide to the RequestSpec object a free-form dictionary
        'scheduler_hints': fields.DictOfListOfStringsField(nullable=True),
        'instance_uuid': fields.UUIDField(),
    }

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
            self.instance_group = objects.InstanceGroup(policies=policies,
                                                        hosts=hosts)
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
            for hint, value in six.iteritems(hints_dict)}

    @classmethod
    def from_primitives(cls, context, request_spec, filter_properties):
        """Returns a new RequestSpec object by hydrating it from legacy dicts.

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
                'group_policies': set(self.instance_group.policies)}

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
        return filt_props

    @staticmethod
    def _from_db_object(context, spec, db_spec):
        spec = spec.obj_from_primitive(jsonutils.loads(db_spec['spec']))
        spec._context = context
        spec.obj_reset_changes()
        return spec

    @staticmethod
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        session = db.get_api_session()

        with session.begin():
            db_spec = session.query(api_models.RequestSpec).filter_by(
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
        # NOTE(alaski): The db schema is the full serialized object in a
        # 'spec' column.  If anything has changed we rewrite the full thing.
        if updates:
            db_updates = {'spec': jsonutils.dumps(self.obj_to_primitive())}
            if 'instance_uuid' in updates:
                db_updates['instance_uuid'] = updates['instance_uuid']
        return db_updates

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        updates = self._get_update_primitives()

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
        db_spec = self._save_in_db(self._context, self.instance_uuid, updates)
        self._from_db_object(self._context, self, db_spec)
        self.obj_reset_changes()


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
