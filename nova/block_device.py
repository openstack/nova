# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
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
                     'connection_info'])


bdm_db_only_fields = set(['id', 'instance_uuid'])


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

    def __init__(self, bdm_dict=None, do_not_default=None):
        super(BlockDeviceDict, self).__init__()

        bdm_dict = bdm_dict or {}
        do_not_default = do_not_default or set()

        self._validate(bdm_dict)
        # NOTE (ndipanov): Never default db fields
        self.update(
            dict((field, None)
                 for field in self._fields - do_not_default))
        self.update(bdm_dict)

    def _validate(self, bdm_dict):
        """Basic data format validations."""
        dict_fields = set(key for key, _ in bdm_dict.iteritems())

        # Check that there are no bogus fields
        if not (dict_fields <=
                (self._fields | self._db_only_fields)):
            raise exception.InvalidBDMFormat(
                details="Some fields are invalid.")

        if bdm_dict.get('no_device'):
            return

        # Check that all required fields are there
        if (self._required_fields and
                not ((dict_fields & self._required_fields) ==
                      self._required_fields)):
            raise exception.InvalidBDMFormat(
                details="Some required fields are missing")

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
                    details="Boot index is invalid.")

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

        new_bdm = dict((fld, val) for fld, val in legacy_bdm.iteritems()
                        if fld in copy_over_fields)

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
                details="Unrecognized legacy format.")

        return cls(new_bdm, non_computable_fields)

    @classmethod
    def from_api(cls, api_dict):
        """Transform the API format of data to the internally used one.

        Only validate if the source_type field makes sense.
        """
        if not api_dict.get('no_device'):

            source_type = api_dict.get('source_type')
            device_uuid = api_dict.get('uuid')

            if source_type not in ('volume', 'image', 'snapshot', 'blank'):
                raise exception.InvalidBDMFormat(
                    details="Invalid source_type field.")
            elif source_type != 'blank':
                if not device_uuid:
                    raise exception.InvalidBDMFormat(
                        details="Missing device UUID.")
                api_dict[source_type + '_id'] = device_uuid

        api_dict.pop('uuid', None)
        return cls(api_dict)

    def legacy(self):
        copy_over_fields = bdm_legacy_fields - set(['virtual_name'])
        copy_over_fields |= (bdm_db_only_fields |
                             bdm_db_inherited_fields)

        legacy_block_device = dict((field, self.get(field))
            for field in copy_over_fields if field in self)

        source_type = self.get('source_type')
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
            # NOTE(ndipanov): Image bdms have no meaning in
            # the legacy format - raise
            raise exception.InvalidBDMForLegacy()

        return legacy_block_device


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
                        root_device_name=None):
    """Transform a legacy list of block devices to the new data format."""

    new_bdms = [BlockDeviceDict.from_legacy(legacy_bdm)
                for legacy_bdm in legacy_block_device_mapping]
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
    """get root device name from image meta data.
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
        #                  is supported by nova.compute
        utils.check_string_length(value, 'Device name',
                                  min_length=1, max_length=255)
    except exception.InvalidInput as e:
        raise exception.InvalidBDMFormat(
            details="Device name empty or too long.")

    if ' ' in value:
        raise exception.InvalidBDMFormat(
            details="Device name contains spaces.")


def validate_and_default_volume_size(bdm):
    if bdm.get('volume_size'):
        try:
            bdm['volume_size'] = utils.validate_integer(
                bdm['volume_size'], 'volume_size', min_value=0)
        except exception.InvalidInput as e:
            raise exception.InvalidBDMFormat(
                details="Invalid volume_size.")


_ephemeral = re.compile('^ephemeral(\d|[1-9]\d+)$')


def is_ephemeral(device_name):
    return _ephemeral.match(device_name) is not None


def ephemeral_num(ephemeral_name):
    assert is_ephemeral(ephemeral_name)
    return int(_ephemeral.sub('\\1', ephemeral_name))


def is_swap_or_ephemeral(device_name):
    return (device_name and
            (device_name == 'swap' or is_ephemeral(device_name)))


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


_pref = re.compile('^((x?v|s)d)')


def strip_prefix(device_name):
    """remove both leading /dev/ and xvd or sd or vd."""
    device_name = strip_dev(device_name)
    return _pref.sub('', device_name)


def instance_block_mapping(instance, bdms):
    root_device_name = instance['root_device_name']
    # NOTE(clayg): remove this when xenapi is setting default_root_device
    if root_device_name is None:
        if driver.compute_driver_matches('xenapi.XenAPIDriver'):
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

    # 'ephemeralN', 'swap' and ebs
    for bdm in bdms:
        if bdm['no_device']:
            continue

        # ebs volume case
        if (bdm['volume_id'] or bdm['snapshot_id']):
            ebs_devices.append(bdm['device_name'])
            continue

        virtual_name = bdm['virtual_name']
        if not virtual_name:
            continue

        if is_swap_or_ephemeral(virtual_name):
            mappings[virtual_name] = bdm['device_name']

    # NOTE(yamahata): I'm not sure how ebs device should be numbered.
    #                 Right now sort by device name for deterministic
    #                 result.
    if ebs_devices:
        nebs = 0
        ebs_devices.sort()
        for ebs in ebs_devices:
            mappings['ebs%d' % nebs] = ebs
            nebs += 1

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

    LOG.debug(_("block_device_list %s"), block_device_list)
    return strip_dev(mount_device) in block_device_list
