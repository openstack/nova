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

import itertools
import re
import typing as ty

from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova import objects
from oslo_utils import versionutils


SUPPORTED_TYPE_PATTERNS = [
    # As defined by nova.virt.libvirt.utils.get_default_machine_type
    r'^pc$',
    r'^q35$',
    r'^virt$',
    r'^s390-ccw-virtio$',
    # versioned types of the above
    r'^pc-\d+.\d+',
    r'^pc-i440fx-\d+.\d+',
    r'^pc-q35-\d+.\d+',
    r'^virt-\d+.\d+',
    r'^s390-ccw-virtio-\d+.\d+',
    # RHEL specific versions of the pc-i440fx and pc-q35 types
    r'^pc-i440fx-rhel\d.\d+.\d+',
    r'^pc-q35-rhel\d.\d+.\d+',
]


ALLOWED_UPDATE_VM_STATES = [
    vm_states.STOPPED,
    vm_states.SHELVED,
    vm_states.SHELVED_OFFLOADED
]


def get_machine_type(
    context: 'nova_context.RequestContext',
    instance_uuid: str,
) -> ty.Optional[str]:
    """Get the registered machine type of an instance

    :param context: Request context.
    :param instance_uuid: Instance UUID to check.
    :returns: The machine type or None.
    :raises: exception.InstanceNotFound, exception.InstanceMappingNotFound
    """
    im = objects.InstanceMapping.get_by_instance_uuid(context, instance_uuid)
    with nova_context.target_cell(context, im.cell_mapping) as cctxt:
        # NOTE(lyarwood): While we are after the value of 'hw_machine_type'
        # stored as an image metadata property this actually comes from the
        # system metadata of the instance so we need to add
        # expected_attrs=['system_metadata'] here.
        instance = objects.instance.Instance.get_by_uuid(
            cctxt, instance_uuid, expected_attrs=['system_metadata'])
        return instance.image_meta.properties.get('hw_machine_type')


def _check_machine_type_support(
    mtype: str
) -> None:
    """Check that the provided machine type is supported

    This check is done without access to the compute host and
    so instead relies on a hardcoded list of supported machine types to
    validate the provided machine type.

    :param machine_type: Machine type to check
    :raises: nova.exception.UnsupportedMachineType
    """
    if not any(m for m in SUPPORTED_TYPE_PATTERNS if re.match(m, mtype)):
        raise exception.UnsupportedMachineType(machine_type=mtype)


def _check_update_to_existing_type(
    existing_type: str,
    machine_type: str
) -> None:
    """Check the update to an existing machine type

    The aim here is to block operators from moving between the underlying
    machine types, between versioned and aliased types or to an older version
    of the same type during an update.

    :param existing_type: The existing machine type
    :param machine_type: The new machine type
    :raises: nova.exception.InvalidMachineTypeUpdate
    """
    # Check that we are not switching between types or between an alias and
    # versioned type such as q35 to pc-q35-5.2.0 etc.
    for m in SUPPORTED_TYPE_PATTERNS:
        if re.match(m, existing_type) and not re.match(m, machine_type):
            raise exception.InvalidMachineTypeUpdate(
                existing_machine_type=existing_type, machine_type=machine_type)

    # Now check that the new version isn't older than the original.
    # This needs to support x.y and x.y.z as used by RHEL shipped QEMU
    version_pattern = r'\d+\.\d+$|\d+\.\d+\.\d+$'
    if any(re.findall(version_pattern, existing_type)):
        existing_version = re.findall(version_pattern, existing_type)[0]
        new_version = re.findall(version_pattern, machine_type)[0]
        if (versionutils.convert_version_to_int(new_version) <
            versionutils.convert_version_to_int(existing_version)):
            raise exception.InvalidMachineTypeUpdate(
                existing_machine_type=existing_type,
                machine_type=machine_type)


def _check_vm_state(
    instance: 'objects.Instance',
):
    """Ensure the vm_state of the instance is in ALLOWED_UPDATE_VM_STATES

    :param instance: Instance object to check
    :raises: nova.exception.InstanceInvalidState
    """
    if instance.vm_state not in ALLOWED_UPDATE_VM_STATES:
        raise exception.InstanceInvalidState(
            instance_uuid=instance.uuid, attr='vm_state',
            state=instance.vm_state, method='update machine type.')


def update_machine_type(
    context: nova_context.RequestContext,
    instance_uuid: str,
    machine_type: str,
    force: bool = False,
) -> ty.Tuple[str, str]:
    """Set or update the stored machine type of an instance

    :param instance_uuid: Instance UUID to update.
    :param machine_type: Machine type to update.
    :param force: If the update should be forced.
    :returns: A tuple of the updated machine type and original machine type.
    """
    im = objects.InstanceMapping.get_by_instance_uuid(context, instance_uuid)
    with nova_context.target_cell(context, im.cell_mapping) as cctxt:

        instance = objects.instance.Instance.get_by_uuid(
            cctxt, instance_uuid, expected_attrs=['system_metadata'])

        # Fetch the existing system metadata machine type if one is recorded
        existing_mtype = instance.image_meta.properties.get('hw_machine_type')

        # Return if the type is already updated
        if existing_mtype and existing_mtype == machine_type:
            return machine_type, existing_mtype

        # If the caller wants to force the update now is the time to do it.
        if force:
            instance.system_metadata['image_hw_machine_type'] = machine_type
            instance.save()
            return machine_type, existing_mtype

        # Ensure the instance is in a suitable vm_state to update
        _check_vm_state(instance)

        # Ensure the supplied machine type is supported
        _check_machine_type_support(machine_type)

        # If the instance already has a type ensure the update is valid
        if existing_mtype:
            _check_update_to_existing_type(existing_mtype, machine_type)

        # Finally save the machine type in the instance system metadata
        instance.system_metadata['image_hw_machine_type'] = machine_type
        instance.save()

        return machine_type, existing_mtype


def _get_instances_without_mtype(
    context: 'nova_context.RequestContext',
) -> ty.List[objects.instance.Instance]:
    """Fetch a list of instance UUIDs from the DB without hw_machine_type set

    :param meta: 'sqlalchemy.MetaData' pointing to a given cell DB
    :returns: A list of Instance objects or an empty list
    """
    instances = objects.InstanceList.get_all(
        context, expected_attrs=['system_metadata'])
    instances_without = []
    for instance in instances:
        if instance.deleted == 0 and instance.vm_state != vm_states.BUILDING:
            if instance.image_meta.properties.get('hw_machine_type') is None:
                instances_without.append(instance)
    return instances_without


def get_instances_without_type(
    context: 'nova_context.RequestContext',
    cell_uuid: ty.Optional[str] = None,
) -> ty.List[objects.instance.Instance]:
    """Find instances without hw_machine_type set, optionally within a cell.

    :param context: Request context
    :param cell_uuid: Optional cell UUID to look within
    :returns: A list of Instance objects or an empty list
    """
    if cell_uuid:
        cell_mapping = objects.CellMapping.get_by_uuid(context, cell_uuid)
        results = nova_context.scatter_gather_single_cell(
            context,
            cell_mapping,
            _get_instances_without_mtype
        )

    results = nova_context.scatter_gather_skip_cell0(
        context,
        _get_instances_without_mtype
    )

    # Flatten the returned list of results into a single list of instances
    return list(itertools.chain(*[r for c, r in results.items()]))
