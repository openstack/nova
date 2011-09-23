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

"""
Cloud Controller: Implementation of EC2 REST API calls, which are
dispatched to other nodes via AMQP RPC. State is via distributed
datastore.
"""

import base64
import netaddr
import os
import re
import shutil
import tempfile
import time
import urllib

from nova import block_device
from nova import compute
from nova import context

from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import ipv6
from nova import log as logging
from nova import network
from nova import rpc
from nova import utils
from nova import volume
from nova.api.ec2 import ec2utils
from nova.compute import instance_types
from nova.compute import vm_states
from nova.image import s3


FLAGS = flags.FLAGS
flags.DECLARE('dhcp_domain', 'nova.network.manager')
flags.DECLARE('service_down_time', 'nova.scheduler.driver')

LOG = logging.getLogger("nova.api.cloud")


def _gen_key(context, user_id, key_name):
    """Generate a key

    This is a module level method because it is slow and we need to defer
    it into a process pool."""
    # NOTE(vish): generating key pair is slow so check for legal
    #             creation before creating key_pair
    try:
        db.key_pair_get(context, user_id, key_name)
        raise exception.KeyPairExists(key_name=key_name)
    except exception.NotFound:
        pass
    private_key, public_key, fingerprint = crypto.generate_key_pair()
    key = {}
    key['user_id'] = user_id
    key['name'] = key_name
    key['public_key'] = public_key
    key['fingerprint'] = fingerprint
    db.key_pair_create(context, key)
    return {'private_key': private_key, 'fingerprint': fingerprint}


# EC2 API can return the following values as documented in the EC2 API
# http://docs.amazonwebservices.com/AWSEC2/latest/APIReference/
#    ApiReference-ItemType-InstanceStateType.html
# pending | running | shutting-down | terminated | stopping | stopped
_STATE_DESCRIPTION_MAP = {
    None: 'pending',
    vm_states.ACTIVE: 'running',
    vm_states.BUILDING: 'pending',
    vm_states.REBUILDING: 'pending',
    vm_states.DELETED: 'terminated',
    vm_states.STOPPED: 'stopped',
    vm_states.MIGRATING: 'migrate',
    vm_states.RESIZING: 'resize',
    vm_states.PAUSED: 'pause',
    vm_states.SUSPENDED: 'suspend',
    vm_states.RESCUED: 'rescue',
}


def state_description_from_vm_state(vm_state):
    """Map the vm state to the server status string"""
    return _STATE_DESCRIPTION_MAP.get(vm_state, vm_state)


# TODO(yamahata): hypervisor dependent default device name
_DEFAULT_ROOT_DEVICE_NAME = '/dev/sda1'
_DEFAULT_MAPPINGS = {'ami': 'sda1',
                     'ephemeral0': 'sda2',
                     'root': _DEFAULT_ROOT_DEVICE_NAME,
                     'swap': 'sda3'}


def _parse_block_device_mapping(bdm):
    """Parse BlockDeviceMappingItemType into flat hash
    BlockDevicedMapping.<N>.DeviceName
    BlockDevicedMapping.<N>.Ebs.SnapshotId
    BlockDevicedMapping.<N>.Ebs.VolumeSize
    BlockDevicedMapping.<N>.Ebs.DeleteOnTermination
    BlockDevicedMapping.<N>.Ebs.NoDevice
    BlockDevicedMapping.<N>.VirtualName
    => remove .Ebs and allow volume id in SnapshotId
    """
    ebs = bdm.pop('ebs', None)
    if ebs:
        ec2_id = ebs.pop('snapshot_id', None)
        if ec2_id:
            id = ec2utils.ec2_id_to_id(ec2_id)
            if ec2_id.startswith('snap-'):
                bdm['snapshot_id'] = id
            elif ec2_id.startswith('vol-'):
                bdm['volume_id'] = id
            ebs.setdefault('delete_on_termination', True)
        bdm.update(ebs)
    return bdm


def _properties_get_mappings(properties):
    return block_device.mappings_prepend_dev(properties.get('mappings', []))


def _format_block_device_mapping(bdm):
    """Contruct BlockDeviceMappingItemType
    {'device_name': '...', 'snapshot_id': , ...}
    => BlockDeviceMappingItemType
    """
    keys = (('deviceName', 'device_name'),
             ('virtualName', 'virtual_name'))
    item = {}
    for name, k in keys:
        if k in bdm:
            item[name] = bdm[k]
    if bdm.get('no_device'):
        item['noDevice'] = True
    if ('snapshot_id' in bdm) or ('volume_id' in bdm):
        ebs_keys = (('snapshotId', 'snapshot_id'),
                    ('snapshotId', 'volume_id'),        # snapshotId is abused
                    ('volumeSize', 'volume_size'),
                    ('deleteOnTermination', 'delete_on_termination'))
        ebs = {}
        for name, k in ebs_keys:
            if k in bdm:
                if k == 'snapshot_id':
                    ebs[name] = ec2utils.id_to_ec2_snap_id(bdm[k])
                elif k == 'volume_id':
                    ebs[name] = ec2utils.id_to_ec2_vol_id(bdm[k])
                else:
                    ebs[name] = bdm[k]
        assert 'snapshotId' in ebs
        item['ebs'] = ebs
    return item


def _format_mappings(properties, result):
    """Format multiple BlockDeviceMappingItemType"""
    mappings = [{'virtualName': m['virtual'], 'deviceName': m['device']}
                for m in _properties_get_mappings(properties)
                if block_device.is_swap_or_ephemeral(m['virtual'])]

    block_device_mapping = [_format_block_device_mapping(bdm) for bdm in
                            properties.get('block_device_mapping', [])]

    # NOTE(yamahata): overwrite mappings with block_device_mapping
    for bdm in block_device_mapping:
        for i in range(len(mappings)):
            if bdm['deviceName'] == mappings[i]['deviceName']:
                del mappings[i]
                break
        mappings.append(bdm)

    # NOTE(yamahata): trim ebs.no_device == true. Is this necessary?
    mappings = [bdm for bdm in mappings if not (bdm.get('noDevice', False))]

    if mappings:
        result['blockDeviceMapping'] = mappings


class CloudController(object):
    """ CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self.image_service = s3.S3ImageService()
        self.network_api = network.API()
        self.volume_api = volume.API()
        self.compute_api = compute.API(
                network_api=self.network_api,
                volume_api=self.volume_api)
        self.setup()

    def __str__(self):
        return 'CloudController'

    def setup(self):
        """ Ensure the keychains and folders exist. """
        # FIXME(ja): this should be moved to a nova-manage command,
        # if not setup throw exceptions instead of running
        # Create keys folder, if it doesn't exist
        if not os.path.exists(FLAGS.keys_path):
            os.makedirs(FLAGS.keys_path)
        # Gen root CA, if we don't have one
        root_ca_path = os.path.join(FLAGS.ca_path, FLAGS.ca_file)
        if not os.path.exists(root_ca_path):
            genrootca_sh_path = os.path.join(os.path.dirname(__file__),
                                             os.path.pardir,
                                             os.path.pardir,
                                             'CA',
                                             'genrootca.sh')

            start = os.getcwd()
            if not os.path.exists(FLAGS.ca_path):
                os.makedirs(FLAGS.ca_path)
            os.chdir(FLAGS.ca_path)
            # TODO(vish): Do this with M2Crypto instead
            utils.runthis(_("Generating root CA: %s"), "sh", genrootca_sh_path)
            os.chdir(start)

    def _get_mpi_data(self, context, project_id):
        result = {}
        search_opts = {'project_id': project_id}
        for instance in self.compute_api.get_all(context,
                search_opts=search_opts):
            if instance['fixed_ips']:
                line = '%s slots=%d' % (instance['fixed_ips'][0]['address'],
                                        instance['vcpus'])
                key = str(instance['key_name'])
                if key in result:
                    result[key].append(line)
                else:
                    result[key] = [line]
        return result

    def _get_availability_zone_by_host(self, context, host):
        services = db.service_get_all_by_host(context.elevated(), host)
        if len(services) > 0:
            return services[0]['availability_zone']
        return 'unknown zone'

    def _get_image_state(self, image):
        # NOTE(vish): fallback status if image_state isn't set
        state = image.get('status')
        if state == 'active':
            state = 'available'
        return image['properties'].get('image_state', state)

    def _format_instance_mapping(self, ctxt, instance_ref):
        root_device_name = instance_ref['root_device_name']
        if root_device_name is None:
            return _DEFAULT_MAPPINGS

        mappings = {}
        mappings['ami'] = block_device.strip_dev(root_device_name)
        mappings['root'] = root_device_name
        default_local_device = instance_ref.get('default_local_device')
        if default_local_device:
            mappings['ephemeral0'] = default_local_device
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

    def get_metadata(self, address):
        ctxt = context.get_admin_context()
        search_opts = {'fixed_ip': address}
        try:
            instance_ref = self.compute_api.get_all(ctxt,
                    search_opts=search_opts)
        except exception.NotFound:
            instance_ref = None
        if not instance_ref:
            return None

        # This ensures that all attributes of the instance
        # are populated.
        instance_ref = db.instance_get(ctxt, instance_ref[0]['id'])

        mpi = self._get_mpi_data(ctxt, instance_ref['project_id'])
        hostname = "%s.%s" % (instance_ref['hostname'], FLAGS.dhcp_domain)
        host = instance_ref['host']
        availability_zone = self._get_availability_zone_by_host(ctxt, host)
        floating_ip = db.instance_get_floating_address(ctxt,
                                                       instance_ref['id'])
        ec2_id = ec2utils.id_to_ec2_id(instance_ref['id'])
        image_ec2_id = self.image_ec2_id(instance_ref['image_ref'])
        security_groups = db.security_group_get_by_instance(ctxt,
                                                            instance_ref['id'])
        security_groups = [x['name'] for x in security_groups]
        mappings = self._format_instance_mapping(ctxt, instance_ref)
        data = {
            'user-data': self._format_user_data(instance_ref),
            'meta-data': {
                'ami-id': image_ec2_id,
                'ami-launch-index': instance_ref['launch_index'],
                'ami-manifest-path': 'FIXME',
                'block-device-mapping': mappings,
                'hostname': hostname,
                'instance-action': 'none',
                'instance-id': ec2_id,
                'instance-type': instance_ref['instance_type']['name'],
                'local-hostname': hostname,
                'local-ipv4': address,
                'placement': {'availability-zone': availability_zone},
                'public-hostname': hostname,
                'public-ipv4': floating_ip or '',
                'reservation-id': instance_ref['reservation_id'],
                'security-groups': security_groups,
                'mpi': mpi}}

        # public-keys should be in meta-data only if user specified one
        if instance_ref['key_name']:
            data['meta-data']['public-keys'] = {
                '0': {'_name': instance_ref['key_name'],
                      'openssh-key': instance_ref['key_data']}}

        for image_type in ['kernel', 'ramdisk']:
            if instance_ref.get('%s_id' % image_type):
                ec2_id = self.image_ec2_id(instance_ref['%s_id' % image_type],
                                           self._image_type(image_type))
                data['meta-data']['%s-id' % image_type] = ec2_id

        if False:  # TODO(vish): store ancestor ids
            data['ancestor-ami-ids'] = []
        if False:  # TODO(vish): store product codes
            data['product-codes'] = []
        return data

    def describe_availability_zones(self, context, **kwargs):
        if ('zone_name' in kwargs and
            'verbose' in kwargs['zone_name'] and
            context.is_admin):
            return self._describe_availability_zones_verbose(context,
                                                             **kwargs)
        else:
            return self._describe_availability_zones(context, **kwargs)

    def _describe_availability_zones(self, context, **kwargs):
        ctxt = context.elevated()
        enabled_services = db.service_get_all(ctxt, False)
        disabled_services = db.service_get_all(ctxt, True)
        available_zones = []
        for zone in [service.availability_zone for service
                     in enabled_services]:
            if not zone in available_zones:
                available_zones.append(zone)
        not_available_zones = []
        for zone in [service.availability_zone for service in disabled_services
                     if not service['availability_zone'] in available_zones]:
            if not zone in not_available_zones:
                not_available_zones.append(zone)
        result = []
        for zone in available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "available"})
        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "not available"})
        return {'availabilityZoneInfo': result}

    def _describe_availability_zones_verbose(self, context, **kwargs):
        rv = {'availabilityZoneInfo': [{'zoneName': 'nova',
                                        'zoneState': 'available'}]}

        services = db.service_get_all(context, False)
        now = utils.utcnow()
        hosts = []
        for host in [service['host'] for service in services]:
            if not host in hosts:
                hosts.append(host)
        for host in hosts:
            rv['availabilityZoneInfo'].append({'zoneName': '|- %s' % host,
                                               'zoneState': ''})
            hsvcs = [service for service in services \
                     if service['host'] == host]
            for svc in hsvcs:
                delta = now - (svc['updated_at'] or svc['created_at'])
                alive = (delta.seconds <= FLAGS.service_down_time)
                art = (alive and ":-)") or "XXX"
                active = 'enabled'
                if svc['disabled']:
                    active = 'disabled'
                rv['availabilityZoneInfo'].append({
                        'zoneName': '| |- %s' % svc['binary'],
                        'zoneState': '%s %s %s' % (active, art,
                                                   svc['updated_at'])})
        return rv

    def describe_regions(self, context, region_name=None, **kwargs):
        if FLAGS.region_list:
            regions = []
            for region in FLAGS.region_list:
                name, _sep, host = region.partition('=')
                endpoint = '%s://%s:%s%s' % (FLAGS.ec2_scheme,
                                             host,
                                             FLAGS.ec2_port,
                                             FLAGS.ec2_path)
                regions.append({'regionName': name,
                                'regionEndpoint': endpoint})
        else:
            regions = [{'regionName': 'nova',
                        'regionEndpoint': '%s://%s:%s%s' % (FLAGS.ec2_scheme,
                                                            FLAGS.ec2_host,
                                                            FLAGS.ec2_port,
                                                            FLAGS.ec2_path)}]
        return {'regionInfo': regions}

    def describe_snapshots(self,
                           context,
                           snapshot_id=None,
                           owner=None,
                           restorable_by=None,
                           **kwargs):
        if snapshot_id:
            snapshots = []
            for ec2_id in snapshot_id:
                internal_id = ec2utils.ec2_id_to_id(ec2_id)
                snapshot = self.volume_api.get_snapshot(
                    context,
                    snapshot_id=internal_id)
                snapshots.append(snapshot)
        else:
            snapshots = self.volume_api.get_all_snapshots(context)
        snapshots = [self._format_snapshot(context, s) for s in snapshots]
        return {'snapshotSet': snapshots}

    def _format_snapshot(self, context, snapshot):
        s = {}
        s['snapshotId'] = ec2utils.id_to_ec2_snap_id(snapshot['id'])
        s['volumeId'] = ec2utils.id_to_ec2_vol_id(snapshot['volume_id'])
        s['status'] = snapshot['status']
        s['startTime'] = snapshot['created_at']
        s['progress'] = snapshot['progress']
        s['ownerId'] = snapshot['project_id']
        s['volumeSize'] = snapshot['volume_size']
        s['description'] = snapshot['display_description']

        s['display_name'] = snapshot['display_name']
        s['display_description'] = snapshot['display_description']
        return s

    def create_snapshot(self, context, volume_id, **kwargs):
        LOG.audit(_("Create snapshot of volume %s"), volume_id,
                  context=context)
        volume_id = ec2utils.ec2_id_to_id(volume_id)
        snapshot = self.volume_api.create_snapshot(
                context,
                volume_id=volume_id,
                name=kwargs.get('display_name'),
                description=kwargs.get('display_description'))
        return self._format_snapshot(context, snapshot)

    def delete_snapshot(self, context, snapshot_id, **kwargs):
        snapshot_id = ec2utils.ec2_id_to_id(snapshot_id)
        self.volume_api.delete_snapshot(context, snapshot_id=snapshot_id)
        return True

    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = db.key_pair_get_all_by_user(context, context.user_id)
        if not key_name is None:
            key_pairs = [x for x in key_pairs if x['name'] in key_name]

        result = []
        for key_pair in key_pairs:
            # filter out the vpn keys
            suffix = FLAGS.vpn_key_suffix
            if context.is_admin or \
               not key_pair['name'].endswith(suffix):
                result.append({
                    'keyName': key_pair['name'],
                    'keyFingerprint': key_pair['fingerprint'],
                })

        return {'keySet': result}

    def create_key_pair(self, context, key_name, **kwargs):
        LOG.audit(_("Create key pair %s"), key_name, context=context)
        data = _gen_key(context, context.user_id, key_name)
        return {'keyName': key_name,
                'keyFingerprint': data['fingerprint'],
                'keyMaterial': data['private_key']}
        # TODO(vish): when context is no longer an object, pass it here

    def import_public_key(self, context, key_name, public_key,
                         fingerprint=None):
        LOG.audit(_("Import key %s"), key_name, context=context)
        key = {}
        key['user_id'] = context.user_id
        key['name'] = key_name
        key['public_key'] = public_key
        if fingerprint is None:
            tmpdir = tempfile.mkdtemp()
            pubfile = os.path.join(tmpdir, 'temp.pub')
            fh = open(pubfile, 'w')
            fh.write(public_key)
            fh.close()
            (out, err) = utils.execute('ssh-keygen', '-q', '-l', '-f',
                                       '%s' % (pubfile))
            fingerprint = out.split(' ')[1]
            shutil.rmtree(tmpdir)
        key['fingerprint'] = fingerprint
        db.key_pair_create(context, key)
        return True

    def delete_key_pair(self, context, key_name, **kwargs):
        LOG.audit(_("Delete key pair %s"), key_name, context=context)
        try:
            db.key_pair_destroy(context, context.user_id, key_name)
        except exception.NotFound:
            # aws returns true even if the key doesn't exist
            pass
        return True

    def describe_security_groups(self, context, group_name=None, group_id=None,
                                 **kwargs):
        self.compute_api.ensure_default_security_group(context)
        if group_name or group_id:
            groups = []
            if group_name:
                for name in group_name:
                    group = db.security_group_get_by_name(context,
                                                          context.project_id,
                                                          name)
                    groups.append(group)
            if group_id:
                for gid in group_id:
                    group = db.security_group_get(context, gid)
                    groups.append(group)
        elif context.is_admin:
            groups = db.security_group_get_all(context)
        else:
            groups = db.security_group_get_by_project(context,
                                                      context.project_id)
        groups = [self._format_security_group(context, g) for g in groups]

        return {'securityGroupInfo':
                list(sorted(groups,
                            key=lambda k: (k['ownerId'], k['groupName'])))}

    def _format_security_group(self, context, group):
        g = {}
        g['groupDescription'] = group.description
        g['groupName'] = group.name
        g['ownerId'] = group.project_id
        g['ipPermissions'] = []
        for rule in group.rules:
            r = {}
            r['groups'] = []
            r['ipRanges'] = []
            if rule.group_id:
                source_group = db.security_group_get(context, rule.group_id)
                r['groups'] += [{'groupName': source_group.name,
                                 'userId': source_group.project_id}]
                if rule.protocol:
                    r['ipProtocol'] = rule.protocol
                    r['fromPort'] = rule.from_port
                    r['toPort'] = rule.to_port
                    g['ipPermissions'] += [dict(r)]
                else:
                    for protocol, min_port, max_port in (('icmp', -1, -1),
                                                         ('tcp', 1, 65535),
                                                         ('udp', 1, 65536)):
                        r['ipProtocol'] = protocol
                        r['fromPort'] = min_port
                        r['toPort'] = max_port
                        g['ipPermissions'] += [dict(r)]
            else:
                r['ipProtocol'] = rule.protocol
                r['fromPort'] = rule.from_port
                r['toPort'] = rule.to_port
                r['ipRanges'] += [{'cidrIp': rule.cidr}]
                g['ipPermissions'] += [r]
        return g

    def _rule_args_to_dict(self, context, kwargs):
        rules = []
        if not 'groups' in kwargs and not 'ip_ranges' in kwargs:
            rule = self._rule_dict_last_step(context, **kwargs)
            if rule:
                rules.append(rule)
            return rules
        if 'ip_ranges' in kwargs:
            rules = self._cidr_args_split(kwargs)
        else:
            rules = [kwargs]
        finalset = []
        for rule in rules:
            if 'groups' in rule:
                groups_values = self._groups_args_split(rule)
                for groups_value in groups_values:
                    final = self._rule_dict_last_step(context, **groups_value)
                    finalset.append(final)
            else:
                final = self._rule_dict_last_step(context, **rule)
                finalset.append(final)
        return finalset

    def _cidr_args_split(self, kwargs):
        cidr_args_split = []
        cidrs = kwargs['ip_ranges']
        for key, cidr in cidrs.iteritems():
            mykwargs = kwargs.copy()
            del mykwargs['ip_ranges']
            mykwargs['cidr_ip'] = cidr['cidr_ip']
            cidr_args_split.append(mykwargs)
        return cidr_args_split

    def _groups_args_split(self, kwargs):
        groups_args_split = []
        groups = kwargs['groups']
        for key, group in groups.iteritems():
            mykwargs = kwargs.copy()
            del mykwargs['groups']
            if 'group_name' in group:
                mykwargs['source_security_group_name'] = group['group_name']
            if 'user_id' in group:
                mykwargs['source_security_group_owner_id'] = group['user_id']
            if 'group_id' in group:
                mykwargs['source_security_group_id'] = group['group_id']
            groups_args_split.append(mykwargs)
        return groups_args_split

    def _rule_dict_last_step(self, context, to_port=None, from_port=None,
                                  ip_protocol=None, cidr_ip=None, user_id=None,
                                  source_security_group_name=None,
                                  source_security_group_owner_id=None):

        values = {}

        if source_security_group_name:
            source_project_id = self._get_source_project_id(context,
                source_security_group_owner_id)

            source_security_group = \
                    db.security_group_get_by_name(context.elevated(),
                                                  source_project_id,
                                                  source_security_group_name)
            notfound = exception.SecurityGroupNotFound
            if not source_security_group:
                raise notfound(security_group_id=source_security_group_name)
            values['group_id'] = source_security_group['id']
        elif cidr_ip:
            # If this fails, it throws an exception. This is what we want.
            cidr_ip = urllib.unquote(cidr_ip).decode()
            netaddr.IPNetwork(cidr_ip)
            values['cidr'] = cidr_ip
        else:
            values['cidr'] = '0.0.0.0/0'

        if ip_protocol and from_port and to_port:
            from_port = int(from_port)
            to_port = int(to_port)
            ip_protocol = str(ip_protocol)

            if ip_protocol.upper() not in ['TCP', 'UDP', 'ICMP']:
                raise exception.InvalidIpProtocol(protocol=ip_protocol)
            if ((min(from_port, to_port) < -1) or
                (max(from_port, to_port) > 65535)):
                raise exception.InvalidPortRange(from_port=from_port,
                                                 to_port=to_port)

            values['protocol'] = ip_protocol
            values['from_port'] = from_port
            values['to_port'] = to_port
        else:
            # If cidr based filtering, protocol and ports are mandatory
            if 'cidr' in values:
                return None

        return values

    def _security_group_rule_exists(self, security_group, values):
        """Indicates whether the specified rule values are already
           defined in the given security group.
        """
        for rule in security_group.rules:
            if 'group_id' in values:
                if rule['group_id'] == values['group_id']:
                    return rule['id']
            else:
                is_duplicate = True
                for key in ('cidr', 'from_port', 'to_port', 'protocol'):
                    if rule[key] != values[key]:
                        is_duplicate = False
                        break
                if is_duplicate:
                    return rule['id']
        return False

    def revoke_security_group_ingress(self, context, group_name=None,
                                      group_id=None, **kwargs):
        if not group_name and not group_id:
            err = "Not enough parameters, need group_name or group_id"
            raise exception.ApiError(_(err))
        self.compute_api.ensure_default_security_group(context)
        notfound = exception.SecurityGroupNotFound
        if group_name:
            security_group = db.security_group_get_by_name(context,
                                                           context.project_id,
                                                           group_name)
            if not security_group:
                raise notfound(security_group_id=group_name)
        if group_id:
            security_group = db.security_group_get(context, group_id)
            if not security_group:
                raise notfound(security_group_id=group_id)

        msg = "Revoke security group ingress %s"
        LOG.audit(_(msg), security_group['name'], context=context)
        prevalues = []
        try:
            prevalues = kwargs['ip_permissions']
        except KeyError:
            prevalues.append(kwargs)
        rule_id = None
        for values in prevalues:
            rulesvalues = self._rule_args_to_dict(context, values)
            if not rulesvalues:
                err = "%s Not enough parameters to build a valid rule"
                raise exception.ApiError(_(err % rulesvalues))

            for values_for_rule in rulesvalues:
                values_for_rule['parent_group_id'] = security_group.id
                rule_id = self._security_group_rule_exists(security_group,
                                                           values_for_rule)
                if rule_id:
                    db.security_group_rule_destroy(context, rule_id)
        if rule_id:
            # NOTE(vish): we removed a rule, so refresh
            self.compute_api.trigger_security_group_rules_refresh(
                    context,
                    security_group_id=security_group['id'])
            return True
        raise exception.ApiError(_("No rule for the specified parameters."))

    # TODO(soren): This has only been tested with Boto as the client.
    #              Unfortunately, it seems Boto is using an old API
    #              for these operations, so support for newer API versions
    #              is sketchy.
    def authorize_security_group_ingress(self, context, group_name=None,
                                         group_id=None, **kwargs):
        if not group_name and not group_id:
            err = "Not enough parameters, need group_name or group_id"
            raise exception.ApiError(_(err))
        self.compute_api.ensure_default_security_group(context)
        notfound = exception.SecurityGroupNotFound
        if group_name:
            security_group = db.security_group_get_by_name(context,
                                                           context.project_id,
                                                           group_name)
            if not security_group:
                raise notfound(security_group_id=group_name)
        if group_id:
            security_group = db.security_group_get(context, group_id)
            if not security_group:
                raise notfound(security_group_id=group_id)

        msg = "Authorize security group ingress %s"
        LOG.audit(_(msg), security_group['name'], context=context)
        prevalues = []
        try:
            prevalues = kwargs['ip_permissions']
        except KeyError:
            prevalues.append(kwargs)
        postvalues = []
        for values in prevalues:
            rulesvalues = self._rule_args_to_dict(context, values)
            if not rulesvalues:
                err = "%s Not enough parameters to build a valid rule"
                raise exception.ApiError(_(err % rulesvalues))
            for values_for_rule in rulesvalues:
                values_for_rule['parent_group_id'] = security_group.id
                if self._security_group_rule_exists(security_group,
                                                    values_for_rule):
                    err = '%s - This rule already exists in group'
                    raise exception.ApiError(_(err) % values_for_rule)
                postvalues.append(values_for_rule)

        for values_for_rule in postvalues:
            security_group_rule = db.security_group_rule_create(
                    context,
                    values_for_rule)

        if postvalues:
            self.compute_api.trigger_security_group_rules_refresh(
                    context,
                    security_group_id=security_group['id'])
            return True

        raise exception.ApiError(_("No rule for the specified parameters."))

    def _get_source_project_id(self, context, source_security_group_owner_id):
        if source_security_group_owner_id:
        # Parse user:project for source group.
            source_parts = source_security_group_owner_id.split(':')

            # If no project name specified, assume it's same as user name.
            # Since we're looking up by project name, the user name is not
            # used here.  It's only read for EC2 API compatibility.
            if len(source_parts) == 2:
                source_project_id = source_parts[1]
            else:
                source_project_id = source_parts[0]
        else:
            source_project_id = context.project_id

        return source_project_id

    def create_security_group(self, context, group_name, group_description):
        if not re.match('^[a-zA-Z0-9_\- ]+$', str(group_name)):
            # Some validation to ensure that values match API spec.
            # - Alphanumeric characters, spaces, dashes, and underscores.
            # TODO(Daviey): LP: #813685 extend beyond group_name checking, and
            #  probably create a param validator that can be used elsewhere.
            err = _("Value (%s) for parameter GroupName is invalid."
                    " Content limited to Alphanumeric characters, "
                    "spaces, dashes, and underscores.") % group_name
            # err not that of master ec2 implementation, as they fail to raise.
            raise exception.InvalidParameterValue(err=err)

        if len(str(group_name)) > 255:
            err = _("Value (%s) for parameter GroupName is invalid."
                    " Length exceeds maximum of 255.") % group_name
            raise exception.InvalidParameterValue(err=err)

        LOG.audit(_("Create Security Group %s"), group_name, context=context)
        self.compute_api.ensure_default_security_group(context)
        if db.security_group_exists(context, context.project_id, group_name):
            raise exception.ApiError(_('group %s already exists') % group_name)

        group = {'user_id': context.user_id,
                 'project_id': context.project_id,
                 'name': group_name,
                 'description': group_description}
        group_ref = db.security_group_create(context, group)

        return {'securityGroupSet': [self._format_security_group(context,
                                                                 group_ref)]}

    def delete_security_group(self, context, group_name=None, group_id=None,
                              **kwargs):
        if not group_name and not group_id:
            err = "Not enough parameters, need group_name or group_id"
            raise exception.ApiError(_(err))
        notfound = exception.SecurityGroupNotFound
        if group_name:
            security_group = db.security_group_get_by_name(context,
                                                           context.project_id,
                                                           group_name)
            if not security_group:
                raise notfound(security_group_id=group_name)
        elif group_id:
            security_group = db.security_group_get(context, group_id)
            if not security_group:
                raise notfound(security_group_id=group_id)
        LOG.audit(_("Delete security group %s"), group_name, context=context)
        db.security_group_destroy(context, security_group.id)
        return True

    def get_console_output(self, context, instance_id, **kwargs):
        LOG.audit(_("Get console output for instance %s"), instance_id,
                  context=context)
        # instance_id may be passed in as a list of instances
        if type(instance_id) == list:
            ec2_id = instance_id[0]
        else:
            ec2_id = instance_id
        instance_id = ec2utils.ec2_id_to_id(ec2_id)
        output = self.compute_api.get_console_output(
                context, instance_id=instance_id)
        now = utils.utcnow()
        return {"InstanceId": ec2_id,
                "Timestamp": now,
                "output": base64.b64encode(output)}

    def get_ajax_console(self, context, instance_id, **kwargs):
        ec2_id = instance_id[0]
        instance_id = ec2utils.ec2_id_to_id(ec2_id)
        return self.compute_api.get_ajax_console(context,
                                                 instance_id=instance_id)

    def get_vnc_console(self, context, instance_id, **kwargs):
        """Returns vnc browser url.  Used by OS dashboard."""
        ec2_id = instance_id
        instance_id = ec2utils.ec2_id_to_id(ec2_id)
        return self.compute_api.get_vnc_console(context,
                                                instance_id=instance_id)

    def describe_volumes(self, context, volume_id=None, **kwargs):
        if volume_id:
            volumes = []
            for ec2_id in volume_id:
                internal_id = ec2utils.ec2_id_to_id(ec2_id)
                volume = self.volume_api.get(context, volume_id=internal_id)
                volumes.append(volume)
        else:
            volumes = self.volume_api.get_all(context)
        volumes = [self._format_volume(context, v) for v in volumes]
        return {'volumeSet': volumes}

    def _format_volume(self, context, volume):
        instance_ec2_id = None
        instance_data = None
        if volume.get('instance', None):
            instance_id = volume['instance']['id']
            instance_ec2_id = ec2utils.id_to_ec2_id(instance_id)
            instance_data = '%s[%s]' % (instance_ec2_id,
                                        volume['instance']['host'])
        v = {}
        v['volumeId'] = ec2utils.id_to_ec2_vol_id(volume['id'])
        v['status'] = volume['status']
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['created_at']
        if context.is_admin:
            v['status'] = '%s (%s, %s, %s, %s)' % (
                volume['status'],
                volume['project_id'],
                volume['host'],
                instance_data,
                volume['mountpoint'])
        if volume['attach_status'] == 'attached':
            v['attachmentSet'] = [{'attachTime': volume['attach_time'],
                                   'deleteOnTermination': False,
                                   'device': volume['mountpoint'],
                                   'instanceId': instance_ec2_id,
                                   'status': 'attached',
                                   'volumeId': v['volumeId']}]
        else:
            v['attachmentSet'] = [{}]
        if volume.get('snapshot_id') != None:
            v['snapshotId'] = ec2utils.id_to_ec2_snap_id(volume['snapshot_id'])
        else:
            v['snapshotId'] = None

        v['display_name'] = volume['display_name']
        v['display_description'] = volume['display_description']
        return v

    def create_volume(self, context, **kwargs):
        size = kwargs.get('size')
        if kwargs.get('snapshot_id') != None:
            snapshot_id = ec2utils.ec2_id_to_id(kwargs['snapshot_id'])
            LOG.audit(_("Create volume from snapshot %s"), snapshot_id,
                      context=context)
        else:
            snapshot_id = None
            LOG.audit(_("Create volume of %s GB"), size, context=context)

        volume = self.volume_api.create(
                context,
                size=size,
                snapshot_id=snapshot_id,
                name=kwargs.get('display_name'),
                description=kwargs.get('display_description'))
        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        return self._format_volume(context, dict(volume))

    def delete_volume(self, context, volume_id, **kwargs):
        volume_id = ec2utils.ec2_id_to_id(volume_id)
        self.volume_api.delete(context, volume_id=volume_id)
        return True

    def update_volume(self, context, volume_id, **kwargs):
        volume_id = ec2utils.ec2_id_to_id(volume_id)
        updatable_fields = ['display_name', 'display_description']
        changes = {}
        for field in updatable_fields:
            if field in kwargs:
                changes[field] = kwargs[field]
        if changes:
            self.volume_api.update(context,
                                   volume_id=volume_id,
                                   fields=changes)
        return True

    def attach_volume(self, context, volume_id, instance_id, device, **kwargs):
        volume_id = ec2utils.ec2_id_to_id(volume_id)
        instance_id = ec2utils.ec2_id_to_id(instance_id)
        msg = _("Attach volume %(volume_id)s to instance %(instance_id)s"
                " at %(device)s") % locals()
        LOG.audit(msg, context=context)
        self.compute_api.attach_volume(context,
                                       instance_id=instance_id,
                                       volume_id=volume_id,
                                       device=device)
        volume = self.volume_api.get(context, volume_id=volume_id)
        return {'attachTime': volume['attach_time'],
                'device': volume['mountpoint'],
                'instanceId': ec2utils.id_to_ec2_id(instance_id),
                'requestId': context.request_id,
                'status': volume['attach_status'],
                'volumeId': ec2utils.id_to_ec2_vol_id(volume_id)}

    def detach_volume(self, context, volume_id, **kwargs):
        volume_id = ec2utils.ec2_id_to_id(volume_id)
        LOG.audit(_("Detach volume %s"), volume_id, context=context)
        volume = self.volume_api.get(context, volume_id=volume_id)
        instance = self.compute_api.detach_volume(context, volume_id=volume_id)
        return {'attachTime': volume['attach_time'],
                'device': volume['mountpoint'],
                'instanceId': ec2utils.id_to_ec2_id(instance['id']),
                'requestId': context.request_id,
                'status': volume['attach_status'],
                'volumeId': ec2utils.id_to_ec2_vol_id(volume_id)}

    def _format_kernel_id(self, instance_ref, result, key):
        kernel_id = instance_ref['kernel_id']
        if kernel_id is None:
            return
        result[key] = self.image_ec2_id(instance_ref['kernel_id'], 'aki')

    def _format_ramdisk_id(self, instance_ref, result, key):
        ramdisk_id = instance_ref['ramdisk_id']
        if ramdisk_id is None:
            return
        result[key] = self.image_ec2_id(instance_ref['ramdisk_id'], 'ari')

    @staticmethod
    def _format_user_data(instance_ref):
        return base64.b64decode(instance_ref['user_data'])

    def describe_instance_attribute(self, context, instance_id, attribute,
                                    **kwargs):
        def _unsupported_attribute(instance, result):
            raise exception.ApiError(_('attribute not supported: %s') %
                                     attribute)

        def _format_attr_block_device_mapping(instance, result):
            tmp = {}
            self._format_instance_root_device_name(instance, tmp)
            self._format_instance_bdm(context, instance_id,
                                      tmp['rootDeviceName'], result)

        def _format_attr_disable_api_termination(instance, result):
            _unsupported_attribute(instance, result)

        def _format_attr_group_set(instance, result):
            CloudController._format_group_set(instance, result)

        def _format_attr_instance_initiated_shutdown_behavior(instance,
                                                               result):
            vm_state = instance['vm_state']
            state_to_value = {
                vm_states.STOPPED: 'stopped',
                vm_states.DELETED: 'terminated',
            }
            value = state_to_value.get(vm_state)
            if value:
                result['instanceInitiatedShutdownBehavior'] = value

        def _format_attr_instance_type(instance, result):
            self._format_instance_type(instance, result)

        def _format_attr_kernel(instance, result):
            self._format_kernel_id(instance, result, 'kernel')

        def _format_attr_ramdisk(instance, result):
            self._format_ramdisk_id(instance, result, 'ramdisk')

        def _format_attr_root_device_name(instance, result):
            self._format_instance_root_device_name(instance, result)

        def _format_attr_source_dest_check(instance, result):
            _unsupported_attribute(instance, result)

        def _format_attr_user_data(instance, result):
            result['userData'] = self._format_user_data(instance)

        attribute_formatter = {
            'blockDeviceMapping': _format_attr_block_device_mapping,
            'disableApiTermination': _format_attr_disable_api_termination,
            'groupSet': _format_attr_group_set,
            'instanceInitiatedShutdownBehavior':
            _format_attr_instance_initiated_shutdown_behavior,
            'instanceType': _format_attr_instance_type,
            'kernel': _format_attr_kernel,
            'ramdisk': _format_attr_ramdisk,
            'rootDeviceName': _format_attr_root_device_name,
            'sourceDestCheck': _format_attr_source_dest_check,
            'userData': _format_attr_user_data,
            }

        fn = attribute_formatter.get(attribute)
        if fn is None:
            raise exception.ApiError(
                _('attribute not supported: %s') % attribute)

        ec2_instance_id = instance_id
        instance_id = ec2utils.ec2_id_to_id(ec2_instance_id)
        instance = self.compute_api.get(context, instance_id)
        result = {'instance_id': ec2_instance_id}
        fn(instance, result)
        return result

    def describe_instances(self, context, **kwargs):
        # Optional DescribeInstances argument
        instance_id = kwargs.get('instance_id', None)
        return self._format_describe_instances(context,
                instance_id=instance_id)

    def describe_instances_v6(self, context, **kwargs):
        # Optional DescribeInstancesV6 argument
        instance_id = kwargs.get('instance_id', None)
        return self._format_describe_instances(context,
                instance_id=instance_id, use_v6=True)

    def _format_describe_instances(self, context, **kwargs):
        return {'reservationSet': self._format_instances(context, **kwargs)}

    def _format_run_instances(self, context, reservation_id):
        i = self._format_instances(context, reservation_id=reservation_id)
        assert len(i) == 1
        return i[0]

    def _format_instance_bdm(self, context, instance_id, root_device_name,
                             result):
        """Format InstanceBlockDeviceMappingResponseItemType"""
        root_device_type = 'instance-store'
        mapping = []
        for bdm in db.block_device_mapping_get_all_by_instance(context,
                                                               instance_id):
            volume_id = bdm['volume_id']
            if (volume_id is None or bdm['no_device']):
                continue

            if (bdm['device_name'] == root_device_name and
                (bdm['snapshot_id'] or bdm['volume_id'])):
                assert not bdm['virtual_name']
                root_device_type = 'ebs'

            vol = self.volume_api.get(context, volume_id=volume_id)
            LOG.debug(_("vol = %s\n"), vol)
            # TODO(yamahata): volume attach time
            ebs = {'volumeId': volume_id,
                   'deleteOnTermination': bdm['delete_on_termination'],
                   'attachTime': vol['attach_time'] or '-',
                   'status': vol['status'], }
            res = {'deviceName': bdm['device_name'],
                   'ebs': ebs, }
            mapping.append(res)

        if mapping:
            result['blockDeviceMapping'] = mapping
        result['rootDeviceType'] = root_device_type

    @staticmethod
    def _format_instance_root_device_name(instance, result):
        result['rootDeviceName'] = (instance.get('root_device_name') or
                                    _DEFAULT_ROOT_DEVICE_NAME)

    @staticmethod
    def _format_instance_type(instance, result):
        if instance['instance_type']:
            result['instanceType'] = instance['instance_type'].get('name')
        else:
            result['instanceType'] = None

    @staticmethod
    def _format_group_set(instance, result):
        security_group_names = []
        if instance.get('security_groups'):
            for security_group in instance['security_groups']:
                security_group_names.append(security_group['name'])
        result['groupSet'] = utils.convert_to_list_dict(
            security_group_names, 'groupId')

    def _format_instances(self, context, instance_id=None, use_v6=False,
            **search_opts):
        # TODO(termie): this method is poorly named as its name does not imply
        #               that it will be making a variety of database calls
        #               rather than simply formatting a bunch of instances that
        #               were handed to it
        reservations = {}
        # NOTE(vish): instance_id is an optional list of ids to filter by
        if instance_id:
            instances = []
            for ec2_id in instance_id:
                internal_id = ec2utils.ec2_id_to_id(ec2_id)
                try:
                    instance = self.compute_api.get(context, internal_id)
                except exception.NotFound:
                    continue
                instances.append(instance)
        else:
            try:
                # always filter out deleted instances
                search_opts['deleted'] = False
                instances = self.compute_api.get_all(context,
                                                     search_opts=search_opts)
            except exception.NotFound:
                instances = []
        for instance in instances:
            if not context.is_admin:
                if instance['image_ref'] == str(FLAGS.vpn_image_id):
                    continue
            i = {}
            instance_id = instance['id']
            ec2_id = ec2utils.id_to_ec2_id(instance_id)
            i['instanceId'] = ec2_id
            i['imageId'] = self.image_ec2_id(instance['image_ref'])
            self._format_kernel_id(instance, i, 'kernelId')
            self._format_ramdisk_id(instance, i, 'ramdiskId')
            i['instanceState'] = {
                'code': instance['power_state'],
                'name': state_description_from_vm_state(instance['vm_state'])}
            fixed_addr = None
            floating_addr = None
            if instance['fixed_ips']:
                fixed = instance['fixed_ips'][0]
                fixed_addr = fixed['address']
                if fixed['floating_ips']:
                    floating_addr = fixed['floating_ips'][0]['address']
                if fixed['network'] and use_v6:
                    i['dnsNameV6'] = ipv6.to_global(
                        fixed['network']['cidr_v6'],
                        fixed['virtual_interface']['address'],
                        instance['project_id'])

            i['privateDnsName'] = fixed_addr
            i['privateIpAddress'] = fixed_addr
            i['publicDnsName'] = floating_addr
            i['ipAddress'] = floating_addr or fixed_addr
            i['dnsName'] = i['publicDnsName'] or i['privateDnsName']
            i['keyName'] = instance['key_name']

            if context.is_admin:
                i['keyName'] = '%s (%s, %s)' % (i['keyName'],
                    instance['project_id'],
                    instance['host'])
            i['productCodesSet'] = utils.convert_to_list_dict([],
                                                              'product_codes')
            self._format_instance_type(instance, i)
            i['launchTime'] = instance['created_at']
            i['amiLaunchIndex'] = instance['launch_index']
            i['displayName'] = instance['display_name']
            i['displayDescription'] = instance['display_description']
            self._format_instance_root_device_name(instance, i)
            self._format_instance_bdm(context, instance_id,
                                      i['rootDeviceName'], i)
            host = instance['host']
            zone = self._get_availability_zone_by_host(context, host)
            i['placement'] = {'availabilityZone': zone}
            if instance['reservation_id'] not in reservations:
                r = {}
                r['reservationId'] = instance['reservation_id']
                r['ownerId'] = instance['project_id']
                self._format_group_set(instance, r)
                r['instancesSet'] = []
                reservations[instance['reservation_id']] = r
            reservations[instance['reservation_id']]['instancesSet'].append(i)

        return list(reservations.values())

    def describe_addresses(self, context, **kwargs):
        return self.format_addresses(context)

    def format_addresses(self, context):
        addresses = []
        if context.is_admin:
            iterator = db.floating_ip_get_all(context)
        else:
            iterator = db.floating_ip_get_all_by_project(context,
                                                         context.project_id)
        for floating_ip_ref in iterator:
            if floating_ip_ref['project_id'] is None:
                continue
            address = floating_ip_ref['address']
            ec2_id = None
            if (floating_ip_ref['fixed_ip']
                and floating_ip_ref['fixed_ip']['instance']):
                instance_id = floating_ip_ref['fixed_ip']['instance']['id']
                ec2_id = ec2utils.id_to_ec2_id(instance_id)
            address_rv = {'public_ip': address,
                          'instance_id': ec2_id}
            if context.is_admin:
                details = "%s (%s)" % (address_rv['instance_id'],
                                       floating_ip_ref['project_id'])
                address_rv['instance_id'] = details
            addresses.append(address_rv)
        return {'addressesSet': addresses}

    def allocate_address(self, context, **kwargs):
        LOG.audit(_("Allocate address"), context=context)
        try:
            public_ip = self.network_api.allocate_floating_ip(context)
            return {'publicIp': public_ip}
        except rpc.RemoteError as ex:
            # NOTE(tr3buchet) - why does this block exist?
            if ex.exc_type == 'NoMoreFloatingIps':
                raise exception.NoMoreFloatingIps()
            else:
                raise

    def release_address(self, context, public_ip, **kwargs):
        LOG.audit(_("Release address %s"), public_ip, context=context)
        self.network_api.release_floating_ip(context, address=public_ip)
        return {'releaseResponse': ["Address released."]}

    def associate_address(self, context, instance_id, public_ip, **kwargs):
        LOG.audit(_("Associate address %(public_ip)s to"
                " instance %(instance_id)s") % locals(), context=context)
        instance_id = ec2utils.ec2_id_to_id(instance_id)
        self.compute_api.associate_floating_ip(context,
                                               instance_id=instance_id,
                                               address=public_ip)
        return {'associateResponse': ["Address associated."]}

    def disassociate_address(self, context, public_ip, **kwargs):
        LOG.audit(_("Disassociate address %s"), public_ip, context=context)
        self.network_api.disassociate_floating_ip(context, address=public_ip)
        return {'disassociateResponse': ["Address disassociated."]}

    def run_instances(self, context, **kwargs):
        max_count = int(kwargs.get('max_count', 1))
        if kwargs.get('kernel_id'):
            kernel = self._get_image(context, kwargs['kernel_id'])
            kwargs['kernel_id'] = kernel['id']
        if kwargs.get('ramdisk_id'):
            ramdisk = self._get_image(context, kwargs['ramdisk_id'])
            kwargs['ramdisk_id'] = ramdisk['id']
        for bdm in kwargs.get('block_device_mapping', []):
            _parse_block_device_mapping(bdm)

        image = self._get_image(context, kwargs['image_id'])

        if image:
            image_state = self._get_image_state(image)
        else:
            raise exception.ImageNotFound(image_id=kwargs['image_id'])

        if image_state != 'available':
            raise exception.ApiError(_('Image must be available'))

        instances = self.compute_api.create(context,
            instance_type=instance_types.get_instance_type_by_name(
                kwargs.get('instance_type', None)),
            image_href=self._get_image(context, kwargs['image_id'])['id'],
            min_count=int(kwargs.get('min_count', max_count)),
            max_count=max_count,
            kernel_id=kwargs.get('kernel_id'),
            ramdisk_id=kwargs.get('ramdisk_id'),
            display_name=kwargs.get('display_name'),
            display_description=kwargs.get('display_description'),
            key_name=kwargs.get('key_name'),
            user_data=kwargs.get('user_data'),
            security_group=kwargs.get('security_group'),
            availability_zone=kwargs.get('placement', {}).get(
                                  'AvailabilityZone'),
            block_device_mapping=kwargs.get('block_device_mapping', {}))
        return self._format_run_instances(context,
                reservation_id=instances[0]['reservation_id'])

    def _do_instance(self, action, context, ec2_id):
        instance_id = ec2utils.ec2_id_to_id(ec2_id)
        action(context, instance_id=instance_id)

    def _do_instances(self, action, context, instance_id):
        for ec2_id in instance_id:
            self._do_instance(action, context, ec2_id)

    def terminate_instances(self, context, instance_id, **kwargs):
        """Terminate each instance in instance_id, which is a list of ec2 ids.
        instance_id is a kwarg so its name cannot be modified."""
        LOG.debug(_("Going to start terminating instances"))
        self._do_instances(self.compute_api.delete, context, instance_id)
        return True

    def reboot_instances(self, context, instance_id, **kwargs):
        """instance_id is a list of instance ids"""
        LOG.audit(_("Reboot instance %r"), instance_id, context=context)
        self._do_instances(self.compute_api.reboot, context, instance_id)
        return True

    def stop_instances(self, context, instance_id, **kwargs):
        """Stop each instances in instance_id.
        Here instance_id is a list of instance ids"""
        LOG.debug(_("Going to stop instances"))
        self._do_instances(self.compute_api.stop, context, instance_id)
        return True

    def start_instances(self, context, instance_id, **kwargs):
        """Start each instances in instance_id.
        Here instance_id is a list of instance ids"""
        LOG.debug(_("Going to start instances"))
        self._do_instances(self.compute_api.start, context, instance_id)
        return True

    def rescue_instance(self, context, instance_id, **kwargs):
        """This is an extension to the normal ec2_api"""
        self._do_instance(self.compute_api.rescue, context, instance_id)
        return True

    def unrescue_instance(self, context, instance_id, **kwargs):
        """This is an extension to the normal ec2_api"""
        self._do_instance(self.compute_api.unrescue, context, instance_id)
        return True

    def update_instance(self, context, instance_id, **kwargs):
        updatable_fields = ['display_name', 'display_description']
        changes = {}
        for field in updatable_fields:
            if field in kwargs:
                changes[field] = kwargs[field]
        if changes:
            instance_id = ec2utils.ec2_id_to_id(instance_id)
            self.compute_api.update(context, instance_id=instance_id,
                                    **changes)
        return True

    @staticmethod
    def _image_type(image_type):
        """Converts to a three letter image type.

        aki, kernel => aki
        ari, ramdisk => ari
        anything else => ami

        """
        if image_type == 'kernel':
            return 'aki'
        if image_type == 'ramdisk':
            return 'ari'
        if image_type not in ['aki', 'ari']:
            return 'ami'
        return image_type

    @staticmethod
    def image_ec2_id(image_id, image_type='ami'):
        """Returns image ec2_id using id and three letter type."""
        template = image_type + '-%08x'
        try:
            return ec2utils.id_to_ec2_id(int(image_id), template=template)
        except ValueError:
            #TODO(wwolf): once we have ec2_id -> glance_id mapping
            # in place, this wont be necessary
            return "ami-00000000"

    def _get_image(self, context, ec2_id):
        try:
            internal_id = ec2utils.ec2_id_to_id(ec2_id)
            image = self.image_service.show(context, internal_id)
        except (exception.InvalidEc2Id, exception.ImageNotFound):
            try:
                return self.image_service.show_by_name(context, ec2_id)
            except exception.NotFound:
                raise exception.ImageNotFound(image_id=ec2_id)
        image_type = ec2_id.split('-')[0]
        if self._image_type(image.get('container_format')) != image_type:
            raise exception.ImageNotFound(image_id=ec2_id)
        return image

    def _format_image(self, image):
        """Convert from format defined by BaseImageService to S3 format."""
        i = {}
        image_type = self._image_type(image.get('container_format'))
        ec2_id = self.image_ec2_id(image.get('id'), image_type)
        name = image.get('name')
        i['imageId'] = ec2_id
        kernel_id = image['properties'].get('kernel_id')
        if kernel_id:
            i['kernelId'] = self.image_ec2_id(kernel_id, 'aki')
        ramdisk_id = image['properties'].get('ramdisk_id')
        if ramdisk_id:
            i['ramdiskId'] = self.image_ec2_id(ramdisk_id, 'ari')
        i['imageOwnerId'] = image['properties'].get('owner_id')
        if name:
            i['imageLocation'] = "%s (%s)" % (image['properties'].
                                              get('image_location'), name)
        else:
            i['imageLocation'] = image['properties'].get('image_location')

        i['imageState'] = self._get_image_state(image)
        i['displayName'] = name
        i['description'] = image.get('description')
        display_mapping = {'aki': 'kernel',
                           'ari': 'ramdisk',
                           'ami': 'machine'}
        i['imageType'] = display_mapping.get(image_type)
        i['isPublic'] = image.get('is_public') == True
        i['architecture'] = image['properties'].get('architecture')

        properties = image['properties']
        root_device_name = block_device.properties_root_device_name(properties)
        root_device_type = 'instance-store'
        for bdm in properties.get('block_device_mapping', []):
            if (bdm.get('device_name') == root_device_name and
                ('snapshot_id' in bdm or 'volume_id' in bdm) and
                not bdm.get('no_device')):
                root_device_type = 'ebs'
        i['rootDeviceName'] = (root_device_name or _DEFAULT_ROOT_DEVICE_NAME)
        i['rootDeviceType'] = root_device_type

        _format_mappings(properties, i)

        return i

    def describe_images(self, context, image_id=None, **kwargs):
        # NOTE: image_id is a list!
        if image_id:
            images = []
            for ec2_id in image_id:
                try:
                    image = self._get_image(context, ec2_id)
                except exception.NotFound:
                    raise exception.ImageNotFound(image_id=ec2_id)
                images.append(image)
        else:
            images = self.image_service.detail(context)
        images = [self._format_image(i) for i in images]
        return {'imagesSet': images}

    def deregister_image(self, context, image_id, **kwargs):
        LOG.audit(_("De-registering image %s"), image_id, context=context)
        image = self._get_image(context, image_id)
        internal_id = image['id']
        self.image_service.delete(context, internal_id)
        return {'imageId': image_id}

    def _register_image(self, context, metadata):
        image = self.image_service.create(context, metadata)
        image_type = self._image_type(image.get('container_format'))
        image_id = self.image_ec2_id(image['id'], image_type)
        return image_id

    def register_image(self, context, image_location=None, **kwargs):
        if image_location is None and 'name' in kwargs:
            image_location = kwargs['name']
        metadata = {'properties': {'image_location': image_location}}

        if 'root_device_name' in kwargs:
            metadata['properties']['root_device_name'] = \
            kwargs.get('root_device_name')

        mappings = [_parse_block_device_mapping(bdm) for bdm in
                    kwargs.get('block_device_mapping', [])]
        if mappings:
            metadata['properties']['block_device_mapping'] = mappings

        image_id = self._register_image(context, metadata)
        msg = _("Registered image %(image_location)s with"
                " id %(image_id)s") % locals()
        LOG.audit(msg, context=context)
        return {'imageId': image_id}

    def describe_image_attribute(self, context, image_id, attribute, **kwargs):
        def _block_device_mapping_attribute(image, result):
            _format_mappings(image['properties'], result)

        def _launch_permission_attribute(image, result):
            result['launchPermission'] = []
            if image['is_public']:
                result['launchPermission'].append({'group': 'all'})

        def _root_device_name_attribute(image, result):
            result['rootDeviceName'] = \
                block_device.properties_root_device_name(image['properties'])
            if result['rootDeviceName'] is None:
                result['rootDeviceName'] = _DEFAULT_ROOT_DEVICE_NAME

        supported_attributes = {
            'blockDeviceMapping': _block_device_mapping_attribute,
            'launchPermission': _launch_permission_attribute,
            'rootDeviceName': _root_device_name_attribute,
            }

        fn = supported_attributes.get(attribute)
        if fn is None:
            raise exception.ApiError(_('attribute not supported: %s')
                                     % attribute)
        try:
            image = self._get_image(context, image_id)
        except exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)

        result = {'imageId': image_id}
        fn(image, result)
        return result

    def modify_image_attribute(self, context, image_id, attribute,
                               operation_type, **kwargs):
        # TODO(devcamcar): Support users and groups other than 'all'.
        if attribute != 'launchPermission':
            raise exception.ApiError(_('attribute not supported: %s')
                                     % attribute)
        if not 'user_group' in kwargs:
            raise exception.ApiError(_('user or group not specified'))
        if len(kwargs['user_group']) != 1 and kwargs['user_group'][0] != 'all':
            raise exception.ApiError(_('only group "all" is supported'))
        if not operation_type in ['add', 'remove']:
            raise exception.ApiError(_('operation_type must be add or remove'))
        LOG.audit(_("Updating image %s publicity"), image_id, context=context)

        try:
            image = self._get_image(context, image_id)
        except exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        internal_id = image['id']
        del(image['id'])

        image['is_public'] = (operation_type == 'add')
        return self.image_service.update(context, internal_id, image)

    def update_image(self, context, image_id, **kwargs):
        internal_id = ec2utils.ec2_id_to_id(image_id)
        result = self.image_service.update(context, internal_id, dict(kwargs))
        return result

    # TODO(yamahata): race condition
    # At the moment there is no way to prevent others from
    # manipulating instances/volumes/snapshots.
    # As other code doesn't take it into consideration, here we don't
    # care of it for now. Ostrich algorithm
    def create_image(self, context, instance_id, **kwargs):
        # NOTE(yamahata): name/description are ignored by register_image(),
        #                 do so here
        no_reboot = kwargs.get('no_reboot', False)

        ec2_instance_id = instance_id
        instance_id = ec2utils.ec2_id_to_id(ec2_instance_id)
        instance = self.compute_api.get(context, instance_id)

        # stop the instance if necessary
        restart_instance = False
        if not no_reboot:
            vm_state = instance['vm_state']

            # if the instance is in subtle state, refuse to proceed.
            if vm_state not in (vm_states.ACTIVE, vm_states.STOPPED):
                raise exception.InstanceNotRunning(instance_id=ec2_instance_id)

            if vm_state == vm_states.ACTIVE:
                restart_instance = True
                self.compute_api.stop(context, instance_id=instance_id)

            # wait instance for really stopped
            start_time = time.time()
            while vm_state != vm_states.STOPPED:
                time.sleep(1)
                instance = self.compute_api.get(context, instance_id)
                vm_state = instance['vm_state']
                # NOTE(yamahata): timeout and error. 1 hour for now for safety.
                #                 Is it too short/long?
                #                 Or is there any better way?
                timeout = 1 * 60 * 60 * 60
                if time.time() > start_time + timeout:
                    raise exception.ApiError(
                        _('Couldn\'t stop instance with in %d sec') % timeout)

        src_image = self._get_image(context, instance['image_ref'])
        properties = src_image['properties']
        if instance['root_device_name']:
            properties['root_device_name'] = instance['root_device_name']

        mapping = []
        bdms = db.block_device_mapping_get_all_by_instance(context,
                                                           instance_id)
        for bdm in bdms:
            if bdm.no_device:
                continue
            m = {}
            for attr in ('device_name', 'snapshot_id', 'volume_id',
                         'volume_size', 'delete_on_termination', 'no_device',
                         'virtual_name'):
                val = getattr(bdm, attr)
                if val is not None:
                    m[attr] = val

            volume_id = m.get('volume_id')
            if m.get('snapshot_id') and volume_id:
                # create snapshot based on volume_id
                vol = self.volume_api.get(context, volume_id=volume_id)
                # NOTE(yamahata): Should we wait for snapshot creation?
                #                 Linux LVM snapshot creation completes in
                #                 short time, it doesn't matter for now.
                snapshot = self.volume_api.create_snapshot_force(
                    context, volume_id=volume_id, name=vol['display_name'],
                    description=vol['display_description'])
                m['snapshot_id'] = snapshot['id']
                del m['volume_id']

            if m:
                mapping.append(m)

        for m in _properties_get_mappings(properties):
            virtual_name = m['virtual']
            if virtual_name in ('ami', 'root'):
                continue

            assert block_device.is_swap_or_ephemeral(virtual_name)
            device_name = m['device']
            if device_name in [b['device_name'] for b in mapping
                               if not b.get('no_device', False)]:
                continue

            # NOTE(yamahata): swap and ephemeral devices are specified in
            #                 AMI, but disabled for this instance by user.
            #                 So disable those device by no_device.
            mapping.append({'device_name': device_name, 'no_device': True})

        if mapping:
            properties['block_device_mapping'] = mapping

        for attr in ('status', 'location', 'id'):
            src_image.pop(attr, None)

        image_id = self._register_image(context, src_image)

        if restart_instance:
            self.compute_api.start(context, instance_id=instance_id)

        return {'imageId': image_id}
