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
import posixpath

from oslo.config import cfg

from nova.api.ec2 import ec2utils
from nova.api.metadata import password
from nova import block_device
from nova.compute import flavors
from nova import conductor
from nova import context
from nova import network
from nova.openstack.common import timeutils
from nova.virt import netutils


metadata_opts = [
    cfg.StrOpt('config_drive_skip_versions',
               default=('1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 '
                        '2007-12-15 2008-02-01 2008-09-01'),
               help=('List of metadata versions to skip placing into the '
                     'config drive')),
    ]

CONF = cfg.CONF
CONF.register_opts(metadata_opts)
CONF.import_opt('dhcp_domain', 'nova.network.manager')


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

FOLSOM = '2012-08-10'
GRIZZLY = '2013-04-04'
OPENSTACK_VERSIONS = [
    FOLSOM,
    GRIZZLY,
]

CONTENT_DIR = "content"
MD_JSON_NAME = "meta_data.json"
UD_NAME = "user_data"
PASS_NAME = "password"


class InvalidMetadataVersion(Exception):
    pass


class InvalidMetadataPath(Exception):
    pass


class InstanceMetadata():
    """Instance metadata."""

    def __init__(self, instance, address=None, content=None, extra_md=None,
                 conductor_api=None):
        """Creation of this object should basically cover all time consuming
        collection.  Methods after that should not cause time delays due to
        network operations or lengthy cpu operations.

        The user should then get a single instance and make multiple method
        calls on it.
        """
        if not content:
            content = []

        self.instance = instance
        self.extra_md = extra_md

        if conductor_api:
            capi = conductor_api
        else:
            capi = conductor.API()

        ctxt = context.get_admin_context()

        self.availability_zone = ec2utils.get_availability_zone_by_host(
                instance['host'], capi)

        self.ip_info = ec2utils.get_ip_info_for_instance(ctxt, instance)

        self.security_groups = capi.security_group_get_by_instance(ctxt,
                                                              instance)

        self.mappings = _format_instance_mapping(capi, ctxt, instance)

        if instance.get('user_data', None) is not None:
            self.userdata_raw = base64.b64decode(instance['user_data'])
        else:
            self.userdata_raw = None

        self.ec2_ids = capi.get_ec2_ids(ctxt, instance)

        self.address = address

        # expose instance metadata.
        self.launch_metadata = {}
        for item in instance.get('metadata', []):
            self.launch_metadata[item['key']] = item['value']

        self.password = password.extract_password(instance)

        self.uuid = instance.get('uuid')

        self.content = {}
        self.files = []

        # get network info, and the rendered network template
        network_info = network.API().get_instance_nw_info(ctxt, instance,
                                                          conductor_api=capi)

        self.network_config = None
        cfg = netutils.get_injected_network_template(network_info)

        if cfg:
            key = "%04i" % len(self.content)
            self.content[key] = cfg
            self.network_config = {"name": "network_config",
                'content_path': "/%s/%s" % (CONTENT_DIR, key)}

        # 'content' is passed in from the configdrive code in
        # nova/virt/libvirt/driver.py.  Thats how we get the injected files
        # (personalities) in. AFAIK they're not stored in the db at all,
        # so are not available later (web service metadata time).
        for (path, contents) in content:
            key = "%04i" % len(self.content)
            self.files.append({'path': path,
                'content_path': "/%s/%s" % (CONTENT_DIR, key)})
            self.content[key] = contents

    def get_ec2_metadata(self, version):
        if version == "latest":
            version = VERSIONS[-1]

        if version not in VERSIONS:
            raise InvalidMetadataVersion(version)

        hostname = self._get_hostname()

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
            instance_type = flavors.extract_instance_type(self.instance)
            meta_data['instance-type'] = instance_type['name']

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
        if self.userdata_raw is not None:
            data['user-data'] = self.userdata_raw

        return data

    def get_ec2_item(self, path_tokens):
        # get_ec2_metadata returns dict without top level version
        data = self.get_ec2_metadata(path_tokens[0])
        return find_path_in_tree(data, path_tokens[1:])

    def get_openstack_item(self, path_tokens):
        if path_tokens[0] == CONTENT_DIR:
            if len(path_tokens) == 1:
                raise KeyError("no listing for %s" % "/".join(path_tokens))
            if len(path_tokens) != 2:
                raise KeyError("Too many tokens for /%s" % CONTENT_DIR)
            return self.content[path_tokens[1]]

        version = path_tokens[0]
        if version == "latest":
            version = OPENSTACK_VERSIONS[-1]

        if version not in OPENSTACK_VERSIONS:
            raise InvalidMetadataVersion(version)

        path = '/'.join(path_tokens[1:])

        if len(path_tokens) == 1:
            # request for /version, give a list of what is available
            ret = [MD_JSON_NAME]
            if self.userdata_raw is not None:
                ret.append(UD_NAME)
            if self._check_os_version(GRIZZLY, version):
                ret.append(PASS_NAME)
            return ret

        if path == UD_NAME:
            if self.userdata_raw is None:
                raise KeyError(path)
            return self.userdata_raw

        if path == PASS_NAME and self._check_os_version(GRIZZLY, version):
            return password.handle_password

        if path != MD_JSON_NAME:
            raise KeyError(path)

        # right now, the only valid path is metadata.json
        metadata = {}
        metadata['uuid'] = self.uuid

        if self.launch_metadata:
            metadata['meta'] = self.launch_metadata

        if self.files:
            metadata['files'] = self.files

        if self.extra_md:
            metadata.update(self.extra_md)

        if self.launch_metadata:
            metadata['meta'] = self.launch_metadata

        if self.network_config:
            metadata['network_config'] = self.network_config

        if self.instance['key_name']:
            metadata['public_keys'] = {
                self.instance['key_name']: self.instance['key_data']
            }

        metadata['hostname'] = self._get_hostname()

        metadata['name'] = self.instance['display_name']
        metadata['launch_index'] = self.instance['launch_index']
        metadata['availability_zone'] = self.availability_zone

        if self._check_os_version(GRIZZLY, version):
            metadata['random_seed'] = base64.b64encode(os.urandom(512))

        data = {
            MD_JSON_NAME: json.dumps(metadata),
        }

        return data[path]

    def _check_version(self, required, requested, versions=VERSIONS):
        return versions.index(requested) >= versions.index(required)

    def _check_os_version(self, required, requested):
        return self._check_version(required, requested, OPENSTACK_VERSIONS)

    def _get_hostname(self):
        return "%s%s%s" % (self.instance['hostname'],
                           '.' if CONF.dhcp_domain else '',
                           CONF.dhcp_domain)

    def lookup(self, path):
        if path == "" or path[0] != "/":
            path = posixpath.normpath("/" + path)
        else:
            path = posixpath.normpath(path)

        # fix up requests, prepending /ec2 to anything that does not match
        path_tokens = path.split('/')[1:]
        if path_tokens[0] not in ("ec2", "openstack"):
            if path_tokens[0] == "":
                # request for /
                path_tokens = ["ec2"]
            else:
                path_tokens = ["ec2"] + path_tokens
            path = "/" + "/".join(path_tokens)

        # all values of 'path' input starts with '/' and have no trailing /

        # specifically handle the top level request
        if len(path_tokens) == 1:
            if path_tokens[0] == "openstack":
                # NOTE(vish): don't show versions that are in the future
                today = timeutils.utcnow().strftime("%Y-%m-%d")
                versions = [v for v in OPENSTACK_VERSIONS if v <= today]
                versions += ["latest"]
            else:
                versions = VERSIONS + ["latest"]
            return versions

        try:
            if path_tokens[0] == "openstack":
                data = self.get_openstack_item(path_tokens[1:])
            else:
                data = self.get_ec2_item(path_tokens[1:])
        except (InvalidMetadataVersion, KeyError):
            raise InvalidMetadataPath(path)

        return data

    def metadata_for_config_drive(self):
        """Yields (path, value) tuples for metadata elements."""
        # EC2 style metadata
        for version in VERSIONS + ["latest"]:
            if version in CONF.config_drive_skip_versions.split(' '):
                continue

            data = self.get_ec2_metadata(version)
            if 'user-data' in data:
                filepath = os.path.join('ec2', version, 'user-data')
                yield (filepath, data['user-data'])
                del data['user-data']

            try:
                del data['public-keys']['0']['_name']
            except KeyError:
                pass

            filepath = os.path.join('ec2', version, 'meta-data.json')
            yield (filepath, json.dumps(data['meta-data']))

        for version in OPENSTACK_VERSIONS + ["latest"]:
            path = 'openstack/%s/%s' % (version, MD_JSON_NAME)
            yield (path, self.lookup(path))

            path = 'openstack/%s/%s' % (version, UD_NAME)
            if self.userdata_raw is not None:
                yield (path, self.lookup(path))

        for (cid, content) in self.content.iteritems():
            yield ('%s/%s/%s' % ("openstack", CONTENT_DIR, cid), content)


def get_metadata_by_address(conductor_api, address):
    ctxt = context.get_admin_context()
    fixed_ip = network.API().get_fixed_ip_by_address(ctxt, address)

    return get_metadata_by_instance_id(conductor_api,
                                       fixed_ip['instance_uuid'],
                                       address,
                                       ctxt)


def get_metadata_by_instance_id(conductor_api, instance_id, address,
                                ctxt=None):
    ctxt = ctxt or context.get_admin_context()
    instance = conductor_api.instance_get_by_uuid(ctxt, instance_id)
    return InstanceMetadata(instance, address)


def _format_instance_mapping(conductor_api, ctxt, instance):
    bdms = conductor_api.block_device_mapping_get_all_by_instance(
               ctxt, instance)
    return block_device.instance_block_mapping(instance, bdms)


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


def find_path_in_tree(data, path_tokens):
    # given a dict/list tree, and a path in that tree, return data found there.
    for i in range(0, len(path_tokens)):
        if isinstance(data, dict) or isinstance(data, list):
            if path_tokens[i] in data:
                data = data[path_tokens[i]]
            else:
                raise KeyError("/".join(path_tokens[0:i]))
        else:
            if i != len(path_tokens) - 1:
                raise KeyError("/".join(path_tokens[0:i]))
            data = data[path_tokens[i]]
    return data
