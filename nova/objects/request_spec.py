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

import six

from nova import objects
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class RequestSpec(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: ImageMeta version 1.6
    # Version 1.2: SchedulerRetries version 1.1
    VERSION = '1.2'

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

    obj_relationships = {
        'image': [('1.0', '1.5'), ('1.1', '1.6')],
        'numa_topology': [('1.0', '1.2')],
        'flavor': [('1.0', '1.1')],
        'pci_requests': [('1.0', '1.1')],
        'retry': [('1.0', '1.0'), ('1.2', '1.1')],
        'limits': [('1.0', '1.0')],
        'instance_group': [('1.0', '1.9')],
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
        if isinstance(instance, objects.Instance):
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
            else:
                setattr(self, field, getter(instance, field))

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
            members = list(filter_properties.get('group_hosts'))
            self.instance_group = objects.InstanceGroup(policies=policies,
                                                        members=members)
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

    obj_relationships = {
        'hosts': [('1.0', '1.13'), ('1.1', '1.14')],
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

    obj_relationships = {
        'numa_topology': [('1.0', '1.0')],
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
