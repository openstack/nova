# Copyright 2014 Intel Corporation
# All Rights Reserved.
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
import functools

from nova import exception


def check_device_status(dev_status=None):
    """Decorator to check device status before changing it."""

    if dev_status is not None and not isinstance(dev_status, set):
        dev_status = set(dev_status)

    def outer(f):
        @functools.wraps(f)
        def inner(devobj, instance=None):
            if devobj['status'] not in dev_status:
                raise exception.PciDeviceInvalidStatus(
                    compute_node_id=devobj.compute_node_id,
                    address=devobj.address, status=devobj.status,
                    hopestatus=dev_status)
            if instance:
                return f(devobj, instance)
            else:
                return f(devobj)
        return inner
    return outer


@check_device_status(dev_status=['available'])
def claim(devobj, instance):
    devobj.status = 'claimed'
    devobj.instance_uuid = instance['uuid']


@check_device_status(dev_status=['available', 'claimed'])
def allocate(devobj, instance):
    if devobj.status == 'claimed' and devobj.instance_uuid != instance['uuid']:
        raise exception.PciDeviceInvalidOwner(
            compute_node_id=devobj.compute_node_id,
            address=devobj.address, owner=devobj.instance_uuid,
            hopeowner=instance['uuid'])

    devobj.status = 'allocated'
    devobj.instance_uuid = instance['uuid']

    # Notes(yjiang5): remove this check when instance object for
    # compute manager is finished
    if isinstance(instance, dict):
        if 'pci_devices' not in instance:
            instance['pci_devices'] = []
        instance['pci_devices'].append(copy.copy(devobj))
    else:
        instance.pci_devices.objects.append(copy.copy(devobj))


@check_device_status(dev_status=['available'])
def remove(devobj):
    devobj.status = 'removed'
    devobj.instance_uuid = None
    devobj.request_id = None


@check_device_status(dev_status=['claimed', 'allocated'])
def free(devobj, instance=None):
    if instance and devobj.instance_uuid != instance['uuid']:
        raise exception.PciDeviceInvalidOwner(
            compute_node_id=devobj.compute_node_id,
            address=devobj.address, owner=devobj.instance_uuid,
            hopeowner=instance['uuid'])
    old_status = devobj.status
    devobj.status = 'available'
    devobj.instance_uuid = None
    devobj.request_id = None
    if old_status == 'allocated' and instance:
        # Notes(yjiang5): remove this check when instance object for
        # compute manager is finished
        existed = next((dev for dev in instance['pci_devices']
            if dev.id == devobj.id))
        if isinstance(instance, dict):
            instance['pci_devices'].remove(existed)
        else:
            instance.pci_devices.objects.remove(existed)


def update_device(devobj, dev_dict):
    """Sync the content from device dictionary to device object.

    The resource tracker updates the available devices periodically.
    To avoid meaningless syncs with the database, we update the device
    object only if a value changed.
    """

    # Note(yjiang5): status/instance_uuid should only be updated by
    # functions like claim/allocate etc. The id is allocated by
    # database. The extra_info is created by the object.
    no_changes = ('status', 'instance_uuid', 'id', 'extra_info')
    map(lambda x: dev_dict.pop(x, None),
        [key for key in no_changes])

    for k, v in dev_dict.items():
        if k in devobj.fields.keys():
            devobj[k] = v
        else:
            # Note (yjiang5) extra_info.update does not update
            # obj_what_changed, set it explicitely
            extra_info = devobj.extra_info
            extra_info.update({k: v})
            devobj.extra_info = extra_info
