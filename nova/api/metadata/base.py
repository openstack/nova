# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Instance Metadata information."""

import base64
import json
import os

from nova.api.ec2 import ec2utils
from nova import block_device
from nova import context
from nova import db
from nova import flags
from nova import network
from nova.openstack.common import cfg


metadata_opts = [
    cfg.StrOpt('config_drive_skip_versions',
               default=('1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 '
                        '2007-12-15 2008-02-01 2008-09-01'),
               help=('List of metadata versions to skip placing into the '
                     'config drive')),
    ]

FLAGS = flags.FLAGS
flags.DECLARE('dhcp_domain', 'nova.network.manager')
FLAGS.register_opts(metadata_opts)


_DEFAULT_MAPPINGS = {'ami': 'sda1',
                     'ephemeral0': 'sda2',
                     'root': block_device.DEFAULT_ROOT_DEV_NAME,
                     'swap': 'sda3'}

VERSIONS = [
    '1.0',
    '2007-01-19',
    '2007-03-01',
    '2007-08-29',
    '2007-10-10',
    '2007-12-15',
    '2008-02-01',
    '2008-09-01',
    '2009-04-04',
]


class InvalidMetadataEc2Version(Exception):
    pass


class InvalidMetadataPath(Exception):
    pass


class InstanceMetadata():
    """Instance metadata."""

    def __init__(self, instance, address=None):
        self.instance = instance

        ctxt = context.get_admin_context()

        services = db.service_get_all_by_host(ctxt.elevated(),
                instance['host'])
        self.availability_zone = ec2utils.get_availability_zone_by_host(
                services, instance['host'])

        self.ip_info = ec2utils.get_ip_info_for_instance(ctxt, instance)

        self.security_groups = db.security_group_get_by_instance(ctxt,
                                                            instance['id'])

        self.mappings = _format_instance_mapping(ctxt, instance)

        if instance.get('user_data', None) is not None:
            self.userdata_b64 = base64.b64decode(instance['user_data'])
        else:
            self.userdata_b64 = None

        self.ec2_ids = {}

        self.ec2_ids['instance-id'] = ec2utils.id_to_ec2_inst_id(
                instance['id'])
        self.ec2_ids['ami-id'] = ec2utils.glance_id_to_ec2_id(ctxt,
            instance['image_ref'])

        for image_type in ['kernel', 'ramdisk']:
            if self.instance.get('%s_id' % image_type):
                image_id = self.instance['%s_id' % image_type]
                ec2_image_type = ec2utils.image_type(image_type)
                ec2_id = ec2utils.glance_id_to_ec2_id(ctxt, image_id,
                                                      ec2_image_type)
                self.ec2_ids['%s-id' % image_type] = ec2_id

        self.address = address

    def get_ec2_metadata(self, version):
        if version == "latest":
            version = VERSIONS[-1]

        if version not in VERSIONS:
            raise InvalidMetadataEc2Version(version)

        hostname = "%s.%s" % (self.instance['hostname'], FLAGS.dhcp_domain)
        floating_ips = self.ip_info['floating_ips']
        floating_ip = floating_ips and floating_ips[0] or ''

        fmt_sgroups = [x['name'] for x in self.security_groups]

        meta_data = {
            'ami-id': self.ec2_ids['ami-id'],
            'ami-launch-index': self.instance['launch_index'],
            'ami-manifest-path': 'FIXME',
            'instance-id': self.ec2_ids['instance-id'],
            'hostname': hostname,
            'local-ipv4': self.address,
            'reservation-id': self.instance['reservation_id'],
            'security-groups': fmt_sgroups}

        # public keys are strangely rendered in ec2 metadata service
        #  meta-data/public-keys/ returns '0=keyname' (with no trailing /)
        # and only if there is a public key given.
        # '0=keyname' means there is a normally rendered dict at
        #  meta-data/public-keys/0
        #
        # meta-data/public-keys/ : '0=%s' % keyname
        # meta-data/public-keys/0/ : 'openssh-key'
        # meta-data/public-keys/0/openssh-key : '%s' % publickey
        if self.instance['key_name']:
            meta_data['public-keys'] = {
                '0': {'_name': "0=" + self.instance['key_name'],
                      'openssh-key': self.instance['key_data']}}

        if self._check_version('2007-01-19', version):
            meta_data['local-hostname'] = hostname
            meta_data['public-hostname'] = hostname
            meta_data['public-ipv4'] = floating_ip

        if False and self._check_version('2007-03-01', version):
            # TODO(vish): store product codes
            meta_data['product-codes'] = []

        if self._check_version('2007-08-29', version):
            meta_data['instance-type'] = self.instance['instance_type']['name']

        if False and self._check_version('2007-10-10', version):
            # TODO(vish): store ancestor ids
            meta_data['ancestor-ami-ids'] = []

        if self._check_version('2007-12-15', version):
            meta_data['block-device-mapping'] = self.mappings
            if 'kernel-id' in self.ec2_ids:
                meta_data['kernel-id'] = self.ec2_ids['kernel-id']
            if 'ramdisk-id' in self.ec2_ids:
                meta_data['ramdisk-id'] = self.ec2_ids['ramdisk-id']

        if self._check_version('2008-02-01', version):
            meta_data['placement'] = {'availability-zone':
                                      self.availability_zone}

        if self._check_version('2008-09-01', version):
            meta_data['instance-action'] = 'none'

        data = {'meta-data': meta_data}
        if self.userdata_b64 is not None:
            data['user-data'] = self.userdata_b64

        return data

    def _check_version(self, required, requested):
        return VERSIONS.index(requested) >= VERSIONS.index(required)

    def lookup(self, path):
        if path == "" or path[0] != "/":
            path = os.path.normpath("/" + path)
        else:
            path = os.path.normpath(path)

        if path == "/":
            return VERSIONS + ["latest"]

        items = path.split('/')[1:]

        try:
            md = self.get_ec2_metadata(items[0])
        except InvalidMetadataEc2Version:
            raise InvalidMetadataPath(path)

        data = md
        for i in range(1, len(items)):
            if isinstance(data, dict) or isinstance(data, list):
                if items[i] in data:
                    data = data[items[i]]
                else:
                    raise InvalidMetadataPath(path)
            else:
                if i != len(items) - 1:
                    raise InvalidMetadataPath(path)
                data = data[items[i]]

        return data

    def metadata_for_config_drive(self, injected_files):
        """Yields (path, value) tuples for metadata elements."""
        # EC2 style metadata
        for version in VERSIONS:
            if version in FLAGS.config_drive_skip_versions.split(' '):
                continue

            data = self.get_ec2_metadata(version)
            if 'user-data' in data:
                filepath = os.path.join('ec2', version, 'userdata.raw')
                yield (filepath, data['user-data'])
                del data['user-data']

            try:
                del data['public-keys']['0']['_name']
            except KeyError:
                pass

            filepath = os.path.join('ec2', version, 'metadata.json')
            yield (filepath, json.dumps(data['meta-data']))

        filepath = os.path.join('ec2', 'latest', 'metadata.json')
        yield (filepath, json.dumps(data['meta-data']))

        # Openstack style metadata
        # TODO(mikal): refactor this later
        files = []
        for path in injected_files:
            files.append({'path': path,
                          'content': injected_files[path]})
        yield ('openstack/2012-08-10/files.json', json.dumps(files))
        yield ('openstack/latest/files.json', json.dumps(files))


def get_metadata_by_address(address):
    ctxt = context.get_admin_context()
    fixed_ip = network.API().get_fixed_ip_by_address(ctxt, address)

    instance = db.instance_get_by_uuid(ctxt, fixed_ip['instance_uuid'])
    return InstanceMetadata(instance, address)


def _format_instance_mapping(ctxt, instance):
    root_device_name = instance['root_device_name']
    if root_device_name is None:
        return _DEFAULT_MAPPINGS

    mappings = {}
    mappings['ami'] = block_device.strip_dev(root_device_name)
    mappings['root'] = root_device_name
    default_ephemeral_device = instance.get('default_ephemeral_device')
    if default_ephemeral_device:
        mappings['ephemeral0'] = default_ephemeral_device
    default_swap_device = instance.get('default_swap_device')
    if default_swap_device:
        mappings['swap'] = default_swap_device
    ebs_devices = []

    # 'ephemeralN', 'swap' and ebs
    for bdm in db.block_device_mapping_get_all_by_instance(
        ctxt, instance['uuid']):
        if bdm['no_device']:
            continue

        # ebs volume case
        if (bdm['volume_id'] or bdm['snapshot_id']):
            ebs_devices.append(bdm['device_name'])
            continue

        virtual_name = bdm['virtual_name']
        if not virtual_name:
            continue

        if block_device.is_swap_or_ephemeral(virtual_name):
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


def ec2_md_print(data):
    if isinstance(data, dict):
        output = ''
        for key in sorted(data.keys()):
            if key == '_name':
                continue
            if isinstance(data[key], dict):
                if '_name' in data[key]:
                    output += str(data[key]['_name'])
                else:
                    output += key + '/'
            else:
                output += key

            output += '\n'
        return output[:-1]
    elif isinstance(data, list):
        return '\n'.join(data)
    else:
        return str(data)
