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
import os
import posixpath

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils
from oslo_utils import timeutils
import six

from nova.api.ec2 import ec2utils
from nova.api.metadata import password
from nova import availability_zones as az
from nova import block_device
from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
import nova.conf
from nova import context
from nova import network
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import keypair as keypair_obj
from nova import utils
from nova.virt import netutils


metadata_opts = [
    cfg.StrOpt('config_drive_skip_versions',
               default=('1.0 2007-01-19 2007-03-01 2007-08-29 2007-10-10 '
                        '2007-12-15 2008-02-01 2008-09-01'),
               help='List of metadata versions to skip placing into the '
                    'config drive'),
    cfg.StrOpt('vendordata_driver',
               default='nova.api.metadata.vendordata_json.JsonFileVendorData',
               help='DEPRECATED: Driver to use for vendor data',
               deprecated_for_removal=True),
]

CONF = nova.conf.CONF
CONF.register_opts(metadata_opts)

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
HAVANA = '2013-10-17'
LIBERTY = '2015-10-15'

OPENSTACK_VERSIONS = [
    FOLSOM,
    GRIZZLY,
    HAVANA,
    LIBERTY,
]

VERSION = "version"
CONTENT = "content"
CONTENT_DIR = "content"
MD_JSON_NAME = "meta_data.json"
VD_JSON_NAME = "vendor_data.json"
NW_JSON_NAME = "network_data.json"
UD_NAME = "user_data"
PASS_NAME = "password"
MIME_TYPE_TEXT_PLAIN = "text/plain"
MIME_TYPE_APPLICATION_JSON = "application/json"

LOG = logging.getLogger(__name__)


class InvalidMetadataVersion(Exception):
    pass


class InvalidMetadataPath(Exception):
    pass


class InstanceMetadata(object):
    """Instance metadata."""

    def __init__(self, instance, address=None, content=None, extra_md=None,
                 network_info=None, vd_driver=None, network_metadata=None):
        """Creation of this object should basically cover all time consuming
        collection.  Methods after that should not cause time delays due to
        network operations or lengthy cpu operations.

        The user should then get a single instance and make multiple method
        calls on it.
        """
        if not content:
            content = []

        ctxt = context.get_admin_context()

        # The default value of mimeType is set to MIME_TYPE_TEXT_PLAIN
        self.set_mimetype(MIME_TYPE_TEXT_PLAIN)
        self.instance = instance
        self.extra_md = extra_md

        self.availability_zone = az.get_instance_availability_zone(ctxt,
                                                                   instance)

        secgroup_api = openstack_driver.get_openstack_security_group_driver()
        self.security_groups = secgroup_api.get_instance_security_groups(
            ctxt, instance)

        self.mappings = _format_instance_mapping(ctxt, instance)

        if instance.user_data is not None:
            self.userdata_raw = base64.b64decode(instance.user_data)
        else:
            self.userdata_raw = None

        self.address = address

        # expose instance metadata.
        self.launch_metadata = utils.instance_meta(instance)

        self.password = password.extract_password(instance)

        self.uuid = instance.uuid

        self.content = {}
        self.files = []

        # get network info, and the rendered network template
        if network_info is None:
            network_info = instance.info_cache.network_info

        # expose network metadata
        if network_metadata is None:
            self.network_metadata = netutils.get_network_metadata(network_info)
        else:
            self.network_metadata = network_metadata

        self.ip_info = \
                ec2utils.get_ip_info_for_instance_from_nw_info(network_info)

        self.network_config = None
        cfg = netutils.get_injected_network_template(network_info)

        if cfg:
            key = "%04i" % len(self.content)
            self.content[key] = cfg
            self.network_config = {"name": "network_config",
                'content_path': "/%s/%s" % (CONTENT_DIR, key)}

        # 'content' is passed in from the configdrive code in
        # nova/virt/libvirt/driver.py.  That's how we get the injected files
        # (personalities) in. AFAIK they're not stored in the db at all,
        # so are not available later (web service metadata time).
        for (path, contents) in content:
            key = "%04i" % len(self.content)
            self.files.append({'path': path,
                'content_path': "/%s/%s" % (CONTENT_DIR, key)})
            self.content[key] = contents

        if vd_driver is None:
            vdclass = importutils.import_class(CONF.vendordata_driver)
        else:
            vdclass = vd_driver

        self.vddriver = vdclass(instance=instance, address=address,
                                extra_md=extra_md, network_info=network_info)

        self.route_configuration = None

    def _route_configuration(self):
        if self.route_configuration:
            return self.route_configuration

        path_handlers = {UD_NAME: self._user_data,
                         PASS_NAME: self._password,
                         VD_JSON_NAME: self._vendor_data,
                         MD_JSON_NAME: self._metadata_as_json,
                         NW_JSON_NAME: self._network_data,
                         VERSION: self._handle_version,
                         CONTENT: self._handle_content}

        self.route_configuration = RouteConfiguration(path_handlers)
        return self.route_configuration

    def set_mimetype(self, mime_type):
        self.md_mimetype = mime_type

    def get_mimetype(self):
        return self.md_mimetype

    def get_ec2_metadata(self, version):
        if version == "latest":
            version = VERSIONS[-1]

        if version not in VERSIONS:
            raise InvalidMetadataVersion(version)

        hostname = self._get_hostname()

        floating_ips = self.ip_info['floating_ips']
        floating_ip = floating_ips and floating_ips[0] or ''

        fixed_ips = self.ip_info['fixed_ips']
        fixed_ip = fixed_ips and fixed_ips[0] or ''

        fmt_sgroups = [x['name'] for x in self.security_groups]

        meta_data = {
            'ami-id': self.instance.ec2_ids.ami_id,
            'ami-launch-index': self.instance.launch_index,
            'ami-manifest-path': 'FIXME',
            'instance-id': self.instance.ec2_ids.instance_id,
            'hostname': hostname,
            'local-ipv4': fixed_ip or self.address,
            'reservation-id': self.instance.reservation_id,
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
        if self.instance.key_name:
            meta_data['public-keys'] = {
                '0': {'_name': "0=" + self.instance.key_name,
                      'openssh-key': self.instance.key_data}}

        if self._check_version('2007-01-19', version):
            meta_data['local-hostname'] = hostname
            meta_data['public-hostname'] = hostname
            meta_data['public-ipv4'] = floating_ip

        if False and self._check_version('2007-03-01', version):
            # TODO(vish): store product codes
            meta_data['product-codes'] = []

        if self._check_version('2007-08-29', version):
            instance_type = self.instance.get_flavor()
            meta_data['instance-type'] = instance_type['name']

        if False and self._check_version('2007-10-10', version):
            # TODO(vish): store ancestor ids
            meta_data['ancestor-ami-ids'] = []

        if self._check_version('2007-12-15', version):
            meta_data['block-device-mapping'] = self.mappings
            if self.instance.ec2_ids.kernel_id:
                meta_data['kernel-id'] = self.instance.ec2_ids.kernel_id
            if self.instance.ec2_ids.ramdisk_id:
                meta_data['ramdisk-id'] = self.instance.ec2_ids.ramdisk_id

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
            return self._handle_content(path_tokens)
        return self._route_configuration().handle_path(path_tokens)

    def _metadata_as_json(self, version, path):
        metadata = {'uuid': self.uuid}
        if self.launch_metadata:
            metadata['meta'] = self.launch_metadata
        if self.files:
            metadata['files'] = self.files
        if self.extra_md:
            metadata.update(self.extra_md)
        if self.network_config:
            metadata['network_config'] = self.network_config
        if self.instance.key_name:
            metadata['public_keys'] = {
                self.instance.key_name: self.instance.key_data
            }

            if cells_opts.get_cell_type() == 'compute':
                cells_api = cells_rpcapi.CellsAPI()
                keypair = cells_api.get_keypair_at_top(
                  context.get_admin_context(), self.instance.user_id,
                  self.instance.key_name)
            else:
                keypair = keypair_obj.KeyPair.get_by_name(
                    context.get_admin_context(), self.instance.user_id,
                    self.instance.key_name)
            metadata['keys'] = [
                {'name': keypair.name,
                 'type': keypair.type,
                 'data': keypair.public_key}
            ]

        metadata['hostname'] = self._get_hostname()
        metadata['name'] = self.instance.display_name
        metadata['launch_index'] = self.instance.launch_index
        metadata['availability_zone'] = self.availability_zone

        if self._check_os_version(GRIZZLY, version):
            metadata['random_seed'] = base64.b64encode(os.urandom(512))

        if self._check_os_version(LIBERTY, version):
            metadata['project_id'] = self.instance.project_id

        self.set_mimetype(MIME_TYPE_APPLICATION_JSON)
        return jsonutils.dump_as_bytes(metadata)

    def _handle_content(self, path_tokens):
        if len(path_tokens) == 1:
            raise KeyError("no listing for %s" % "/".join(path_tokens))
        if len(path_tokens) != 2:
            raise KeyError("Too many tokens for /%s" % CONTENT_DIR)
        return self.content[path_tokens[1]]

    def _handle_version(self, version, path):
        # request for /version, give a list of what is available
        ret = [MD_JSON_NAME]
        if self.userdata_raw is not None:
            ret.append(UD_NAME)
        if self._check_os_version(GRIZZLY, version):
            ret.append(PASS_NAME)
        if self._check_os_version(HAVANA, version):
            ret.append(VD_JSON_NAME)
        if self._check_os_version(LIBERTY, version):
            ret.append(NW_JSON_NAME)

        return ret

    def _user_data(self, version, path):
        if self.userdata_raw is None:
            raise KeyError(path)
        return self.userdata_raw

    def _network_data(self, version, path):
        if self.network_metadata is None:
            return jsonutils.dump_as_bytes({})
        return jsonutils.dump_as_bytes(self.network_metadata)

    def _password(self, version, path):
        if self._check_os_version(GRIZZLY, version):
            return password.handle_password
        raise KeyError(path)

    def _vendor_data(self, version, path):
        if self._check_os_version(HAVANA, version):
            self.set_mimetype(MIME_TYPE_APPLICATION_JSON)
            return jsonutils.dump_as_bytes(self.vddriver.get())
        raise KeyError(path)

    def _check_version(self, required, requested, versions=VERSIONS):
        return versions.index(requested) >= versions.index(required)

    def _check_os_version(self, required, requested):
        return self._check_version(required, requested, OPENSTACK_VERSIONS)

    def _get_hostname(self):
        return "%s%s%s" % (self.instance.hostname,
                           '.' if CONF.dhcp_domain else '',
                           CONF.dhcp_domain)

    def lookup(self, path):
        if path == "" or path[0] != "/":
            path = posixpath.normpath("/" + path)
        else:
            path = posixpath.normpath(path)

        # Set default mimeType. It will be modified only if there is a change
        self.set_mimetype(MIME_TYPE_TEXT_PLAIN)

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
                if OPENSTACK_VERSIONS != versions:
                    LOG.debug("future versions %s hidden in version list",
                              [v for v in OPENSTACK_VERSIONS
                               if v not in versions])
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
            yield (filepath, jsonutils.dump_as_bytes(data['meta-data']))

        ALL_OPENSTACK_VERSIONS = OPENSTACK_VERSIONS + ["latest"]
        for version in ALL_OPENSTACK_VERSIONS:
            path = 'openstack/%s/%s' % (version, MD_JSON_NAME)
            yield (path, self.lookup(path))

            path = 'openstack/%s/%s' % (version, UD_NAME)
            if self.userdata_raw is not None:
                yield (path, self.lookup(path))

            if self._check_version(HAVANA, version, ALL_OPENSTACK_VERSIONS):
                path = 'openstack/%s/%s' % (version, VD_JSON_NAME)
                yield (path, self.lookup(path))

            if self._check_version(LIBERTY, version, ALL_OPENSTACK_VERSIONS):
                path = 'openstack/%s/%s' % (version, NW_JSON_NAME)
                yield (path, self.lookup(path))

        for (cid, content) in six.iteritems(self.content):
            yield ('%s/%s/%s' % ("openstack", CONTENT_DIR, cid), content)


class RouteConfiguration(object):
    """Routes metadata paths to request handlers."""

    def __init__(self, path_handler):
        self.path_handlers = path_handler

    def _version(self, version):
        if version == "latest":
            version = OPENSTACK_VERSIONS[-1]

        if version not in OPENSTACK_VERSIONS:
            raise InvalidMetadataVersion(version)

        return version

    def handle_path(self, path_tokens):
        version = self._version(path_tokens[0])
        if len(path_tokens) == 1:
            path = VERSION
        else:
            path = '/'.join(path_tokens[1:])

        path_handler = self.path_handlers[path]

        if path_handler is None:
            raise KeyError(path)

        return path_handler(version, path)


class VendorDataDriver(object):
    """The base VendorData Drivers should inherit from."""

    def __init__(self, *args, **kwargs):
        """Init method should do all expensive operations."""
        self._data = {}

    def get(self):
        """Return a dictionary of primitives to be rendered in metadata

        :return: A dictionary or primitives.
        """
        return self._data


def get_metadata_by_address(address):
    ctxt = context.get_admin_context()
    fixed_ip = network.API().get_fixed_ip_by_address(ctxt, address)

    return get_metadata_by_instance_id(fixed_ip['instance_uuid'],
                                       address,
                                       ctxt)


def get_metadata_by_instance_id(instance_id, address, ctxt=None):
    ctxt = ctxt or context.get_admin_context()
    instance = objects.Instance.get_by_uuid(
        ctxt, instance_id, expected_attrs=['ec2_ids', 'flavor', 'info_cache',
                                           'metadata', 'system_metadata',
                                           'security_groups'])
    return InstanceMetadata(instance, address)


def _format_instance_mapping(ctxt, instance):
    bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            ctxt, instance.uuid)
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
