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

"""Metadata request handler."""

import base64
import collections

import webob.dec
import webob.exc

from nova.api.ec2 import ec2utils
from nova import block_device
from nova import compute
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import network
from nova.rpc import common as rpc_common
from nova import utils
from nova import volume
from nova import wsgi


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('use_forwarded_for', 'nova.api.auth')
flags.DECLARE('dhcp_domain', 'nova.network.manager')

if FLAGS.memcached_servers:
    import memcache
else:
    from nova.common import memorycache as memcache

_DEFAULT_MAPPINGS = {'ami': 'sda1',
                     'ephemeral0': 'sda2',
                     'root': block_device.DEFAULT_ROOT_DEV_NAME,
                     'swap': 'sda3'}


class Versions(wsgi.Application):

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Respond to a request for all versions."""
        # available api versions
        versions = [
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
        return ''.join('%s\n' % v for v in versions)


class MetadataRequestHandler(wsgi.Application):
    """Serve metadata."""

    def __init__(self):
        self.network_api = network.API()
        self.compute_api = compute.API(
                network_api=self.network_api,
                volume_api=volume.API())

        self.metadata_mapper = {
            'user-data': self.user_data,
            'meta-data': {
                'instance-id': self.instance_id,
                'instance-type': self.instance_type,
                'ami-id': self.ami_id,
                'kernel-id': self.kernel_id,
                'ramdisk-id': self.ramdisk_id,
                'block-device-mapping': self.block_device_mapping,
                'hostname': self.hostname,
                'public-hostname': self.hostname,
                'local-hostname': self.hostname,
                'local-ipv4': self.local_ipv4,
                'public-ipv4': self.public_ipv4,
                'security-groups': self.security_groups,
                'public-keys': self.public_keys,
                'ami-launch-index': self.ami_launch_index,
                'reservation-id': self.reservation_id,
                'placement': self.placement,
                'instance-action': self.instance_action,
                'ami-manifest-path': self.ami_manifest_path,
            }
        }

        self._cache = memcache.Client(FLAGS.memcached_servers, debug=0)

    def _format_instance_mapping(self, instance_ref):
        ctxt = context.get_admin_context()

        root_device_name = instance_ref['root_device_name']
        if root_device_name is None:
            return _DEFAULT_MAPPINGS

        mappings = {}
        mappings['ami'] = block_device.strip_dev(root_device_name)
        mappings['root'] = root_device_name
        default_ephemeral_device = instance_ref.get('default_ephemeral_device')
        if default_ephemeral_device:
            mappings['ephemeral0'] = default_ephemeral_device
        default_swap_device = instance_ref.get('default_swap_device')
        if default_swap_device:
            mappings['swap'] = default_swap_device
        ebs_devices = []

        # 'ephemeralN', 'swap' and ebs
        for bdm in db.block_device_mapping_get_all_by_instance(
            ctxt, instance_ref['id']):
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

    def get_instance(self, address):
        """get instance_ref for a given fixed_ip, raising
        exception.NotFound if unable to find instance

        this will attempt to use memcache or fake memcache (an in-memory
        cache) to remove the DB query + RPC query for batched calls (eg
        cloud-init making dozens of queries on boot)
        """

        cache_key = 'metadata-%s' % address
        instance_dict = self._cache.get(cache_key)
        if instance_dict:
            return instance_dict

        if not address:
            raise exception.FixedIpNotFoundForAddress(address=address)

        ctxt = context.get_admin_context()

        try:
            fixed_ip = self.network_api.get_fixed_ip_by_address(ctxt, address)
        except rpc_common.RemoteError:
            raise exception.FixedIpNotFoundForAddress(address=address)
        instance_ref = db.instance_get(ctxt, fixed_ip['instance_id'])
        instance_dict = utils.to_primitive(instance_ref)

        self._cache.set(cache_key, instance_dict, 15)

        return instance_dict

    def user_data(self, address):
        instance_ref = self.get_instance(address)
        return base64.b64decode(instance_ref['user_data'])

    def instance_id(self, address):
        instance_ref = self.get_instance(address)
        return ec2utils.id_to_ec2_id(instance_ref['id'])

    def instance_type(self, address):
        instance_ref = self.get_instance(address)
        return instance_ref['instance_type']['name']

    def ami_id(self, address):
        instance_ref = self.get_instance(address)
        return ec2utils.image_ec2_id(instance_ref['image_ref'])

    def kernel_id(self, address):
        instance_ref = self.get_instance(address)
        kernel_id = instance_ref.get('kernel_id')
        if kernel_id:
            return ec2utils.image_ec2_id(kernel_id,
                                         ec2utils.image_type('kernel'))

    def ramdisk_id(self, address):
        instance_ref = self.get_instance(address)
        ramdisk_id = instance_ref.get('ramdisk_id')
        if ramdisk_id:
            return ec2utils.image_ec2_id(ramdisk_id,
                                         ec2utils.image_type('ramdisk'))

    def ami_launch_index(self, address):
        instance_ref = self.get_instance(address)
        return instance_ref['launch_index']

    def block_device_mapping(self, address):
        instance_ref = self.get_instance(address)
        return self._format_instance_mapping(instance_ref)

    def hostname(self, address):
        instance_ref = self.get_instance(address)
        return "%s.%s" % (instance_ref['hostname'], FLAGS.dhcp_domain)

    def local_ipv4(self, address):
        return address

    def public_ipv4(self, address):
        instance_ref = self.get_instance(address)
        ctxt = context.get_admin_context()
        ip_info = ec2utils.get_ip_info_for_instance(ctxt, instance_ref)
        floating_ips = ip_info['floating_ips']
        floating_ip = floating_ips and floating_ips[0] or ''
        return floating_ip

    def reservation_id(self, address):
        instance_ref = self.get_instance(address)
        return instance_ref['reservation_id']

    def placement(self, address):
        instance_ref = self.get_instance(address)
        host = instance_ref['host']
        ctxt = context.get_admin_context()
        # note(ja): original code had ctx.elevated?
        services = db.service_get_all_by_host(ctxt, host)
        zone = ec2utils.get_availability_zone_by_host(services, host)
        return {'availability-zone': zone}

    def security_groups(self, address):
        instance_ref = self.get_instance(address)
        ctxt = context.get_admin_context()
        groups = db.security_group_get_by_instance(ctxt,
                                                   instance_ref['id'])
        return [g['name'] for g in groups]

    def public_keys(self, address):
        instance_ref = self.get_instance(address)
        # public-keys should be in meta-data only if user specified one
        if instance_ref['key_name']:
            return {'0': {'_name': instance_ref['key_name'],
                          'openssh-key': instance_ref['key_data']}}

    def ami_manifest_path(self, address):
        return 'Not Implemented'

    def instance_action(self, address):
        return 'none'

    def format_data(self, data):
        if isinstance(data, dict):
            output = ''
            for key in data:
                if key == '_name':
                    continue
                output += key
                if isinstance(data[key], dict):
                    if '_name' in data[key]:
                        output += '=' + str(data[key]['_name'])
                    else:
                        output += '/'
                output += '\n'
            # Cut off last \n
            return output[:-1]
        elif isinstance(data, list):
            return '\n'.join(data)
        else:
            return str(data)

    def lookup(self, path, address):
        items = path.split('/')
        data = self.metadata_mapper
        for item in items:
            if item:
                if not isinstance(data, dict):
                    # FIXME(ja): should we check that we are at the end
                    # of the path as well before we just return?
                    return data
                if not item in data:
                    return None
                data = data[item]
                if isinstance(data, collections.Callable):
                    # lazy evaluation
                    data = data(address)
        return data

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        remote_address = req.remote_addr
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        try:
            data = self.lookup(req.path_info,
                               remote_address)
        except (exception.NotFound, exception.FixedIpNotFoundForAddress):
            LOG.error(_('Failed to get metadata for ip: %s'), remote_address)
            return webob.exc.HTTPNotFound()
        except:
            LOG.exception(_('Failed to get metadata for ip: %s'),
                          remote_address)
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            return webob.exc.HTTPInternalServerError(explanation=unicode(msg))

        if data is None:
            raise webob.exc.HTTPNotFound()
        return self.format_data(data)
