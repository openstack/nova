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
import datetime
import logging
import re
import os

from nova import context
import IPy

from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import quota
from nova import rpc
from nova import utils
from nova.compute import api as compute_api
from nova.compute import instance_types


FLAGS = flags.FLAGS
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')

InvalidInputException = exception.InvalidInputException


def _gen_key(context, user_id, key_name):
    """Generate a key

    This is a module level method because it is slow and we need to defer
    it into a process pool."""
    # NOTE(vish): generating key pair is slow so check for legal
    #             creation before creating key_pair
    try:
        db.key_pair_get(context, user_id, key_name)
        raise exception.Duplicate("The key_pair %s already exists"
                                  % key_name)
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


def ec2_id_to_internal_id(ec2_id):
    """Convert an ec2 ID (i-[base 36 number]) to an internal id (int)"""
    return int(ec2_id[2:], 36)


def internal_id_to_ec2_id(internal_id):
    """Convert an internal ID (int) to an ec2 ID (i-[base 36 number])"""
    digits = []
    while internal_id != 0:
        internal_id, remainder = divmod(internal_id, 36)
        digits.append('0123456789abcdefghijklmnopqrstuvwxyz'[remainder])
    return "i-%s" % ''.join(reversed(digits))


class CloudController(object):
    """ CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self.image_service = utils.import_object(FLAGS.image_service)
        self.compute_api = compute_api.ComputeAPI(self.network_manager,
                                                  self.image_service)
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
            start = os.getcwd()
            os.chdir(FLAGS.ca_path)
            # TODO(vish): Do this with M2Crypto instead
            utils.runthis(_("Generating root CA: %s"), "sh genrootca.sh")
            os.chdir(start)

    def _get_mpi_data(self, context, project_id):
        result = {}
        for instance in self.compute_api.get_instances(context, project_id):
            if instance['fixed_ip']:
                line = '%s slots=%d' % (instance['fixed_ip']['address'],
                                        instance['vcpus'])
                key = str(instance['key_name'])
                if key in result:
                    result[key].append(line)
                else:
                    result[key] = [line]
        return result

    def _trigger_refresh_security_group(self, context, security_group):
        nodes = set([instance['host'] for instance in security_group.instances
                       if instance['host'] is not None])
        for node in nodes:
            rpc.cast(context,
                     '%s.%s' % (FLAGS.compute_topic, node),
                     {"method": "refresh_security_group",
                      "args": {"security_group_id": security_group.id}})

    def _get_availability_zone_by_host(self, context, hostname):
        services = db.service_get_all_compute_by_host(context, hostname)
        if len(services) > 0:
            return services[0]['availability_zone']
        raise Exception(_('No service with hostname: %s' % hostname))

    def get_metadata(self, address):
        ctxt = context.get_admin_context()
        instance_ref = db.fixed_ip_get_instance(ctxt, address)
        if instance_ref is None:
            return None
        mpi = self._get_mpi_data(ctxt, instance_ref['project_id'])
        if instance_ref['key_name']:
            keys = {'0': {'_name': instance_ref['key_name'],
                          'openssh-key': instance_ref['key_data']}}
        else:
            keys = ''
        hostname = instance_ref['hostname']
        availability_zone = self._get_availability_zone_by_host(ctxt, hostname)
        floating_ip = db.instance_get_floating_address(ctxt,
                                                       instance_ref['id'])
        ec2_id = internal_id_to_ec2_id(instance_ref['internal_id'])
        data = {
            'user-data': base64.b64decode(instance_ref['user_data']),
            'meta-data': {
                'ami-id': instance_ref['image_id'],
                'ami-launch-index': instance_ref['launch_index'],
                'ami-manifest-path': 'FIXME',
                'block-device-mapping': {
                    # TODO(vish): replace with real data
                    'ami': 'sda1',
                    'ephemeral0': 'sda2',
                    'root': '/dev/sda1',
                    'swap': 'sda3'},
                'hostname': hostname,
                'instance-action': 'none',
                'instance-id': ec2_id,
                'instance-type': instance_ref['instance_type'],
                'local-hostname': hostname,
                'local-ipv4': address,
                'kernel-id': instance_ref['kernel_id'],
                'placement': {'availability-zone': availability_zone},
                'public-hostname': hostname,
                'public-ipv4': floating_ip or '',
                'public-keys': keys,
                'ramdisk-id': instance_ref['ramdisk_id'],
                'reservation-id': instance_ref['reservation_id'],
                'security-groups': '',
                'mpi': mpi}}
        if False:  # TODO(vish): store ancestor ids
            data['ancestor-ami-ids'] = []
        if False:  # TODO(vish): store product codes
            data['product-codes'] = []
        return data

    def describe_availability_zones(self, context, **kwargs):
        enabled_services = db.service_get_all_by_topic(context, 'compute')
        disabled_services = db.service_get_all_by_topic(context, 'compute', True)
        available_zones = [service.availability_zone for service in enabled_services]
        not_available_zones = [service.availability_zone for service in disabled_services
                              and not service['availability_zone'] in available_zones]

        result = []
        for zone in available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "available"})
        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "not available"})
        return {'availabilityZoneInfo': result}

    def describe_regions(self, context, region_name=None, **kwargs):
        if FLAGS.region_list:
            regions = []
            for region in FLAGS.region_list:
                name, _sep, host = region.partition('=')
                endpoint = '%s://%s:%s%s' % (FLAGS.ec2_prefix,
                                             host,
                                             FLAGS.cc_port,
                                             FLAGS.ec2_suffix)
                regions.append({'regionName': name,
                                'regionEndpoint': endpoint})
        else:
            regions = [{'regionName': 'nova',
                        'regionEndpoint': '%s://%s:%s%s' % (FLAGS.ec2_prefix,
                                                            FLAGS.cc_host,
                                                            FLAGS.cc_port,
                                                            FLAGS.ec2_suffix)}]

    def describe_snapshots(self,
                           context,
                           snapshot_id=None,
                           owner=None,
                           restorable_by=None,
                           **kwargs):
        return {'snapshotSet': [{'snapshotId': 'fixme',
                                 'volumeId': 'fixme',
                                 'status': 'fixme',
                                 'startTime': 'fixme',
                                 'progress': 'fixme',
                                 'ownerId': 'fixme',
                                 'volumeSize': 0,
                                 'description': 'fixme'}]}

    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = db.key_pair_get_all_by_user(context, context.user.id)
        if not key_name is None:
            key_pairs = [x for x in key_pairs if x['name'] in key_name]

        result = []
        for key_pair in key_pairs:
            # filter out the vpn keys
            suffix = FLAGS.vpn_key_suffix
            if context.user.is_admin() or \
               not key_pair['name'].endswith(suffix):
                result.append({
                    'keyName': key_pair['name'],
                    'keyFingerprint': key_pair['fingerprint'],
                })

        return {'keypairsSet': result}

    def create_key_pair(self, context, key_name, **kwargs):
        data = _gen_key(context, context.user.id, key_name)
        return {'keyName': key_name,
                'keyFingerprint': data['fingerprint'],
                'keyMaterial': data['private_key']}
        # TODO(vish): when context is no longer an object, pass it here

    def delete_key_pair(self, context, key_name, **kwargs):
        try:
            db.key_pair_destroy(context, context.user.id, key_name)
        except exception.NotFound:
            # aws returns true even if the key doesn't exist
            pass
        return True

    def describe_security_groups(self, context, group_name=None, **kwargs):
        self.compute_api.ensure_default_security_group(context)
        if context.user.is_admin():
            groups = db.security_group_get_all(context)
        else:
            groups = db.security_group_get_by_project(context,
                                                      context.project_id)
        groups = [self._format_security_group(context, g) for g in groups]
        if not group_name is None:
            groups = [g for g in groups if g.name in group_name]

        return {'securityGroupInfo': groups}

    def _format_security_group(self, context, group):
        g = {}
        g['groupDescription'] = group.description
        g['groupName'] = group.name
        g['ownerId'] = group.project_id
        g['ipPermissions'] = []
        for rule in group.rules:
            r = {}
            r['ipProtocol'] = rule.protocol
            r['fromPort'] = rule.from_port
            r['toPort'] = rule.to_port
            r['groups'] = []
            r['ipRanges'] = []
            if rule.group_id:
                source_group = db.security_group_get(context, rule.group_id)
                r['groups'] += [{'groupName': source_group.name,
                                 'userId': source_group.project_id}]
            else:
                r['ipRanges'] += [{'cidrIp': rule.cidr}]
            g['ipPermissions'] += [r]
        return g

    def _revoke_rule_args_to_dict(self, context, to_port=None, from_port=None,
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
            values['group_id'] = source_security_group['id']
        elif cidr_ip:
            # If this fails, it throws an exception. This is what we want.
            IPy.IP(cidr_ip)
            values['cidr'] = cidr_ip
        else:
            values['cidr'] = '0.0.0.0/0'

        if ip_protocol and from_port and to_port:
            from_port = int(from_port)
            to_port = int(to_port)
            ip_protocol = str(ip_protocol)

            if ip_protocol.upper() not in ['TCP', 'UDP', 'ICMP']:
                raise InvalidInputException(_('%s is not a valid ipProtocol') %
                                            (ip_protocol,))
            if ((min(from_port, to_port) < -1) or
                (max(from_port, to_port) > 65535)):
                raise InvalidInputException(_('Invalid port range'))

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
                    return True
            else:
                is_duplicate = True
                for key in ('cidr', 'from_port', 'to_port', 'protocol'):
                    if rule[key] != values[key]:
                        is_duplicate = False
                        break
                if is_duplicate:
                    return True
        return False

    def revoke_security_group_ingress(self, context, group_name, **kwargs):
        self.compute_api.ensure_default_security_group(context)
        security_group = db.security_group_get_by_name(context,
                                                       context.project_id,
                                                       group_name)

        criteria = self._revoke_rule_args_to_dict(context, **kwargs)
        if criteria == None:
            raise exception.ApiError(_("No rule for the specified "
                                       "parameters."))

        for rule in security_group.rules:
            match = True
            for (k, v) in criteria.iteritems():
                if getattr(rule, k, False) != v:
                    match = False
            if match:
                db.security_group_rule_destroy(context, rule['id'])
                self._trigger_refresh_security_group(context, security_group)
                return True
        raise exception.ApiError(_("No rule for the specified parameters."))

    # TODO(soren): This has only been tested with Boto as the client.
    #              Unfortunately, it seems Boto is using an old API
    #              for these operations, so support for newer API versions
    #              is sketchy.
    def authorize_security_group_ingress(self, context, group_name, **kwargs):
        self.compute_api.ensure_default_security_group(context)
        security_group = db.security_group_get_by_name(context,
                                                       context.project_id,
                                                       group_name)

        values = self._revoke_rule_args_to_dict(context, **kwargs)
        values['parent_group_id'] = security_group.id

        if self._security_group_rule_exists(security_group, values):
            raise exception.ApiError(_('This rule already exists in group %s')
                                     % group_name)

        security_group_rule = db.security_group_rule_create(context, values)

        self._trigger_refresh_security_group(context, security_group)

        return True

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
        self.compute_api.ensure_default_security_group(context)
        if db.security_group_exists(context, context.project_id, group_name):
            raise exception.ApiError(_('group %s already exists') % group_name)

        group = {'user_id': context.user.id,
                 'project_id': context.project_id,
                 'name': group_name,
                 'description': group_description}
        group_ref = db.security_group_create(context, group)

        return {'securityGroupSet': [self._format_security_group(context,
                                                                 group_ref)]}

    def delete_security_group(self, context, group_name, **kwargs):
        security_group = db.security_group_get_by_name(context,
                                                       context.project_id,
                                                       group_name)
        db.security_group_destroy(context, security_group.id)
        return True

    def get_console_output(self, context, instance_id, **kwargs):
        # instance_id is passed in as a list of instances
        ec2_id = instance_id[0]
        internal_id = ec2_id_to_internal_id(ec2_id)
        instance_ref = self.compute_api.get_instance(context, internal_id)
        output = rpc.call(context,
                          '%s.%s' % (FLAGS.compute_topic,
                                     instance_ref['host']),
                          {"method": "get_console_output",
                           "args": {"instance_id": instance_ref['id']}})

        now = datetime.datetime.utcnow()
        return {"InstanceId": ec2_id,
                "Timestamp": now,
                "output": base64.b64encode(output)}

    def describe_volumes(self, context, volume_id=None, **kwargs):
        if context.user.is_admin():
            volumes = db.volume_get_all(context)
        else:
            volumes = db.volume_get_all_by_project(context, context.project_id)

        # NOTE(vish): volume_id is an optional list of volume ids to filter by.
        volumes = [self._format_volume(context, v) for v in volumes
                   if volume_id is None or v['ec2_id'] in volume_id]

        return {'volumeSet': volumes}

    def _format_volume(self, context, volume):
        instance_ec2_id = None
        instance_data = None
        if volume.get('instance', None):
            internal_id = volume['instance']['internal_id']
            instance_ec2_id = internal_id_to_ec2_id(internal_id)
            instance_data = '%s[%s]' % (instance_ec2_id,
                                        volume['instance']['host'])
        v = {}
        v['volumeId'] = volume['ec2_id']
        v['status'] = volume['status']
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['created_at']
        if context.is_admin:
            v['status'] = '%s (%s, %s, %s, %s)' % (
                volume['status'],
                volume['user_id'],
                volume['host'],
                instance_data,
                volume['mountpoint'])
        if volume['attach_status'] == 'attached':
            v['attachmentSet'] = [{'attachTime': volume['attach_time'],
                                   'deleteOnTermination': False,
                                   'device': volume['mountpoint'],
                                   'instanceId': instance_ec2_id,
                                   'status': 'attached',
                                   'volume_id': volume['ec2_id']}]
        else:
            v['attachmentSet'] = [{}]

        v['display_name'] = volume['display_name']
        v['display_description'] = volume['display_description']
        return v

    def create_volume(self, context, size, **kwargs):
        # check quota
        if quota.allowed_volumes(context, 1, size) < 1:
            logging.warn("Quota exceeeded for %s, tried to create %sG volume",
                         context.project_id, size)
            raise quota.QuotaError("Volume quota exceeded. You cannot "
                                   "create a volume of size %s" % size)
        vol = {}
        vol['size'] = size
        vol['user_id'] = context.user.id
        vol['project_id'] = context.project_id
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        vol['display_name'] = kwargs.get('display_name')
        vol['display_description'] = kwargs.get('display_description')
        volume_ref = db.volume_create(context, vol)

        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "create_volume",
                  "args": {"topic": FLAGS.volume_topic,
                           "volume_id": volume_ref['id']}})

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        return {'volumeSet': [self._format_volume(context, dict(volume_ref))]}

    def attach_volume(self, context, volume_id, instance_id, device, **kwargs):
        volume_ref = db.volume_get_by_ec2_id(context, volume_id)
        if not re.match("^/dev/[a-z]d[a-z]+$", device):
            raise exception.ApiError(_("Invalid device specified: %s. "
                                     "Example device: /dev/vdb") % device)
        # TODO(vish): abstract status checking?
        if volume_ref['status'] != "available":
            raise exception.ApiError(_("Volume status must be available"))
        if volume_ref['attach_status'] == "attached":
            raise exception.ApiError(_("Volume is already attached"))
        internal_id = ec2_id_to_internal_id(instance_id)
        instance_ref = self.compute_api.get_instance(context, internal_id)
        host = instance_ref['host']
        rpc.cast(context,
                 db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "attach_volume",
                  "args": {"volume_id": volume_ref['id'],
                           "instance_id": instance_ref['id'],
                           "mountpoint": device}})
        return {'attachTime': volume_ref['attach_time'],
                'device': volume_ref['mountpoint'],
                'instanceId': instance_ref['id'],
                'requestId': context.request_id,
                'status': volume_ref['attach_status'],
                'volumeId': volume_ref['id']}

    def detach_volume(self, context, volume_id, **kwargs):
        volume_ref = db.volume_get_by_ec2_id(context, volume_id)
        instance_ref = db.volume_get_instance(context.elevated(),
                                              volume_ref['id'])
        if not instance_ref:
            raise exception.ApiError(_("Volume isn't attached to anything!"))
        # TODO(vish): abstract status checking?
        if volume_ref['status'] == "available":
            raise exception.ApiError(_("Volume is already detached"))
        try:
            host = instance_ref['host']
            rpc.cast(context,
                     db.queue_get_for(context, FLAGS.compute_topic, host),
                     {"method": "detach_volume",
                      "args": {"instance_id": instance_ref['id'],
                               "volume_id": volume_ref['id']}})
        except exception.NotFound:
            # If the instance doesn't exist anymore,
            # then we need to call detach blind
            db.volume_detached(context)
        internal_id = instance_ref['internal_id']
        ec2_id = internal_id_to_ec2_id(internal_id)
        return {'attachTime': volume_ref['attach_time'],
                'device': volume_ref['mountpoint'],
                'instanceId': internal_id,
                'requestId': context.request_id,
                'status': volume_ref['attach_status'],
                'volumeId': volume_ref['id']}

    def _convert_to_set(self, lst, label):
        if lst == None or lst == []:
            return None
        if not isinstance(lst, list):
            lst = [lst]
        return [{label: x} for x in lst]

    def update_volume(self, context, volume_id, **kwargs):
        updatable_fields = ['display_name', 'display_description']
        changes = {}
        for field in updatable_fields:
            if field in kwargs:
                changes[field] = kwargs[field]
        if changes:
            db.volume_update(context, volume_id, kwargs)
        return True

    def describe_instances(self, context, **kwargs):
        return self._format_describe_instances(context)

    def _format_describe_instances(self, context):
        return {'reservationSet': self._format_instances(context)}

    def _format_run_instances(self, context, reservation_id):
        i = self._format_instances(context, reservation_id)
        assert len(i) == 1
        return i[0]

    def _format_instances(self, context, reservation_id=None):
        reservations = {}
        if reservation_id:
            instances = db.instance_get_all_by_reservation(context,
                                                           reservation_id)
        else:
            instances = self.compute_api.get_instances(context)
        for instance in instances:
            if not context.user.is_admin():
                if instance['image_id'] == FLAGS.vpn_image_id:
                    continue
            i = {}
            internal_id = instance['internal_id']
            ec2_id = internal_id_to_ec2_id(internal_id)
            i['instanceId'] = ec2_id
            i['imageId'] = instance['image_id']
            i['instanceState'] = {
                'code': instance['state'],
                'name': instance['state_description']}
            fixed_addr = None
            floating_addr = None
            if instance['fixed_ip']:
                fixed_addr = instance['fixed_ip']['address']
                if instance['fixed_ip']['floating_ips']:
                    fixed = instance['fixed_ip']
                    floating_addr = fixed['floating_ips'][0]['address']
            i['privateDnsName'] = fixed_addr
            i['publicDnsName'] = floating_addr
            i['dnsName'] = i['publicDnsName'] or i['privateDnsName']
            i['keyName'] = instance['key_name']
            if context.user.is_admin():
                i['keyName'] = '%s (%s, %s)' % (i['keyName'],
                    instance['project_id'],
                    instance['host'])
            i['productCodesSet'] = self._convert_to_set([], 'product_codes')
            i['instanceType'] = instance['instance_type']
            i['launchTime'] = instance['created_at']
            i['amiLaunchIndex'] = instance['launch_index']
            i['displayName'] = instance['display_name']
            i['displayDescription'] = instance['display_description']
            if instance['reservation_id'] not in reservations:
                r = {}
                r['reservationId'] = instance['reservation_id']
                r['ownerId'] = instance['project_id']
                r['groupSet'] = self._convert_to_set([], 'groups')
                r['instancesSet'] = []
                reservations[instance['reservation_id']] = r
            availability_zone = self._get_availability_zone_by_host(context, instance['hostname'])
            i['placement'] = {'availabilityZone': availability_zone}
            reservations[instance['reservation_id']]['instancesSet'].append(i)

        return list(reservations.values())

    def describe_addresses(self, context, **kwargs):
        return self.format_addresses(context)

    def format_addresses(self, context):
        addresses = []
        if context.user.is_admin():
            iterator = db.floating_ip_get_all(context)
        else:
            iterator = db.floating_ip_get_all_by_project(context,
                                                         context.project_id)
        for floating_ip_ref in iterator:
            address = floating_ip_ref['address']
            ec2_id = None
            if (floating_ip_ref['fixed_ip']
                and floating_ip_ref['fixed_ip']['instance']):
                internal_id = floating_ip_ref['fixed_ip']['instance']['ec2_id']
                ec2_id = internal_id_to_ec2_id(internal_id)
            address_rv = {'public_ip': address,
                          'instance_id': ec2_id}
            if context.user.is_admin():
                details = "%s (%s)" % (address_rv['instance_id'],
                                       floating_ip_ref['project_id'])
                address_rv['instance_id'] = details
            addresses.append(address_rv)
        return {'addressesSet': addresses}

    def allocate_address(self, context, **kwargs):
        # check quota
        if quota.allowed_floating_ips(context, 1) < 1:
            logging.warn(_("Quota exceeeded for %s, tried to allocate "
                           "address"),
                         context.project_id)
            raise quota.QuotaError(_("Address quota exceeded. You cannot "
                                   "allocate any more addresses"))
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        public_ip = rpc.call(context,
                             FLAGS.network_topic,
                             {"method": "allocate_floating_ip",
                              "args": {"project_id": context.project_id}})
        return {'addressSet': [{'publicIp': public_ip}]}

    def release_address(self, context, public_ip, **kwargs):
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        # NOTE(vish): We don't know which network host should get the ip
        #             when we deallocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        rpc.cast(context,
                 FLAGS.network_topic,
                 {"method": "deallocate_floating_ip",
                  "args": {"floating_address": floating_ip_ref['address']}})
        return {'releaseResponse': ["Address released."]}

    def associate_address(self, context, instance_id, public_ip, **kwargs):
        internal_id = ec2_id_to_internal_id(instance_id)
        instance_ref = self.compute_api.get_instance(context, internal_id)
        fixed_address = db.instance_get_fixed_address(context,
                                                      instance_ref['id'])
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        # NOTE(vish): Perhaps we should just pass this on to compute and
        #             let compute communicate with network.
        network_topic = self.compute_api.get_network_topic(context,
                                                           internal_id)
        rpc.cast(context,
                 network_topic,
                 {"method": "associate_floating_ip",
                  "args": {"floating_address": floating_ip_ref['address'],
                           "fixed_address": fixed_address}})
        return {'associateResponse': ["Address associated."]}

    def disassociate_address(self, context, public_ip, **kwargs):
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        # NOTE(vish): Get the topic from the host name of the network of
        #             the associated fixed ip.
        if not floating_ip_ref.get('fixed_ip'):
            raise exception.ApiError('Address is not associated.')
        host = floating_ip_ref['fixed_ip']['network']['host']
        topic = db.queue_get_for(context, FLAGS.network_topic, host)
        rpc.cast(context,
                 topic,
                 {"method": "disassociate_floating_ip",
                  "args": {"floating_address": floating_ip_ref['address']}})
        return {'disassociateResponse': ["Address disassociated."]}

    def run_instances(self, context, **kwargs):
        max_count = int(kwargs.get('max_count', 1))
        placement = kwargs.get('placement')
        avzone = None
        if placement is not None:
            avzone = placement['availability_zone']
        instances = self.compute_api.create_instances(context,
            instance_types.get_by_type(kwargs.get('instance_type', None)),
            kwargs['image_id'],
            min_count=int(kwargs.get('min_count', max_count)),
            max_count=max_count,
            kernel_id=kwargs.get('kernel_id', None),
            ramdisk_id=kwargs.get('ramdisk_id'),
            display_name=kwargs.get('display_name'),
            description=kwargs.get('display_description'),
            key_name=kwargs.get('key_name'),
            user_data=kwargs.get('user_data'),
            security_group=kwargs.get('security_group'),
            generate_hostname=internal_id_to_ec2_id,
            availability_zone=avzone)
        return self._format_run_instances(context,
                                          instances[0]['reservation_id'])

    def terminate_instances(self, context, instance_id, **kwargs):
        """Terminate each instance in instance_id, which is a list of ec2 ids.
        instance_id is a kwarg so its name cannot be modified."""
        logging.debug("Going to start terminating instances")
        for ec2_id in instance_id:
            internal_id = ec2_id_to_internal_id(ec2_id)
            self.compute_api.delete_instance(context, internal_id)
        return True

    def reboot_instances(self, context, instance_id, **kwargs):
        """instance_id is a list of instance ids"""
        for ec2_id in instance_id:
            internal_id = ec2_id_to_internal_id(ec2_id)
            self.compute_api.reboot(context, internal_id)
        return True

    def rescue_instance(self, context, instance_id, **kwargs):
        """This is an extension to the normal ec2_api"""
        internal_id = ec2_id_to_internal_id(instance_id)
        self.compute_api.rescue(context, internal_id)
        return True

    def unrescue_instance(self, context, instance_id, **kwargs):
        """This is an extension to the normal ec2_api"""
        internal_id = ec2_id_to_internal_id(instance_id)
        self.compute_api.unrescue(context, internal_id)
        return True

    def update_instance(self, context, ec2_id, **kwargs):
        updatable_fields = ['display_name', 'display_description']
        changes = {}
        for field in updatable_fields:
            if field in kwargs:
                changes[field] = kwargs[field]
        if changes:
            internal_id = ec2_id_to_internal_id(ec2_id)
            inst = self.compute_api.get_instance(context, internal_id)
            db.instance_update(context, inst['id'], kwargs)
        return True

    def delete_volume(self, context, volume_id, **kwargs):
        # TODO: return error if not authorized
        volume_ref = db.volume_get_by_ec2_id(context, volume_id)
        if volume_ref['status'] != "available":
            raise exception.ApiError(_("Volume status must be available"))
        now = datetime.datetime.utcnow()
        db.volume_update(context, volume_ref['id'], {'status': 'deleting',
                                                     'terminated_at': now})
        host = volume_ref['host']
        rpc.cast(context,
                 db.queue_get_for(context, FLAGS.volume_topic, host),
                            {"method": "delete_volume",
                             "args": {"volume_id": volume_ref['id']}})
        return True

    def describe_images(self, context, image_id=None, **kwargs):
        # Note: image_id is a list!
        images = self.image_service.index(context)
        if image_id:
            images = filter(lambda x: x['imageId'] in image_id, images)
        return {'imagesSet': images}

    def deregister_image(self, context, image_id, **kwargs):
        self.image_service.deregister(context, image_id)
        return {'imageId': image_id}

    def register_image(self, context, image_location=None, **kwargs):
        if image_location is None and 'name' in kwargs:
            image_location = kwargs['name']
        image_id = self.image_service.register(context, image_location)
        logging.debug("Registered %s as %s" % (image_location, image_id))
        return {'imageId': image_id}

    def describe_image_attribute(self, context, image_id, attribute, **kwargs):
        if attribute != 'launchPermission':
            raise exception.ApiError(_('attribute not supported: %s')
                                     % attribute)
        try:
            image = self.image_service.show(context, image_id)
        except IndexError:
            raise exception.ApiError(_('invalid id: %s') % image_id)
        result = {'image_id': image_id, 'launchPermission': []}
        if image['isPublic']:
            result['launchPermission'].append({'group': 'all'})
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
        return self.image_service.modify(context, image_id, operation_type)

    def update_image(self, context, image_id, **kwargs):
        result = self.image_service.update(context, image_id, dict(kwargs))
        return result
