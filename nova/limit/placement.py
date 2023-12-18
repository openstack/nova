#    Copyright 2022 StackHPC
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

import typing as ty

import os_resource_classes as orc
from oslo_limit import exception as limit_exceptions
from oslo_limit import limit
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.limit import utils as limit_utils
from nova import objects
from nova import quota
from nova.scheduler.client import report
from nova.scheduler import utils

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

# Cache to avoid repopulating ksa state
PLACEMENT_CLIENT = None

LEGACY_LIMITS = {
    "servers": "instances",
    "class:VCPU": "cores",
    "class:MEMORY_MB": "ram",
}


def _get_placement_usages(
    context: 'nova.context.RequestContext', project_id: str
) -> ty.Dict[str, int]:
    return report.report_client_singleton().get_usages_counts_for_limits(
        context, project_id)


def _get_usage(
    context: 'nova.context.RequestContext',
    project_id: str,
    resource_names: ty.List[str],
) -> ty.Dict[str, int]:
    """Called by oslo_limit's enforcer"""
    if not limit_utils.use_unified_limits():
        raise NotImplementedError("Unified limits support is disabled")

    count_servers = False
    resource_classes = []

    for resource in resource_names:
        if resource == "servers":
            count_servers = True
            continue

        if not resource.startswith("class:"):
            raise ValueError("Unknown resource type: %s" % resource)

        # Temporarily strip resource class prefix as placement does not use it.
        # Example: limit resource 'class:VCPU' will be returned as 'VCPU' from
        # placement.
        r_class = resource.lstrip("class:")
        if r_class in orc.STANDARDS or orc.is_custom(r_class):
            resource_classes.append(r_class)
        else:
            raise ValueError("Unknown resource class: %s" % r_class)

    if not count_servers and len(resource_classes) == 0:
        raise ValueError("no resources to check")

    resource_counts = {}
    if count_servers:
        # TODO(melwitt): Change this to count servers from placement once nova
        # is using placement consumer types and is able to differentiate
        # between "instance" allocations vs "migration" allocations.
        if not quota.is_qfd_populated(context):
            LOG.error('Must migrate all instance mappings before using '
                      'unified limits')
            raise ValueError("must first migrate instance mappings")
        mappings = objects.InstanceMappingList.get_counts(context, project_id)
        resource_counts['servers'] = mappings['project']['instances']

    try:
        usages = _get_placement_usages(context, project_id)
    except exception.UsagesRetrievalFailed as e:
        msg = ("Failed to retrieve usages from placement while enforcing "
               "%s quota limits." % ", ".join(resource_names))
        LOG.error(msg + " Error: " + str(e))
        raise exception.UsagesRetrievalFailed(msg)

    # Use legacy behavior VCPU = VCPU + PCPU if configured.
    if CONF.workarounds.unified_limits_count_pcpu_as_vcpu:
        # If PCPU is in resource_classes, that means it was specified in the
        # flavor explicitly. In that case, we expect it to have its own limit
        # registered and we should not fold it into VCPU.
        if orc.PCPU in usages and orc.PCPU not in resource_classes:
            usages[orc.VCPU] = (usages.get(orc.VCPU, 0) +
                                usages.get(orc.PCPU, 0))

    for resource_class in resource_classes:
        # Need to add back resource class prefix that was stripped earlier
        resource_name = 'class:' + resource_class
        # Placement doesn't know about classes with zero usage
        # so default to zero to tell oslo.limit usage is zero
        resource_counts[resource_name] = usages.get(resource_class, 0)

    return resource_counts


def _get_deltas_by_flavor(
    flavor: 'objects.Flavor', is_bfv: bool, count: int
) -> ty.Dict[str, int]:
    if flavor is None:
        raise ValueError("flavor")
    if count < 0:
        raise ValueError("count")

    # NOTE(johngarbutt): this skips bfv, port, and cyborg resources
    # but it still gives us better checks than before unified limits
    # We need an instance in the DB to use the current is_bfv logic
    # which doesn't work well for instances that don't yet have a uuid
    deltas_from_flavor = utils.resources_for_limits(flavor, is_bfv)

    deltas = {"servers": count}
    for resource, amount in deltas_from_flavor.items():
        if amount != 0:
            deltas["class:%s" % resource] = amount * count
    return deltas


def _get_enforcer(
    context: 'nova.context.RequestContext', project_id: str
) -> limit.Enforcer:
    # NOTE(johngarbutt) should we move context arg into oslo.limit?
    def callback(project_id, resource_names):
        return _get_usage(context, project_id, resource_names)

    return limit.Enforcer(callback)


def enforce_num_instances_and_flavor(
    context: 'nova.context.RequestContext',
    project_id: str,
    flavor: 'objects.Flavor',
    is_bfvm: bool,
    min_count: int,
    max_count: int,
    enforcer: ty.Optional[limit.Enforcer] = None,
    delta_updates: ty.Optional[ty.Dict[str, int]] = None,
) -> int:
    """Return max instances possible, else raise TooManyInstances exception."""
    if not limit_utils.use_unified_limits():
        return max_count

    # Ensure the recursion will always complete
    if min_count < 0 or min_count > max_count:
        raise ValueError("invalid min_count")
    if max_count < 0:
        raise ValueError("invalid max_count")

    deltas = _get_deltas_by_flavor(flavor, is_bfvm, max_count)
    if delta_updates:
        deltas.update(delta_updates)

    enforcer = enforcer or _get_enforcer(context, project_id)
    try:
        enforcer.enforce(project_id, deltas)
    except limit_exceptions.ProjectOverLimit as e:
        # NOTE(johngarbutt) we can do better, but this is very simple
        LOG.debug("Limit check failed with count %s retrying with count %s",
                  max_count, max_count - 1)
        try:
            return enforce_num_instances_and_flavor(context, project_id,
                                                    flavor, is_bfvm, min_count,
                                                    max_count - 1,
                                                    enforcer=enforcer)
        except ValueError:
            # Copy the *original* exception message to a OverQuota to
            # propagate to the API layer
            raise exception.TooManyInstances(str(e))

    # no problems with max_count, so we return max count
    return max_count


def _convert_keys_to_legacy_name(new_dict):
    legacy = {}
    for new_name, old_name in LEGACY_LIMITS.items():
        # defensive in case oslo or keystone doesn't give us an answer
        legacy[old_name] = new_dict.get(new_name) or 0
    return legacy


def get_legacy_default_limits():
    enforcer = limit.Enforcer(lambda: None)
    new_limits = enforcer.get_registered_limits(LEGACY_LIMITS.keys())
    return _convert_keys_to_legacy_name(dict(new_limits))


def get_legacy_project_limits(project_id):
    enforcer = limit.Enforcer(lambda: None)
    new_limits = enforcer.get_project_limits(project_id, LEGACY_LIMITS.keys())
    return _convert_keys_to_legacy_name(dict(new_limits))


def get_legacy_counts(context, project_id):
    resource_names = list(LEGACY_LIMITS.keys())
    resource_names.sort()
    new_usage = _get_usage(context, project_id, resource_names)
    return _convert_keys_to_legacy_name(new_usage)
