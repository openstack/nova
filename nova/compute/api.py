# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012-2013 Red Hat, Inc.
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

"""Handles all requests relating to compute resources (e.g. guest VMs,
networking and storage of VMs, and compute hosts on which they run)."""

import base64
import collections
import copy
import functools
import re
import string

from oslo_log import log as logging
from oslo_messaging import exceptions as oslo_exceptions
from oslo_serialization import base64 as base64utils
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
from oslo_utils import uuidutils
import six
from six.moves import range

from nova import availability_zones
from nova import block_device
from nova.cells import opts as cells_opts
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
import nova.conf
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context as nova_context
from nova import crypto
from nova.db import base
from nova import exception
from nova import exception_wrapper
from nova import hooks
from nova.i18n import _
from nova import image
from nova import keymgr
from nova import network
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova.network.security_group import security_group_base
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import fields as fields_obj
from nova.objects import keypair as keypair_obj
from nova.objects import quotas as quotas_obj
from nova.pci import request as pci_request
from nova.policies import servers as servers_policies
import nova.policy
from nova import profiler
from nova import rpc
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import servicegroup
from nova import utils
from nova.virt import hardware
from nova.volume import cinder

LOG = logging.getLogger(__name__)

get_notifier = functools.partial(rpc.get_notifier, service='compute')
# NOTE(gibi): legacy notification used compute as a service but these
# calls still run on the client side of the compute service which is
# nova-api. By setting the binary to nova-api below, we can make sure
# that the new versioned notifications has the right publisher_id but the
# legacy notifications does not change.
wrap_exception = functools.partial(exception_wrapper.wrap_exception,
                                   get_notifier=get_notifier,
                                   binary='nova-api')
CONF = nova.conf.CONF

MAX_USERDATA_SIZE = 65535
RO_SECURITY_GROUPS = ['default']

AGGREGATE_ACTION_UPDATE = 'Update'
AGGREGATE_ACTION_UPDATE_META = 'UpdateMeta'
AGGREGATE_ACTION_DELETE = 'Delete'
AGGREGATE_ACTION_ADD = 'Add'
BFV_RESERVE_MIN_COMPUTE_VERSION = 17

# FIXME(danms): Keep a global cache of the cells we find the
# first time we look. This needs to be refreshed on a timer or
# trigger.
CELLS = []


def check_instance_state(vm_state=None, task_state=(None,),
                         must_have_launched=True):
    """Decorator to check VM and/or task state before entry to API functions.

    If the instance is in the wrong state, or has not been successfully
    started at least once the wrapper will raise an exception.
    """

    if vm_state is not None and not isinstance(vm_state, set):
        vm_state = set(vm_state)
    if task_state is not None and not isinstance(task_state, set):
        task_state = set(task_state)

    def outer(f):
        @six.wraps(f)
        def inner(self, context, instance, *args, **kw):
            if vm_state is not None and instance.vm_state not in vm_state:
                raise exception.InstanceInvalidState(
                    attr='vm_state',
                    instance_uuid=instance.uuid,
                    state=instance.vm_state,
                    method=f.__name__)
            if (task_state is not None and
                    instance.task_state not in task_state):
                raise exception.InstanceInvalidState(
                    attr='task_state',
                    instance_uuid=instance.uuid,
                    state=instance.task_state,
                    method=f.__name__)
            if must_have_launched and not instance.launched_at:
                raise exception.InstanceInvalidState(
                    attr='launched_at',
                    instance_uuid=instance.uuid,
                    state=instance.launched_at,
                    method=f.__name__)

            return f(self, context, instance, *args, **kw)
        return inner
    return outer


def _set_or_none(q):
    return q if q is None or isinstance(q, set) else set(q)


def reject_instance_state(vm_state=None, task_state=None):
    """Decorator.  Raise InstanceInvalidState if instance is in any of the
    given states.
    """

    vm_state = _set_or_none(vm_state)
    task_state = _set_or_none(task_state)

    def outer(f):
        @six.wraps(f)
        def inner(self, context, instance, *args, **kw):
            _InstanceInvalidState = functools.partial(
                exception.InstanceInvalidState,
                instance_uuid=instance.uuid,
                method=f.__name__)

            if vm_state is not None and instance.vm_state in vm_state:
                raise _InstanceInvalidState(
                    attr='vm_state', state=instance.vm_state)

            if task_state is not None and instance.task_state in task_state:
                raise _InstanceInvalidState(
                    attr='task_state', state=instance.task_state)

            return f(self, context, instance, *args, **kw)
        return inner
    return outer


def check_instance_host(function):
    @six.wraps(function)
    def wrapped(self, context, instance, *args, **kwargs):
        if not instance.host:
            raise exception.InstanceNotReady(instance_id=instance.uuid)
        return function(self, context, instance, *args, **kwargs)
    return wrapped


def check_instance_lock(function):
    @six.wraps(function)
    def inner(self, context, instance, *args, **kwargs):
        if instance.locked and not context.is_admin:
            raise exception.InstanceIsLocked(instance_uuid=instance.uuid)
        return function(self, context, instance, *args, **kwargs)
    return inner


def check_instance_cell(fn):
    @six.wraps(fn)
    def _wrapped(self, context, instance, *args, **kwargs):
        self._validate_cell(instance)
        return fn(self, context, instance, *args, **kwargs)
    return _wrapped


def _diff_dict(orig, new):
    """Return a dict describing how to change orig to new.  The keys
    correspond to values that have changed; the value will be a list
    of one or two elements.  The first element of the list will be
    either '+' or '-', indicating whether the key was updated or
    deleted; if the key was updated, the list will contain a second
    element, giving the updated value.
    """
    # Figure out what keys went away
    result = {k: ['-'] for k in set(orig.keys()) - set(new.keys())}
    # Compute the updates
    for key, value in new.items():
        if key not in orig or value != orig[key]:
            result[key] = ['+', value]
    return result


def load_cells():
    global CELLS
    if not CELLS:
        CELLS = objects.CellMappingList.get_all(
            nova_context.get_admin_context())
        LOG.debug('Found %(count)i cells: %(cells)s',
                  dict(count=len(CELLS),
                       cells=','.join([c.identity for c in CELLS])))

    if not CELLS:
        LOG.error('No cells are configured, unable to continue')


@profiler.trace_cls("compute_api")
class API(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, image_api=None, network_api=None, volume_api=None,
                 security_group_api=None, **kwargs):
        self.image_api = image_api or image.API()
        self.network_api = network_api or network.API()
        self.volume_api = volume_api or cinder.API()
        # NOTE(mriedem): This looks a bit weird but we get the reportclient
        # via SchedulerClient since it lazy-loads SchedulerReportClient on
        # the first usage which helps to avoid a bunch of lockutils spam in
        # the nova-api logs every time the service is restarted (remember
        # that pretty much all of the REST API controllers construct this
        # API class).
        self.placementclient = scheduler_client.SchedulerClient().reportclient
        self.security_group_api = (security_group_api or
            openstack_driver.get_openstack_security_group_driver())
        self.consoleauth_rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.compute_task_api = conductor.ComputeTaskAPI()
        self.servicegroup_api = servicegroup.API()
        self.notifier = rpc.get_notifier('compute', CONF.host)
        if CONF.ephemeral_storage_encryption.enabled:
            self.key_manager = keymgr.API()

        super(API, self).__init__(**kwargs)

    @property
    def cell_type(self):
        try:
            return getattr(self, '_cell_type')
        except AttributeError:
            self._cell_type = cells_opts.get_cell_type()
            return self._cell_type

    def _validate_cell(self, instance):
        if self.cell_type != 'api':
            return
        cell_name = instance.cell_name
        if not cell_name:
            raise exception.InstanceUnknownCell(
                    instance_uuid=instance.uuid)

    def _record_action_start(self, context, instance, action):
        objects.InstanceAction.action_start(context, instance.uuid,
                                            action, want_result=False)

    def _check_injected_file_quota(self, context, injected_files):
        """Enforce quota limits on injected files.

        Raises a QuotaError if any limit is exceeded.
        """
        if injected_files is None:
            return

        # Check number of files first
        try:
            objects.Quotas.limit_check(context,
                                       injected_files=len(injected_files))
        except exception.OverQuota:
            raise exception.OnsetFileLimitExceeded()

        # OK, now count path and content lengths; we're looking for
        # the max...
        max_path = 0
        max_content = 0
        for path, content in injected_files:
            max_path = max(max_path, len(path))
            max_content = max(max_content, len(content))

        try:
            objects.Quotas.limit_check(context,
                                       injected_file_path_bytes=max_path,
                                       injected_file_content_bytes=max_content)
        except exception.OverQuota as exc:
            # Favor path limit over content limit for reporting
            # purposes
            if 'injected_file_path_bytes' in exc.kwargs['overs']:
                raise exception.OnsetFilePathLimitExceeded()
            else:
                raise exception.OnsetFileContentLimitExceeded()

    def _check_metadata_properties_quota(self, context, metadata=None):
        """Enforce quota limits on metadata properties."""
        if not metadata:
            metadata = {}
        if not isinstance(metadata, dict):
            msg = (_("Metadata type should be dict."))
            raise exception.InvalidMetadata(reason=msg)
        num_metadata = len(metadata)
        try:
            objects.Quotas.limit_check(context, metadata_items=num_metadata)
        except exception.OverQuota as exc:
            quota_metadata = exc.kwargs['quotas']['metadata_items']
            raise exception.MetadataLimitExceeded(allowed=quota_metadata)

        # Because metadata is stored in the DB, we hard-code the size limits
        # In future, we may support more variable length strings, so we act
        #  as if this is quota-controlled for forwards compatibility.
        # Those are only used in V2 API, from V2.1 API, those checks are
        # validated at API layer schema validation.
        for k, v in metadata.items():
            try:
                utils.check_string_length(v)
                utils.check_string_length(k, min_length=1)
            except exception.InvalidInput as e:
                raise exception.InvalidMetadata(reason=e.format_message())

            if len(k) > 255:
                msg = _("Metadata property key greater than 255 characters")
                raise exception.InvalidMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property value greater than 255 characters")
                raise exception.InvalidMetadataSize(reason=msg)

    def _check_requested_secgroups(self, context, secgroups):
        """Check if the security group requested exists and belongs to
        the project.

        :param context: The nova request context.
        :type context: nova.context.RequestContext
        :param secgroups: list of requested security group names, or uuids in
            the case of Neutron.
        :type secgroups: list
        :returns: list of requested security group names unmodified if using
            nova-network. If using Neutron, the list returned is all uuids.
            Note that 'default' is a special case and will be unmodified if
            it's requested.
        """
        security_groups = []
        for secgroup in secgroups:
            # NOTE(sdague): default is handled special
            if secgroup == "default":
                security_groups.append(secgroup)
                continue
            secgroup_dict = self.security_group_api.get(context, secgroup)
            if not secgroup_dict:
                raise exception.SecurityGroupNotFoundForProject(
                    project_id=context.project_id, security_group_id=secgroup)

            # Check to see if it's a nova-network or neutron type.
            if isinstance(secgroup_dict['id'], int):
                # This is nova-network so just return the requested name.
                security_groups.append(secgroup)
            else:
                # The id for neutron is a uuid, so we return the id (uuid).
                security_groups.append(secgroup_dict['id'])

        return security_groups

    def _check_requested_networks(self, context, requested_networks,
                                  max_count):
        """Check if the networks requested belongs to the project
        and the fixed IP address for each network provided is within
        same the network block
        """
        if requested_networks is not None:
            if requested_networks.no_allocate:
                # If the network request was specifically 'none' meaning don't
                # allocate any networks, we just return the number of requested
                # instances since quotas don't change at all.
                return max_count

            # NOTE(danms): Temporary transition
            requested_networks = requested_networks.as_tuples()

        return self.network_api.validate_networks(context, requested_networks,
                                                  max_count)

    def _handle_kernel_and_ramdisk(self, context, kernel_id, ramdisk_id,
                                   image):
        """Choose kernel and ramdisk appropriate for the instance.

        The kernel and ramdisk can be chosen in one of three ways:

            1. Passed in with create-instance request.

            2. Inherited from image.

            3. Forced to None by using `null_kernel` FLAG.
        """
        # Inherit from image if not specified
        image_properties = image.get('properties', {})

        if kernel_id is None:
            kernel_id = image_properties.get('kernel_id')

        if ramdisk_id is None:
            ramdisk_id = image_properties.get('ramdisk_id')

        # Force to None if using null_kernel
        if kernel_id == str(CONF.null_kernel):
            kernel_id = None
            ramdisk_id = None

        # Verify kernel and ramdisk exist (fail-fast)
        if kernel_id is not None:
            kernel_image = self.image_api.get(context, kernel_id)
            # kernel_id could have been a URI, not a UUID, so to keep behaviour
            # from before, which leaked that implementation detail out to the
            # caller, we return the image UUID of the kernel image and ramdisk
            # image (below) and not any image URIs that might have been
            # supplied.
            # TODO(jaypipes): Get rid of this silliness once we move to a real
            # Image object and hide all of that stuff within nova.image.api.
            kernel_id = kernel_image['id']

        if ramdisk_id is not None:
            ramdisk_image = self.image_api.get(context, ramdisk_id)
            ramdisk_id = ramdisk_image['id']

        return kernel_id, ramdisk_id

    @staticmethod
    def parse_availability_zone(context, availability_zone):
        # NOTE(vish): We have a legacy hack to allow admins to specify hosts
        #             via az using az:host:node. It might be nice to expose an
        #             api to specify specific hosts to force onto, but for
        #             now it just supports this legacy hack.
        # NOTE(deva): It is also possible to specify az::node, in which case
        #             the host manager will determine the correct host.
        forced_host = None
        forced_node = None
        if availability_zone and ':' in availability_zone:
            c = availability_zone.count(':')
            if c == 1:
                availability_zone, forced_host = availability_zone.split(':')
            elif c == 2:
                if '::' in availability_zone:
                    availability_zone, forced_node = \
                            availability_zone.split('::')
                else:
                    availability_zone, forced_host, forced_node = \
                            availability_zone.split(':')
            else:
                raise exception.InvalidInput(
                        reason="Unable to parse availability_zone")

        if not availability_zone:
            availability_zone = CONF.default_schedule_zone

        return availability_zone, forced_host, forced_node

    def _ensure_auto_disk_config_is_valid(self, auto_disk_config_img,
                                          auto_disk_config, image):
        auto_disk_config_disabled = \
                utils.is_auto_disk_config_disabled(auto_disk_config_img)
        if auto_disk_config_disabled and auto_disk_config:
            raise exception.AutoDiskConfigDisabledByImage(image=image)

    def _inherit_properties_from_image(self, image, auto_disk_config):
        image_properties = image.get('properties', {})
        auto_disk_config_img = \
                utils.get_auto_disk_config_from_image_props(image_properties)
        self._ensure_auto_disk_config_is_valid(auto_disk_config_img,
                                               auto_disk_config,
                                               image.get("id"))
        if auto_disk_config is None:
            auto_disk_config = strutils.bool_from_string(auto_disk_config_img)

        return {
            'os_type': image_properties.get('os_type'),
            'architecture': image_properties.get('architecture'),
            'vm_mode': image_properties.get('vm_mode'),
            'auto_disk_config': auto_disk_config
        }

    def _new_instance_name_from_template(self, uuid, display_name, index):
        params = {
            'uuid': uuid,
            'name': display_name,
            'count': index + 1,
        }
        try:
            new_name = (CONF.multi_instance_display_name_template %
                        params)
        except (KeyError, TypeError):
            LOG.exception('Failed to set instance name using '
                          'multi_instance_display_name_template.')
            new_name = display_name
        return new_name

    def _apply_instance_name_template(self, context, instance, index):
        original_name = instance.display_name
        new_name = self._new_instance_name_from_template(instance.uuid,
                instance.display_name, index)
        instance.display_name = new_name
        if not instance.get('hostname', None):
            if utils.sanitize_hostname(original_name) == "":
                instance.hostname = self._default_host_name(instance.uuid)
            else:
                instance.hostname = utils.sanitize_hostname(new_name)
        return instance

    def _check_config_drive(self, config_drive):
        if config_drive:
            try:
                bool_val = strutils.bool_from_string(config_drive,
                                                     strict=True)
            except ValueError:
                raise exception.ConfigDriveInvalidValue(option=config_drive)
        else:
            bool_val = False
        # FIXME(comstud):  Bug ID 1193438 filed for this. This looks silly,
        # but this is because the config drive column is a String.  False
        # is represented by using an empty string.  And for whatever
        # reason, we rely on the DB to cast True to a String.
        return True if bool_val else ''

    def _check_requested_image(self, context, image_id, image,
                               instance_type, root_bdm):
        if not image:
            return

        if image['status'] != 'active':
            raise exception.ImageNotActive(image_id=image_id)

        image_properties = image.get('properties', {})
        config_drive_option = image_properties.get(
            'img_config_drive', 'optional')
        if config_drive_option not in ['optional', 'mandatory']:
            raise exception.InvalidImageConfigDrive(
                config_drive=config_drive_option)

        if instance_type['memory_mb'] < int(image.get('min_ram') or 0):
            raise exception.FlavorMemoryTooSmall()

        # Image min_disk is in gb, size is in bytes. For sanity, have them both
        # in bytes.
        image_min_disk = int(image.get('min_disk') or 0) * units.Gi
        image_size = int(image.get('size') or 0)

        # Target disk is a volume. Don't check flavor disk size because it
        # doesn't make sense, and check min_disk against the volume size.
        if (root_bdm is not None and root_bdm.is_volume):
            # There are 2 possibilities here: either the target volume already
            # exists, or it doesn't, in which case the bdm will contain the
            # intended volume size.
            #
            # Cinder does its own check against min_disk, so if the target
            # volume already exists this has already been done and we don't
            # need to check it again here. In this case, volume_size may not be
            # set on the bdm.
            #
            # If we're going to create the volume, the bdm will contain
            # volume_size. Therefore we should check it if it exists. This will
            # still be checked again by cinder when the volume is created, but
            # that will not happen until the request reaches a host. By
            # checking it here, the user gets an immediate and useful failure
            # indication.
            #
            # The third possibility is that we have failed to consider
            # something, and there are actually more than 2 possibilities. In
            # this case cinder will still do the check at volume creation time.
            # The behaviour will still be correct, but the user will not get an
            # immediate failure from the api, and will instead have to
            # determine why the instance is in an error state with a task of
            # block_device_mapping.
            #
            # We could reasonably refactor this check into _validate_bdm at
            # some future date, as the various size logic is already split out
            # in there.
            dest_size = root_bdm.volume_size
            if dest_size is not None:
                dest_size *= units.Gi

                if image_min_disk > dest_size:
                    raise exception.VolumeSmallerThanMinDisk(
                        volume_size=dest_size, image_min_disk=image_min_disk)

        # Target disk is a local disk whose size is taken from the flavor
        else:
            dest_size = instance_type['root_gb'] * units.Gi

            # NOTE(johannes): root_gb is allowed to be 0 for legacy reasons
            # since libvirt interpreted the value differently than other
            # drivers. A value of 0 means don't check size.
            if dest_size != 0:
                if image_size > dest_size:
                    raise exception.FlavorDiskSmallerThanImage(
                        flavor_size=dest_size, image_size=image_size)

                if image_min_disk > dest_size:
                    raise exception.FlavorDiskSmallerThanMinDisk(
                        flavor_size=dest_size, image_min_disk=image_min_disk)
            else:
                # The user is attempting to create a server with a 0-disk
                # image-backed flavor, which can lead to issues with a large
                # image consuming an unexpectedly large amount of local disk
                # on the compute host. Check to see if the deployment will
                # allow that.
                if not context.can(
                        servers_policies.ZERO_DISK_FLAVOR, fatal=False):
                    raise exception.BootFromVolumeRequiredForZeroDiskFlavor()

    def _get_image_defined_bdms(self, instance_type, image_meta,
                                root_device_name):
        image_properties = image_meta.get('properties', {})

        # Get the block device mappings defined by the image.
        image_defined_bdms = image_properties.get('block_device_mapping', [])
        legacy_image_defined = not image_properties.get('bdm_v2', False)

        image_mapping = image_properties.get('mappings', [])

        if legacy_image_defined:
            image_defined_bdms = block_device.from_legacy_mapping(
                image_defined_bdms, None, root_device_name)
        else:
            image_defined_bdms = list(map(block_device.BlockDeviceDict,
                                          image_defined_bdms))

        if image_mapping:
            image_mapping = self._prepare_image_mapping(instance_type,
                                                        image_mapping)
            image_defined_bdms = self._merge_bdms_lists(
                image_mapping, image_defined_bdms)

        return image_defined_bdms

    def _get_flavor_defined_bdms(self, instance_type, block_device_mapping):
        flavor_defined_bdms = []

        have_ephemeral_bdms = any(filter(
            block_device.new_format_is_ephemeral, block_device_mapping))
        have_swap_bdms = any(filter(
            block_device.new_format_is_swap, block_device_mapping))

        if instance_type.get('ephemeral_gb') and not have_ephemeral_bdms:
            flavor_defined_bdms.append(
                block_device.create_blank_bdm(instance_type['ephemeral_gb']))
        if instance_type.get('swap') and not have_swap_bdms:
            flavor_defined_bdms.append(
                block_device.create_blank_bdm(instance_type['swap'], 'swap'))

        return flavor_defined_bdms

    def _merge_bdms_lists(self, overridable_mappings, overrider_mappings):
        """Override any block devices from the first list by device name

        :param overridable_mappings: list which items are overridden
        :param overrider_mappings: list which items override

        :returns: A merged list of bdms
        """
        device_names = set(bdm['device_name'] for bdm in overrider_mappings
                           if bdm['device_name'])
        return (overrider_mappings +
                [bdm for bdm in overridable_mappings
                 if bdm['device_name'] not in device_names])

    def _check_and_transform_bdm(self, context, base_options, instance_type,
                                 image_meta, min_count, max_count,
                                 block_device_mapping, legacy_bdm):
        # NOTE (ndipanov): Assume root dev name is 'vda' if not supplied.
        #                  It's needed for legacy conversion to work.
        root_device_name = (base_options.get('root_device_name') or 'vda')
        image_ref = base_options.get('image_ref', '')
        # If the instance is booted by image and has a volume attached,
        # the volume cannot have the same device name as root_device_name
        if image_ref:
            for bdm in block_device_mapping:
                if (bdm.get('destination_type') == 'volume' and
                    block_device.strip_dev(bdm.get(
                    'device_name')) == root_device_name):
                    msg = _('The volume cannot be assigned the same device'
                            ' name as the root device %s') % root_device_name
                    raise exception.InvalidRequest(msg)

        image_defined_bdms = self._get_image_defined_bdms(
            instance_type, image_meta, root_device_name)
        root_in_image_bdms = (
            block_device.get_root_bdm(image_defined_bdms) is not None)

        if legacy_bdm:
            block_device_mapping = block_device.from_legacy_mapping(
                block_device_mapping, image_ref, root_device_name,
                no_root=root_in_image_bdms)
        elif root_in_image_bdms:
            # NOTE (ndipanov): client will insert an image mapping into the v2
            # block_device_mapping, but if there is a bootable device in image
            # mappings - we need to get rid of the inserted image
            # NOTE (gibi): another case is when a server is booted with an
            # image to bdm mapping where the image only contains a bdm to a
            # snapshot. In this case the other image to bdm mapping
            # contains an unnecessary device with boot_index == 0.
            # Also in this case the image_ref is None as we are booting from
            # an image to volume bdm.
            def not_image_and_root_bdm(bdm):
                return not (bdm.get('boot_index') == 0 and
                            bdm.get('source_type') == 'image')

            block_device_mapping = list(
                filter(not_image_and_root_bdm, block_device_mapping))

        block_device_mapping = self._merge_bdms_lists(
            image_defined_bdms, block_device_mapping)

        if min_count > 1 or max_count > 1:
            if any(map(lambda bdm: bdm['source_type'] == 'volume',
                       block_device_mapping)):
                msg = _('Cannot attach one or more volumes to multiple'
                        ' instances')
                raise exception.InvalidRequest(msg)

        block_device_mapping += self._get_flavor_defined_bdms(
            instance_type, block_device_mapping)

        return block_device_obj.block_device_make_list_from_dicts(
                context, block_device_mapping)

    def _get_image(self, context, image_href):
        if not image_href:
            return None, {}

        image = self.image_api.get(context, image_href)
        return image['id'], image

    def _checks_for_create_and_rebuild(self, context, image_id, image,
                                       instance_type, metadata,
                                       files_to_inject, root_bdm):
        self._check_metadata_properties_quota(context, metadata)
        self._check_injected_file_quota(context, files_to_inject)
        self._check_requested_image(context, image_id, image,
                                    instance_type, root_bdm)

    def _validate_and_build_base_options(self, context, instance_type,
                                         boot_meta, image_href, image_id,
                                         kernel_id, ramdisk_id, display_name,
                                         display_description, key_name,
                                         key_data, security_groups,
                                         availability_zone, user_data,
                                         metadata, access_ip_v4, access_ip_v6,
                                         requested_networks, config_drive,
                                         auto_disk_config, reservation_id,
                                         max_count):
        """Verify all the input parameters regardless of the provisioning
        strategy being performed.
        """
        if instance_type['disabled']:
            raise exception.FlavorNotFound(flavor_id=instance_type['id'])

        if user_data:
            l = len(user_data)
            if l > MAX_USERDATA_SIZE:
                # NOTE(mikal): user_data is stored in a text column, and
                # the database might silently truncate if its over length.
                raise exception.InstanceUserDataTooLarge(
                    length=l, maxsize=MAX_USERDATA_SIZE)

            try:
                base64utils.decode_as_bytes(user_data)
            except (base64.binascii.Error, TypeError):
                # TODO(harlowja): reduce the above exceptions caught to
                # only type error once we get a new oslo.serialization
                # release that captures and makes only one be output.
                #
                # We can eliminate the capture of `binascii.Error` when:
                #
                # https://review.openstack.org/#/c/418066/ is released.
                raise exception.InstanceUserDataMalformed()

        # When using Neutron, _check_requested_secgroups will translate and
        # return any requested security group names to uuids.
        security_groups = (
            self._check_requested_secgroups(context, security_groups))

        # Note:  max_count is the number of instances requested by the user,
        # max_network_count is the maximum number of instances taking into
        # account any network quotas
        max_network_count = self._check_requested_networks(context,
                                     requested_networks, max_count)

        kernel_id, ramdisk_id = self._handle_kernel_and_ramdisk(
                context, kernel_id, ramdisk_id, boot_meta)

        config_drive = self._check_config_drive(config_drive)

        if key_data is None and key_name is not None:
            key_pair = objects.KeyPair.get_by_name(context,
                                                   context.user_id,
                                                   key_name)
            key_data = key_pair.public_key
        else:
            key_pair = None

        root_device_name = block_device.prepend_dev(
                block_device.properties_root_device_name(
                    boot_meta.get('properties', {})))

        try:
            image_meta = objects.ImageMeta.from_dict(boot_meta)
        except ValueError as e:
            # there must be invalid values in the image meta properties so
            # consider this an invalid request
            msg = _('Invalid image metadata. Error: %s') % six.text_type(e)
            raise exception.InvalidRequest(msg)
        numa_topology = hardware.numa_get_constraints(
                instance_type, image_meta)

        system_metadata = {}

        # PCI requests come from two sources: instance flavor and
        # requested_networks. The first call in below returns an
        # InstancePCIRequests object which is a list of InstancePCIRequest
        # objects. The second call in below creates an InstancePCIRequest
        # object for each SR-IOV port, and append it to the list in the
        # InstancePCIRequests object
        pci_request_info = pci_request.get_pci_requests_from_flavor(
            instance_type)
        self.network_api.create_pci_requests_for_sriov_ports(context,
            pci_request_info, requested_networks)

        base_options = {
            'reservation_id': reservation_id,
            'image_ref': image_href,
            'kernel_id': kernel_id or '',
            'ramdisk_id': ramdisk_id or '',
            'power_state': power_state.NOSTATE,
            'vm_state': vm_states.BUILDING,
            'config_drive': config_drive,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'instance_type_id': instance_type['id'],
            'memory_mb': instance_type['memory_mb'],
            'vcpus': instance_type['vcpus'],
            'root_gb': instance_type['root_gb'],
            'ephemeral_gb': instance_type['ephemeral_gb'],
            'display_name': display_name,
            'display_description': display_description,
            'user_data': user_data,
            'key_name': key_name,
            'key_data': key_data,
            'locked': False,
            'metadata': metadata or {},
            'access_ip_v4': access_ip_v4,
            'access_ip_v6': access_ip_v6,
            'availability_zone': availability_zone,
            'root_device_name': root_device_name,
            'progress': 0,
            'pci_requests': pci_request_info,
            'numa_topology': numa_topology,
            'system_metadata': system_metadata}

        options_from_image = self._inherit_properties_from_image(
                boot_meta, auto_disk_config)

        base_options.update(options_from_image)

        # return the validated options and maximum number of instances allowed
        # by the network quotas
        return base_options, max_network_count, key_pair, security_groups

    def _provision_instances(self, context, instance_type, min_count,
            max_count, base_options, boot_meta, security_groups,
            block_device_mapping, shutdown_terminate,
            instance_group, check_server_group_quota, filter_properties,
            key_pair, tags):
        # Check quotas
        num_instances = compute_utils.check_num_instances_quota(
                context, instance_type, min_count, max_count)
        security_groups = self.security_group_api.populate_security_groups(
                security_groups)
        self.security_group_api.ensure_default(context)
        LOG.debug("Going to run %s instances...", num_instances)
        instances_to_build = []
        try:
            for i in range(num_instances):
                # Create a uuid for the instance so we can store the
                # RequestSpec before the instance is created.
                instance_uuid = uuidutils.generate_uuid()
                # Store the RequestSpec that will be used for scheduling.
                req_spec = objects.RequestSpec.from_components(context,
                        instance_uuid, boot_meta, instance_type,
                        base_options['numa_topology'],
                        base_options['pci_requests'], filter_properties,
                        instance_group, base_options['availability_zone'],
                        security_groups=security_groups)
                # NOTE(danms): We need to record num_instances on the request
                # spec as this is how the conductor knows how many were in this
                # batch.
                req_spec.num_instances = num_instances
                req_spec.create()

                # Create an instance object, but do not store in db yet.
                instance = objects.Instance(context=context)
                instance.uuid = instance_uuid
                instance.update(base_options)
                instance.keypairs = objects.KeyPairList(objects=[])
                if key_pair:
                    instance.keypairs.objects.append(key_pair)
                instance = self.create_db_entry_for_new_instance(context,
                        instance_type, boot_meta, instance, security_groups,
                        block_device_mapping, num_instances, i,
                        shutdown_terminate, create_instance=False)
                block_device_mapping = (
                    self._bdm_validate_set_size_and_instance(context,
                        instance, instance_type, block_device_mapping))
                instance_tags = self._transform_tags(tags, instance.uuid)

                build_request = objects.BuildRequest(context,
                        instance=instance, instance_uuid=instance.uuid,
                        project_id=instance.project_id,
                        block_device_mappings=block_device_mapping,
                        tags=instance_tags)
                build_request.create()

                # Create an instance_mapping.  The null cell_mapping indicates
                # that the instance doesn't yet exist in a cell, and lookups
                # for it need to instead look for the RequestSpec.
                # cell_mapping will be populated after scheduling, with a
                # scheduling failure using the cell_mapping for the special
                # cell0.
                inst_mapping = objects.InstanceMapping(context=context)
                inst_mapping.instance_uuid = instance_uuid
                inst_mapping.project_id = context.project_id
                inst_mapping.cell_mapping = None
                inst_mapping.create()

                instances_to_build.append(
                    (req_spec, build_request, inst_mapping))

                if instance_group:
                    if check_server_group_quota:
                        try:
                            objects.Quotas.check_deltas(
                                context, {'server_group_members': 1},
                                instance_group, context.user_id)
                        except exception.OverQuota:
                            msg = _("Quota exceeded, too many servers in "
                                    "group")
                            raise exception.QuotaError(msg)

                    members = objects.InstanceGroup.add_members(
                        context, instance_group.uuid, [instance.uuid])

                    # NOTE(melwitt): We recheck the quota after creating the
                    # object to prevent users from allocating more resources
                    # than their allowed quota in the event of a race. This is
                    # configurable because it can be expensive if strict quota
                    # limits are not required in a deployment.
                    if CONF.quota.recheck_quota and check_server_group_quota:
                        try:
                            objects.Quotas.check_deltas(
                                context, {'server_group_members': 0},
                                instance_group, context.user_id)
                        except exception.OverQuota:
                            objects.InstanceGroup._remove_members_in_db(
                                context, instance_group.id, [instance.uuid])
                            msg = _("Quota exceeded, too many servers in "
                                    "group")
                            raise exception.QuotaError(msg)
                    # list of members added to servers group in this iteration
                    # is needed to check quota of server group during add next
                    # instance
                    instance_group.members.extend(members)

        # In the case of any exceptions, attempt DB cleanup
        except Exception:
            with excutils.save_and_reraise_exception():
                self._cleanup_build_artifacts(None, instances_to_build)

        return instances_to_build

    def _get_bdm_image_metadata(self, context, block_device_mapping,
                                legacy_bdm=True):
        """If we are booting from a volume, we need to get the
        volume details from Cinder and make sure we pass the
        metadata back accordingly.
        """
        if not block_device_mapping:
            return {}

        for bdm in block_device_mapping:
            if (legacy_bdm and
                    block_device.get_device_letter(
                       bdm.get('device_name', '')) != 'a'):
                continue
            elif not legacy_bdm and bdm.get('boot_index') != 0:
                continue

            volume_id = bdm.get('volume_id')
            snapshot_id = bdm.get('snapshot_id')
            if snapshot_id:
                # NOTE(alaski): A volume snapshot inherits metadata from the
                # originating volume, but the API does not expose metadata
                # on the snapshot itself.  So we query the volume for it below.
                snapshot = self.volume_api.get_snapshot(context, snapshot_id)
                volume_id = snapshot['volume_id']

            if bdm.get('image_id'):
                try:
                    image_id = bdm['image_id']
                    image_meta = self.image_api.get(context, image_id)
                    return image_meta
                except Exception:
                    raise exception.InvalidBDMImage(id=image_id)
            elif volume_id:
                try:
                    volume = self.volume_api.get(context, volume_id)
                except exception.CinderConnectionFailed:
                    raise
                except Exception:
                    raise exception.InvalidBDMVolume(id=volume_id)

                if not volume.get('bootable', True):
                    raise exception.InvalidBDMVolumeNotBootable(id=volume_id)

                return utils.get_image_metadata_from_volume(volume)
        return {}

    @staticmethod
    def _get_requested_instance_group(context, filter_properties):
        if (not filter_properties or
                not filter_properties.get('scheduler_hints')):
            return

        group_hint = filter_properties.get('scheduler_hints').get('group')
        if not group_hint:
            return

        return objects.InstanceGroup.get_by_uuid(context, group_hint)

    def _create_instance(self, context, instance_type,
               image_href, kernel_id, ramdisk_id,
               min_count, max_count,
               display_name, display_description,
               key_name, key_data, security_groups,
               availability_zone, user_data, metadata, injected_files,
               admin_password, access_ip_v4, access_ip_v6,
               requested_networks, config_drive,
               block_device_mapping, auto_disk_config, filter_properties,
               reservation_id=None, legacy_bdm=True, shutdown_terminate=False,
               check_server_group_quota=False, tags=None):
        """Verify all the input parameters regardless of the provisioning
        strategy being performed and schedule the instance(s) for
        creation.
        """

        # Normalize and setup some parameters
        if reservation_id is None:
            reservation_id = utils.generate_uid('r')
        security_groups = security_groups or ['default']
        min_count = min_count or 1
        max_count = max_count or min_count
        block_device_mapping = block_device_mapping or []
        tags = tags or []

        if image_href:
            image_id, boot_meta = self._get_image(context, image_href)
        else:
            image_id = None
            boot_meta = self._get_bdm_image_metadata(
                context, block_device_mapping, legacy_bdm)

        self._check_auto_disk_config(image=boot_meta,
                                     auto_disk_config=auto_disk_config)

        base_options, max_net_count, key_pair, security_groups = \
                self._validate_and_build_base_options(
                    context, instance_type, boot_meta, image_href, image_id,
                    kernel_id, ramdisk_id, display_name, display_description,
                    key_name, key_data, security_groups, availability_zone,
                    user_data, metadata, access_ip_v4, access_ip_v6,
                    requested_networks, config_drive, auto_disk_config,
                    reservation_id, max_count)

        # max_net_count is the maximum number of instances requested by the
        # user adjusted for any network quota constraints, including
        # consideration of connections to each requested network
        if max_net_count < min_count:
            raise exception.PortLimitExceeded()
        elif max_net_count < max_count:
            LOG.info("max count reduced from %(max_count)d to "
                     "%(max_net_count)d due to network port quota",
                     {'max_count': max_count,
                      'max_net_count': max_net_count})
            max_count = max_net_count

        block_device_mapping = self._check_and_transform_bdm(context,
            base_options, instance_type, boot_meta, min_count, max_count,
            block_device_mapping, legacy_bdm)

        # We can't do this check earlier because we need bdms from all sources
        # to have been merged in order to get the root bdm.
        self._checks_for_create_and_rebuild(context, image_id, boot_meta,
                instance_type, metadata, injected_files,
                block_device_mapping.root_bdm())

        instance_group = self._get_requested_instance_group(context,
                                   filter_properties)

        tags = self._create_tag_list_obj(context, tags)

        instances_to_build = self._provision_instances(
            context, instance_type, min_count, max_count, base_options,
            boot_meta, security_groups, block_device_mapping,
            shutdown_terminate, instance_group, check_server_group_quota,
            filter_properties, key_pair, tags)

        instances = []
        request_specs = []
        build_requests = []
        for rs, build_request, im in instances_to_build:
            build_requests.append(build_request)
            instance = build_request.get_new_instance(context)
            instances.append(instance)
            request_specs.append(rs)

        if CONF.cells.enable:
            # NOTE(danms): CellsV1 can't do the new thing, so we
            # do the old thing here. We can remove this path once
            # we stop supporting v1.
            for instance in instances:
                instance.create()
            # NOTE(melwitt): We recheck the quota after creating the objects
            # to prevent users from allocating more resources than their
            # allowed quota in the event of a race. This is configurable
            # because it can be expensive if strict quota limits are not
            # required in a deployment.
            if CONF.quota.recheck_quota:
                try:
                    compute_utils.check_num_instances_quota(
                        context, instance_type, 0, 0,
                        orig_num_req=len(instances))
                except exception.TooManyInstances:
                    with excutils.save_and_reraise_exception():
                        # Need to clean up all the instances we created
                        # along with the build requests, request specs,
                        # and instance mappings.
                        self._cleanup_build_artifacts(instances,
                                                      instances_to_build)

            self.compute_task_api.build_instances(context,
                instances=instances, image=boot_meta,
                filter_properties=filter_properties,
                admin_password=admin_password,
                injected_files=injected_files,
                requested_networks=requested_networks,
                security_groups=security_groups,
                block_device_mapping=block_device_mapping,
                legacy_bdm=False)
        else:
            self.compute_task_api.schedule_and_build_instances(
                context,
                build_requests=build_requests,
                request_spec=request_specs,
                image=boot_meta,
                admin_password=admin_password,
                injected_files=injected_files,
                requested_networks=requested_networks,
                block_device_mapping=block_device_mapping,
                tags=tags)

        return (instances, reservation_id)

    @staticmethod
    def _cleanup_build_artifacts(instances, instances_to_build):
        # instances_to_build is a list of tuples:
        # (RequestSpec, BuildRequest, InstanceMapping)

        # Be paranoid about artifacts being deleted underneath us.
        for instance in instances or []:
            try:
                instance.destroy()
            except exception.InstanceNotFound:
                pass
        for rs, build_request, im in instances_to_build or []:
            try:
                rs.destroy()
            except exception.RequestSpecNotFound:
                pass
            try:
                build_request.destroy()
            except exception.BuildRequestNotFound:
                pass
            try:
                im.destroy()
            except exception.InstanceMappingNotFound:
                pass

    @staticmethod
    def _volume_size(instance_type, bdm):
        size = bdm.get('volume_size')
        # NOTE (ndipanov): inherit flavor size only for swap and ephemeral
        if (size is None and bdm.get('source_type') == 'blank' and
                bdm.get('destination_type') == 'local'):
            if bdm.get('guest_format') == 'swap':
                size = instance_type.get('swap', 0)
            else:
                size = instance_type.get('ephemeral_gb', 0)
        return size

    def _prepare_image_mapping(self, instance_type, mappings):
        """Extract and format blank devices from image mappings."""

        prepared_mappings = []

        for bdm in block_device.mappings_prepend_dev(mappings):
            LOG.debug("Image bdm %s", bdm)

            virtual_name = bdm['virtual']
            if virtual_name == 'ami' or virtual_name == 'root':
                continue

            if not block_device.is_swap_or_ephemeral(virtual_name):
                continue

            guest_format = bdm.get('guest_format')
            if virtual_name == 'swap':
                guest_format = 'swap'
            if not guest_format:
                guest_format = CONF.default_ephemeral_format

            values = block_device.BlockDeviceDict({
                'device_name': bdm['device'],
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': guest_format,
                'delete_on_termination': True,
                'boot_index': -1})

            values['volume_size'] = self._volume_size(
                instance_type, values)
            if values['volume_size'] == 0:
                continue

            prepared_mappings.append(values)

        return prepared_mappings

    def _bdm_validate_set_size_and_instance(self, context, instance,
                                            instance_type,
                                            block_device_mapping):
        """Ensure the bdms are valid, then set size and associate with instance

        Because this method can be called multiple times when more than one
        instance is booted in a single request it makes a copy of the bdm list.
        """
        LOG.debug("block_device_mapping %s", list(block_device_mapping),
                  instance_uuid=instance.uuid)
        self._validate_bdm(
            context, instance, instance_type, block_device_mapping)
        instance_block_device_mapping = block_device_mapping.obj_clone()
        for bdm in instance_block_device_mapping:
            bdm.volume_size = self._volume_size(instance_type, bdm)
            bdm.instance_uuid = instance.uuid
        return instance_block_device_mapping

    def _create_block_device_mapping(self, block_device_mapping):
        # Copy the block_device_mapping because this method can be called
        # multiple times when more than one instance is booted in a single
        # request. This avoids 'id' being set and triggering the object dupe
        # detection
        db_block_device_mapping = copy.deepcopy(block_device_mapping)
        # Create the BlockDeviceMapping objects in the db.
        for bdm in db_block_device_mapping:
            # TODO(alaski): Why is this done?
            if bdm.volume_size == 0:
                continue

            bdm.update_or_create()

    def _validate_bdm(self, context, instance, instance_type,
                      block_device_mappings):
        def _subsequent_list(l):
            # Each device which is capable of being used as boot device should
            # be given a unique boot index, starting from 0 in ascending order.
            return all(el + 1 == l[i + 1] for i, el in enumerate(l[:-1]))

        # Make sure that the boot indexes make sense.
        # Setting a negative value or None indicates that the device should not
        # be used for booting.
        boot_indexes = sorted([bdm.boot_index
                               for bdm in block_device_mappings
                               if bdm.boot_index is not None
                               and bdm.boot_index >= 0])

        if 0 not in boot_indexes or not _subsequent_list(boot_indexes):
            # Convert the BlockDeviceMappingList to a list for repr details.
            LOG.debug('Invalid block device mapping boot sequence for '
                      'instance: %s', list(block_device_mappings),
                      instance=instance)
            raise exception.InvalidBDMBootSequence()

        for bdm in block_device_mappings:
            # NOTE(vish): For now, just make sure the volumes are accessible.
            # Additionally, check that the volume can be attached to this
            # instance.
            snapshot_id = bdm.snapshot_id
            volume_id = bdm.volume_id
            image_id = bdm.image_id
            if (image_id is not None and
                    image_id != instance.get('image_ref')):
                try:
                    self._get_image(context, image_id)
                except Exception:
                    raise exception.InvalidBDMImage(id=image_id)
                if (bdm.source_type == 'image' and
                        bdm.destination_type == 'volume' and
                        not bdm.volume_size):
                    raise exception.InvalidBDM(message=_("Images with "
                        "destination_type 'volume' need to have a non-zero "
                        "size specified"))
            elif volume_id is not None:
                # The instance is being created and we don't know which
                # cell it's going to land in, so check all cells.
                min_compute_version = \
                    objects.service.get_minimum_version_all_cells(
                        context, ['nova-compute'])
                try:
                    # NOTE(ildikov): The boot from volume operation did not
                    # reserve the volume before Pike and as the older computes
                    # are running 'check_attach' which will fail if the volume
                    # is in 'attaching' state; if the compute service version
                    # is not high enough we will just perform the old check as
                    # opposed to reserving the volume here.
                    if (min_compute_version >=
                        BFV_RESERVE_MIN_COMPUTE_VERSION):
                        volume = self._check_attach_and_reserve_volume(
                            context, volume_id, instance)
                    else:
                        # NOTE(ildikov): This call is here only for backward
                        # compatibility can be removed after Ocata EOL.
                        volume = self._check_attach(context, volume_id,
                                                    instance)
                    bdm.volume_size = volume.get('size')

                    # NOTE(mnaser): If we end up reserving the volume, it will
                    #               not have an attachment_id which is needed
                    #               for cleanups.  This can be removed once
                    #               all calls to reserve_volume are gone.
                    if 'attachment_id' not in bdm:
                        bdm.attachment_id = None
                except (exception.CinderConnectionFailed,
                        exception.InvalidVolume):
                    raise
                except exception.InvalidInput as exc:
                    raise exception.InvalidVolume(reason=exc.format_message())
                except Exception:
                    raise exception.InvalidBDMVolume(id=volume_id)
            elif snapshot_id is not None:
                try:
                    snap = self.volume_api.get_snapshot(context, snapshot_id)
                    bdm.volume_size = bdm.volume_size or snap.get('size')
                except exception.CinderConnectionFailed:
                    raise
                except Exception:
                    raise exception.InvalidBDMSnapshot(id=snapshot_id)
            elif (bdm.source_type == 'blank' and
                    bdm.destination_type == 'volume' and
                    not bdm.volume_size):
                raise exception.InvalidBDM(message=_("Blank volumes "
                    "(source: 'blank', dest: 'volume') need to have non-zero "
                    "size"))

        ephemeral_size = sum(bdm.volume_size or instance_type['ephemeral_gb']
                for bdm in block_device_mappings
                if block_device.new_format_is_ephemeral(bdm))
        if ephemeral_size > instance_type['ephemeral_gb']:
            raise exception.InvalidBDMEphemeralSize()

        # There should be only one swap
        swap_list = block_device.get_bdm_swap_list(block_device_mappings)
        if len(swap_list) > 1:
            msg = _("More than one swap drive requested.")
            raise exception.InvalidBDMFormat(details=msg)

        if swap_list:
            swap_size = swap_list[0].volume_size or 0
            if swap_size > instance_type['swap']:
                raise exception.InvalidBDMSwapSize()

        max_local = CONF.max_local_block_devices
        if max_local >= 0:
            num_local = len([bdm for bdm in block_device_mappings
                             if bdm.destination_type == 'local'])
            if num_local > max_local:
                raise exception.InvalidBDMLocalsLimit()

    def _check_attach(self, context, volume_id, instance):
        # TODO(ildikov): This check_attach code is kept only for backward
        # compatibility and should be removed after Ocata EOL.
        volume = self.volume_api.get(context, volume_id)
        if volume['status'] != 'available':
            msg = _("volume '%(vol)s' status must be 'available'. Currently "
                    "in '%(status)s'") % {'vol': volume['id'],
                                          'status': volume['status']}
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == 'attached':
            msg = _("volume %s already attached") % volume['id']
            raise exception.InvalidVolume(reason=msg)
        self.volume_api.check_availability_zone(context, volume,
                                                instance=instance)

        return volume

    def _populate_instance_names(self, instance, num_instances):
        """Populate instance display_name and hostname."""
        display_name = instance.get('display_name')
        if instance.obj_attr_is_set('hostname'):
            hostname = instance.get('hostname')
        else:
            hostname = None

        # NOTE(mriedem): This is only here for test simplicity since a server
        # name is required in the REST API.
        if display_name is None:
            display_name = self._default_display_name(instance.uuid)
            instance.display_name = display_name

        if hostname is None and num_instances == 1:
            # NOTE(russellb) In the multi-instance case, we're going to
            # overwrite the display_name using the
            # multi_instance_display_name_template.  We need the default
            # display_name set so that it can be used in the template, though.
            # Only set the hostname here if we're only creating one instance.
            # Otherwise, it will be built after the template based
            # display_name.
            hostname = display_name
            default_hostname = self._default_host_name(instance.uuid)
            instance.hostname = utils.sanitize_hostname(hostname,
                                                        default_hostname)

    def _default_display_name(self, instance_uuid):
        return "Server %s" % instance_uuid

    def _default_host_name(self, instance_uuid):
        return "Server-%s" % instance_uuid

    def _populate_instance_for_create(self, context, instance, image,
                                      index, security_groups, instance_type,
                                      num_instances, shutdown_terminate):
        """Build the beginning of a new instance."""

        instance.launch_index = index
        instance.vm_state = vm_states.BUILDING
        instance.task_state = task_states.SCHEDULING
        info_cache = objects.InstanceInfoCache()
        info_cache.instance_uuid = instance.uuid
        info_cache.network_info = network_model.NetworkInfo()
        instance.info_cache = info_cache
        instance.flavor = instance_type
        instance.old_flavor = None
        instance.new_flavor = None
        if CONF.ephemeral_storage_encryption.enabled:
            # NOTE(kfarr): dm-crypt expects the cipher in a
            # hyphenated format: cipher-chainmode-ivmode
            # (ex: aes-xts-plain64). The algorithm needs
            # to be parsed out to pass to the key manager (ex: aes).
            cipher = CONF.ephemeral_storage_encryption.cipher
            algorithm = cipher.split('-')[0] if cipher else None
            instance.ephemeral_key_uuid = self.key_manager.create_key(
                context,
                algorithm=algorithm,
                length=CONF.ephemeral_storage_encryption.key_size)
        else:
            instance.ephemeral_key_uuid = None

        # Store image properties so we can use them later
        # (for notifications, etc).  Only store what we can.
        if not instance.obj_attr_is_set('system_metadata'):
            instance.system_metadata = {}
        # Make sure we have the dict form that we need for instance_update.
        instance.system_metadata = utils.instance_sys_meta(instance)

        system_meta = utils.get_system_metadata_from_image(
            image, instance_type)

        # In case we couldn't find any suitable base_image
        system_meta.setdefault('image_base_image_ref', instance.image_ref)

        system_meta['owner_user_name'] = context.user_name
        system_meta['owner_project_name'] = context.project_name

        instance.system_metadata.update(system_meta)

        if CONF.use_neutron:
            # For Neutron we don't actually store anything in the database, we
            # proxy the security groups on the instance from the ports
            # attached to the instance.
            instance.security_groups = objects.SecurityGroupList()
        else:
            instance.security_groups = security_groups

        self._populate_instance_names(instance, num_instances)
        instance.shutdown_terminate = shutdown_terminate
        if num_instances > 1 and self.cell_type != 'api':
            instance = self._apply_instance_name_template(context, instance,
                                                          index)

        return instance

    def _create_tag_list_obj(self, context, tags):
        """Create TagList objects from simple string tags.

        :param context: security context.
        :param tags: simple string tags from API request.
        :returns: TagList object.
        """
        tag_list = [objects.Tag(context=context, tag=t) for t in tags]
        tag_list_obj = objects.TagList(objects=tag_list)
        return tag_list_obj

    def _transform_tags(self, tags, resource_id):
        """Change the resource_id of the tags according to the input param.

        Because this method can be called multiple times when more than one
        instance is booted in a single request it makes a copy of the tags
        list.

        :param tags: TagList object.
        :param resource_id: string.
        :returns: TagList object.
        """
        instance_tags = tags.obj_clone()
        for tag in instance_tags:
            tag.resource_id = resource_id
        return instance_tags

    # This method remains because cellsv1 uses it in the scheduler
    def create_db_entry_for_new_instance(self, context, instance_type, image,
            instance, security_group, block_device_mapping, num_instances,
            index, shutdown_terminate=False, create_instance=True):
        """Create an entry in the DB for this new instance,
        including any related table updates (such as security group,
        etc).

        This is called by the scheduler after a location for the
        instance has been determined.

        :param create_instance: Determines if the instance is created here or
            just populated for later creation. This is done so that this code
            can be shared with cellsv1 which needs the instance creation to
            happen here. It should be removed and this method cleaned up when
            cellsv1 is a distant memory.
        """
        self._populate_instance_for_create(context, instance, image, index,
                                           security_group, instance_type,
                                           num_instances, shutdown_terminate)

        if create_instance:
            instance.create()

        return instance

    def _check_multiple_instances_with_neutron_ports(self,
                                                     requested_networks):
        """Check whether multiple instances are created from port id(s)."""
        for requested_net in requested_networks:
            if requested_net.port_id:
                msg = _("Unable to launch multiple instances with"
                        " a single configured port ID. Please launch your"
                        " instance one by one with different ports.")
                raise exception.MultiplePortsNotApplicable(reason=msg)

    def _check_multiple_instances_with_specified_ip(self, requested_networks):
        """Check whether multiple instances are created with specified ip."""

        for requested_net in requested_networks:
            if requested_net.network_id and requested_net.address:
                msg = _("max_count cannot be greater than 1 if an fixed_ip "
                        "is specified.")
                raise exception.InvalidFixedIpAndMaxCountRequest(reason=msg)

    @hooks.add_hook("create_instance")
    def create(self, context, instance_type,
               image_href, kernel_id=None, ramdisk_id=None,
               min_count=None, max_count=None,
               display_name=None, display_description=None,
               key_name=None, key_data=None, security_groups=None,
               availability_zone=None, forced_host=None, forced_node=None,
               user_data=None, metadata=None, injected_files=None,
               admin_password=None, block_device_mapping=None,
               access_ip_v4=None, access_ip_v6=None, requested_networks=None,
               config_drive=None, auto_disk_config=None, scheduler_hints=None,
               legacy_bdm=True, shutdown_terminate=False,
               check_server_group_quota=False, tags=None):
        """Provision instances, sending instance information to the
        scheduler.  The scheduler will determine where the instance(s)
        go and will handle creating the DB entries.

        Returns a tuple of (instances, reservation_id)
        """
        if requested_networks and max_count is not None and max_count > 1:
            self._check_multiple_instances_with_specified_ip(
                requested_networks)
            if utils.is_neutron():
                self._check_multiple_instances_with_neutron_ports(
                    requested_networks)

        if availability_zone:
            available_zones = availability_zones.\
                get_availability_zones(context.elevated(), True)
            if forced_host is None and availability_zone not in \
                    available_zones:
                msg = _('The requested availability zone is not available')
                raise exception.InvalidRequest(msg)

        filter_properties = scheduler_utils.build_filter_properties(
                scheduler_hints, forced_host, forced_node, instance_type)

        return self._create_instance(
                       context, instance_type,
                       image_href, kernel_id, ramdisk_id,
                       min_count, max_count,
                       display_name, display_description,
                       key_name, key_data, security_groups,
                       availability_zone, user_data, metadata,
                       injected_files, admin_password,
                       access_ip_v4, access_ip_v6,
                       requested_networks, config_drive,
                       block_device_mapping, auto_disk_config,
                       filter_properties=filter_properties,
                       legacy_bdm=legacy_bdm,
                       shutdown_terminate=shutdown_terminate,
                       check_server_group_quota=check_server_group_quota,
                       tags=tags)

    def _check_auto_disk_config(self, instance=None, image=None,
                                **extra_instance_updates):
        auto_disk_config = extra_instance_updates.get("auto_disk_config")
        if auto_disk_config is None:
            return
        if not image and not instance:
            return

        if image:
            image_props = image.get("properties", {})
            auto_disk_config_img = \
                utils.get_auto_disk_config_from_image_props(image_props)
            image_ref = image.get("id")
        else:
            sys_meta = utils.instance_sys_meta(instance)
            image_ref = sys_meta.get('image_base_image_ref')
            auto_disk_config_img = \
                utils.get_auto_disk_config_from_instance(sys_meta=sys_meta)

        self._ensure_auto_disk_config_is_valid(auto_disk_config_img,
                                               auto_disk_config,
                                               image_ref)

    def _lookup_instance(self, context, uuid):
        '''Helper method for pulling an instance object from a database.

        During the transition to cellsv2 there is some complexity around
        retrieving an instance from the database which this method hides. If
        there is an instance mapping then query the cell for the instance, if
        no mapping exists then query the configured nova database.

        Once we are past the point that all deployments can be assumed to be
        migrated to cellsv2 this method can go away.
        '''
        inst_map = None
        try:
            inst_map = objects.InstanceMapping.get_by_instance_uuid(
                context, uuid)
        except exception.InstanceMappingNotFound:
            # TODO(alaski): This exception block can be removed once we're
            # guaranteed everyone is using cellsv2.
            pass

        if (inst_map is None or inst_map.cell_mapping is None or
                CONF.cells.enable):
            # If inst_map is None then the deployment has not migrated to
            # cellsv2 yet.
            # If inst_map.cell_mapping is None then the instance is not in a
            # cell yet. Until instance creation moves to the conductor the
            # instance can be found in the configured database, so attempt
            # to look it up.
            # If we're on cellsv1, we can't yet short-circuit the cells
            # messaging path
            cell = None
            try:
                instance = objects.Instance.get_by_uuid(context, uuid)
            except exception.InstanceNotFound:
                # If we get here then the conductor is in charge of writing the
                # instance to the database and hasn't done that yet. It's up to
                # the caller of this method to determine what to do with that
                # information.
                return None, None
        else:
            cell = inst_map.cell_mapping
            with nova_context.target_cell(context, cell) as cctxt:
                try:
                    instance = objects.Instance.get_by_uuid(cctxt, uuid)
                except exception.InstanceNotFound:
                    # Since the cell_mapping exists we know the instance is in
                    # the cell, however InstanceNotFound means it's already
                    # deleted.
                    return None, None
        return cell, instance

    def _delete_while_booting(self, context, instance):
        """Handle deletion if the instance has not reached a cell yet

        Deletion before an instance reaches a cell needs to be handled
        differently. What we're attempting to do is delete the BuildRequest
        before the api level conductor does.  If we succeed here then the boot
        request stops before reaching a cell.  If not then the instance will
        need to be looked up in a cell db and the normal delete path taken.
        """
        deleted = self._attempt_delete_of_buildrequest(context, instance)

        # After service version 15 deletion of the BuildRequest will halt the
        # build process in the conductor. In that case run the rest of this
        # method and consider the instance deleted. If we have not yet reached
        # service version 15 then just return False so the rest of the delete
        # process will proceed usually.
        service_version = objects.Service.get_minimum_version(
            context, 'nova-osapi_compute')
        if service_version < 15:
            return False

        if deleted:
            # If we've reached this block the successful deletion of the
            # buildrequest indicates that the build process should be halted by
            # the conductor.

            # NOTE(alaski): Though the conductor halts the build process it
            # does not currently delete the instance record. This is
            # because in the near future the instance record will not be
            # created if the buildrequest has been deleted here. For now we
            # ensure the instance has been set to deleted at this point.
            # Yes this directly contradicts the comment earlier in this
            # method, but this is a temporary measure.
            # Look up the instance because the current instance object was
            # stashed on the buildrequest and therefore not complete enough
            # to run .destroy().
            try:
                instance_uuid = instance.uuid
                cell, instance = self._lookup_instance(context, instance_uuid)
                if instance is not None:
                    # If instance is None it has already been deleted.
                    if cell:
                        with nova_context.target_cell(context, cell) as cctxt:
                            # FIXME: When the instance context is targeted,
                            # we can remove this
                            with compute_utils.notify_about_instance_delete(
                                    self.notifier, cctxt, instance):
                                instance.destroy()
                    else:
                        instance.destroy()
            except exception.InstanceNotFound:
                pass

            return True
        return False

    def _attempt_delete_of_buildrequest(self, context, instance):
        # If there is a BuildRequest then the instance may not have been
        # written to a cell db yet. Delete the BuildRequest here, which
        # will indicate that the Instance build should not proceed.
        try:
            build_req = objects.BuildRequest.get_by_instance_uuid(
                context, instance.uuid)
            build_req.destroy()
        except exception.BuildRequestNotFound:
            # This means that conductor has deleted the BuildRequest so the
            # instance is now in a cell and the delete needs to proceed
            # normally.
            return False

        # We need to detach from any volumes so they aren't orphaned.
        self._local_cleanup_bdm_volumes(
            build_req.block_device_mappings, instance, context)

        return True

    def _delete(self, context, instance, delete_type, cb, **instance_attrs):
        if instance.disable_terminate:
            LOG.info('instance termination disabled', instance=instance)
            return

        cell = None
        # If there is an instance.host (or the instance is shelved-offloaded or
        # in error state), the instance has been scheduled and sent to a
        # cell/compute which means it was pulled from the cell db.
        # Normal delete should be attempted.
        may_have_ports_or_volumes = self._may_have_ports_or_volumes(instance)
        if not instance.host and not may_have_ports_or_volumes:
            try:
                if self._delete_while_booting(context, instance):
                    return
                # If instance.host was not set it's possible that the Instance
                # object here was pulled from a BuildRequest object and is not
                # fully populated. Notably it will be missing an 'id' field
                # which will prevent instance.destroy from functioning
                # properly. A lookup is attempted which will either return a
                # full Instance or None if not found. If not found then it's
                # acceptable to skip the rest of the delete processing.
                cell, instance = self._lookup_instance(context, instance.uuid)
                if cell and instance:
                    try:
                        # Now destroy the instance from the cell it lives in.
                        with compute_utils.notify_about_instance_delete(
                                self.notifier, context, instance):
                            instance.destroy()
                    except exception.InstanceNotFound:
                        pass
                    # The instance was deleted or is already gone.
                    return
                if not instance:
                    # Instance is already deleted.
                    return
            except exception.ObjectActionError:
                # NOTE(melwitt): This means the instance.host changed
                # under us indicating the instance became scheduled
                # during the destroy(). Refresh the instance from the DB and
                # continue on with the delete logic for a scheduled instance.
                # NOTE(danms): If instance.host is set, we should be able to
                # do the following lookup. If not, there's not much we can
                # do to recover.
                cell, instance = self._lookup_instance(context, instance.uuid)
                if not instance:
                    # Instance is already deleted
                    return

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        # At these states an instance has a snapshot associate.
        if instance.vm_state in (vm_states.SHELVED,
                                 vm_states.SHELVED_OFFLOADED):
            snapshot_id = instance.system_metadata.get('shelved_image_id')
            LOG.info("Working on deleting snapshot %s "
                     "from shelved instance...",
                     snapshot_id, instance=instance)
            try:
                self.image_api.delete(context, snapshot_id)
            except (exception.ImageNotFound,
                    exception.ImageNotAuthorized) as exc:
                LOG.warning("Failed to delete snapshot "
                            "from shelved instance (%s).",
                            exc.format_message(), instance=instance)
            except Exception:
                LOG.exception("Something wrong happened when trying to "
                              "delete snapshot from shelved instance.",
                              instance=instance)

        original_task_state = instance.task_state
        try:
            # NOTE(maoy): no expected_task_state needs to be set
            instance.update(instance_attrs)
            instance.progress = 0
            instance.save()

            # NOTE(dtp): cells.enable = False means "use cells v2".
            # Run everywhere except v1 compute cells.
            if not CONF.cells.enable or self.cell_type == 'api':
                self.consoleauth_rpcapi.delete_tokens_for_instance(
                    context, instance.uuid)

            if self.cell_type == 'api':
                # NOTE(comstud): If we're in the API cell, we need to
                # skip all remaining logic and just call the callback,
                # which will cause a cast to the child cell.
                cb(context, instance, bdms)
                return
            if not instance.host and not may_have_ports_or_volumes:
                try:
                    compute_utils.notify_about_instance_usage(
                            self.notifier, context, instance,
                            "%s.start" % delete_type)
                    instance.destroy()
                    compute_utils.notify_about_instance_usage(
                            self.notifier, context, instance,
                            "%s.end" % delete_type,
                            system_metadata=instance.system_metadata)
                    LOG.info('Instance deleted and does not have host '
                             'field, its vm_state is %(state)s.',
                             {'state': instance.vm_state},
                              instance=instance)
                    return
                except exception.ObjectActionError as ex:
                    # The instance's host likely changed under us as
                    # this instance could be building and has since been
                    # scheduled. Continue with attempts to delete it.
                    LOG.debug('Refreshing instance because: %s', ex,
                              instance=instance)
                    instance.refresh()

            if instance.vm_state == vm_states.RESIZED:
                self._confirm_resize_on_deleting(context, instance)

            is_local_delete = True
            try:
                # instance.host must be set in order to look up the service.
                if instance.host is not None:
                    service = objects.Service.get_by_compute_host(
                        context.elevated(), instance.host)
                    is_local_delete = not self.servicegroup_api.service_is_up(
                        service)
                if not is_local_delete:
                    if original_task_state in (task_states.DELETING,
                                                  task_states.SOFT_DELETING):
                        LOG.info('Instance is already in deleting state, '
                                 'ignoring this request',
                                 instance=instance)
                        return
                    self._record_action_start(context, instance,
                                              instance_actions.DELETE)

                    cb(context, instance, bdms)
            except exception.ComputeHostNotFound:
                LOG.debug('Compute host %s not found during service up check, '
                          'going to local delete instance', instance.host,
                          instance=instance)

            if is_local_delete:
                # If instance is in shelved_offloaded state or compute node
                # isn't up, delete instance from db and clean bdms info and
                # network info
                if cell is None:
                    # NOTE(danms): If we didn't get our cell from one of the
                    # paths above, look it up now.
                    try:
                        im = objects.InstanceMapping.get_by_instance_uuid(
                            context, instance.uuid)
                        cell = im.cell_mapping
                    except exception.InstanceMappingNotFound:
                        LOG.warning('During local delete, failed to find '
                                    'instance mapping', instance=instance)
                        return

                LOG.debug('Doing local delete in cell %s', cell.identity,
                          instance=instance)
                with nova_context.target_cell(context, cell) as cctxt:
                    self._local_delete(cctxt, instance, bdms, delete_type, cb)

        except exception.InstanceNotFound:
            # NOTE(comstud): Race condition. Instance already gone.
            pass

    def _may_have_ports_or_volumes(self, instance):
        # NOTE(melwitt): When an instance build fails in the compute manager,
        # the instance host and node are set to None and the vm_state is set
        # to ERROR. In the case, the instance with host = None has actually
        # been scheduled and may have ports and/or volumes allocated on the
        # compute node.
        if instance.vm_state in (vm_states.SHELVED_OFFLOADED, vm_states.ERROR):
            return True
        return False

    def _confirm_resize_on_deleting(self, context, instance):
        # If in the middle of a resize, use confirm_resize to
        # ensure the original instance is cleaned up too
        migration = None
        for status in ('finished', 'confirming'):
            try:
                migration = objects.Migration.get_by_instance_and_status(
                        context.elevated(), instance.uuid, status)
                LOG.info('Found an unconfirmed migration during delete, '
                         'id: %(id)s, status: %(status)s',
                         {'id': migration.id,
                          'status': migration.status},
                         instance=instance)
                break
            except exception.MigrationNotFoundByStatus:
                pass

        if not migration:
            LOG.info('Instance may have been confirmed during delete',
                     instance=instance)
            return

        src_host = migration.source_compute

        self._record_action_start(context, instance,
                                  instance_actions.CONFIRM_RESIZE)

        self.compute_rpcapi.confirm_resize(context,
                instance, migration, src_host, cast=False)

    def _get_stashed_volume_connector(self, bdm, instance):
        """Lookup a connector dict from the bdm.connection_info if set

        Gets the stashed connector dict out of the bdm.connection_info if set
        and the connector host matches the instance host.

        :param bdm: nova.objects.block_device.BlockDeviceMapping
        :param instance: nova.objects.instance.Instance
        :returns: volume connector dict or None
        """
        if 'connection_info' in bdm and bdm.connection_info is not None:
            # NOTE(mriedem): We didn't start stashing the connector in the
            # bdm.connection_info until Mitaka so it might not be there on old
            # attachments. Also, if the volume was attached when the instance
            # was in shelved_offloaded state and it hasn't been unshelved yet
            # we don't have the attachment/connection information either.
            connector = jsonutils.loads(bdm.connection_info).get('connector')
            if connector:
                if connector.get('host') == instance.host:
                    return connector
                LOG.debug('Found stashed volume connector for instance but '
                          'connector host %(connector_host)s does not match '
                          'the instance host %(instance_host)s.',
                          {'connector_host': connector.get('host'),
                           'instance_host': instance.host}, instance=instance)
                if (instance.host is None and
                        self._may_have_ports_or_volumes(instance)):
                    LOG.debug('Allowing use of stashed volume connector with '
                              'instance host None because instance with '
                              'vm_state %(vm_state)s has been scheduled in '
                              'the past.', {'vm_state': instance.vm_state},
                              instance=instance)
                    return connector

    def _local_cleanup_bdm_volumes(self, bdms, instance, context):
        """The method deletes the bdm records and, if a bdm is a volume, call
        the terminate connection and the detach volume via the Volume API.
        """
        elevated = context.elevated()
        for bdm in bdms:
            if bdm.is_volume:
                try:
                    if bdm.attachment_id:
                        self.volume_api.attachment_delete(context,
                                                          bdm.attachment_id)
                    else:
                        connector = self._get_stashed_volume_connector(
                            bdm, instance)
                        if connector:
                            self.volume_api.terminate_connection(context,
                                                                 bdm.volume_id,
                                                                 connector)
                        else:
                            LOG.debug('Unable to find connector for volume %s,'
                                      ' not attempting terminate_connection.',
                                      bdm.volume_id, instance=instance)
                        # Attempt to detach the volume. If there was no
                        # connection made in the first place this is just
                        # cleaning up the volume state in the Cinder DB.
                        self.volume_api.detach(elevated, bdm.volume_id,
                                               instance.uuid)

                    if bdm.delete_on_termination:
                        self.volume_api.delete(context, bdm.volume_id)
                except Exception as exc:
                    LOG.warning("Ignoring volume cleanup failure due to %s",
                                exc, instance=instance)
            # If we're cleaning up volumes from an instance that wasn't yet
            # created in a cell, i.e. the user deleted the server while
            # the BuildRequest still existed, then the BDM doesn't actually
            # exist in the DB to destroy it.
            if 'id' in bdm:
                bdm.destroy()

    def _local_delete(self, context, instance, bdms, delete_type, cb):
        if instance.vm_state == vm_states.SHELVED_OFFLOADED:
            LOG.info("instance is in SHELVED_OFFLOADED state, cleanup"
                     " the instance's info from database.",
                     instance=instance)
        else:
            LOG.warning("instance's host %s is down, deleting from "
                        "database", instance.host, instance=instance)
        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, "%s.start" % delete_type)

        elevated = context.elevated()
        if self.cell_type != 'api':
            # NOTE(liusheng): In nova-network multi_host scenario,deleting
            # network info of the instance may need instance['host'] as
            # destination host of RPC call. If instance in SHELVED_OFFLOADED
            # state, instance['host'] is None, here, use shelved_host as host
            # to deallocate network info and reset instance['host'] after that.
            # Here we shouldn't use instance.save(), because this will mislead
            # user who may think the instance's host has been changed, and
            # actually, the instance.host is always None.
            orig_host = instance.host
            try:
                if instance.vm_state == vm_states.SHELVED_OFFLOADED:
                    sysmeta = getattr(instance,
                                      obj_base.get_attrname('system_metadata'))
                    instance.host = sysmeta.get('shelved_host')
                self.network_api.deallocate_for_instance(elevated,
                                                         instance)
            finally:
                instance.host = orig_host

        # cleanup volumes
        self._local_cleanup_bdm_volumes(bdms, instance, context)
        # Cleanup allocations in Placement since we can't do it from the
        # compute service.
        self.placementclient.delete_allocation_for_instance(instance.uuid)
        cb(context, instance, bdms, local=True)
        sys_meta = instance.system_metadata
        instance.destroy()
        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, "%s.end" % delete_type,
            system_metadata=sys_meta)

    def _do_delete(self, context, instance, bdms, local=False):
        if local:
            instance.vm_state = vm_states.DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            instance.save()
        else:
            self.compute_rpcapi.terminate_instance(context, instance, bdms,
                                                   delete_type='delete')

    def _do_force_delete(self, context, instance, bdms, local=False):
        if local:
            instance.vm_state = vm_states.DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            instance.save()
        else:
            self.compute_rpcapi.terminate_instance(context, instance, bdms,
                                                   delete_type='force_delete')

    def _do_soft_delete(self, context, instance, bdms, local=False):
        if local:
            instance.vm_state = vm_states.SOFT_DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            instance.save()
        else:
            self.compute_rpcapi.soft_delete_instance(context, instance)

    # NOTE(maoy): we allow delete to be called no matter what vm_state says.
    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=None, task_state=None,
                          must_have_launched=True)
    def soft_delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug('Going to try to soft delete instance',
                  instance=instance)

        self._delete(context, instance, 'soft_delete', self._do_soft_delete,
                     task_state=task_states.SOFT_DELETING,
                     deleted_at=timeutils.utcnow())

    def _delete_instance(self, context, instance):
        self._delete(context, instance, 'delete', self._do_delete,
                     task_state=task_states.DELETING)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=None, task_state=None,
                          must_have_launched=False)
    def delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug("Going to try to terminate instance", instance=instance)
        self._delete_instance(context, instance)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SOFT_DELETED])
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        # Check quotas
        flavor = instance.get_flavor()
        project_id, user_id = quotas_obj.ids_from_instance(context, instance)
        compute_utils.check_num_instances_quota(context, flavor, 1, 1,
                project_id=project_id, user_id=user_id)

        self._record_action_start(context, instance, instance_actions.RESTORE)

        if instance.host:
            instance.task_state = task_states.RESTORING
            instance.deleted_at = None
            instance.save(expected_task_state=[None])
            # TODO(melwitt): We're not rechecking for strict quota here to
            # guard against going over quota during a race at this time because
            # the resource consumption for this operation is written to the
            # database by compute.
            self.compute_rpcapi.restore_instance(context, instance)
        else:
            instance.vm_state = vm_states.ACTIVE
            instance.task_state = None
            instance.deleted_at = None
            instance.save(expected_task_state=[None])

    @check_instance_lock
    @check_instance_state(task_state=None,
                          must_have_launched=False)
    def force_delete(self, context, instance):
        """Force delete an instance in any vm_state/task_state."""
        self._delete(context, instance, 'force_delete', self._do_force_delete,
                     task_state=task_states.DELETING)

    def force_stop(self, context, instance, do_cast=True, clean_shutdown=True):
        LOG.debug("Going to try to stop instance", instance=instance)

        instance.task_state = task_states.POWERING_OFF
        instance.progress = 0
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.STOP)

        self.compute_rpcapi.stop_instance(context, instance, do_cast=do_cast,
                                          clean_shutdown=clean_shutdown)

    @check_instance_lock
    @check_instance_host
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.ERROR])
    def stop(self, context, instance, do_cast=True, clean_shutdown=True):
        """Stop an instance."""
        self.force_stop(context, instance, do_cast, clean_shutdown)

    @check_instance_lock
    @check_instance_host
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.STOPPED])
    def start(self, context, instance):
        """Start an instance."""
        LOG.debug("Going to try to start instance", instance=instance)

        instance.task_state = task_states.POWERING_ON
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.START)
        # TODO(yamahata): injected_files isn't supported right now.
        #                 It is used only for osapi. not for ec2 api.
        #                 availability_zone isn't used by run_instance.
        self.compute_rpcapi.start_instance(context, instance)

    @check_instance_lock
    @check_instance_host
    @check_instance_cell
    @check_instance_state(vm_state=vm_states.ALLOW_TRIGGER_CRASH_DUMP)
    def trigger_crash_dump(self, context, instance):
        """Trigger crash dump in an instance."""
        LOG.debug("Try to trigger crash dump", instance=instance)

        self._record_action_start(context, instance,
                                  instance_actions.TRIGGER_CRASH_DUMP)

        self.compute_rpcapi.trigger_crash_dump(context, instance)

    def _get_instance_map_or_none(self, context, instance_uuid):
        try:
            inst_map = objects.InstanceMapping.get_by_instance_uuid(
                    context, instance_uuid)
        except exception.InstanceMappingNotFound:
            # InstanceMapping should always be found generally. This exception
            # may be raised if a deployment has partially migrated the nova-api
            # services.
            inst_map = None
        return inst_map

    def _get_instance(self, context, instance_uuid, expected_attrs):
        # Before service version 15 the BuildRequest is not cleaned up during
        # a delete request so there is no reason to look it up here as we can't
        # trust that it's not referencing a deleted instance. Also even if
        # there is an instance mapping we don't need to honor it for older
        # service versions.
        service_version = objects.Service.get_minimum_version(
            context, 'nova-osapi_compute')
        # If we're on cellsv1, we also need to consult the top-level
        # merged replica instead of the cell directly, so fall through
        # here in that case as well.
        if service_version < 15 or CONF.cells.enable:
            return objects.Instance.get_by_uuid(context, instance_uuid,
                                                expected_attrs=expected_attrs)
        inst_map = self._get_instance_map_or_none(context, instance_uuid)
        if inst_map and (inst_map.cell_mapping is not None):
            nova_context.set_target_cell(context, inst_map.cell_mapping)
            instance = objects.Instance.get_by_uuid(
                context, instance_uuid, expected_attrs=expected_attrs)
        elif inst_map and (inst_map.cell_mapping is None):
            # This means the instance has not been scheduled and put in
            # a cell yet. For now it also may mean that the deployer
            # has not created their cell(s) yet.
            try:
                build_req = objects.BuildRequest.get_by_instance_uuid(
                        context, instance_uuid)
                instance = build_req.instance
            except exception.BuildRequestNotFound:
                # Instance was mapped and the BuildRequest was deleted
                # while fetching. Try again.
                inst_map = self._get_instance_map_or_none(context,
                                                          instance_uuid)
                if inst_map and (inst_map.cell_mapping is not None):
                    nova_context.set_target_cell(context,
                                                 inst_map.cell_mapping)
                    instance = objects.Instance.get_by_uuid(
                        context, instance_uuid,
                        expected_attrs=expected_attrs)
                else:
                    raise exception.InstanceNotFound(instance_id=instance_uuid)
        else:
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        return instance

    def get(self, context, instance_id, expected_attrs=None):
        """Get a single instance with the given instance_id."""
        if not expected_attrs:
            expected_attrs = []
        expected_attrs.extend(['metadata', 'system_metadata',
                               'security_groups', 'info_cache'])
        # NOTE(ameade): we still need to support integer ids for ec2
        try:
            if uuidutils.is_uuid_like(instance_id):
                LOG.debug("Fetching instance by UUID",
                           instance_uuid=instance_id)

                instance = self._get_instance(context, instance_id,
                                              expected_attrs)
            else:
                LOG.debug("Failed to fetch instance by id %s", instance_id)
                raise exception.InstanceNotFound(instance_id=instance_id)
        except exception.InvalidID:
            LOG.debug("Invalid instance id %s", instance_id)
            raise exception.InstanceNotFound(instance_id=instance_id)

        return instance

    def get_all(self, context, search_opts=None, limit=None, marker=None,
                expected_attrs=None, sort_keys=None, sort_dirs=None):
        """Get all instances filtered by one of the given parameters.

        If there is no filter and the context is an admin, it will retrieve
        all instances in the system.

        Deleted instances will be returned by default, unless there is a
        search option that says otherwise.

        The results will be sorted based on the list of sort keys in the
        'sort_keys' parameter (first value is primary sort key, second value is
        secondary sort ket, etc.). For each sort key, the associated sort
        direction is based on the list of sort directions in the 'sort_dirs'
        parameter.
        """
        if search_opts is None:
            search_opts = {}

        LOG.debug("Searching by: %s", str(search_opts))

        # Fixups for the DB call
        filters = {}

        def _remap_flavor_filter(flavor_id):
            flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
            filters['instance_type_id'] = flavor.id

        def _remap_fixed_ip_filter(fixed_ip):
            # Turn fixed_ip into a regexp match. Since '.' matches
            # any character, we need to use regexp escaping for it.
            filters['ip'] = '^%s$' % fixed_ip.replace('.', '\\.')

        def _remap_metadata_filter(metadata):
            filters['metadata'] = jsonutils.loads(metadata)

        def _remap_system_metadata_filter(metadata):
            filters['system_metadata'] = jsonutils.loads(metadata)

        # search_option to filter_name mapping.
        filter_mapping = {
                'image': 'image_ref',
                'name': 'display_name',
                'tenant_id': 'project_id',
                'flavor': _remap_flavor_filter,
                'fixed_ip': _remap_fixed_ip_filter,
                'metadata': _remap_metadata_filter,
                'system_metadata': _remap_system_metadata_filter}

        # copy from search_opts, doing various remappings as necessary
        for opt, value in search_opts.items():
            # Do remappings.
            # Values not in the filter_mapping table are copied as-is.
            # If remapping is None, option is not copied
            # If the remapping is a string, it is the filter_name to use
            try:
                remap_object = filter_mapping[opt]
            except KeyError:
                filters[opt] = value
            else:
                # Remaps are strings to translate to, or functions to call
                # to do the translating as defined by the table above.
                if isinstance(remap_object, six.string_types):
                    filters[remap_object] = value
                else:
                    try:
                        remap_object(value)

                    # We already know we can't match the filter, so
                    # return an empty list
                    except ValueError:
                        return objects.InstanceList()

        # IP address filtering cannot be applied at the DB layer, remove any DB
        # limit so that it can be applied after the IP filter.
        filter_ip = 'ip6' in filters or 'ip' in filters
        orig_limit = limit
        if filter_ip and limit:
            LOG.debug('Removing limit for DB query due to IP filter')
            limit = None

        # The ordering of instances will be
        # [sorted instances with no host] + [sorted instances with host].
        # This means BuildRequest and cell0 instances first, then cell
        # instances
        try:
            build_requests = objects.BuildRequestList.get_by_filters(
                context, filters, limit=limit, marker=marker,
                sort_keys=sort_keys, sort_dirs=sort_dirs)
            # If we found the marker in we need to set it to None
            # so we don't expect to find it in the cells below.
            marker = None
        except exception.MarkerNotFound:
            # If we didn't find the marker in the build requests then keep
            # looking for it in the cells.
            build_requests = objects.BuildRequestList()
        build_req_instances = objects.InstanceList(
            objects=[build_req.instance for build_req in build_requests])
        # Only subtract from limit if it is not None
        limit = (limit - len(build_req_instances)) if limit else limit

        try:
            cell0_mapping = objects.CellMapping.get_by_uuid(context,
                objects.CellMapping.CELL0_UUID)
        except exception.CellMappingNotFound:
            cell0_instances = objects.InstanceList(objects=[])
        else:
            with nova_context.target_cell(context, cell0_mapping) as cctxt:
                try:
                    cell0_instances = self._get_instances_by_filters(
                        cctxt, filters, limit=limit, marker=marker,
                        expected_attrs=expected_attrs, sort_keys=sort_keys,
                        sort_dirs=sort_dirs)
                    # If we found the marker in cell0 we need to set it to None
                    # so we don't expect to find it in the cells below.
                    marker = None
                except exception.MarkerNotFound:
                    # We can ignore this since we need to look in the cell DB
                    cell0_instances = objects.InstanceList(objects=[])
        # Only subtract from limit if it is not None
        limit = (limit - len(cell0_instances)) if limit else limit

        # There is only planned support for a single cell here. Multiple cell
        # instance lists should be proxied to project Searchlight, or a similar
        # alternative.
        if limit is None or limit > 0:
            if not CONF.cells.enable:
                cell_instances = self._get_instances_by_filters_all_cells(
                        context, filters,
                        limit=limit, marker=marker,
                        expected_attrs=expected_attrs, sort_keys=sort_keys,
                        sort_dirs=sort_dirs)
            else:
                # NOTE(melwitt): If we're on cells v1, we need to read
                # instances from the top-level database because reading from
                # cells results in changed behavior, because of the syncing.
                # We can remove this path once we stop supporting cells v1.
                cell_instances = self._get_instances_by_filters(
                    context, filters, limit=limit, marker=marker,
                    expected_attrs=expected_attrs, sort_keys=sort_keys,
                    sort_dirs=sort_dirs)
        else:
            LOG.debug('Limit excludes any results from real cells')
            cell_instances = objects.InstanceList(objects=[])

        def _get_unique_filter_method():
            seen_uuids = set()

            def _filter(instance):
                if instance.uuid in seen_uuids:
                    return False
                seen_uuids.add(instance.uuid)
                return True

            return _filter

        filter_method = _get_unique_filter_method()
        # Only subtract from limit if it is not None
        limit = (limit - len(cell_instances)) if limit else limit
        # TODO(alaski): Clean up the objects concatenation when List objects
        # support it natively.
        instances = objects.InstanceList(
            objects=list(filter(filter_method,
                           build_req_instances.objects +
                           cell0_instances.objects +
                           cell_instances.objects)))

        if filter_ip:
            instances = self._ip_filter(instances, filters, orig_limit)

        return instances

    @staticmethod
    def _ip_filter(inst_models, filters, limit):
        ipv4_f = re.compile(str(filters.get('ip')))
        ipv6_f = re.compile(str(filters.get('ip6')))

        def _match_instance(instance):
            nw_info = instance.get_network_info()
            for vif in nw_info:
                for fixed_ip in vif.fixed_ips():
                    address = fixed_ip.get('address')
                    if not address:
                        continue
                    version = fixed_ip.get('version')
                    if ((version == 4 and ipv4_f.match(address)) or
                        (version == 6 and ipv6_f.match(address))):
                        return True
            return False

        result_objs = []
        for instance in inst_models:
            if _match_instance(instance):
                result_objs.append(instance)
                if limit and len(result_objs) == limit:
                    break
        return objects.InstanceList(objects=result_objs)

    def _get_instances_by_filters_all_cells(self, context, *args, **kwargs):
        """This is just a wrapper that iterates (non-zero) cells."""
        load_cells()
        if len(CELLS) == 1:
            # We always expect at least two cells; one for cell0 and one for at
            # least a single main cell. If there is only one cell it indicates
            # that nova-api was started before all of the cells were mapped and
            # we should provide a warning to the operator.
            LOG.warning('At least two cells are expected but only one '
                        'was found (%s). cell0 and the initial main cell '
                        'should be created before starting nova-api since '
                        'the cells are cached in each worker. When you '
                        'create more cells, you will need to restart the '
                        'nova-api service to reset the cache.',
                        CELLS[0].identity)

        limit = kwargs.pop('limit', None)

        instances = []
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                LOG.debug('Skipping already-collected cell0 list')
                continue
            LOG.debug('Listing %s instances in cell %s',
                      limit or 'all', cell.identity)
            with nova_context.target_cell(context, cell) as ccontext:
                try:
                    cell_insts = self._get_instances_by_filters(ccontext,
                                                                *args,
                                                                limit=limit,
                                                                **kwargs)
                except exception.MarkerNotFound:
                    # NOTE(danms): We need to keep looking through the
                    # later cells to find the marker
                    continue
                instances.extend(cell_insts)
                # NOTE(danms): We must have found a marker if we had one,
                # so make sure we don't require a marker in the next cell
                kwargs['marker'] = None
                if limit:
                    limit -= len(cell_insts)
                    if limit <= 0:
                        break

        marker = kwargs.get('marker')
        if marker is not None and len(instances) == 0:
            # NOTE(danms): If we did not find the marker in any cell,
            # mimic the db_api behavior here.
            raise exception.MarkerNotFound(marker=marker)

        return objects.InstanceList(objects=instances)

    def _get_instances_by_filters(self, context, filters,
                                  limit=None, marker=None, expected_attrs=None,
                                  sort_keys=None, sort_dirs=None):
        fields = ['metadata', 'system_metadata', 'info_cache',
                  'security_groups']
        if expected_attrs:
            fields.extend(expected_attrs)
        return objects.InstanceList.get_by_filters(
            context, filters=filters, limit=limit, marker=marker,
            expected_attrs=fields, sort_keys=sort_keys, sort_dirs=sort_dirs)

    def update_instance(self, context, instance, updates):
        """Updates a single Instance object with some updates dict.

        Returns the updated instance.
        """

        # NOTE(sbauza): Given we only persist the Instance object after we
        # create the BuildRequest, we are sure that if the Instance object
        # has an ID field set, then it was persisted in the right Cell DB.
        if instance.obj_attr_is_set('id'):
            instance.update(updates)
            # Instance has been scheduled and the BuildRequest has been deleted
            # we can directly write the update down to the right cell.
            inst_map = self._get_instance_map_or_none(context, instance.uuid)
            # If we have a cell_mapping and we're not on cells v1, then
            # look up the instance in the cell database
            if inst_map and (inst_map.cell_mapping is not None) and (
                    not CONF.cells.enable):
                with nova_context.target_cell(context,
                                              inst_map.cell_mapping) as cctxt:
                    with instance.obj_alternate_context(cctxt):
                        instance.save()
            else:
                # If inst_map.cell_mapping does not point at a cell then cell
                # migration has not happened yet.
                # TODO(alaski): Make this a failure case after we put in
                # a block that requires migrating to cellsv2.
                instance.save()
        else:
            # Instance is not yet mapped to a cell, so we need to update
            # BuildRequest instead
            # TODO(sbauza): Fix the possible race conditions where BuildRequest
            # could be deleted because of either a concurrent instance delete
            # or because the scheduler just returned a destination right
            # after we called the instance in the API.
            try:
                build_req = objects.BuildRequest.get_by_instance_uuid(
                    context, instance.uuid)
                instance = build_req.instance
                instance.update(updates)
                # FIXME(sbauza): Here we are updating the current
                # thread-related BuildRequest object. Given that another worker
                # could have looking up at that BuildRequest in the API, it
                # means that it could pass it down to the conductor without
                # making sure that it's not updated, we could have some race
                # condition where it would missing the updated fields, but
                # that's something we could discuss once the instance record
                # is persisted by the conductor.
                build_req.save()
            except exception.BuildRequestNotFound:
                # Instance was mapped and the BuildRequest was deleted
                # while fetching (and possibly the instance could have been
                # deleted as well). We need to lookup again the Instance object
                # in order to correctly update it.
                # TODO(sbauza): Figure out a good way to know the expected
                # attributes by checking which fields are set or not.
                expected_attrs = ['flavor', 'pci_devices', 'numa_topology',
                                  'tags', 'metadata', 'system_metadata',
                                  'security_groups', 'info_cache']
                inst_map = self._get_instance_map_or_none(context,
                                                          instance.uuid)
                if inst_map and (inst_map.cell_mapping is not None):
                    with nova_context.target_cell(
                            context,
                            inst_map.cell_mapping) as cctxt:
                        instance = objects.Instance.get_by_uuid(
                            cctxt, instance.uuid,
                            expected_attrs=expected_attrs)
                        instance.update(updates)
                        instance.save()
                else:
                    # If inst_map.cell_mapping does not point at a cell then
                    # cell migration has not happened yet.
                    # TODO(alaski): Make this a failure case after we put in
                    # a block that requires migrating to cellsv2.
                    instance = objects.Instance.get_by_uuid(
                        context, instance.uuid, expected_attrs=expected_attrs)
                    instance.update(updates)
                    instance.save()
        return instance

    # NOTE(melwitt): We don't check instance lock for backup because lock is
    #                intended to prevent accidental change/delete of instances
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.PAUSED, vm_states.SUSPENDED])
    def backup(self, context, instance, name, backup_type, rotation,
               extra_properties=None):
        """Backup the given instance

        :param instance: nova.objects.instance.Instance object
        :param name: name of the backup
        :param backup_type: 'daily' or 'weekly'
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        :param extra_properties: dict of extra image properties to include
                                 when creating the image.
        :returns: A dict containing image metadata
        """
        props_copy = dict(extra_properties, backup_type=backup_type)

        if compute_utils.is_volume_backed_instance(context, instance):
            LOG.info("It's not supported to backup volume backed "
                     "instance.", instance=instance)
            raise exception.InvalidRequest(
                _('Backup is not supported for volume-backed instances.'))
        else:
            image_meta = self._create_image(context, instance,
                                            name, 'backup',
                                            extra_properties=props_copy)

        # NOTE(comstud): Any changes to this method should also be made
        # to the backup_instance() method in nova/cells/messaging.py

        instance.task_state = task_states.IMAGE_BACKUP
        instance.save(expected_task_state=[None])

        self.compute_rpcapi.backup_instance(context, instance,
                                            image_meta['id'],
                                            backup_type,
                                            rotation)
        return image_meta

    # NOTE(melwitt): We don't check instance lock for snapshot because lock is
    #                intended to prevent accidental change/delete of instances
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.PAUSED, vm_states.SUSPENDED])
    def snapshot(self, context, instance, name, extra_properties=None):
        """Snapshot the given instance.

        :param instance: nova.objects.instance.Instance object
        :param name: name of the snapshot
        :param extra_properties: dict of extra image properties to include
                                 when creating the image.
        :returns: A dict containing image metadata
        """
        image_meta = self._create_image(context, instance, name,
                                        'snapshot',
                                        extra_properties=extra_properties)

        # NOTE(comstud): Any changes to this method should also be made
        # to the snapshot_instance() method in nova/cells/messaging.py
        instance.task_state = task_states.IMAGE_SNAPSHOT_PENDING
        try:
            instance.save(expected_task_state=[None])
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError) as ex:
            # Changing the instance task state to use in raising the
            # InstanceInvalidException below
            LOG.debug('Instance disappeared during snapshot.',
                      instance=instance)
            try:
                image_id = image_meta['id']
                self.image_api.delete(context, image_id)
                LOG.info('Image %s deleted because instance '
                         'deleted before snapshot started.',
                         image_id, instance=instance)
            except exception.ImageNotFound:
                pass
            except Exception as exc:
                LOG.warning("Error while trying to clean up image %(img_id)s: "
                            "%(error_msg)s",
                            {"img_id": image_meta['id'],
                             "error_msg": six.text_type(exc)})
            attr = 'task_state'
            state = task_states.DELETING
            if type(ex) == exception.InstanceNotFound:
                attr = 'vm_state'
                state = vm_states.DELETED
            raise exception.InstanceInvalidState(attr=attr,
                                           instance_uuid=instance.uuid,
                                           state=state,
                                           method='snapshot')

        self.compute_rpcapi.snapshot_instance(context, instance,
                                              image_meta['id'])

        return image_meta

    def _create_image(self, context, instance, name, image_type,
                      extra_properties=None):
        """Create new image entry in the image service.  This new image
        will be reserved for the compute manager to upload a snapshot
        or backup.

        :param context: security context
        :param instance: nova.objects.instance.Instance object
        :param name: string for name of the snapshot
        :param image_type: snapshot | backup
        :param extra_properties: dict of extra image properties to include

        """
        properties = {
            'instance_uuid': instance.uuid,
            'user_id': str(context.user_id),
            'image_type': image_type,
        }
        properties.update(extra_properties or {})

        image_meta = self._initialize_instance_snapshot_metadata(
            instance, name, properties)
        # if we're making a snapshot, omit the disk and container formats,
        # since the image may have been converted to another format, and the
        # original values won't be accurate.  The driver will populate these
        # with the correct values later, on image upload.
        if image_type == 'snapshot':
            image_meta.pop('disk_format', None)
            image_meta.pop('container_format', None)
        return self.image_api.create(context, image_meta)

    def _initialize_instance_snapshot_metadata(self, instance, name,
                                               extra_properties=None):
        """Initialize new metadata for a snapshot of the given instance.

        :param instance: nova.objects.instance.Instance object
        :param name: string for name of the snapshot
        :param extra_properties: dict of extra metadata properties to include

        :returns: the new instance snapshot metadata
        """
        image_meta = utils.get_image_from_system_metadata(
            instance.system_metadata)
        image_meta.update({'name': name,
                           'is_public': False})

        # Delete properties that are non-inheritable
        properties = image_meta['properties']
        for key in CONF.non_inheritable_image_properties:
            properties.pop(key, None)

        # The properties in extra_properties have precedence
        properties.update(extra_properties or {})

        return image_meta

    # NOTE(melwitt): We don't check instance lock for snapshot because lock is
    #                intended to prevent accidental change/delete of instances
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.SUSPENDED])
    def snapshot_volume_backed(self, context, instance, name,
                               extra_properties=None):
        """Snapshot the given volume-backed instance.

        :param instance: nova.objects.instance.Instance object
        :param name: name of the backup or snapshot
        :param extra_properties: dict of extra image properties to include

        :returns: the new image metadata
        """
        image_meta = self._initialize_instance_snapshot_metadata(
            instance, name, extra_properties)
        # the new image is simply a bucket of properties (particularly the
        # block device mapping, kernel and ramdisk IDs) with no image data,
        # hence the zero size
        image_meta['size'] = 0
        for attr in ('container_format', 'disk_format'):
            image_meta.pop(attr, None)
        properties = image_meta['properties']
        # clean properties before filling
        for key in ('block_device_mapping', 'bdm_v2', 'root_device_name'):
            properties.pop(key, None)
        if instance.root_device_name:
            properties['root_device_name'] = instance.root_device_name

        quiesced = False
        if instance.vm_state == vm_states.ACTIVE:
            try:
                LOG.info("Attempting to quiesce instance before volume "
                         "snapshot.", instance=instance)
                self.compute_rpcapi.quiesce_instance(context, instance)
                quiesced = True
            except (exception.InstanceQuiesceNotSupported,
                    exception.QemuGuestAgentNotEnabled,
                    exception.NovaException, NotImplementedError) as err:
                if strutils.bool_from_string(instance.system_metadata.get(
                        'image_os_require_quiesce')):
                    raise
                else:
                    LOG.info('Skipping quiescing instance: %(reason)s.',
                             {'reason': err},
                             instance=instance)
            # NOTE(tasker): discovered that an uncaught exception could occur
            #               after the instance has been frozen. catch and thaw.
            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error("An error occurred during quiesce of instance. "
                              "Unquiescing to ensure instance is thawed. "
                              "Error: %s", six.text_type(ex),
                              instance=instance)
                    self.compute_rpcapi.unquiesce_instance(context, instance,
                                                           mapping=None)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        mapping = []
        try:
            for bdm in bdms:
                if bdm.no_device:
                    continue

                if bdm.is_volume:
                    # create snapshot based on volume_id
                    volume = self.volume_api.get(context, bdm.volume_id)
                    # NOTE(yamahata): Should we wait for snapshot creation?
                    # Linux LVM snapshot creation completes in short time,
                    # it doesn't matter for now.
                    name = _('snapshot for %s') % image_meta['name']
                    LOG.debug('Creating snapshot from volume %s.',
                              volume['id'], instance=instance)
                    snapshot = self.volume_api.create_snapshot_force(
                        context, volume['id'],
                        name, volume['display_description'])
                    mapping_dict = block_device.snapshot_from_bdm(
                        snapshot['id'], bdm)
                    mapping_dict = mapping_dict.get_image_mapping()
                else:
                    mapping_dict = bdm.get_image_mapping()

                mapping.append(mapping_dict)
        # NOTE(tasker): No error handling is done in the above for loop.
        # This means that if the snapshot fails and throws an exception
        # the traceback will skip right over the unquiesce needed below.
        # Here, catch any exception, unquiesce the instance, and raise the
        # error so that the calling function can do what it needs to in
        # order to properly treat a failed snap.
        except Exception:
            with excutils.save_and_reraise_exception():
                if quiesced:
                    LOG.info("Unquiescing instance after volume snapshot "
                             "failure.", instance=instance)
                    self.compute_rpcapi.unquiesce_instance(
                        context, instance, mapping)

        if quiesced:
            self.compute_rpcapi.unquiesce_instance(context, instance, mapping)

        if mapping:
            properties['block_device_mapping'] = mapping
            properties['bdm_v2'] = True

        return self.image_api.create(context, image_meta)

    @check_instance_lock
    def reboot(self, context, instance, reboot_type):
        """Reboot the given instance."""
        if reboot_type == 'SOFT':
            self._soft_reboot(context, instance)
        else:
            self._hard_reboot(context, instance)

    @check_instance_state(vm_state=set(vm_states.ALLOW_SOFT_REBOOT),
                          task_state=[None])
    def _soft_reboot(self, context, instance):
        expected_task_state = [None]
        instance.task_state = task_states.REBOOTING
        instance.save(expected_task_state=expected_task_state)

        self._record_action_start(context, instance, instance_actions.REBOOT)

        self.compute_rpcapi.reboot_instance(context, instance=instance,
                                            block_device_info=None,
                                            reboot_type='SOFT')

    @check_instance_state(vm_state=set(vm_states.ALLOW_HARD_REBOOT),
                          task_state=task_states.ALLOW_REBOOT)
    def _hard_reboot(self, context, instance):
        instance.task_state = task_states.REBOOTING_HARD
        expected_task_state = [None,
                               task_states.REBOOTING,
                               task_states.REBOOT_PENDING,
                               task_states.REBOOT_STARTED,
                               task_states.REBOOTING_HARD,
                               task_states.RESUMING,
                               task_states.UNPAUSING,
                               task_states.SUSPENDING]
        instance.save(expected_task_state = expected_task_state)

        self._record_action_start(context, instance, instance_actions.REBOOT)

        self.compute_rpcapi.reboot_instance(context, instance=instance,
                                            block_device_info=None,
                                            reboot_type='HARD')

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.ERROR])
    def rebuild(self, context, instance, image_href, admin_password,
                files_to_inject=None, **kwargs):
        """Rebuild the given instance with the provided attributes."""
        files_to_inject = files_to_inject or []
        metadata = kwargs.get('metadata', {})
        preserve_ephemeral = kwargs.get('preserve_ephemeral', False)
        auto_disk_config = kwargs.get('auto_disk_config')

        image_id, image = self._get_image(context, image_href)
        self._check_auto_disk_config(image=image, **kwargs)

        flavor = instance.get_flavor()
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        root_bdm = compute_utils.get_root_bdm(context, instance, bdms)

        # Check to see if the image is changing and we have a volume-backed
        # server.
        is_volume_backed = compute_utils.is_volume_backed_instance(
            context, instance, bdms)
        if is_volume_backed:
            # For boot from volume, instance.image_ref is empty, so we need to
            # query the image from the volume.
            if root_bdm is None:
                # This shouldn't happen and is an error, we need to fail. This
                # is not the users fault, it's an internal error. Without a
                # root BDM we have no way of knowing the backing volume (or
                # image in that volume) for this instance.
                raise exception.NovaException(
                    _('Unable to find root block device mapping for '
                      'volume-backed instance.'))

            volume = self.volume_api.get(context, root_bdm.volume_id)
            volume_image_metadata = volume.get('volume_image_metadata', {})
            orig_image_ref = volume_image_metadata.get('image_id')
        else:
            orig_image_ref = instance.image_ref

        self._checks_for_create_and_rebuild(context, image_id, image,
                flavor, metadata, files_to_inject, root_bdm)

        kernel_id, ramdisk_id = self._handle_kernel_and_ramdisk(
                context, None, None, image)

        def _reset_image_metadata():
            """Remove old image properties that we're storing as instance
            system metadata.  These properties start with 'image_'.
            Then add the properties for the new image.
            """
            # FIXME(comstud): There's a race condition here in that if
            # the system_metadata for this instance is updated after
            # we do the previous save() and before we update.. those
            # other updates will be lost. Since this problem exists in
            # a lot of other places, I think it should be addressed in
            # a DB layer overhaul.

            orig_sys_metadata = dict(instance.system_metadata)
            # Remove the old keys
            for key in list(instance.system_metadata.keys()):
                if key.startswith(utils.SM_IMAGE_PROP_PREFIX):
                    del instance.system_metadata[key]

            # Add the new ones
            new_sys_metadata = utils.get_system_metadata_from_image(
                image, flavor)

            instance.system_metadata.update(new_sys_metadata)
            instance.save()
            return orig_sys_metadata

        # Since image might have changed, we may have new values for
        # os_type, vm_mode, etc
        options_from_image = self._inherit_properties_from_image(
                image, auto_disk_config)
        instance.update(options_from_image)

        instance.task_state = task_states.REBUILDING
        instance.image_ref = image_href
        instance.kernel_id = kernel_id or ""
        instance.ramdisk_id = ramdisk_id or ""
        instance.progress = 0
        instance.update(kwargs)
        instance.save(expected_task_state=[None])

        # On a rebuild, since we're potentially changing images, we need to
        # wipe out the old image properties that we're storing as instance
        # system metadata... and copy in the properties for the new image.
        orig_sys_metadata = _reset_image_metadata()

        self._record_action_start(context, instance, instance_actions.REBUILD)

        # NOTE(sbauza): The migration script we provided in Newton should make
        # sure that all our instances are currently migrated to have an
        # attached RequestSpec object but let's consider that the operator only
        # half migrated all their instances in the meantime.
        host = instance.host
        try:
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
            # If a new image is provided on rebuild, we will need to run
            # through the scheduler again, but we want the instance to be
            # rebuilt on the same host it's already on.
            if orig_image_ref != image_href:
                # We have to modify the request spec that goes to the scheduler
                # to contain the new image. We persist this since we've already
                # changed the instance.image_ref above so we're being
                # consistent.
                request_spec.image = objects.ImageMeta.from_dict(image)
                request_spec.save()
                if 'scheduler_hints' not in request_spec:
                    request_spec.scheduler_hints = {}
                # Nuke the id on this so we can't accidentally save
                # this hint hack later
                del request_spec.id

                # NOTE(danms): Passing host=None tells conductor to
                # call the scheduler. The _nova_check_type hint
                # requires that the scheduler returns only the same
                # host that we are currently on and only checks
                # rebuild-related filters.
                request_spec.scheduler_hints['_nova_check_type'] = ['rebuild']
                request_spec.force_hosts = [instance.host]
                request_spec.force_nodes = [instance.node]
                host = None
        except exception.RequestSpecNotFound:
            # Some old instances can still have no RequestSpec object attached
            # to them, we need to support the old way
            request_spec = None

        self.compute_task_api.rebuild_instance(context, instance=instance,
                new_pass=admin_password, injected_files=files_to_inject,
                image_ref=image_href, orig_image_ref=orig_image_ref,
                orig_sys_metadata=orig_sys_metadata, bdms=bdms,
                preserve_ephemeral=preserve_ephemeral, host=host,
                request_spec=request_spec,
                kwargs=kwargs)

    @staticmethod
    def _check_quota_for_upsize(context, instance, current_flavor, new_flavor):
        project_id, user_id = quotas_obj.ids_from_instance(context,
                                                           instance)
        # Deltas will be empty if the resize is not an upsize.
        deltas = compute_utils.upsize_quota_delta(context, new_flavor,
                                                  current_flavor)
        if deltas:
            try:
                res_deltas = {'cores': deltas.get('cores', 0),
                              'ram': deltas.get('ram', 0)}
                objects.Quotas.check_deltas(context, res_deltas,
                                            project_id, user_id=user_id,
                                            check_project_id=project_id,
                                            check_user_id=user_id)
            except exception.OverQuota as exc:
                quotas = exc.kwargs['quotas']
                overs = exc.kwargs['overs']
                usages = exc.kwargs['usages']
                headroom = compute_utils.get_headroom(quotas, usages,
                                                      deltas)
                (overs, reqs, total_alloweds,
                 useds) = compute_utils.get_over_quota_detail(headroom,
                                                              overs,
                                                              quotas,
                                                              deltas)
                LOG.warning("%(overs)s quota exceeded for %(pid)s,"
                            " tried to resize instance.",
                            {'overs': overs, 'pid': context.project_id})
                raise exception.TooManyInstances(overs=overs,
                                                 req=reqs,
                                                 used=useds,
                                                 allowed=total_alloweds)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.RESIZED])
    def revert_resize(self, context, instance):
        """Reverts a resize, deleting the 'new' instance in the process."""
        elevated = context.elevated()
        migration = objects.Migration.get_by_instance_and_status(
            elevated, instance.uuid, 'finished')

        # If this is a resize down, a revert might go over quota.
        self._check_quota_for_upsize(context, instance, instance.flavor,
                                     instance.old_flavor)

        # The AZ for the server may have changed when it was migrated so while
        # we are in the API and have access to the API DB, update the
        # instance.availability_zone before casting off to the compute service.
        # Note that we do this in the API to avoid an "up-call" from the
        # compute service to the API DB. This is not great in case something
        # fails during revert before the instance.host is updated to the
        # original source host, but it is good enough for now. Long-term we
        # could consider passing the AZ down to compute so it can set it when
        # the instance.host value is set in finish_revert_resize.
        instance.availability_zone = (
            availability_zones.get_host_availability_zone(
                context, migration.source_compute))

        instance.task_state = task_states.RESIZE_REVERTING
        instance.save(expected_task_state=[None])

        migration.status = 'reverting'
        migration.save()

        self._record_action_start(context, instance,
                                  instance_actions.REVERT_RESIZE)

        # Conductor updated the RequestSpec.flavor during the initial resize
        # operation to point at the new flavor, so we need to update the
        # RequestSpec to point back at the original flavor, otherwise
        # subsequent move operations through the scheduler will be using the
        # wrong flavor.
        try:
            reqspec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
            reqspec.flavor = instance.old_flavor
            reqspec.save()
        except exception.RequestSpecNotFound:
            # TODO(mriedem): Make this a failure in Stein when we drop
            # compatibility for missing request specs.
            pass

        # TODO(melwitt): We're not rechecking for strict quota here to guard
        # against going over quota during a race at this time because the
        # resource consumption for this operation is written to the database
        # by compute.
        self.compute_rpcapi.revert_resize(context, instance,
                                          migration,
                                          migration.dest_compute)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.RESIZED])
    def confirm_resize(self, context, instance, migration=None):
        """Confirms a migration/resize and deletes the 'old' instance."""
        elevated = context.elevated()
        # NOTE(melwitt): We're not checking quota here because there isn't a
        # change in resource usage when confirming a resize. Resource
        # consumption for resizes are written to the database by compute, so
        # a confirm resize is just a clean up of the migration objects and a
        # state change in compute.
        if migration is None:
            migration = objects.Migration.get_by_instance_and_status(
                elevated, instance.uuid, 'finished')

        migration.status = 'confirming'
        migration.save()

        self._record_action_start(context, instance,
                                  instance_actions.CONFIRM_RESIZE)

        self.compute_rpcapi.confirm_resize(context,
                                           instance,
                                           migration,
                                           migration.source_compute)

    @staticmethod
    def _resize_cells_support(context, instance,
                              current_instance_type, new_instance_type):
        """Special API cell logic for resize."""
        # NOTE(johannes/comstud): The API cell needs a local migration
        # record for later resize_confirm and resize_reverts.
        # We don't need source and/or destination
        # information, just the old and new flavors. Status is set to
        # 'finished' since nothing else will update the status along
        # the way.
        mig = objects.Migration(context=context.elevated())
        mig.instance_uuid = instance.uuid
        mig.old_instance_type_id = current_instance_type['id']
        mig.new_instance_type_id = new_instance_type['id']
        mig.status = 'finished'
        mig.migration_type = (
            mig.old_instance_type_id != mig.new_instance_type_id and
            'resize' or 'migration')
        mig.create()

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED])
    def resize(self, context, instance, flavor_id=None, clean_shutdown=True,
               **extra_instance_updates):
        """Resize (ie, migrate) a running instance.

        If flavor_id is None, the process is considered a migration, keeping
        the original flavor_id. If flavor_id is not None, the instance should
        be migrated to a new host and resized to the new flavor_id.
        """
        self._check_auto_disk_config(instance, **extra_instance_updates)

        current_instance_type = instance.get_flavor()

        # If flavor_id is not provided, only migrate the instance.
        if not flavor_id:
            LOG.debug("flavor_id is None. Assuming migration.",
                      instance=instance)
            new_instance_type = current_instance_type
        else:
            new_instance_type = flavors.get_flavor_by_flavor_id(
                    flavor_id, read_deleted="no")
            if (new_instance_type.get('root_gb') == 0 and
                current_instance_type.get('root_gb') != 0 and
                not compute_utils.is_volume_backed_instance(context,
                    instance)):
                reason = _('Resize to zero disk flavor is not allowed.')
                raise exception.CannotResizeDisk(reason=reason)

        if not new_instance_type:
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        current_instance_type_name = current_instance_type['name']
        new_instance_type_name = new_instance_type['name']
        LOG.debug("Old instance type %(current_instance_type_name)s, "
                  "new instance type %(new_instance_type_name)s",
                  {'current_instance_type_name': current_instance_type_name,
                   'new_instance_type_name': new_instance_type_name},
                  instance=instance)

        same_instance_type = (current_instance_type['id'] ==
                              new_instance_type['id'])

        # NOTE(sirp): We don't want to force a customer to change their flavor
        # when Ops is migrating off of a failed host.
        if not same_instance_type and new_instance_type.get('disabled'):
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        if same_instance_type and flavor_id and self.cell_type != 'compute':
            raise exception.CannotResizeToSameFlavor()

        # ensure there is sufficient headroom for upsizes
        if flavor_id:
            self._check_quota_for_upsize(context, instance,
                                         current_instance_type,
                                         new_instance_type)

        instance.task_state = task_states.RESIZE_PREP
        instance.progress = 0
        instance.update(extra_instance_updates)
        instance.save(expected_task_state=[None])

        filter_properties = {'ignore_hosts': []}

        if not CONF.allow_resize_to_same_host:
            filter_properties['ignore_hosts'].append(instance.host)

        if self.cell_type == 'api':
            # Create migration record.
            self._resize_cells_support(context, instance,
                                       current_instance_type,
                                       new_instance_type)

        if not flavor_id:
            self._record_action_start(context, instance,
                                      instance_actions.MIGRATE)
        else:
            self._record_action_start(context, instance,
                                      instance_actions.RESIZE)

        # NOTE(sbauza): The migration script we provided in Newton should make
        # sure that all our instances are currently migrated to have an
        # attached RequestSpec object but let's consider that the operator only
        # half migrated all their instances in the meantime.
        try:
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
            request_spec.ignore_hosts = filter_properties['ignore_hosts']
        except exception.RequestSpecNotFound:
            # Some old instances can still have no RequestSpec object attached
            # to them, we need to support the old way
            request_spec = None

        # TODO(melwitt): We're not rechecking for strict quota here to guard
        # against going over quota during a race at this time because the
        # resource consumption for this operation is written to the database
        # by compute.
        scheduler_hint = {'filter_properties': filter_properties}
        self.compute_task_api.resize_instance(context, instance,
                extra_instance_updates, scheduler_hint=scheduler_hint,
                flavor=new_instance_type,
                clean_shutdown=clean_shutdown,
                request_spec=request_spec)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.PAUSED, vm_states.SUSPENDED])
    def shelve(self, context, instance, clean_shutdown=True):
        """Shelve an instance.

        Shuts down an instance and frees it up to be removed from the
        hypervisor.
        """
        instance.task_state = task_states.SHELVING
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.SHELVE)

        if not compute_utils.is_volume_backed_instance(context, instance):
            name = '%s-shelved' % instance.display_name
            image_meta = self._create_image(context, instance, name,
                    'snapshot')
            image_id = image_meta['id']
            self.compute_rpcapi.shelve_instance(context, instance=instance,
                    image_id=image_id, clean_shutdown=clean_shutdown)
        else:
            self.compute_rpcapi.shelve_offload_instance(context,
                    instance=instance, clean_shutdown=clean_shutdown)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SHELVED])
    def shelve_offload(self, context, instance, clean_shutdown=True):
        """Remove a shelved instance from the hypervisor."""
        instance.task_state = task_states.SHELVING_OFFLOADING
        instance.save(expected_task_state=[None])

        self.compute_rpcapi.shelve_offload_instance(context, instance=instance,
            clean_shutdown=clean_shutdown)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SHELVED,
        vm_states.SHELVED_OFFLOADED])
    def unshelve(self, context, instance):
        """Restore a shelved instance."""
        instance.task_state = task_states.UNSHELVING
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.UNSHELVE)

        try:
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
        except exception.RequestSpecNotFound:
            # Some old instances can still have no RequestSpec object attached
            # to them, we need to support the old way
            request_spec = None
        self.compute_task_api.unshelve_instance(context, instance,
                                                request_spec)

    @check_instance_lock
    def add_fixed_ip(self, context, instance, network_id):
        """Add fixed_ip from specified network to given instance."""
        self.compute_rpcapi.add_fixed_ip_to_instance(context,
                instance=instance, network_id=network_id)

    @check_instance_lock
    def remove_fixed_ip(self, context, instance, address):
        """Remove fixed_ip from specified network to given instance."""
        self.compute_rpcapi.remove_fixed_ip_from_instance(context,
                instance=instance, address=address)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def pause(self, context, instance):
        """Pause the given instance."""
        instance.task_state = task_states.PAUSING
        instance.save(expected_task_state=[None])
        self._record_action_start(context, instance, instance_actions.PAUSE)
        self.compute_rpcapi.pause_instance(context, instance)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.PAUSED])
    def unpause(self, context, instance):
        """Unpause the given instance."""
        instance.task_state = task_states.UNPAUSING
        instance.save(expected_task_state=[None])
        self._record_action_start(context, instance, instance_actions.UNPAUSE)
        self.compute_rpcapi.unpause_instance(context, instance)

    @check_instance_host
    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        return self.compute_rpcapi.get_diagnostics(context, instance=instance)

    @check_instance_host
    def get_instance_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        return self.compute_rpcapi.get_instance_diagnostics(context,
                                                            instance=instance)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def suspend(self, context, instance):
        """Suspend the given instance."""
        instance.task_state = task_states.SUSPENDING
        instance.save(expected_task_state=[None])
        self._record_action_start(context, instance, instance_actions.SUSPEND)
        self.compute_rpcapi.suspend_instance(context, instance)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.SUSPENDED])
    def resume(self, context, instance):
        """Resume the given instance."""
        instance.task_state = task_states.RESUMING
        instance.save(expected_task_state=[None])
        self._record_action_start(context, instance, instance_actions.RESUME)
        self.compute_rpcapi.resume_instance(context, instance)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.ERROR])
    def rescue(self, context, instance, rescue_password=None,
               rescue_image_ref=None, clean_shutdown=True):
        """Rescue the given instance."""

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)
        for bdm in bdms:
            if bdm.volume_id:
                vol = self.volume_api.get(context, bdm.volume_id)
                self.volume_api.check_attached(context, vol)
        if compute_utils.is_volume_backed_instance(context, instance, bdms):
            reason = _("Cannot rescue a volume-backed instance")
            raise exception.InstanceNotRescuable(instance_id=instance.uuid,
                                                 reason=reason)

        instance.task_state = task_states.RESCUING
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.RESCUE)

        self.compute_rpcapi.rescue_instance(context, instance=instance,
            rescue_password=rescue_password, rescue_image_ref=rescue_image_ref,
            clean_shutdown=clean_shutdown)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.RESCUED])
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        instance.task_state = task_states.UNRESCUING
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance, instance_actions.UNRESCUE)

        self.compute_rpcapi.unrescue_instance(context, instance=instance)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def set_admin_password(self, context, instance, password=None):
        """Set the root/admin password for the given instance.

        @param context: Nova auth context.
        @param instance: Nova instance object.
        @param password: The admin password for the instance.
        """
        instance.task_state = task_states.UPDATING_PASSWORD
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance,
                                  instance_actions.CHANGE_PASSWORD)

        self.compute_rpcapi.set_admin_password(context,
                                               instance=instance,
                                               new_pass=password)

    @check_instance_host
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_vnc_console(self, context, instance, console_type):
        """Get a url to an instance Console."""
        connect_info = self.compute_rpcapi.get_vnc_console(context,
                instance=instance, console_type=console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type,
                connect_info['host'], connect_info['port'],
                connect_info['internal_access_path'], instance.uuid,
                access_url=connect_info['access_url'])

        return {'url': connect_info['access_url']}

    @check_instance_host
    def get_vnc_connect_info(self, context, instance, console_type):
        """Used in a child cell to get console info."""
        connect_info = self.compute_rpcapi.get_vnc_console(context,
                instance=instance, console_type=console_type)
        return connect_info

    @check_instance_host
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_spice_console(self, context, instance, console_type):
        """Get a url to an instance Console."""
        connect_info = self.compute_rpcapi.get_spice_console(context,
                instance=instance, console_type=console_type)
        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type,
                connect_info['host'], connect_info['port'],
                connect_info['internal_access_path'], instance.uuid,
                access_url=connect_info['access_url'])

        return {'url': connect_info['access_url']}

    @check_instance_host
    def get_spice_connect_info(self, context, instance, console_type):
        """Used in a child cell to get console info."""
        connect_info = self.compute_rpcapi.get_spice_console(context,
                instance=instance, console_type=console_type)
        return connect_info

    @check_instance_host
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_rdp_console(self, context, instance, console_type):
        """Get a url to an instance Console."""
        connect_info = self.compute_rpcapi.get_rdp_console(context,
                instance=instance, console_type=console_type)
        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type,
                connect_info['host'], connect_info['port'],
                connect_info['internal_access_path'], instance.uuid,
                access_url=connect_info['access_url'])

        return {'url': connect_info['access_url']}

    @check_instance_host
    def get_rdp_connect_info(self, context, instance, console_type):
        """Used in a child cell to get console info."""
        connect_info = self.compute_rpcapi.get_rdp_console(context,
                instance=instance, console_type=console_type)
        return connect_info

    @check_instance_host
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_serial_console(self, context, instance, console_type):
        """Get a url to a serial console."""
        connect_info = self.compute_rpcapi.get_serial_console(context,
                instance=instance, console_type=console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type,
                connect_info['host'], connect_info['port'],
                connect_info['internal_access_path'], instance.uuid,
                access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_host
    def get_serial_console_connect_info(self, context, instance, console_type):
        """Used in a child cell to get serial console."""
        connect_info = self.compute_rpcapi.get_serial_console(context,
                instance=instance, console_type=console_type)
        return connect_info

    @check_instance_host
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_mks_console(self, context, instance, console_type):
        """Get a url to a MKS console."""
        connect_info = self.compute_rpcapi.get_mks_console(context,
                instance=instance, console_type=console_type)
        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type,
                connect_info['host'], connect_info['port'],
                connect_info['internal_access_path'], instance.uuid,
                access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_host
    def get_console_output(self, context, instance, tail_length=None):
        """Get console output for an instance."""
        return self.compute_rpcapi.get_console_output(context,
                instance=instance, tail_length=tail_length)

    def lock(self, context, instance):
        """Lock the given instance."""
        # Only update the lock if we are an admin (non-owner)
        is_owner = instance.project_id == context.project_id
        if instance.locked and is_owner:
            return

        context = context.elevated()
        LOG.debug('Locking', instance=instance)
        instance.locked = True
        instance.locked_by = 'owner' if is_owner else 'admin'
        instance.save()

    def is_expected_locked_by(self, context, instance):
        is_owner = instance.project_id == context.project_id
        expect_locked_by = 'owner' if is_owner else 'admin'
        locked_by = instance.locked_by
        if locked_by and locked_by != expect_locked_by:
            return False
        return True

    def unlock(self, context, instance):
        """Unlock the given instance."""
        context = context.elevated()
        LOG.debug('Unlocking', instance=instance)
        instance.locked = False
        instance.locked_by = None
        instance.save()

    @check_instance_lock
    @check_instance_cell
    def reset_network(self, context, instance):
        """Reset networking on the instance."""
        self.compute_rpcapi.reset_network(context, instance=instance)

    @check_instance_lock
    @check_instance_cell
    def inject_network_info(self, context, instance):
        """Inject network info for the instance."""
        self.compute_rpcapi.inject_network_info(context, instance=instance)

    def _create_volume_bdm(self, context, instance, device, volume_id,
                           disk_bus, device_type, is_local_creation=False,
                           tag=None):
        if is_local_creation:
            # when the creation is done locally we can't specify the device
            # name as we do not have a way to check that the name specified is
            # a valid one.
            # We leave the setting of that value when the actual attach
            # happens on the compute manager
            # NOTE(artom) Local attach (to a shelved-offload instance) cannot
            # support device tagging because we have no way to call the compute
            # manager to check that it supports device tagging. In fact, we
            # don't even know which computer manager the instance will
            # eventually end up on when it's unshelved.
            volume_bdm = objects.BlockDeviceMapping(
                context=context,
                source_type='volume', destination_type='volume',
                instance_uuid=instance.uuid, boot_index=None,
                volume_id=volume_id,
                device_name=None, guest_format=None,
                disk_bus=disk_bus, device_type=device_type)
            volume_bdm.create()
        else:
            # NOTE(vish): This is done on the compute host because we want
            #             to avoid a race where two devices are requested at
            #             the same time. When db access is removed from
            #             compute, the bdm will be created here and we will
            #             have to make sure that they are assigned atomically.
            volume_bdm = self.compute_rpcapi.reserve_block_device_name(
                context, instance, device, volume_id, disk_bus=disk_bus,
                device_type=device_type, tag=tag)
        return volume_bdm

    def _check_attach_and_reserve_volume(self, context, volume_id, instance):
        volume = self.volume_api.get(context, volume_id)
        self.volume_api.check_availability_zone(context, volume,
                                                instance=instance)
        self.volume_api.reserve_volume(context, volume_id)

        return volume

    def _attach_volume(self, context, instance, volume_id, device,
                       disk_bus, device_type, tag=None):
        """Attach an existing volume to an existing instance.

        This method is separated to make it possible for cells version
        to override it.
        """
        volume_bdm = self._create_volume_bdm(
            context, instance, device, volume_id, disk_bus=disk_bus,
            device_type=device_type, tag=tag)
        try:
            self._check_attach_and_reserve_volume(context, volume_id, instance)
            self.compute_rpcapi.attach_volume(context, instance, volume_bdm)
        except Exception:
            with excutils.save_and_reraise_exception():
                volume_bdm.destroy()

        return volume_bdm.device_name

    def _attach_volume_shelved_offloaded(self, context, instance, volume_id,
                                         device, disk_bus, device_type):
        """Attach an existing volume to an instance in shelved offloaded state.

        Attaching a volume for an instance in shelved offloaded state requires
        to perform the regular check to see if we can attach and reserve the
        volume then we need to call the attach method on the volume API
        to mark the volume as 'in-use'.
        The instance at this stage is not managed by a compute manager
        therefore the actual attachment will be performed once the
        instance will be unshelved.
        """

        volume_bdm = self._create_volume_bdm(
            context, instance, device, volume_id, disk_bus=disk_bus,
            device_type=device_type, is_local_creation=True)
        try:
            self._check_attach_and_reserve_volume(context, volume_id, instance)
            self.volume_api.attach(context,
                                   volume_id,
                                   instance.uuid,
                                   device)
        except Exception:
            with excutils.save_and_reraise_exception():
                volume_bdm.destroy()

        return volume_bdm.device_name

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.STOPPED, vm_states.RESIZED,
                                    vm_states.SOFT_DELETED, vm_states.SHELVED,
                                    vm_states.SHELVED_OFFLOADED])
    def attach_volume(self, context, instance, volume_id, device=None,
                      disk_bus=None, device_type=None, tag=None):
        """Attach an existing volume to an existing instance."""
        # NOTE(vish): Fail fast if the device is not going to pass. This
        #             will need to be removed along with the test if we
        #             change the logic in the manager for what constitutes
        #             a valid device.
        if device and not block_device.match_device(device):
            raise exception.InvalidDevicePath(path=device)

        is_shelved_offloaded = instance.vm_state == vm_states.SHELVED_OFFLOADED
        if is_shelved_offloaded:
            if tag:
                # NOTE(artom) Local attach (to a shelved-offload instance)
                # cannot support device tagging because we have no way to call
                # the compute manager to check that it supports device tagging.
                # In fact, we don't even know which computer manager the
                # instance will eventually end up on when it's unshelved.
                raise exception.VolumeTaggedAttachToShelvedNotSupported()
            return self._attach_volume_shelved_offloaded(context,
                                                         instance,
                                                         volume_id,
                                                         device,
                                                         disk_bus,
                                                         device_type)

        return self._attach_volume(context, instance, volume_id, device,
                                   disk_bus, device_type, tag=tag)

    def _detach_volume(self, context, instance, volume):
        """Detach volume from instance.

        This method is separated to make it easier for cells version
        to override.
        """
        try:
            self.volume_api.begin_detaching(context, volume['id'])
        except exception.InvalidInput as exc:
            raise exception.InvalidVolume(reason=exc.format_message())
        attachments = volume.get('attachments', {})
        attachment_id = None
        if attachments and instance.uuid in attachments:
            attachment_id = attachments[instance.uuid]['attachment_id']
        self.compute_rpcapi.detach_volume(context, instance=instance,
                volume_id=volume['id'], attachment_id=attachment_id)

    def _detach_volume_shelved_offloaded(self, context, instance, volume):
        """Detach a volume from an instance in shelved offloaded state.

        If the instance is shelved offloaded we just need to cleanup volume
        calling the volume api detach, the volume api terminate_connection
        and delete the bdm record.
        If the volume has delete_on_termination option set then we call the
        volume api delete as well.
        """
        try:
            self.volume_api.begin_detaching(context, volume['id'])
        except exception.InvalidInput as exc:
            raise exception.InvalidVolume(reason=exc.format_message())
        bdms = [objects.BlockDeviceMapping.get_by_volume_id(
                context, volume['id'], instance.uuid)]
        self._local_cleanup_bdm_volumes(bdms, instance, context)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.STOPPED, vm_states.RESIZED,
                                    vm_states.SOFT_DELETED, vm_states.SHELVED,
                                    vm_states.SHELVED_OFFLOADED])
    def detach_volume(self, context, instance, volume):
        """Detach a volume from an instance."""
        if instance.vm_state == vm_states.SHELVED_OFFLOADED:
            self._detach_volume_shelved_offloaded(context, instance, volume)
        else:
            self._detach_volume(context, instance, volume)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.RESIZED])
    def swap_volume(self, context, instance, old_volume, new_volume):
        """Swap volume attached to an instance."""
        # The caller likely got the instance from volume['attachments']
        # in the first place, but let's sanity check.
        if not old_volume.get('attachments', {}).get(instance.uuid):
            msg = _("Old volume is attached to a different instance.")
            raise exception.InvalidVolume(reason=msg)
        if new_volume['attach_status'] == 'attached':
            msg = _("New volume must be detached in order to swap.")
            raise exception.InvalidVolume(reason=msg)
        if int(new_volume['size']) < int(old_volume['size']):
            msg = _("New volume must be the same size or larger.")
            raise exception.InvalidVolume(reason=msg)
        self.volume_api.check_availability_zone(context, new_volume,
                                                instance=instance)
        try:
            self.volume_api.begin_detaching(context, old_volume['id'])
        except exception.InvalidInput as exc:
            raise exception.InvalidVolume(reason=exc.format_message())

        # Get the BDM for the attached (old) volume so we can tell if it was
        # attached with the new-style Cinder 3.27 API.
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
            context, old_volume['id'], instance.uuid)
        new_attachment_id = None
        if bdm.attachment_id is None:
            # This is an old-style attachment so reserve the new volume before
            # we cast to the compute host.
            self.volume_api.reserve_volume(context, new_volume['id'])
        else:
            # This is a new-style attachment so for the volume that we are
            # going to swap to, create a new volume attachment.
            new_attachment_id = self.volume_api.attachment_create(
                context, new_volume['id'], instance.uuid)['id']

        try:
            self.compute_rpcapi.swap_volume(
                    context, instance=instance,
                    old_volume_id=old_volume['id'],
                    new_volume_id=new_volume['id'],
                    new_attachment_id=new_attachment_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.volume_api.roll_detaching(context, old_volume['id'])
                if new_attachment_id is None:
                    self.volume_api.unreserve_volume(context, new_volume['id'])
                else:
                    self.volume_api.attachment_delete(
                        context, new_attachment_id)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.STOPPED],
                          task_state=[None])
    def attach_interface(self, context, instance, network_id, port_id,
                         requested_ip, tag=None):
        """Use hotplug to add an network adapter to an instance."""
        return self.compute_rpcapi.attach_interface(context,
            instance=instance, network_id=network_id, port_id=port_id,
            requested_ip=requested_ip, tag=tag)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.STOPPED],
                          task_state=[None])
    def detach_interface(self, context, instance, port_id):
        """Detach an network adapter from an instance."""
        self.compute_rpcapi.detach_interface(context, instance=instance,
            port_id=port_id)

    def get_instance_metadata(self, context, instance):
        """Get all metadata associated with an instance."""
        return self.db.instance_metadata_get(context, instance.uuid)

    def get_all_instance_metadata(self, context, search_filts):
        return self._get_all_instance_metadata(
            context, search_filts, metadata_type='metadata')

    def get_all_system_metadata(self, context, search_filts):
        return self._get_all_instance_metadata(
            context, search_filts, metadata_type='system_metadata')

    def _get_all_instance_metadata(self, context, search_filts, metadata_type):
        """Get all metadata."""
        instances = self._get_instances_by_filters(context, filters={},
                                                   sort_keys=['created_at'],
                                                   sort_dirs=['desc'])
        return utils.filter_and_format_resource_metadata('instance', instances,
                search_filts, metadata_type)

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.SUSPENDED, vm_states.STOPPED],
                          task_state=None)
    def delete_instance_metadata(self, context, instance, key):
        """Delete the given metadata item from an instance."""
        instance.delete_metadata_key(key)
        self.compute_rpcapi.change_instance_metadata(context,
                                                     instance=instance,
                                                     diff={key: ['-']})

    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED,
                                    vm_states.SUSPENDED, vm_states.STOPPED],
                          task_state=None)
    def update_instance_metadata(self, context, instance,
                                 metadata, delete=False):
        """Updates or creates instance metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        orig = dict(instance.metadata)
        if delete:
            _metadata = metadata
        else:
            _metadata = dict(instance.metadata)
            _metadata.update(metadata)

        self._check_metadata_properties_quota(context, _metadata)
        instance.metadata = _metadata
        instance.save()
        diff = _diff_dict(orig, instance.metadata)
        self.compute_rpcapi.change_instance_metadata(context,
                                                     instance=instance,
                                                     diff=diff)
        return _metadata

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.PAUSED])
    def live_migrate(self, context, instance, block_migration,
                     disk_over_commit, host_name, force=None, async=False):
        """Migrate a server lively to a new host."""
        LOG.debug("Going to try to live migrate instance to %s",
                  host_name or "another host", instance=instance)

        if host_name:
            # Validate the specified host before changing the instance task
            # state.
            nodes = objects.ComputeNodeList.get_all_by_host(context, host_name)

        instance.task_state = task_states.MIGRATING
        instance.save(expected_task_state=[None])

        self._record_action_start(context, instance,
                                  instance_actions.LIVE_MIGRATION)

        self.consoleauth_rpcapi.delete_tokens_for_instance(
            context, instance.uuid)

        try:
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
        except exception.RequestSpecNotFound:
            # Some old instances can still have no RequestSpec object attached
            # to them, we need to support the old way
            request_spec = None

        # NOTE(sbauza): Force is a boolean by the new related API version
        if force is False and host_name:
            # Unset the host to make sure we call the scheduler
            # from the conductor LiveMigrationTask. Yes this is tightly-coupled
            # to behavior in conductor and not great.
            host_name = None
            # FIXME(sbauza): Since only Ironic driver uses more than one
            # compute per service but doesn't support live migrations,
            # let's provide the first one.
            target = nodes[0]
            if request_spec:
                # TODO(sbauza): Hydrate a fake spec for old instances not yet
                # having a request spec attached to them (particularly true for
                # cells v1). For the moment, let's keep the same behaviour for
                # all the instances but provide the destination only if a spec
                # is found.
                destination = objects.Destination(
                    host=target.host,
                    node=target.hypervisor_hostname
                )
                # This is essentially a hint to the scheduler to only consider
                # the specified host but still run it through the filters.
                request_spec.requested_destination = destination

        try:
            self.compute_task_api.live_migrate_instance(context, instance,
                host_name, block_migration=block_migration,
                disk_over_commit=disk_over_commit,
                request_spec=request_spec, async=async)
        except oslo_exceptions.MessagingTimeout as messaging_timeout:
            with excutils.save_and_reraise_exception():
                # NOTE(pkoniszewski): It is possible that MessagingTimeout
                # occurs, but LM will still be in progress, so write
                # instance fault to database
                compute_utils.add_instance_fault_from_exc(context,
                                                          instance,
                                                          messaging_timeout)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE],
                          task_state=[task_states.MIGRATING])
    def live_migrate_force_complete(self, context, instance, migration_id):
        """Force live migration to complete.

        :param context: Security context
        :param instance: The instance that is being migrated
        :param migration_id: ID of ongoing migration

        """
        LOG.debug("Going to try to force live migration to complete",
                  instance=instance)

        # NOTE(pkoniszewski): Get migration object to check if there is ongoing
        # live migration for particular instance. Also pass migration id to
        # compute to double check and avoid possible race condition.
        migration = objects.Migration.get_by_id_and_instance(
            context, migration_id, instance.uuid)
        if migration.status != 'running':
            raise exception.InvalidMigrationState(migration_id=migration_id,
                                                  instance_uuid=instance.uuid,
                                                  state=migration.status,
                                                  method='force complete')

        self._record_action_start(
            context, instance, instance_actions.LIVE_MIGRATION_FORCE_COMPLETE)

        self.compute_rpcapi.live_migration_force_complete(
            context, instance, migration)

    @check_instance_lock
    @check_instance_cell
    @check_instance_state(task_state=[task_states.MIGRATING])
    def live_migrate_abort(self, context, instance, migration_id):
        """Abort an in-progress live migration.

        :param context: Security context
        :param instance: The instance that is being migrated
        :param migration_id: ID of in-progress live migration

        """
        migration = objects.Migration.get_by_id_and_instance(context,
                    migration_id, instance.uuid)
        LOG.debug("Going to cancel live migration %s",
                  migration.id, instance=instance)

        if migration.status != 'running':
            raise exception.InvalidMigrationState(migration_id=migration_id,
                    instance_uuid=instance.uuid,
                    state=migration.status,
                    method='abort live migration')
        self._record_action_start(context, instance,
                                  instance_actions.LIVE_MIGRATION_CANCEL)

        self.compute_rpcapi.live_migration_abort(context,
                instance, migration.id)

    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.ERROR])
    def evacuate(self, context, instance, host, on_shared_storage,
                 admin_password=None, force=None):
        """Running evacuate to target host.

        Checking vm compute host state, if the host not in expected_state,
        raising an exception.

        :param instance: The instance to evacuate
        :param host: Target host. if not set, the scheduler will pick up one
        :param on_shared_storage: True if instance files on shared storage
        :param admin_password: password to set on rebuilt instance
        :param force: Force the evacuation to the specific host target

        """
        LOG.debug('vm evacuation scheduled', instance=instance)
        inst_host = instance.host
        service = objects.Service.get_by_compute_host(context, inst_host)
        if self.servicegroup_api.service_is_up(service):
            LOG.error('Instance compute service state on %s '
                      'expected to be down, but it was up.', inst_host)
            raise exception.ComputeServiceInUse(host=inst_host)

        instance.task_state = task_states.REBUILDING
        instance.save(expected_task_state=[None])
        self._record_action_start(context, instance, instance_actions.EVACUATE)

        # NOTE(danms): Create this as a tombstone for the source compute
        # to find and cleanup. No need to pass it anywhere else.
        migration = objects.Migration(context,
                                      source_compute=instance.host,
                                      source_node=instance.node,
                                      instance_uuid=instance.uuid,
                                      status='accepted',
                                      migration_type='evacuation')
        if host:
            migration.dest_compute = host
        migration.create()

        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, "evacuate")

        try:
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                context, instance.uuid)
        except exception.RequestSpecNotFound:
            # Some old instances can still have no RequestSpec object attached
            # to them, we need to support the old way
            request_spec = None

        # NOTE(sbauza): Force is a boolean by the new related API version
        if force is False and host:
            nodes = objects.ComputeNodeList.get_all_by_host(context, host)
            # NOTE(sbauza): Unset the host to make sure we call the scheduler
            host = None
            # FIXME(sbauza): Since only Ironic driver uses more than one
            # compute per service but doesn't support evacuations,
            # let's provide the first one.
            target = nodes[0]
            if request_spec:
                # TODO(sbauza): Hydrate a fake spec for old instances not yet
                # having a request spec attached to them (particularly true for
                # cells v1). For the moment, let's keep the same behaviour for
                # all the instances but provide the destination only if a spec
                # is found.
                destination = objects.Destination(
                    host=target.host,
                    node=target.hypervisor_hostname
                )
                request_spec.requested_destination = destination

        return self.compute_task_api.rebuild_instance(context,
                       instance=instance,
                       new_pass=admin_password,
                       injected_files=None,
                       image_ref=None,
                       orig_image_ref=None,
                       orig_sys_metadata=None,
                       bdms=None,
                       recreate=True,
                       on_shared_storage=on_shared_storage,
                       host=host,
                       request_spec=request_spec,
                       )

    def get_migrations(self, context, filters):
        """Get all migrations for the given filters."""
        load_cells()

        migrations = []
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            with nova_context.target_cell(context, cell) as cctxt:
                migrations.extend(objects.MigrationList.get_by_filters(
                    cctxt, filters).objects)
        return objects.MigrationList(objects=migrations)

    def get_migrations_in_progress_by_instance(self, context, instance_uuid,
                                               migration_type=None):
        """Get all migrations of an instance in progress."""
        return objects.MigrationList.get_in_progress_by_instance(
                context, instance_uuid, migration_type)

    def get_migration_by_id_and_instance(self, context,
                                         migration_id, instance_uuid):
        """Get the migration of an instance by id."""
        return objects.Migration.get_by_id_and_instance(
                context, migration_id, instance_uuid)

    def _get_bdm_by_volume_id(self, context, volume_id, expected_attrs=None):
        """Retrieve a BDM without knowing its cell.

        .. note:: The context will be targeted to the cell in which the
            BDM is found, if any.

        :param context: The API request context.
        :param volume_id: The ID of the volume.
        :param expected_attrs: list of any additional attributes that should
            be joined when the BDM is loaded from the database.
        :raises: nova.exception.VolumeBDMNotFound if not found in any cell
        """
        load_cells()
        for cell in CELLS:
            nova_context.set_target_cell(context, cell)
            try:
                return objects.BlockDeviceMapping.get_by_volume(
                    context, volume_id, expected_attrs=expected_attrs)
            except exception.NotFound:
                continue
        raise exception.VolumeBDMNotFound(volume_id=volume_id)

    def volume_snapshot_create(self, context, volume_id, create_info):
        bdm = self._get_bdm_by_volume_id(
            context, volume_id, expected_attrs=['instance'])

        # We allow creating the snapshot in any vm_state as long as there is
        # no task being performed on the instance and it has a host.
        @check_instance_host
        @check_instance_state(vm_state=None)
        def do_volume_snapshot_create(self, context, instance):
            self.compute_rpcapi.volume_snapshot_create(context, instance,
                    volume_id, create_info)
            snapshot = {
                'snapshot': {
                    'id': create_info.get('id'),
                    'volumeId': volume_id
                }
            }
            return snapshot

        return do_volume_snapshot_create(self, context, bdm.instance)

    def volume_snapshot_delete(self, context, volume_id, snapshot_id,
                               delete_info):
        bdm = self._get_bdm_by_volume_id(
            context, volume_id, expected_attrs=['instance'])

        # We allow deleting the snapshot in any vm_state as long as there is
        # no task being performed on the instance and it has a host.
        @check_instance_host
        @check_instance_state(vm_state=None)
        def do_volume_snapshot_delete(self, context, instance):
            self.compute_rpcapi.volume_snapshot_delete(context, instance,
                    volume_id, snapshot_id, delete_info)

        do_volume_snapshot_delete(self, context, bdm.instance)

    def external_instance_event(self, api_context, instances, events):
        # NOTE(danms): The external API consumer just provides events,
        # but doesn't know where they go. We need to collate lists
        # by the host the affected instance is on and dispatch them
        # according to host
        instances_by_host = collections.defaultdict(list)
        events_by_host = collections.defaultdict(list)
        hosts_by_instance = collections.defaultdict(list)
        cell_contexts_by_host = {}
        for instance in instances:
            # instance._context is used here since it's already targeted to
            # the cell that the instance lives in, and we need to use that
            # cell context to lookup any migrations associated to the instance.
            for host in self._get_relevant_hosts(instance._context, instance):
                # NOTE(danms): All instances on a host must have the same
                # mapping, so just use that
                # NOTE(mdbooth): We don't currently support migrations between
                # cells, and given that the Migration record is hosted in the
                # cell _get_relevant_hosts will likely have to change before we
                # do. Consequently we can currently assume that the context for
                # both the source and destination hosts of a migration is the
                # same.
                if host not in cell_contexts_by_host:
                    cell_contexts_by_host[host] = instance._context

                instances_by_host[host].append(instance)
                hosts_by_instance[instance.uuid].append(host)

        for event in events:
            if event.name == 'volume-extended':
                # Volume extend is a user-initiated operation starting in the
                # Block Storage service API. We record an instance action so
                # the user can monitor the operation to completion.
                host = hosts_by_instance[event.instance_uuid][0]
                cell_context = cell_contexts_by_host[host]
                objects.InstanceAction.action_start(
                    cell_context, event.instance_uuid,
                    instance_actions.EXTEND_VOLUME, want_result=False)
            for host in hosts_by_instance[event.instance_uuid]:
                events_by_host[host].append(event)

        for host in instances_by_host:
            cell_context = cell_contexts_by_host[host]

            # TODO(salv-orlando): Handle exceptions raised by the rpc api layer
            # in order to ensure that a failure in processing events on a host
            # will not prevent processing events on other hosts
            self.compute_rpcapi.external_instance_event(
                cell_context, instances_by_host[host], events_by_host[host],
                host=host)

    def _get_relevant_hosts(self, context, instance):
        hosts = set()
        hosts.add(instance.host)
        if instance.migration_context is not None:
            migration_id = instance.migration_context.migration_id
            migration = objects.Migration.get_by_id(context, migration_id)
            hosts.add(migration.dest_compute)
            hosts.add(migration.source_compute)
            LOG.debug('Instance %(instance)s is migrating, '
                      'copying events to all relevant hosts: '
                      '%(hosts)s', {'instance': instance.uuid,
                                    'hosts': hosts})
        return hosts

    def get_instance_host_status(self, instance):
        if instance.host:
            try:
                service = [service for service in instance.services if
                           service.binary == 'nova-compute'][0]
                if service.forced_down:
                    host_status = fields_obj.HostStatus.DOWN
                elif service.disabled:
                    host_status = fields_obj.HostStatus.MAINTENANCE
                else:
                    alive = self.servicegroup_api.service_is_up(service)
                    host_status = ((alive and fields_obj.HostStatus.UP) or
                                   fields_obj.HostStatus.UNKNOWN)
            except IndexError:
                host_status = fields_obj.HostStatus.NONE
        else:
            host_status = fields_obj.HostStatus.NONE
        return host_status

    def get_instances_host_statuses(self, instance_list):
        host_status_dict = dict()
        host_statuses = dict()
        for instance in instance_list:
            if instance.host:
                if instance.host not in host_status_dict:
                    host_status = self.get_instance_host_status(instance)
                    host_status_dict[instance.host] = host_status
                else:
                    host_status = host_status_dict[instance.host]
            else:
                host_status = fields_obj.HostStatus.NONE
            host_statuses[instance.uuid] = host_status
        return host_statuses


def target_host_cell(fn):
    """Target a host-based function to a cell.

    Expects to wrap a function of signature:

       func(self, context, host, ...)
    """

    @functools.wraps(fn)
    def targeted(self, context, host, *args, **kwargs):
        mapping = objects.HostMapping.get_by_host(context, host)
        nova_context.set_target_cell(context, mapping.cell_mapping)
        return fn(self, context, host, *args, **kwargs)
    return targeted


def _find_service_in_cell(context, service_id=None, service_host=None):
    """Find a service by id or hostname by searching all cells.

    If one matching service is found, return it. If none or multiple
    are found, raise an exception.

    :param context: A context.RequestContext
    :param service_id: If not none, the DB ID of the service to find
    :param service_host: If not None, the hostname of the service to find
    :returns: An objects.Service
    :raises: ServiceNotUnique if multiple matching IDs are found
    :raises: NotFound if no matches are found
    :raises: NovaException if called with neither search option
    """

    load_cells()
    service = None
    found_in_cell = None

    is_uuid = False
    if service_id is not None:
        is_uuid = uuidutils.is_uuid_like(service_id)
        if is_uuid:
            lookup_fn = lambda c: objects.Service.get_by_uuid(c, service_id)
        else:
            lookup_fn = lambda c: objects.Service.get_by_id(c, service_id)
    elif service_host is not None:
        lookup_fn = lambda c: (
            objects.Service.get_by_compute_host(c, service_host))
    else:
        LOG.exception('_find_service_in_cell called with no search parameters')
        # This is intentionally cryptic so we don't leak implementation details
        # out of the API.
        raise exception.NovaException()

    for cell in CELLS:
        # NOTE(danms): Services can be in cell0, so don't skip it here
        try:
            with nova_context.target_cell(context, cell) as cctxt:
                cell_service = lookup_fn(cctxt)
        except exception.NotFound:
            # NOTE(danms): Keep looking in other cells
            continue
        if service and cell_service:
            raise exception.ServiceNotUnique()
        service = cell_service
        found_in_cell = cell
        if service and is_uuid:
            break

    if service:
        # NOTE(danms): Set the cell on the context so it remains
        # when we return to our caller
        nova_context.set_target_cell(context, found_in_cell)
        return service
    else:
        raise exception.NotFound()


class HostAPI(base.Base):
    """Sub-set of the Compute Manager API for managing host operations."""

    def __init__(self, rpcapi=None):
        self.rpcapi = rpcapi or compute_rpcapi.ComputeAPI()
        self.servicegroup_api = servicegroup.API()
        super(HostAPI, self).__init__()

    def _assert_host_exists(self, context, host_name, must_be_up=False):
        """Raise HostNotFound if compute host doesn't exist."""
        service = objects.Service.get_by_compute_host(context, host_name)
        if not service:
            raise exception.HostNotFound(host=host_name)
        if must_be_up and not self.servicegroup_api.service_is_up(service):
            raise exception.ComputeServiceUnavailable(host=host_name)
        return service['host']

    @wrap_exception()
    @target_host_cell
    def set_host_enabled(self, context, host_name, enabled):
        """Sets the specified host's ability to accept new instances."""
        host_name = self._assert_host_exists(context, host_name)
        payload = {'host_name': host_name, 'enabled': enabled}
        compute_utils.notify_about_host_update(context,
                                               'set_enabled.start',
                                               payload)
        result = self.rpcapi.set_host_enabled(context, enabled=enabled,
                host=host_name)
        compute_utils.notify_about_host_update(context,
                                               'set_enabled.end',
                                               payload)
        return result

    @target_host_cell
    def get_host_uptime(self, context, host_name):
        """Returns the result of calling "uptime" on the target host."""
        host_name = self._assert_host_exists(context, host_name,
                         must_be_up=True)
        return self.rpcapi.get_host_uptime(context, host=host_name)

    @wrap_exception()
    @target_host_cell
    def host_power_action(self, context, host_name, action):
        """Reboots, shuts down or powers up the host."""
        host_name = self._assert_host_exists(context, host_name)
        payload = {'host_name': host_name, 'action': action}
        compute_utils.notify_about_host_update(context,
                                               'power_action.start',
                                               payload)
        result = self.rpcapi.host_power_action(context, action=action,
                host=host_name)
        compute_utils.notify_about_host_update(context,
                                               'power_action.end',
                                               payload)
        return result

    @wrap_exception()
    @target_host_cell
    def set_host_maintenance(self, context, host_name, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        host_name = self._assert_host_exists(context, host_name)
        payload = {'host_name': host_name, 'mode': mode}
        compute_utils.notify_about_host_update(context,
                                               'set_maintenance.start',
                                               payload)
        result = self.rpcapi.host_maintenance_mode(context,
                host_param=host_name, mode=mode, host=host_name)
        compute_utils.notify_about_host_update(context,
                                               'set_maintenance.end',
                                               payload)
        return result

    def service_get_all(self, context, filters=None, set_zones=False,
                        all_cells=False):
        """Returns a list of services, optionally filtering the results.

        If specified, 'filters' should be a dictionary containing services
        attributes and matching values.  Ie, to get a list of services for
        the 'compute' topic, use filters={'topic': 'compute'}.

        If all_cells=True, then scan all cells and merge the results.
        """
        if filters is None:
            filters = {}
        disabled = filters.pop('disabled', None)
        if 'availability_zone' in filters:
            set_zones = True

        # NOTE(danms): Eventually this all_cells nonsense should go away
        # and we should always iterate over the cells. However, certain
        # callers need the legacy behavior for now.
        if all_cells:
            services = []
            service_dict = nova_context.scatter_gather_all_cells(context,
                objects.ServiceList.get_all, disabled, set_zones=set_zones)
            for service in service_dict.values():
                if service not in (nova_context.did_not_respond_sentinel,
                                   nova_context.raised_exception_sentinel):
                    services.extend(service)
        else:
            services = objects.ServiceList.get_all(context, disabled,
                                                   set_zones=set_zones)
        ret_services = []
        for service in services:
            for key, val in filters.items():
                if service[key] != val:
                    break
            else:
                # All filters matched.
                ret_services.append(service)
        return ret_services

    def service_get_by_id(self, context, service_id):
        """Get service entry for the given service id or uuid."""
        try:
            return _find_service_in_cell(context, service_id=service_id)
        except exception.NotFound:
            raise exception.ServiceNotFound(service_id=service_id)

    @target_host_cell
    def service_get_by_compute_host(self, context, host_name):
        """Get service entry for the given compute hostname."""
        return objects.Service.get_by_compute_host(context, host_name)

    def _service_update(self, context, host_name, binary, params_to_update):
        """Performs the actual service update operation."""
        service = objects.Service.get_by_args(context, host_name, binary)
        service.update(params_to_update)
        service.save()
        return service

    @target_host_cell
    def service_update(self, context, host_name, binary, params_to_update):
        """Enable / Disable a service.

        For compute services, this stops new builds and migrations going to
        the host.
        """
        return self._service_update(context, host_name, binary,
                                    params_to_update)

    def _service_delete(self, context, service_id):
        """Performs the actual Service deletion operation."""
        try:
            service = _find_service_in_cell(context, service_id=service_id)
        except exception.NotFound:
            raise exception.ServiceNotFound(service_id=service_id)
        service.destroy()

    def service_delete(self, context, service_id):
        """Deletes the specified service found via id or uuid."""
        self._service_delete(context, service_id)

    @target_host_cell
    def instance_get_all_by_host(self, context, host_name):
        """Return all instances on the given host."""
        return objects.InstanceList.get_by_host(context, host_name)

    def task_log_get_all(self, context, task_name, period_beginning,
                         period_ending, host=None, state=None):
        """Return the task logs within a given range, optionally
        filtering by host and/or state.
        """
        return self.db.task_log_get_all(context, task_name,
                                        period_beginning,
                                        period_ending,
                                        host=host,
                                        state=state)

    def compute_node_get(self, context, compute_id):
        """Return compute node entry for particular integer ID or UUID."""
        load_cells()

        # NOTE(danms): Unfortunately this API exposes database identifiers
        # which means we really can't do something efficient here
        is_uuid = uuidutils.is_uuid_like(compute_id)
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            with nova_context.target_cell(context, cell) as cctxt:
                try:
                    if is_uuid:
                        # NOTE(mriedem): We wouldn't have to loop over cells if
                        # we stored the ComputeNode.uuid in the HostMapping but
                        # we don't have that. It could be added but would
                        # require an online data migration to update existing
                        # host mappings.
                        return objects.ComputeNode.get_by_uuid(cctxt,
                                                               compute_id)
                    return objects.ComputeNode.get_by_id(cctxt,
                                                         int(compute_id))
                except exception.ComputeHostNotFound:
                    # NOTE(danms): Keep looking in other cells
                    continue

        raise exception.ComputeHostNotFound(host=compute_id)

    def compute_node_get_all(self, context, limit=None, marker=None):
        load_cells()

        computes = []
        uuid_marker = marker and uuidutils.is_uuid_like(marker)
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            with nova_context.target_cell(context, cell) as cctxt:

                # If we have a marker and it's a uuid, see if the compute node
                # is in this cell.
                if marker and uuid_marker:
                    try:
                        compute_marker = objects.ComputeNode.get_by_uuid(
                            cctxt, marker)
                        # we found the marker compute node, so use it's id
                        # for the actual marker for paging in this cell's db
                        marker = compute_marker.id
                    except exception.ComputeHostNotFound:
                        # The marker node isn't in this cell so keep looking.
                        continue

                try:
                    cell_computes = objects.ComputeNodeList.get_by_pagination(
                        cctxt, limit=limit, marker=marker)
                except exception.MarkerNotFound:
                    # NOTE(danms): Keep looking through cells
                    continue
                computes.extend(cell_computes)
                # NOTE(danms): We must have found the marker, so continue on
                # without one
                marker = None
                if limit:
                    limit -= len(cell_computes)
                    if limit <= 0:
                        break

        if marker is not None and len(computes) == 0:
            # NOTE(danms): If we did not find the marker in any cell,
            # mimic the db_api behavior here.
            raise exception.MarkerNotFound(marker=marker)

        return objects.ComputeNodeList(objects=computes)

    def compute_node_search_by_hypervisor(self, context, hypervisor_match):
        load_cells()

        computes = []
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            with nova_context.target_cell(context, cell) as cctxt:
                cell_computes = objects.ComputeNodeList.get_by_hypervisor(
                    cctxt, hypervisor_match)
            computes.extend(cell_computes)
        return objects.ComputeNodeList(objects=computes)

    def compute_node_statistics(self, context):
        load_cells()

        cell_stats = []
        for cell in CELLS:
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            with nova_context.target_cell(context, cell) as cctxt:
                cell_stats.append(self.db.compute_node_statistics(cctxt))

        if cell_stats:
            keys = cell_stats[0].keys()
            return {k: sum(stats[k] for stats in cell_stats)
                    for k in keys}
        else:
            return {}


class InstanceActionAPI(base.Base):
    """Sub-set of the Compute Manager API for managing instance actions."""

    def actions_get(self, context, instance):
        return objects.InstanceActionList.get_by_instance_uuid(
            context, instance.uuid)

    def action_get_by_request_id(self, context, instance, request_id):
        return objects.InstanceAction.get_by_request_id(
            context, instance.uuid, request_id)

    def action_events_get(self, context, instance, action_id):
        return objects.InstanceActionEventList.get_by_action(
            context, action_id)


class AggregateAPI(base.Base):
    """Sub-set of the Compute Manager API for managing host aggregates."""
    def __init__(self, **kwargs):
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.scheduler_client = scheduler_client.SchedulerClient()
        super(AggregateAPI, self).__init__(**kwargs)

    @wrap_exception()
    def create_aggregate(self, context, aggregate_name, availability_zone):
        """Creates the model for the aggregate."""

        aggregate = objects.Aggregate(context=context)
        aggregate.name = aggregate_name
        if availability_zone:
            aggregate.metadata = {'availability_zone': availability_zone}
        aggregate.create()
        self.scheduler_client.update_aggregates(context, [aggregate])
        return aggregate

    def get_aggregate(self, context, aggregate_id):
        """Get an aggregate by id."""
        return objects.Aggregate.get_by_id(context, aggregate_id)

    def get_aggregate_list(self, context):
        """Get all the aggregates."""
        return objects.AggregateList.get_all(context)

    def get_aggregates_by_host(self, context, compute_host):
        """Get all the aggregates where the given host is presented."""
        return objects.AggregateList.get_by_host(context, compute_host)

    @wrap_exception()
    def update_aggregate(self, context, aggregate_id, values):
        """Update the properties of an aggregate."""
        aggregate = objects.Aggregate.get_by_id(context, aggregate_id)
        if 'name' in values:
            aggregate.name = values.pop('name')
            aggregate.save()
        self.is_safe_to_update_az(context, values, aggregate=aggregate,
                                  action_name=AGGREGATE_ACTION_UPDATE)
        if values:
            aggregate.update_metadata(values)
            aggregate.updated_at = timeutils.utcnow()
        self.scheduler_client.update_aggregates(context, [aggregate])
        # If updated values include availability_zones, then the cache
        # which stored availability_zones and host need to be reset
        if values.get('availability_zone'):
            availability_zones.reset_cache()
        return aggregate

    @wrap_exception()
    def update_aggregate_metadata(self, context, aggregate_id, metadata):
        """Updates the aggregate metadata."""
        aggregate = objects.Aggregate.get_by_id(context, aggregate_id)
        self.is_safe_to_update_az(context, metadata, aggregate=aggregate,
                                  action_name=AGGREGATE_ACTION_UPDATE_META)
        aggregate.update_metadata(metadata)
        self.scheduler_client.update_aggregates(context, [aggregate])
        # If updated metadata include availability_zones, then the cache
        # which stored availability_zones and host need to be reset
        if metadata and metadata.get('availability_zone'):
            availability_zones.reset_cache()
        aggregate.updated_at = timeutils.utcnow()
        return aggregate

    @wrap_exception()
    def delete_aggregate(self, context, aggregate_id):
        """Deletes the aggregate."""
        aggregate_payload = {'aggregate_id': aggregate_id}
        compute_utils.notify_about_aggregate_update(context,
                                                    "delete.start",
                                                    aggregate_payload)
        aggregate = objects.Aggregate.get_by_id(context, aggregate_id)

        compute_utils.notify_about_aggregate_action(
            context=context,
            aggregate=aggregate,
            action=fields_obj.NotificationAction.DELETE,
            phase=fields_obj.NotificationPhase.START)

        if len(aggregate.hosts) > 0:
            msg = _("Host aggregate is not empty")
            raise exception.InvalidAggregateActionDelete(
                aggregate_id=aggregate_id, reason=msg)
        aggregate.destroy()
        self.scheduler_client.delete_aggregate(context, aggregate)
        compute_utils.notify_about_aggregate_update(context,
                                                    "delete.end",
                                                    aggregate_payload)
        compute_utils.notify_about_aggregate_action(
            context=context,
            aggregate=aggregate,
            action=fields_obj.NotificationAction.DELETE,
            phase=fields_obj.NotificationPhase.END)

    def is_safe_to_update_az(self, context, metadata, aggregate,
                             hosts=None,
                             action_name=AGGREGATE_ACTION_ADD):
        """Determine if updates alter an aggregate's availability zone.

            :param context: local context
            :param metadata: Target metadata for updating aggregate
            :param aggregate: Aggregate to update
            :param hosts: Hosts to check. If None, aggregate.hosts is used
            :type hosts: list
            :action_name: Calling method for logging purposes

        """
        if 'availability_zone' in metadata:
            if not metadata['availability_zone']:
                msg = _("Aggregate %s does not support empty named "
                        "availability zone") % aggregate.name
                self._raise_invalid_aggregate_exc(action_name, aggregate.id,
                                                  msg)
            _hosts = hosts or aggregate.hosts
            host_aggregates = objects.AggregateList.get_by_metadata_key(
                context, 'availability_zone', hosts=_hosts)
            conflicting_azs = [
                agg.availability_zone for agg in host_aggregates
                if agg.availability_zone != metadata['availability_zone']
                and agg.id != aggregate.id]
            if conflicting_azs:
                msg = _("One or more hosts already in availability zone(s) "
                        "%s") % conflicting_azs
                self._raise_invalid_aggregate_exc(action_name, aggregate.id,
                                                  msg)

    def _raise_invalid_aggregate_exc(self, action_name, aggregate_id, reason):
        if action_name == AGGREGATE_ACTION_ADD:
            raise exception.InvalidAggregateActionAdd(
                aggregate_id=aggregate_id, reason=reason)
        elif action_name == AGGREGATE_ACTION_UPDATE:
            raise exception.InvalidAggregateActionUpdate(
                aggregate_id=aggregate_id, reason=reason)
        elif action_name == AGGREGATE_ACTION_UPDATE_META:
            raise exception.InvalidAggregateActionUpdateMeta(
                aggregate_id=aggregate_id, reason=reason)
        elif action_name == AGGREGATE_ACTION_DELETE:
            raise exception.InvalidAggregateActionDelete(
                aggregate_id=aggregate_id, reason=reason)

        raise exception.NovaException(
            _("Unexpected aggregate action %s") % action_name)

    def _update_az_cache_for_host(self, context, host_name, aggregate_meta):
        # Update the availability_zone cache to avoid getting wrong
        # availability_zone in cache retention time when add/remove
        # host to/from aggregate.
        if aggregate_meta and aggregate_meta.get('availability_zone'):
            availability_zones.update_host_availability_zone_cache(context,
                                                                   host_name)

    @wrap_exception()
    def add_host_to_aggregate(self, context, aggregate_id, host_name):
        """Adds the host to an aggregate."""
        aggregate_payload = {'aggregate_id': aggregate_id,
                             'host_name': host_name}
        compute_utils.notify_about_aggregate_update(context,
                                                    "addhost.start",
                                                    aggregate_payload)
        # validates the host; HostMappingNotFound or ComputeHostNotFound
        # is raised if invalid
        try:
            mapping = objects.HostMapping.get_by_host(context, host_name)
            nova_context.set_target_cell(context, mapping.cell_mapping)
            service = objects.Service.get_by_compute_host(context, host_name)
        except exception.HostMappingNotFound:
            try:
                # NOTE(danms): This targets our cell
                service = _find_service_in_cell(context,
                                                service_host=host_name)
            except exception.NotFound:
                raise exception.ComputeHostNotFound(host=host_name)

        if service.host != host_name:
            # NOTE(danms): If we found a service but it is not an
            # exact match, we may have a case-insensitive backend
            # database (like mysql) which will end up with us
            # adding the host-aggregate mapping with a
            # non-matching hostname.
            raise exception.ComputeHostNotFound(host=host_name)

        aggregate = objects.Aggregate.get_by_id(context, aggregate_id)
        self.is_safe_to_update_az(context, aggregate.metadata,
                                  hosts=[host_name], aggregate=aggregate)

        aggregate.add_host(host_name)
        self.scheduler_client.update_aggregates(context, [aggregate])
        self._update_az_cache_for_host(context, host_name, aggregate.metadata)
        # NOTE(jogo): Send message to host to support resource pools
        self.compute_rpcapi.add_aggregate_host(context,
                aggregate=aggregate, host_param=host_name, host=host_name)
        aggregate_payload.update({'name': aggregate.name})
        compute_utils.notify_about_aggregate_update(context,
                                                    "addhost.end",
                                                    aggregate_payload)
        return aggregate

    @wrap_exception()
    def remove_host_from_aggregate(self, context, aggregate_id, host_name):
        """Removes host from the aggregate."""
        aggregate_payload = {'aggregate_id': aggregate_id,
                             'host_name': host_name}
        compute_utils.notify_about_aggregate_update(context,
                                                    "removehost.start",
                                                    aggregate_payload)
        # validates the host; HostMappingNotFound or ComputeHostNotFound
        # is raised if invalid
        mapping = objects.HostMapping.get_by_host(context, host_name)
        nova_context.set_target_cell(context, mapping.cell_mapping)
        objects.Service.get_by_compute_host(context, host_name)
        aggregate = objects.Aggregate.get_by_id(context, aggregate_id)
        aggregate.delete_host(host_name)
        self.scheduler_client.update_aggregates(context, [aggregate])
        self._update_az_cache_for_host(context, host_name, aggregate.metadata)
        self.compute_rpcapi.remove_aggregate_host(context,
                aggregate=aggregate, host_param=host_name, host=host_name)
        compute_utils.notify_about_aggregate_update(context,
                                                    "removehost.end",
                                                    aggregate_payload)
        return aggregate


class KeypairAPI(base.Base):
    """Subset of the Compute Manager API for managing key pairs."""

    get_notifier = functools.partial(rpc.get_notifier, service='api')
    wrap_exception = functools.partial(exception_wrapper.wrap_exception,
                                       get_notifier=get_notifier,
                                       binary='nova-api')

    def _notify(self, context, event_suffix, keypair_name):
        payload = {
            'tenant_id': context.project_id,
            'user_id': context.user_id,
            'key_name': keypair_name,
        }
        notify = self.get_notifier()
        notify.info(context, 'keypair.%s' % event_suffix, payload)

    def _validate_new_key_pair(self, context, user_id, key_name, key_type):
        safe_chars = "_- " + string.digits + string.ascii_letters
        clean_value = "".join(x for x in key_name if x in safe_chars)
        if clean_value != key_name:
            raise exception.InvalidKeypair(
                reason=_("Keypair name contains unsafe characters"))

        try:
            utils.check_string_length(key_name, min_length=1, max_length=255)
        except exception.InvalidInput:
            raise exception.InvalidKeypair(
                reason=_('Keypair name must be string and between '
                         '1 and 255 characters long'))
        try:
            objects.Quotas.check_deltas(context, {'key_pairs': 1}, user_id)
        except exception.OverQuota:
            raise exception.KeypairLimitExceeded()

    @wrap_exception()
    def import_key_pair(self, context, user_id, key_name, public_key,
                        key_type=keypair_obj.KEYPAIR_TYPE_SSH):
        """Import a key pair using an existing public key."""
        self._validate_new_key_pair(context, user_id, key_name, key_type)

        self._notify(context, 'import.start', key_name)

        fingerprint = self._generate_fingerprint(public_key, key_type)

        keypair = objects.KeyPair(context)
        keypair.user_id = user_id
        keypair.name = key_name
        keypair.type = key_type
        keypair.fingerprint = fingerprint
        keypair.public_key = public_key
        keypair.create()

        self._notify(context, 'import.end', key_name)

        return keypair

    @wrap_exception()
    def create_key_pair(self, context, user_id, key_name,
                        key_type=keypair_obj.KEYPAIR_TYPE_SSH):
        """Create a new key pair."""
        self._validate_new_key_pair(context, user_id, key_name, key_type)

        keypair = objects.KeyPair(context)
        keypair.user_id = user_id
        keypair.name = key_name
        keypair.type = key_type
        keypair.fingerprint = None
        keypair.public_key = None

        self._notify(context, 'create.start', key_name)
        compute_utils.notify_about_keypair_action(
            context=context,
            keypair=keypair,
            action=fields_obj.NotificationAction.CREATE,
            phase=fields_obj.NotificationPhase.START)

        private_key, public_key, fingerprint = self._generate_key_pair(
            user_id, key_type)

        keypair.fingerprint = fingerprint
        keypair.public_key = public_key
        keypair.create()

        # NOTE(melwitt): We recheck the quota after creating the object to
        # prevent users from allocating more resources than their allowed quota
        # in the event of a race. This is configurable because it can be
        # expensive if strict quota limits are not required in a deployment.
        if CONF.quota.recheck_quota:
            try:
                objects.Quotas.check_deltas(context, {'key_pairs': 0}, user_id)
            except exception.OverQuota:
                keypair.destroy()
                raise exception.KeypairLimitExceeded()

        compute_utils.notify_about_keypair_action(
            context=context,
            keypair=keypair,
            action=fields_obj.NotificationAction.CREATE,
            phase=fields_obj.NotificationPhase.END)

        self._notify(context, 'create.end', key_name)

        return keypair, private_key

    def _generate_fingerprint(self, public_key, key_type):
        if key_type == keypair_obj.KEYPAIR_TYPE_SSH:
            return crypto.generate_fingerprint(public_key)
        elif key_type == keypair_obj.KEYPAIR_TYPE_X509:
            return crypto.generate_x509_fingerprint(public_key)

    def _generate_key_pair(self, user_id, key_type):
        if key_type == keypair_obj.KEYPAIR_TYPE_SSH:
            return crypto.generate_key_pair()
        elif key_type == keypair_obj.KEYPAIR_TYPE_X509:
            return crypto.generate_winrm_x509_cert(user_id)

    @wrap_exception()
    def delete_key_pair(self, context, user_id, key_name):
        """Delete a keypair by name."""
        self._notify(context, 'delete.start', key_name)
        objects.KeyPair.destroy_by_name(context, user_id, key_name)
        self._notify(context, 'delete.end', key_name)

    def get_key_pairs(self, context, user_id, limit=None, marker=None):
        """List key pairs."""
        return objects.KeyPairList.get_by_user(
            context, user_id, limit=limit, marker=marker)

    def get_key_pair(self, context, user_id, key_name):
        """Get a keypair by name."""
        return objects.KeyPair.get_by_name(context, user_id, key_name)


class SecurityGroupAPI(base.Base, security_group_base.SecurityGroupBase):
    """Sub-set of the Compute API related to managing security groups
    and security group rules
    """

    # The nova security group api does not use a uuid for the id.
    id_is_uuid = False

    def __init__(self, **kwargs):
        super(SecurityGroupAPI, self).__init__(**kwargs)
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def validate_property(self, value, property, allowed):
        """Validate given security group property.

        :param value:          the value to validate, as a string or unicode
        :param property:       the property, either 'name' or 'description'
        :param allowed:        the range of characters allowed
        """

        try:
            val = value.strip()
        except AttributeError:
            msg = _("Security group %s is not a string or unicode") % property
            self.raise_invalid_property(msg)
        utils.check_string_length(val, name=property, min_length=1,
                                  max_length=255)

        if allowed and not re.match(allowed, val):
            # Some validation to ensure that values match API spec.
            # - Alphanumeric characters, spaces, dashes, and underscores.
            # TODO(Daviey): LP: #813685 extend beyond group_name checking, and
            #  probably create a param validator that can be used elsewhere.
            msg = (_("Value (%(value)s) for parameter Group%(property)s is "
                     "invalid. Content limited to '%(allowed)s'.") %
                   {'value': value, 'allowed': allowed,
                    'property': property.capitalize()})
            self.raise_invalid_property(msg)

    def ensure_default(self, context):
        """Ensure that a context has a security group.

        Creates a security group for the security context if it does not
        already exist.

        :param context: the security context
        """
        self.db.security_group_ensure_default(context)

    def create_security_group(self, context, name, description):
        try:
            objects.Quotas.check_deltas(context, {'security_groups': 1},
                                        context.project_id,
                                        user_id=context.user_id)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many security groups.")
            self.raise_over_quota(msg)

        LOG.info("Create Security Group %s", name)

        self.ensure_default(context)

        group = {'user_id': context.user_id,
                 'project_id': context.project_id,
                 'name': name,
                 'description': description}
        try:
            group_ref = self.db.security_group_create(context, group)
        except exception.SecurityGroupExists:
            msg = _('Security group %s already exists') % name
            self.raise_group_already_exists(msg)

        # NOTE(melwitt): We recheck the quota after creating the object to
        # prevent users from allocating more resources than their allowed quota
        # in the event of a race. This is configurable because it can be
        # expensive if strict quota limits are not required in a deployment.
        if CONF.quota.recheck_quota:
            try:
                objects.Quotas.check_deltas(context, {'security_groups': 0},
                                            context.project_id,
                                            user_id=context.user_id)
            except exception.OverQuota:
                self.db.security_group_destroy(context, group_ref['id'])
                msg = _("Quota exceeded, too many security groups.")
                self.raise_over_quota(msg)

        return group_ref

    def update_security_group(self, context, security_group,
                                name, description):
        if security_group['name'] in RO_SECURITY_GROUPS:
            msg = (_("Unable to update system group '%s'") %
                    security_group['name'])
            self.raise_invalid_group(msg)

        group = {'name': name,
                 'description': description}

        columns_to_join = ['rules.grantee_group']
        group_ref = self.db.security_group_update(context,
                security_group['id'],
                group,
                columns_to_join=columns_to_join)
        return group_ref

    def get(self, context, name=None, id=None, map_exception=False):
        self.ensure_default(context)
        cols = ['rules']
        try:
            if name:
                return self.db.security_group_get_by_name(context,
                                                          context.project_id,
                                                          name,
                                                          columns_to_join=cols)
            elif id:
                return self.db.security_group_get(context, id,
                                                  columns_to_join=cols)
        except exception.NotFound as exp:
            if map_exception:
                msg = exp.format_message()
                self.raise_not_found(msg)
            else:
                raise

    def list(self, context, names=None, ids=None, project=None,
             search_opts=None):
        self.ensure_default(context)

        groups = []
        if names or ids:
            if names:
                for name in names:
                    groups.append(self.db.security_group_get_by_name(context,
                                                                     project,
                                                                     name))
            if ids:
                for id in ids:
                    groups.append(self.db.security_group_get(context, id))

        elif context.is_admin:
            # TODO(eglynn): support a wider set of search options than just
            # all_tenants, at least include the standard filters defined for
            # the EC2 DescribeSecurityGroups API for the non-admin case also
            if (search_opts and 'all_tenants' in search_opts):
                groups = self.db.security_group_get_all(context)
            else:
                groups = self.db.security_group_get_by_project(context,
                                                               project)

        elif project:
            groups = self.db.security_group_get_by_project(context, project)

        return groups

    def destroy(self, context, security_group):
        if security_group['name'] in RO_SECURITY_GROUPS:
            msg = _("Unable to delete system group '%s'") % \
                    security_group['name']
            self.raise_invalid_group(msg)

        if self.db.security_group_in_use(context, security_group['id']):
            msg = _("Security group is still in use")
            self.raise_invalid_group(msg)

        LOG.info("Delete security group %s", security_group['name'])
        self.db.security_group_destroy(context, security_group['id'])

    def is_associated_with_server(self, security_group, instance_uuid):
        """Check if the security group is already associated
           with the instance. If Yes, return True.
        """

        if not security_group:
            return False

        instances = security_group.get('instances')
        if not instances:
            return False

        for inst in instances:
            if (instance_uuid == inst['uuid']):
                return True

        return False

    def add_to_instance(self, context, instance, security_group_name):
        """Add security group to the instance."""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance.uuid

        # check if the security group is associated with the server
        if self.is_associated_with_server(security_group, instance_uuid):
            raise exception.SecurityGroupExistsForInstance(
                                        security_group_id=security_group['id'],
                                        instance_id=instance_uuid)

        self.db.instance_add_security_group(context.elevated(),
                                            instance_uuid,
                                            security_group['id'])
        if instance.host:
            self.compute_rpcapi.refresh_instance_security_rules(
                    context, instance, instance.host)

    def remove_from_instance(self, context, instance, security_group_name):
        """Remove the security group associated with the instance."""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance.uuid

        # check if the security group is associated with the server
        if not self.is_associated_with_server(security_group, instance_uuid):
            raise exception.SecurityGroupNotExistsForInstance(
                                    security_group_id=security_group['id'],
                                    instance_id=instance_uuid)

        self.db.instance_remove_security_group(context.elevated(),
                                               instance_uuid,
                                               security_group['id'])
        if instance.host:
            self.compute_rpcapi.refresh_instance_security_rules(
                    context, instance, instance.host)

    def get_rule(self, context, id):
        self.ensure_default(context)
        try:
            return self.db.security_group_rule_get(context, id)
        except exception.NotFound:
            msg = _("Rule (%s) not found") % id
            self.raise_not_found(msg)

    def add_rules(self, context, id, name, vals):
        """Add security group rule(s) to security group.

        Note: the Nova security group API doesn't support adding multiple
        security group rules at once but the EC2 one does. Therefore,
        this function is written to support both.
        """

        try:
            objects.Quotas.check_deltas(context,
                                        {'security_group_rules': len(vals)},
                                        id)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many security group rules.")
            self.raise_over_quota(msg)

        msg = ("Security group %(name)s added %(protocol)s ingress "
               "(%(from_port)s:%(to_port)s)")
        rules = []
        for v in vals:
            rule = self.db.security_group_rule_create(context, v)

            # NOTE(melwitt): We recheck the quota after creating the object to
            # prevent users from allocating more resources than their allowed
            # quota in the event of a race. This is configurable because it can
            # be expensive if strict quota limits are not required in a
            # deployment.
            if CONF.quota.recheck_quota:
                try:
                    objects.Quotas.check_deltas(context,
                                                {'security_group_rules': 0},
                                                id)
                except exception.OverQuota:
                    self.db.security_group_rule_destroy(context, rule['id'])
                    msg = _("Quota exceeded, too many security group rules.")
                    self.raise_over_quota(msg)

            rules.append(rule)
            LOG.info(msg, {'name': name,
                           'protocol': rule.protocol,
                           'from_port': rule.from_port,
                           'to_port': rule.to_port})

        self.trigger_rules_refresh(context, id=id)
        return rules

    def remove_rules(self, context, security_group, rule_ids):
        msg = ("Security group %(name)s removed %(protocol)s ingress "
               "(%(from_port)s:%(to_port)s)")
        for rule_id in rule_ids:
            rule = self.get_rule(context, rule_id)
            LOG.info(msg, {'name': security_group['name'],
                           'protocol': rule.protocol,
                           'from_port': rule.from_port,
                           'to_port': rule.to_port})

            self.db.security_group_rule_destroy(context, rule_id)

        # NOTE(vish): we removed some rules, so refresh
        self.trigger_rules_refresh(context, id=security_group['id'])

    def remove_default_rules(self, context, rule_ids):
        for rule_id in rule_ids:
            self.db.security_group_default_rule_destroy(context, rule_id)

    def add_default_rules(self, context, vals):
        rules = [self.db.security_group_default_rule_create(context, v)
                 for v in vals]
        return rules

    def default_rule_exists(self, context, values):
        """Indicates whether the specified rule values are already
           defined in the default security group rules.
        """
        for rule in self.db.security_group_default_rule_list(context):
            keys = ('cidr', 'from_port', 'to_port', 'protocol')
            for key in keys:
                if rule.get(key) != values.get(key):
                    break
            else:
                return rule.get('id') or True
        return False

    def get_all_default_rules(self, context):
        try:
            rules = self.db.security_group_default_rule_list(context)
        except Exception:
            msg = 'cannot get default security group rules'
            raise exception.SecurityGroupDefaultRuleNotFound(msg)

        return rules

    def get_default_rule(self, context, id):
        return self.db.security_group_default_rule_get(context, id)

    def validate_id(self, id):
        try:
            return int(id)
        except ValueError:
            msg = _("Security group id should be integer")
            self.raise_invalid_property(msg)

    def _refresh_instance_security_rules(self, context, instances):
        for instance in instances:
            if instance.host is not None:
                self.compute_rpcapi.refresh_instance_security_rules(
                        context, instance, instance.host)

    def trigger_rules_refresh(self, context, id):
        """Called when a rule is added to or removed from a security_group."""
        instances = objects.InstanceList.get_by_security_group_id(context, id)
        self._refresh_instance_security_rules(context, instances)

    def trigger_members_refresh(self, context, group_ids):
        """Called when a security group gains a new or loses a member.

        Sends an update request to each compute node for each instance for
        which this is relevant.
        """
        instances = objects.InstanceList.get_by_grantee_security_group_ids(
            context, group_ids)
        self._refresh_instance_security_rules(context, instances)

    def get_instance_security_groups(self, context, instance, detailed=False):
        if detailed:
            return self.db.security_group_get_by_instance(context,
                                                          instance.uuid)
        return [{'name': group.name} for group in instance.security_groups]
