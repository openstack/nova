# Copyright 2011 Isaku Yamahata <yamahata@valinux co jp>
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

import re

from oslo_log import log as logging
from oslo_utils import strutils


import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt import driver

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

DEFAULT_ROOT_DEV_NAME = '/dev/sda1'
_DEFAULT_MAPPINGS = {'ami': 'sda1',
                     'ephemeral0': 'sda2',
                     'root': DEFAULT_ROOT_DEV_NAME,
                     'swap': 'sda3'}


bdm_legacy_fields = set(['device_name', 'delete_on_termination',
                         'virtual_name', 'snapshot_id',
                         'volume_id', 'volume_size', 'no_device',
                         'connection_info'])


bdm_new_fields = set(['source_type', 'destination_type',
                     'guest_format', 'device_type', 'disk_bus', 'boot_index',
                     'device_name', 'delete_on_termination', 'snapshot_id',
                     'volume_id', 'volume_size', 'image_id', 'no_device',
                     'connection_info', 'tag'])


bdm_db_only_fields = set(['id', 'instance_uuid', 'attachment_id'])


bdm_db_inherited_fields = set(['created_at', 'updated_at',
                               'deleted_at', 'deleted'])


bdm_new_non_api_fields = set(['volume_id', 'snapshot_id',
                              'image_id', 'connection_info'])


bdm_new_api_only_fields = set(['uuid'])


bdm_new_api_fields = ((bdm_new_fields - bdm_new_non_api_fields) |
                      bdm_new_api_only_fields)


class BlockDeviceDict(dict):
    """Represents a Block Device Mapping in Nova."""

    _fields = bdm_new_fields
    _db_only_fields = (bdm_db_only_fields |
               bdm_db_inherited_fields)

    _required_fields = set(['source_type'])

    def __init__(self, bdm_dict=None, do_not_default=None, **kwargs):
        super(BlockDeviceDict, self).__init__()

        bdm_dict = bdm_dict or {}
        bdm_dict.update(kwargs)
        do_not_default = do_not_default or set()

        self._validate(bdm_dict)
        if bdm_dict.get('device_name'):
            bdm_dict['device_name'] = prepend_dev(bdm_dict['device_name'])
        bdm_dict['delete_on_termination'] = bool(
            bdm_dict.get('delete_on_termination'))
        # NOTE (ndipanov): Never default db fields
        self.update({field: None for field in self._fields - do_not_default})
        self.update(bdm_dict.items())

    def _validate(self, bdm_dict):
        """Basic data format validations."""
        dict_fields = set(key for key, _ in bdm_dict.items())

        # Check that there are no bogus fields
        if not (dict_fields <=
                (self._fields | self._db_only_fields)):
            raise exception.InvalidBDMFormat(
                details=_("Some fields are invalid."))

        if bdm_dict.get('no_device'):
            return

        # Check that all required fields are there
        if (self._required_fields and
                not ((dict_fields & self._required_fields) ==
                      self._required_fields)):
            raise exception.InvalidBDMFormat(
                details=_("Some required fields are missing"))

        if 'delete_on_termination' in bdm_dict:
            bdm_dict['delete_on_termination'] = strutils.bool_from_string(
                bdm_dict['delete_on_termination'])

        if bdm_dict.get('device_name') is not None:
            validate_device_name(bdm_dict['device_name'])

        validate_and_default_volume_size(bdm_dict)

        if bdm_dict.get('boot_index'):
            try:
                bdm_dict['boot_index'] = int(bdm_dict['boot_index'])
            except ValueError:
                raise exception.InvalidBDMFormat(
                    details=_("Boot index is invalid."))

    @classmethod
    def from_legacy(cls, legacy_bdm):

        copy_over_fields = bdm_legacy_fields & bdm_new_fields
        copy_over_fields |= (bdm_db_only_fields |
                             bdm_db_inherited_fields)
        # NOTE (ndipanov): These fields cannot be computed
        # from legacy bdm, so do not default them
        # to avoid overwriting meaningful values in the db
        non_computable_fields = set(['boot_index', 'disk_bus',
                                     'guest_format', 'device_type'])

        new_bdm = {fld: val for fld, val in legacy_bdm.items()
                   if fld in copy_over_fields}

        virt_name = legacy_bdm.get('virtual_name')

        if is_swap_or_ephemeral(virt_name):
            new_bdm['source_type'] = 'blank'
            new_bdm['delete_on_termination'] = True
            new_bdm['destination_type'] = 'local'

            if virt_name == 'swap':
                new_bdm['guest_format'] = 'swap'
            else:
                new_bdm['guest_format'] = CONF.default_ephemeral_format

        elif legacy_bdm.get('snapshot_id'):
            new_bdm['source_type'] = 'snapshot'
            new_bdm['destination_type'] = 'volume'

        elif legacy_bdm.get('volume_id'):
            new_bdm['source_type'] = 'volume'
            new_bdm['destination_type'] = 'volume'

        elif legacy_bdm.get('no_device'):
            # NOTE (ndipanov): Just keep the BDM for now,
            pass

        else:
            raise exception.InvalidBDMFormat(
                details=_("Unrecognized legacy format."))

        return cls(new_bdm, non_computable_fields)

    @classmethod
    def from_api(cls, api_dict, image_uuid_specified):
        """Transform the API format of data to the internally used one.

        Only validate if the source_type field makes sense.
        """
        if not api_dict.get('no_device'):

            source_type = api_dict.get('source_type')
            device_uuid = api_dict.get('uuid')
            destination_type = api_dict.get('destination_type')

            if source_type == 'blank' and device_uuid:
                raise exception.InvalidBDMFormat(
                    details=_("Invalid device UUID."))
            elif source_type != 'blank':
                if not device_uuid:
                    raise exception.InvalidBDMFormat(
                        details=_("Missing device UUID."))
                api_dict[source_type + '_id'] = device_uuid
            if source_type == 'image' and destination_type == 'local':
                # NOTE(mriedem): boot_index can be None so we need to
                # account for that to avoid a TypeError.
                boot_index = api_dict.get('boot_index', -1)
                if boot_index is None:
                    # boot_index=None is equivalent to -1.
                    boot_index = -1
                boot_index = int(boot_index)

                # if this bdm is generated from --image ,then
                # source_type = image and destination_type = local is allowed
                if not (image_uuid_specified and boot_index == 0):
                    raise exception.InvalidBDMFormat(
                        details=_("Mapping image to local is not supported."))

        api_dict.pop('uuid', None)
        return cls(api_dict)

    def legacy(self):
        copy_over_fields = bdm_legacy_fields - set(['virtual_name'])
        copy_over_fields |= (bdm_db_only_fields |
                             bdm_db_inherited_fields)

        legacy_block_device = {field: self.get(field)
            for field in copy_over_fields if field in self}

        source_type = self.get('source_type')
        destination_type = self.get('destination_type')
        no_device = self.get('no_device')
        if source_type == 'blank':
            if self['guest_format'] == 'swap':
                legacy_block_device['virtual_name'] = 'swap'
            else:
                # NOTE (ndipanov): Always label as 0, it is up to
                # the calling routine to re-enumerate them
                legacy_block_device['virtual_name'] = 'ephemeral0'
        elif source_type in ('volume', 'snapshot') or no_device:
            legacy_block_device['virtual_name'] = None
        elif source_type == 'image':
            if destination_type != 'volume':
                # NOTE(ndipanov): Image bdms with local destination
                # have no meaning in the legacy format - raise
                raise exception.InvalidBDMForLegacy()
            legacy_block_device['virtual_name'] = None

        return legacy_block_device

    def get_image_mapping(self):
        drop_fields = (set(['connection_info']) |
                       self._db_only_fields)
        mapping_dict = dict(self)
        for fld in drop_fields:
            mapping_dict.pop(fld, None)
        return mapping_dict


def is_safe_for_update(block_device_dict):
    """Determine if passed dict is a safe subset for update.

    Safe subset in this case means a safe subset of both legacy
    and new versions of data, that can be passed to an UPDATE query
    without any transformation.
    """
    fields = set(block_device_dict.keys())
    return fields <= (bdm_new_fields |
                      bdm_db_inherited_fields |
                      bdm_db_only_fields)


def create_image_bdm(image_ref, boot_index=0):
    """Create a block device dict based on the image_ref.

    This is useful in the API layer to keep the compatibility
    with having an image_ref as a field in the instance requests
    """
    return BlockDeviceDict(
        {'source_type': 'image',
         'image_id': image_ref,
         'delete_on_termination': True,
         'boot_index': boot_index,
         'device_type': 'disk',
         'destination_type': 'local'})


def create_blank_bdm(size, guest_format=None):
    return BlockDeviceDict(
        {'source_type': 'blank',
         'delete_on_termination': True,
         'device_type': 'disk',
         'boot_index': -1,
         'destination_type': 'local',
         'guest_format': guest_format,
         'volume_size': size})


def snapshot_from_bdm(snapshot_id, template):
    """Create a basic volume snapshot BDM from a given template bdm."""

    copy_from_template = ('disk_bus', 'device_type', 'boot_index',
                          'delete_on_termination', 'volume_size',
                          'device_name')
    snapshot_dict = {'source_type': 'snapshot',
                     'destination_type': 'volume',
                     'snapshot_id': snapshot_id}
    for key in copy_from_template:
        snapshot_dict[key] = template.get(key)
    return BlockDeviceDict(snapshot_dict)


def legacy_mapping(block_device_mapping):
    """Transform a list of block devices of an instance back to the
    legacy data format.
    """

    legacy_block_device_mapping = []

    for bdm in block_device_mapping:
        try:
            legacy_block_device = BlockDeviceDict(bdm).legacy()
        except exception.InvalidBDMForLegacy:
            continue

        legacy_block_device_mapping.append(legacy_block_device)

    # Re-enumerate the ephemeral devices
    for i, dev in enumerate(dev for dev in legacy_block_device_mapping
                            if dev['virtual_name'] and
                            is_ephemeral(dev['virtual_name'])):
        dev['virtual_name'] = dev['virtual_name'][:-1] + str(i)

    return legacy_block_device_mapping


def from_legacy_mapping(legacy_block_device_mapping, image_uuid='',
                        root_device_name=None, no_root=False):
    """Transform a legacy list of block devices to the new data format."""

    new_bdms = [BlockDeviceDict.from_legacy(legacy_bdm)
                for legacy_bdm in legacy_block_device_mapping]
    # NOTE (ndipanov): We will not decide which device is root here - we assume
    # that it will be supplied later. This is useful for having the root device
    # as part of the image defined mappings that are already in the v2 format.
    if no_root:
        for bdm in new_bdms:
            bdm['boot_index'] = -1
        return new_bdms

    image_bdm = None
    volume_backed = False

    # Try to assign boot_device
    if not root_device_name and not image_uuid:
        # NOTE (ndipanov): If there is no root_device, pick the first non
        #                  blank one.
        non_blank = [bdm for bdm in new_bdms if bdm['source_type'] != 'blank']
        if non_blank:
            non_blank[0]['boot_index'] = 0
    else:
        for bdm in new_bdms:
            if (bdm['source_type'] in ('volume', 'snapshot', 'image') and
                    root_device_name is not None and
                    (strip_dev(bdm.get('device_name')) ==
                     strip_dev(root_device_name))):
                bdm['boot_index'] = 0
                volume_backed = True
            elif not bdm['no_device']:
                bdm['boot_index'] = -1
            else:
                bdm['boot_index'] = None

        if not volume_backed and image_uuid:
            image_bdm = create_image_bdm(image_uuid, boot_index=0)

    return ([image_bdm] if image_bdm else []) + new_bdms


def properties_root_device_name(properties):
    """Get root device name from image meta data.
    If it isn't specified, return None.
    """
    root_device_name = None

    # NOTE(yamahata): see image_service.s3.s3create()
    for bdm in properties.get('mappings', []):
        if bdm['virtual'] == 'root':
            root_device_name = bdm['device']

    # NOTE(yamahata): register_image's command line can override
    #                 <machine>.manifest.xml
    if 'root_device_name' in properties:
        root_device_name = properties['root_device_name']

    return root_device_name


def validate_device_name(value):
    try:
        # NOTE (ndipanov): Do not allow empty device names
        #                  until assigning default values
        #                  are supported by nova.compute
        utils.check_string_length(value, 'Device name',
                                  min_length=1, max_length=255)
    except exception.InvalidInput:
        raise exception.InvalidBDMFormat(
            details=_("Device name empty or too long."))

    if ' ' in value:
        raise exception.InvalidBDMFormat(
            details=_("Device name contains spaces."))


def validate_and_default_volume_size(bdm):
    if bdm.get('volume_size'):
        try:
            bdm['volume_size'] = utils.validate_integer(
                bdm['volume_size'], 'volume_size', min_value=0)
        except exception.InvalidInput:
            # NOTE: We can remove this validation code after removing
            # Nova v2.0 API code, because v2.1 API validates this case
            # already at its REST API layer.
            raise exception.InvalidBDMFormat(
                details=_("Invalid volume_size."))


_ephemeral = re.compile('^ephemeral(\d|[1-9]\d+)$')


def is_ephemeral(device_name):
    return _ephemeral.match(device_name) is not None


def ephemeral_num(ephemeral_name):
    assert is_ephemeral(ephemeral_name)
    return int(_ephemeral.sub('\\1', ephemeral_name))


def is_swap_or_ephemeral(device_name):
    return (device_name and
            (device_name == 'swap' or is_ephemeral(device_name)))


def new_format_is_swap(bdm):
    if (bdm.get('source_type') == 'blank' and
            bdm.get('destination_type') == 'local' and
            bdm.get('guest_format') == 'swap'):
        return True
    return False


def new_format_is_ephemeral(bdm):
    if (bdm.get('source_type') == 'blank' and
            bdm.get('destination_type') == 'local' and
            bdm.get('guest_format') != 'swap'):
        return True
    return False


def get_root_bdm(bdms):
    try:
        return next(bdm for bdm in bdms if bdm.get('boot_index', -1) == 0)
    except StopIteration:
        return None


def get_bdms_to_connect(bdms, exclude_root_mapping=False):
    """Will return non-root mappings, when exclude_root_mapping is true.
       Otherwise all mappings will be returned.
    """
    return (bdm for bdm in bdms if bdm.get('boot_index', -1) != 0 or
            not exclude_root_mapping)


def mappings_prepend_dev(mappings):
    """Prepend '/dev/' to 'device' entry of swap/ephemeral virtual type."""
    for m in mappings:
        virtual = m['virtual']
        if (is_swap_or_ephemeral(virtual) and
                (not m['device'].startswith('/'))):
            m['device'] = '/dev/' + m['device']
    return mappings


_dev = re.compile('^/dev/')


def strip_dev(device_name):
    """remove leading '/dev/'."""
    return _dev.sub('', device_name) if device_name else device_name


def prepend_dev(device_name):
    """Make sure there is a leading '/dev/'."""
    return device_name and '/dev/' + strip_dev(device_name)


_pref = re.compile('^((x?v|s|h)d)')


def strip_prefix(device_name):
    """remove both leading /dev/ and xvd or sd or vd or hd."""
    device_name = strip_dev(device_name)
    return _pref.sub('', device_name) if device_name else device_name


_nums = re.compile('\d+')


def get_device_letter(device_name):
    letter = strip_prefix(device_name)
    # NOTE(vish): delete numbers in case we have something like
    #             /dev/sda1
    return _nums.sub('', letter) if device_name else device_name


def instance_block_mapping(instance, bdms):
    root_device_name = instance['root_device_name']
    # NOTE(clayg): remove this when xenapi is setting default_root_device
    if root_device_name is None:
        if driver.is_xenapi():
            root_device_name = '/dev/xvda'
        else:
            return _DEFAULT_MAPPINGS

    mappings = {}
    mappings['ami'] = strip_dev(root_device_name)
    mappings['root'] = root_device_name
    default_ephemeral_device = instance.get('default_ephemeral_device')
    if default_ephemeral_device:
        mappings['ephemeral0'] = default_ephemeral_device
    default_swap_device = instance.get('default_swap_device')
    if default_swap_device:
        mappings['swap'] = default_swap_device
    ebs_devices = []
    blanks = []

    # 'ephemeralN', 'swap' and ebs
    for bdm in bdms:
        # ebs volume case
        if bdm.destination_type == 'volume':
            ebs_devices.append(bdm.device_name)
            continue

        if bdm.source_type == 'blank':
            blanks.append(bdm)

    # NOTE(yamahata): I'm not sure how ebs device should be numbered.
    #                 Right now sort by device name for deterministic
    #                 result.
    if ebs_devices:
        # NOTE(claudiub): python2.7 sort places None values first.
        # this sort will maintain the same behaviour for both py27 and py34.
        ebs_devices = sorted(ebs_devices, key=lambda x: (x is not None, x))
        for nebs, ebs in enumerate(ebs_devices):
            mappings['ebs%d' % nebs] = ebs

    swap = [bdm for bdm in blanks if bdm.guest_format == 'swap']
    if swap:
        mappings['swap'] = swap.pop().device_name

    ephemerals = [bdm for bdm in blanks if bdm.guest_format != 'swap']
    if ephemerals:
        for num, eph in enumerate(ephemerals):
            mappings['ephemeral%d' % num] = eph.device_name

    return mappings


def match_device(device):
    """Matches device name and returns prefix, suffix."""
    match = re.match("(^/dev/x{0,1}[a-z]{0,1}d{0,1})([a-z]+)[0-9]*$", device)
    if not match:
        return None
    return match.groups()


def volume_in_mapping(mount_device, block_device_info):
    block_device_list = [strip_dev(vol['mount_device'])
                         for vol in
                         driver.block_device_info_get_mapping(
                         block_device_info)]

    swap = driver.block_device_info_get_swap(block_device_info)
    if driver.swap_is_usable(swap):
        block_device_list.append(strip_dev(swap['device_name']))

    block_device_list += [strip_dev(ephemeral['device_name'])
                          for ephemeral in
                          driver.block_device_info_get_ephemerals(
                          block_device_info)]

    LOG.debug("block_device_list %s", sorted(filter(None, block_device_list)))
    return strip_dev(mount_device) in block_device_list


def get_bdm_ephemeral_disk_size(block_device_mappings):
    return sum(bdm.get('volume_size', 0)
            for bdm in block_device_mappings
            if new_format_is_ephemeral(bdm))


def get_bdm_swap_list(block_device_mappings):
    return [bdm for bdm in block_device_mappings
            if new_format_is_swap(bdm)]


def get_bdm_local_disk_num(block_device_mappings):
    return len([bdm for bdm in block_device_mappings
                if bdm.get('destination_type') == 'local'])
