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
import time

from oslo.config import cfg

from nova.api.ec2 import ec2utils
from nova.api.ec2 import inst_state
from nova.api.metadata import password
from nova.api import validator
from nova import availability_zones
from nova import block_device
from nova.cloudpipe import pipelib
from nova import compute
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.image import s3
from nova import network
from nova.network.security_group import quantum_driver
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import quota
from nova import servicegroup
from nova import utils
from nova import volume

ec2_opts = [
    cfg.StrOpt('ec2_host',
               default='$my_ip',
               help='the ip of the ec2 api server'),
    cfg.StrOpt('ec2_dmz_host',
               default='$my_ip',
               help='the internal ip of the ec2 api server'),
    cfg.IntOpt('ec2_port',
               default=8773,
               help='the port of the ec2 api server'),
    cfg.StrOpt('ec2_scheme',
               default='http',
               help='the protocol to use when connecting to the ec2 api '
                    'server (http, https)'),
    cfg.StrOpt('ec2_path',
               default='/services/Cloud',
               help='the path prefix used to call the ec2 api server'),
    cfg.ListOpt('region_list',
                default=[],
                help='list of region=fqdn pairs separated by commas'),
]

CONF = cfg.CONF
CONF.register_opts(ec2_opts)
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('vpn_key_suffix', 'nova.cloudpipe.pipelib')
CONF.import_opt('internal_service_availability_zone',
        'nova.availability_zones')

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS


def validate_ec2_id(val):
    if not validator.validate_str()(val):
        raise exception.InvalidInstanceIDMalformed(val=val)
    try:
        ec2utils.ec2_id_to_id(val)
    except exception.InvalidEc2Id:
        raise exception.InvalidInstanceIDMalformed(val=val)


# EC2 API can return the following values as documented in the EC2 API
# http://docs.amazonwebservices.com/AWSEC2/latest/APIReference/
#    ApiReference-ItemType-InstanceStateType.html
# pending 0 | running 16 | shutting-down 32 | terminated 48 | stopping 64 |
# stopped 80
_STATE_DESCRIPTION_MAP = {
    None: inst_state.PENDING,
    vm_states.ACTIVE: inst_state.RUNNING,
    vm_states.BUILDING: inst_state.PENDING,
    vm_states.DELETED: inst_state.TERMINATED,
    vm_states.SOFT_DELETED: inst_state.TERMINATED,
    vm_states.STOPPED: inst_state.STOPPED,
    vm_states.PAUSED: inst_state.PAUSE,
    vm_states.SUSPENDED: inst_state.SUSPEND,
    vm_states.RESCUED: inst_state.RESCUE,
    vm_states.RESIZED: inst_state.RESIZE,
}


def _state_description(vm_state, _shutdown_terminate):
    """Map the vm state to the server status string."""
    # Note(maoy): We do not provide EC2 compatibility
    # in shutdown_terminate flag behavior. So we ignore
    # it here.
    name = _STATE_DESCRIPTION_MAP.get(vm_state, vm_state)

    return {'code': inst_state.name_to_code(name),
            'name': name}


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
            if ec2_id.startswith('snap-'):
                bdm['snapshot_id'] = ec2utils.ec2_snap_id_to_uuid(ec2_id)
            elif ec2_id.startswith('vol-'):
                bdm['volume_id'] = ec2utils.ec2_vol_id_to_uuid(ec2_id)
            ebs.setdefault('delete_on_termination', True)
        bdm.update(ebs)
    return bdm


def _properties_get_mappings(properties):
    return block_device.mappings_prepend_dev(properties.get('mappings', []))


def _format_block_device_mapping(bdm):
    """Construct BlockDeviceMappingItemType
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
    """Format multiple BlockDeviceMappingItemType."""
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
    """CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self.image_service = s3.S3ImageService()
        self.network_api = network.API()
        self.volume_api = volume.API()
        self.security_group_api = get_cloud_security_group_api()
        self.compute_api = compute.API(network_api=self.network_api,
                                   volume_api=self.volume_api,
                                   security_group_api=self.security_group_api)
        self.keypair_api = compute_api.KeypairAPI()
        self.servicegroup_api = servicegroup.API()

    def __str__(self):
        return 'CloudController'

    def _enforce_valid_instance_ids(self, context, instance_ids):
        # NOTE(mikal): Amazon's implementation of the EC2 API requires that
        # _all_ instance ids passed in be valid.
        instances = {}
        if instance_ids:
            for ec2_id in instance_ids:
                instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
                instance = self.compute_api.get(context, instance_uuid)
                instances[ec2_id] = instance
        return instances

    def _get_image_state(self, image):
        # NOTE(vish): fallback status if image_state isn't set
        state = image.get('status')
        if state == 'active':
            state = 'available'
        return image['properties'].get('image_state', state)

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
        available_zones, not_available_zones = \
            availability_zones.get_availability_zones(ctxt)

        result = []
        for zone in available_zones:
            # Hide internal_service_availability_zone
            if zone == CONF.internal_service_availability_zone:
                continue
            result.append({'zoneName': zone,
                           'zoneState': "available"})
        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "not available"})
        return {'availabilityZoneInfo': result}

    def _describe_availability_zones_verbose(self, context, **kwargs):
        ctxt = context.elevated()
        available_zones, not_available_zones = \
            availability_zones.get_availability_zones(ctxt)

        # Available services
        enabled_services = db.service_get_all(context, False)
        enabled_services = availability_zones.set_availability_zones(context,
                enabled_services)
        zone_hosts = {}
        host_services = {}
        for service in enabled_services:
            zone_hosts.setdefault(service['availability_zone'], [])
            if service['host'] not in zone_hosts[service['availability_zone']]:
                zone_hosts[service['availability_zone']].append(
                    service['host'])

            host_services.setdefault(service['availability_zone'] +
                    service['host'], [])
            host_services[service['availability_zone'] + service['host']].\
                    append(service)

        result = []
        for zone in available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "available"})
            for host in zone_hosts[zone]:
                result.append({'zoneName': '|- %s' % host,
                               'zoneState': ''})

                for service in host_services[zone + host]:
                    alive = self.servicegroup_api.service_is_up(service)
                    art = (alive and ":-)") or "XXX"
                    active = 'enabled'
                    if service['disabled']:
                        active = 'disabled'
                    result.append({'zoneName': '| |- %s' % service['binary'],
                                   'zoneState': ('%s %s %s'
                                                 % (active, art,
                                                    service['updated_at']))})

        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': "not available"})

        return {'availabilityZoneInfo': result}

    def describe_regions(self, context, region_name=None, **kwargs):
        if CONF.region_list:
            regions = []
            for region in CONF.region_list:
                name, _sep, host = region.partition('=')
                endpoint = '%s://%s:%s%s' % (CONF.ec2_scheme,
                                             host,
                                             CONF.ec2_port,
                                             CONF.ec2_path)
                regions.append({'regionName': name,
                                'regionEndpoint': endpoint})
        else:
            regions = [{'regionName': 'nova',
                        'regionEndpoint': '%s://%s:%s%s' % (CONF.ec2_scheme,
                                                            CONF.ec2_host,
                                                            CONF.ec2_port,
                                                            CONF.ec2_path)}]
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
                internal_id = ec2utils.ec2_snap_id_to_uuid(ec2_id)
                snapshot = self.volume_api.get_snapshot(
                    context,
                    snapshot_id=internal_id)
                snapshots.append(snapshot)
        else:
            snapshots = self.volume_api.get_all_snapshots(context)

        formatted_snapshots = []
        for s in snapshots:
            formatted = self._format_snapshot(context, s)
            if formatted:
                formatted_snapshots.append(formatted)
        return {'snapshotSet': formatted_snapshots}

    def _format_snapshot(self, context, snapshot):
        # NOTE(mikal): this is just a set of strings in cinder. If they
        # implement an enum, then we should move this code to use it. The
        # valid ec2 statuses are "pending", "completed", and "error".
        status_map = {'new': 'pending',
                      'creating': 'pending',
                      'available': 'completed',
                      'active': 'completed',
                      'deleting': 'pending',
                      'deleted': None,
                      'error': 'error'}

        mapped_status = status_map.get(snapshot['status'], snapshot['status'])
        if not mapped_status:
            return None

        s = {}
        s['snapshotId'] = ec2utils.id_to_ec2_snap_id(snapshot['id'])
        s['volumeId'] = ec2utils.id_to_ec2_vol_id(snapshot['volume_id'])
        s['status'] = mapped_status
        s['startTime'] = snapshot['created_at']
        s['progress'] = snapshot['progress']
        s['ownerId'] = snapshot['project_id']
        s['volumeSize'] = snapshot['volume_size']
        s['description'] = snapshot['display_description']
        return s

    def create_snapshot(self, context, volume_id, **kwargs):
        validate_ec2_id(volume_id)
        LOG.audit(_("Create snapshot of volume %s"), volume_id,
                  context=context)
        volume_id = ec2utils.ec2_vol_id_to_uuid(volume_id)
        args = (context, volume_id, kwargs.get('name'),
                kwargs.get('description'))
        if kwargs.get('force', False):
            snapshot = self.volume_api.create_snapshot_force(*args)
        else:
            snapshot = self.volume_api.create_snapshot(*args)

        db.ec2_snapshot_create(context, snapshot['id'])
        return self._format_snapshot(context, snapshot)

    def delete_snapshot(self, context, snapshot_id, **kwargs):
        snapshot_id = ec2utils.ec2_snap_id_to_uuid(snapshot_id)
        self.volume_api.delete_snapshot(context, snapshot_id)
        return True

    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = self.keypair_api.get_key_pairs(context, context.user_id)
        if key_name is not None:
            key_pairs = [x for x in key_pairs if x['name'] in key_name]

        #If looking for non existent key pair
        if key_name is not None and not key_pairs:
            msg = _('Could not find key pair(s): %s') % ','.join(key_name)
            raise exception.KeypairNotFound(msg,
                                            code="InvalidKeyPair.Duplicate")

        result = []
        for key_pair in key_pairs:
            # filter out the vpn keys
            suffix = CONF.vpn_key_suffix
            if context.is_admin or not key_pair['name'].endswith(suffix):
                result.append({
                    'keyName': key_pair['name'],
                    'keyFingerprint': key_pair['fingerprint'],
                })

        return {'keySet': result}

    def create_key_pair(self, context, key_name, **kwargs):
        LOG.audit(_("Create key pair %s"), key_name, context=context)

        try:
            keypair = self.keypair_api.create_key_pair(context,
                                                       context.user_id,
                                                       key_name)
        except exception.KeypairLimitExceeded:
            msg = _("Quota exceeded, too many key pairs.")
            raise exception.EC2APIError(msg, code='ResourceLimitExceeded')
        return {'keyName': key_name,
                'keyFingerprint': keypair['fingerprint'],
                'keyMaterial': keypair['private_key']}
        # TODO(vish): when context is no longer an object, pass it here

    def import_key_pair(self, context, key_name, public_key_material,
                        **kwargs):
        LOG.audit(_("Import key %s"), key_name, context=context)

        public_key = base64.b64decode(public_key_material)

        try:
            keypair = self.keypair_api.import_key_pair(context,
                                                       context.user_id,
                                                       key_name,
                                                       public_key)
        except exception.KeypairLimitExceeded:
            msg = _("Quota exceeded, too many key pairs.")
            raise exception.EC2APIError(msg)
        except exception.InvalidKeypair:
            msg = _("Keypair data is invalid")
            raise exception.EC2APIError(msg)

        return {'keyName': key_name,
                'keyFingerprint': keypair['fingerprint']}

    def delete_key_pair(self, context, key_name, **kwargs):
        LOG.audit(_("Delete key pair %s"), key_name, context=context)
        try:
            self.keypair_api.delete_key_pair(context, context.user_id,
                                             key_name)
        except exception.NotFound:
            # aws returns true even if the key doesn't exist
            pass
        return True

    def describe_security_groups(self, context, group_name=None, group_id=None,
                                 **kwargs):
        search_opts = ec2utils.search_opts_from_filters(kwargs.get('filter'))

        raw_groups = self.security_group_api.list(context,
                                                  group_name,
                                                  group_id,
                                                  context.project_id,
                                                  search_opts=search_opts)

        groups = [self._format_security_group(context, g) for g in raw_groups]

        return {'securityGroupInfo':
                list(sorted(groups,
                            key=lambda k: (k['ownerId'], k['groupName'])))}

    def _format_security_group(self, context, group):
        g = {}
        g['groupDescription'] = group['description']
        g['groupName'] = group['name']
        g['ownerId'] = group['project_id']
        g['ipPermissions'] = []
        for rule in group['rules']:
            r = {}
            r['groups'] = []
            r['ipRanges'] = []
            if rule['group_id']:
                if rule.get('grantee_group'):
                    source_group = rule['grantee_group']
                    r['groups'] += [{'groupName': source_group['name'],
                                     'userId': source_group['project_id']}]
                else:
                    # rule is not always joined with grantee_group
                    # for example when using quantum driver.
                    source_group = self.security_group_api.get(
                        context, id=rule['group_id'])
                    r['groups'] += [{'groupName': source_group.get('name'),
                                     'userId': source_group.get('project_id')}]
                if rule['protocol']:
                    r['ipProtocol'] = rule['protocol'].lower()
                    r['fromPort'] = rule['from_port']
                    r['toPort'] = rule['to_port']
                    g['ipPermissions'] += [dict(r)]
                else:
                    for protocol, min_port, max_port in (('icmp', -1, -1),
                                                         ('tcp', 1, 65535),
                                                         ('udp', 1, 65535)):
                        r['ipProtocol'] = protocol
                        r['fromPort'] = min_port
                        r['toPort'] = max_port
                        g['ipPermissions'] += [dict(r)]
            else:
                r['ipProtocol'] = rule['protocol']
                r['fromPort'] = rule['from_port']
                r['toPort'] = rule['to_port']
                r['ipRanges'] += [{'cidrIp': rule['cidr']}]
                g['ipPermissions'] += [r]
        return g

    def _rule_args_to_dict(self, context, kwargs):
        rules = []
        if 'groups' not in kwargs and 'ip_ranges' not in kwargs:
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

        if source_security_group_name:
            source_project_id = self._get_source_project_id(context,
                source_security_group_owner_id)

            source_security_group = db.security_group_get_by_name(
                    context.elevated(),
                    source_project_id,
                    source_security_group_name)
            notfound = exception.SecurityGroupNotFound
            if not source_security_group:
                raise notfound(security_group_id=source_security_group_name)
            group_id = source_security_group['id']
            return self.security_group_api.new_group_ingress_rule(
                                    group_id, ip_protocol, from_port, to_port)
        else:
            cidr = self.security_group_api.parse_cidr(cidr_ip)
            return self.security_group_api.new_cidr_ingress_rule(
                                        cidr, ip_protocol, from_port, to_port)

    def _validate_group_identifier(self, group_name, group_id):
        if not group_name and not group_id:
            err = _("Not enough parameters, need group_name or group_id")
            raise exception.EC2APIError(err)

    def _validate_rulevalues(self, rulesvalues):
        if not rulesvalues:
            err = _("%s Not enough parameters to build a valid rule")
            raise exception.EC2APIError(err % rulesvalues)

    def _validate_security_group_protocol(self, values):
        validprotocols = ['tcp', 'udp', 'icmp', '6', '17', '1']
        if 'ip_protocol' in values and \
            values['ip_protocol'] not in validprotocols:
            err = _('Invalid IP protocol %s.') % values['ip_protocol']
            raise exception.EC2APIError(message=err, code="400")

    def revoke_security_group_ingress(self, context, group_name=None,
                                      group_id=None, **kwargs):
        self._validate_group_identifier(group_name, group_id)

        security_group = self.security_group_api.get(context, group_name,
                                                     group_id)

        prevalues = kwargs.get('ip_permissions', [kwargs])

        rule_ids = []
        for values in prevalues:
            rulesvalues = self._rule_args_to_dict(context, values)
            self._validate_rulevalues(rulesvalues)
            for values_for_rule in rulesvalues:
                values_for_rule['parent_group_id'] = security_group['id']

                rule_ids.append(self.security_group_api.rule_exists(
                                             security_group, values_for_rule))

        rule_ids = [id for id in rule_ids if id]

        if rule_ids:
            self.security_group_api.remove_rules(context, security_group,
                                                 rule_ids)

            return True

        raise exception.EC2APIError(_("No rule for the specified parameters."))

    # TODO(soren): This has only been tested with Boto as the client.
    #              Unfortunately, it seems Boto is using an old API
    #              for these operations, so support for newer API versions
    #              is sketchy.
    def authorize_security_group_ingress(self, context, group_name=None,
                                         group_id=None, **kwargs):
        self._validate_group_identifier(group_name, group_id)

        security_group = self.security_group_api.get(context, group_name,
                                                     group_id)

        prevalues = kwargs.get('ip_permissions', [kwargs])
        postvalues = []
        for values in prevalues:
            self._validate_security_group_protocol(values)
            rulesvalues = self._rule_args_to_dict(context, values)
            self._validate_rulevalues(rulesvalues)
            for values_for_rule in rulesvalues:
                values_for_rule['parent_group_id'] = security_group['id']
                if self.security_group_api.rule_exists(security_group,
                                                       values_for_rule):
                    err = _('%s - This rule already exists in group')
                    raise exception.EC2APIError(err % values_for_rule)
                postvalues.append(values_for_rule)

        if postvalues:
            self.security_group_api.add_rules(context, security_group['id'],
                                           security_group['name'], postvalues)
            return True

        raise exception.EC2APIError(_("No rule for the specified parameters."))

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
        if isinstance(group_name, unicode):
            group_name = group_name.encode('utf-8')
        if CONF.ec2_strict_validation:
            # EC2 specification gives constraints for name and description:
            # Accepts alphanumeric characters, spaces, dashes, and underscores
            allowed = '^[a-zA-Z0-9_\- ]+$'
            self.security_group_api.validate_property(group_name, 'name',
                                                      allowed)
            self.security_group_api.validate_property(group_description,
                                                      'description', allowed)
        else:
            # Amazon accepts more symbols.
            # So, allow POSIX [:print:] characters.
            allowed = r'^[\x20-\x7E]+$'
            self.security_group_api.validate_property(group_name, 'name',
                                                      allowed)

        group_ref = self.security_group_api.create_security_group(
            context, group_name, group_description)

        return {'securityGroupSet': [self._format_security_group(context,
                                                                 group_ref)]}

    def delete_security_group(self, context, group_name=None, group_id=None,
                              **kwargs):
        if not group_name and not group_id:
            err = _("Not enough parameters, need group_name or group_id")
            raise exception.EC2APIError(err)

        security_group = self.security_group_api.get(context, group_name,
                                                     group_id)

        self.security_group_api.destroy(context, security_group)

        return True

    def get_password_data(self, context, instance_id, **kwargs):
        # instance_id may be passed in as a list of instances
        if isinstance(instance_id, list):
            ec2_id = instance_id[0]
        else:
            ec2_id = instance_id
        validate_ec2_id(ec2_id)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
        instance = self.compute_api.get(context, instance_uuid)
        output = password.extract_password(instance)
        # NOTE(vish): this should be timestamp from the metadata fields
        #             but it isn't important enough to implement properly
        now = timeutils.utcnow()
        return {"InstanceId": ec2_id,
                "Timestamp": now,
                "passwordData": output}

    def get_console_output(self, context, instance_id, **kwargs):
        LOG.audit(_("Get console output for instance %s"), instance_id,
                  context=context)
        # instance_id may be passed in as a list of instances
        if isinstance(instance_id, list):
            ec2_id = instance_id[0]
        else:
            ec2_id = instance_id
        validate_ec2_id(ec2_id)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
        instance = self.compute_api.get(context, instance_uuid)
        output = self.compute_api.get_console_output(context, instance)
        now = timeutils.utcnow()
        return {"InstanceId": ec2_id,
                "Timestamp": now,
                "output": base64.b64encode(output)}

    def describe_volumes(self, context, volume_id=None, **kwargs):
        if volume_id:
            volumes = []
            for ec2_id in volume_id:
                validate_ec2_id(ec2_id)
                internal_id = ec2utils.ec2_vol_id_to_uuid(ec2_id)
                volume = self.volume_api.get(context, internal_id)
                volumes.append(volume)
        else:
            volumes = self.volume_api.get_all(context)
        volumes = [self._format_volume(context, v) for v in volumes]
        return {'volumeSet': volumes}

    def _format_volume(self, context, volume):
        valid_ec2_api_volume_status_map = {
            'attaching': 'in-use',
            'detaching': 'in-use'}

        instance_ec2_id = None
        instance_data = None

        if volume.get('instance_uuid', None):
            instance_uuid = volume['instance_uuid']
            instance = db.instance_get_by_uuid(context.elevated(),
                    instance_uuid)

            instance_ec2_id = ec2utils.id_to_ec2_inst_id(instance_uuid)
            instance_data = '%s[%s]' % (instance_ec2_id,
                                        instance['host'])
        v = {}
        v['volumeId'] = ec2utils.id_to_ec2_vol_id(volume['id'])
        v['status'] = valid_ec2_api_volume_status_map.get(volume['status'],
                                                          volume['status'])
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['created_at']
        if volume['attach_status'] == 'attached':
            v['attachmentSet'] = [{'attachTime': volume['attach_time'],
                                   'deleteOnTermination': False,
                                   'device': volume['mountpoint'],
                                   'instanceId': instance_ec2_id,
                                   'status': 'attached',
                                   'volumeId': v['volumeId']}]
        else:
            v['attachmentSet'] = [{}]
        if volume.get('snapshot_id') is not None:
            v['snapshotId'] = ec2utils.id_to_ec2_snap_id(volume['snapshot_id'])
        else:
            v['snapshotId'] = None

        return v

    def create_volume(self, context, **kwargs):
        snapshot_ec2id = kwargs.get('snapshot_id', None)
        if snapshot_ec2id is not None:
            snapshot_id = ec2utils.ec2_snap_id_to_uuid(kwargs['snapshot_id'])
            snapshot = self.volume_api.get_snapshot(context, snapshot_id)
            LOG.audit(_("Create volume from snapshot %s"), snapshot_ec2id,
                      context=context)
        else:
            snapshot = None
            LOG.audit(_("Create volume of %s GB"),
                        kwargs.get('size'),
                        context=context)

        create_kwargs = dict(snapshot=snapshot,
                             volume_type=kwargs.get('volume_type'),
                             metadata=kwargs.get('metadata'),
                             availability_zone=kwargs.get('availability_zone'))

        volume = self.volume_api.create(context,
                                        kwargs.get('size'),
                                        kwargs.get('name'),
                                        kwargs.get('description'),
                                        **create_kwargs)

        db.ec2_volume_create(context, volume['id'])
        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        return self._format_volume(context, dict(volume))

    def delete_volume(self, context, volume_id, **kwargs):
        validate_ec2_id(volume_id)
        volume_id = ec2utils.ec2_vol_id_to_uuid(volume_id)
        try:
            self.volume_api.delete(context, volume_id)
        except exception.InvalidVolume:
            raise exception.EC2APIError(_('Delete Failed'))

        return True

    def attach_volume(self, context,
                      volume_id,
                      instance_id,
                      device, **kwargs):
        validate_ec2_id(instance_id)
        validate_ec2_id(volume_id)
        volume_id = ec2utils.ec2_vol_id_to_uuid(volume_id)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, instance_id)
        instance = self.compute_api.get(context, instance_uuid)
        LOG.audit(_('Attach volume %(volume_id)s to instance %(instance_id)s '
                    'at %(device)s'),
                  {'volume_id': volume_id,
                   'instance_id': instance_id,
                   'device': device},
                  context=context)

        try:
            self.compute_api.attach_volume(context, instance,
                                           volume_id, device)
        except exception.InvalidVolume:
            raise exception.EC2APIError(_('Attach Failed.'))

        volume = self.volume_api.get(context, volume_id)
        return {'attachTime': volume['attach_time'],
                'device': volume['mountpoint'],
                'instanceId': ec2utils.id_to_ec2_inst_id(instance_uuid),
                'requestId': context.request_id,
                'status': volume['attach_status'],
                'volumeId': ec2utils.id_to_ec2_vol_id(volume_id)}

    def _get_instance_from_volume(self, context, volume):
        if volume['instance_uuid']:
            try:
                return db.instance_get_by_uuid(context,
                                               volume['instance_uuid'])
            except exception.InstanceNotFound:
                pass
        raise exception.VolumeUnattached(volume_id=volume['id'])

    def detach_volume(self, context, volume_id, **kwargs):
        validate_ec2_id(volume_id)
        volume_id = ec2utils.ec2_vol_id_to_uuid(volume_id)
        LOG.audit(_("Detach volume %s"), volume_id, context=context)
        volume = self.volume_api.get(context, volume_id)
        instance = self._get_instance_from_volume(context, volume)

        try:
            self.compute_api.detach_volume(context, instance, volume)
        except exception.InvalidVolume:
            raise exception.EC2APIError(_('Detach Volume Failed.'))

        return {'attachTime': volume['attach_time'],
                'device': volume['mountpoint'],
                'instanceId': ec2utils.id_to_ec2_inst_id(
                                    volume['instance_uuid']),
                'requestId': context.request_id,
                'status': volume['attach_status'],
                'volumeId': ec2utils.id_to_ec2_vol_id(volume_id)}

    def _format_kernel_id(self, context, instance_ref, result, key):
        kernel_uuid = instance_ref['kernel_id']
        if kernel_uuid is None or kernel_uuid == '':
            return
        result[key] = ec2utils.glance_id_to_ec2_id(context, kernel_uuid, 'aki')

    def _format_ramdisk_id(self, context, instance_ref, result, key):
        ramdisk_uuid = instance_ref['ramdisk_id']
        if ramdisk_uuid is None or ramdisk_uuid == '':
            return
        result[key] = ec2utils.glance_id_to_ec2_id(context, ramdisk_uuid,
                                                   'ari')

    def describe_instance_attribute(self, context, instance_id, attribute,
                                    **kwargs):
        def _unsupported_attribute(instance, result):
            raise exception.EC2APIError(_('attribute not supported: %s') %
                                     attribute)

        def _format_attr_block_device_mapping(instance, result):
            tmp = {}
            self._format_instance_root_device_name(instance, tmp)
            self._format_instance_bdm(context, instance['uuid'],
                                      tmp['rootDeviceName'], result)

        def _format_attr_disable_api_termination(instance, result):
            result['disableApiTermination'] = instance['disable_terminate']

        def _format_attr_group_set(instance, result):
            CloudController._format_group_set(instance, result)

        def _format_attr_instance_initiated_shutdown_behavior(instance,
                                                               result):
            if instance['shutdown_terminate']:
                result['instanceInitiatedShutdownBehavior'] = 'terminate'
            else:
                result['instanceInitiatedShutdownBehavior'] = 'stop'

        def _format_attr_instance_type(instance, result):
            self._format_instance_type(instance, result)

        def _format_attr_kernel(instance, result):
            self._format_kernel_id(context, instance, result, 'kernel')

        def _format_attr_ramdisk(instance, result):
            self._format_ramdisk_id(context, instance, result, 'ramdisk')

        def _format_attr_root_device_name(instance, result):
            self._format_instance_root_device_name(instance, result)

        def _format_attr_source_dest_check(instance, result):
            _unsupported_attribute(instance, result)

        def _format_attr_user_data(instance, result):
            result['userData'] = base64.b64decode(instance['user_data'])

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
            raise exception.EC2APIError(
                _('attribute not supported: %s') % attribute)

        validate_ec2_id(instance_id)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, instance_id)
        instance = self.compute_api.get(context, instance_uuid)
        result = {'instance_id': instance_id}
        fn(instance, result)
        return result

    def describe_instances(self, context, **kwargs):
        # Optional DescribeInstances argument
        instance_id = kwargs.get('instance_id', None)
        filters = kwargs.get('filter', None)
        instances = self._enforce_valid_instance_ids(context, instance_id)
        return self._format_describe_instances(context,
                                               instance_id=instance_id,
                                               instance_cache=instances,
                                               filter=filters)

    def describe_instances_v6(self, context, **kwargs):
        # Optional DescribeInstancesV6 argument
        instance_id = kwargs.get('instance_id', None)
        filters = kwargs.get('filter', None)
        instances = self._enforce_valid_instance_ids(context, instance_id)
        return self._format_describe_instances(context,
                                               instance_id=instance_id,
                                               instance_cache=instances,
                                               filter=filters,
                                               use_v6=True)

    def _format_describe_instances(self, context, **kwargs):
        return {'reservationSet': self._format_instances(context, **kwargs)}

    def _format_run_instances(self, context, reservation_id):
        i = self._format_instances(context, reservation_id=reservation_id)
        assert len(i) == 1
        return i[0]

    def _format_terminate_instances(self, context, instance_id,
                                    previous_states):
        instances_set = []
        for (ec2_id, previous_state) in zip(instance_id, previous_states):
            i = {}
            i['instanceId'] = ec2_id
            i['previousState'] = _state_description(previous_state['vm_state'],
                                        previous_state['shutdown_terminate'])
            try:
                instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
                instance = self.compute_api.get(context, instance_uuid)
                i['currentState'] = _state_description(instance['vm_state'],
                                            instance['shutdown_terminate'])
            except exception.NotFound:
                i['currentState'] = _state_description(vm_states.DELETED,
                                                        True)
            instances_set.append(i)
        return {'instancesSet': instances_set}

    def _format_instance_bdm(self, context, instance_uuid, root_device_name,
                             result):
        """Format InstanceBlockDeviceMappingResponseItemType."""
        root_device_type = 'instance-store'
        mapping = []
        for bdm in block_device.legacy_mapping(
            db.block_device_mapping_get_all_by_instance(context,
                                                        instance_uuid)):
            volume_id = bdm['volume_id']
            if (volume_id is None or bdm['no_device']):
                continue

            if (bdm['device_name'] == root_device_name and
                (bdm['snapshot_id'] or bdm['volume_id'])):
                assert not bdm['virtual_name']
                root_device_type = 'ebs'

            vol = self.volume_api.get(context, volume_id)
            LOG.debug(_("vol = %s\n"), vol)
            # TODO(yamahata): volume attach time
            ebs = {'volumeId': ec2utils.id_to_ec2_vol_id(volume_id),
                   'deleteOnTermination': bdm['delete_on_termination'],
                   'attachTime': vol['attach_time'] or '',
                   'status': vol['attach_status'], }
            res = {'deviceName': bdm['device_name'],
                   'ebs': ebs, }
            mapping.append(res)

        if mapping:
            result['blockDeviceMapping'] = mapping
        result['rootDeviceType'] = root_device_type

    @staticmethod
    def _format_instance_root_device_name(instance, result):
        result['rootDeviceName'] = (instance.get('root_device_name') or
                                    block_device.DEFAULT_ROOT_DEV_NAME)

    @staticmethod
    def _format_instance_type(instance, result):
        instance_type = flavors.extract_instance_type(instance)
        result['instanceType'] = instance_type['name']

    @staticmethod
    def _format_group_set(instance, result):
        security_group_names = []
        if instance.get('security_groups'):
            for security_group in instance['security_groups']:
                security_group_names.append(security_group['name'])
        result['groupSet'] = utils.convert_to_list_dict(
            security_group_names, 'groupId')

    def _format_instances(self, context, instance_id=None, use_v6=False,
            instances_cache=None, **search_opts):
        # TODO(termie): this method is poorly named as its name does not imply
        #               that it will be making a variety of database calls
        #               rather than simply formatting a bunch of instances that
        #               were handed to it
        reservations = {}

        if not instances_cache:
            instances_cache = {}

        # NOTE(vish): instance_id is an optional list of ids to filter by
        if instance_id:
            instances = []
            for ec2_id in instance_id:
                if ec2_id in instances_cache:
                    instances.append(instances_cache[ec2_id])
                else:
                    try:
                        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context,
                                                                     ec2_id)
                        instance = self.compute_api.get(context, instance_uuid)
                    except exception.NotFound:
                        continue
                    instances.append(instance)
        else:
            try:
                # always filter out deleted instances
                search_opts['deleted'] = False
                instances = self.compute_api.get_all(context,
                                                     search_opts=search_opts,
                                                     sort_dir='asc')
            except exception.NotFound:
                instances = []

        for instance in instances:
            if not context.is_admin:
                if pipelib.is_vpn_image(instance['image_ref']):
                    continue
            i = {}
            instance_uuid = instance['uuid']
            ec2_id = ec2utils.id_to_ec2_inst_id(instance_uuid)
            i['instanceId'] = ec2_id
            image_uuid = instance['image_ref']
            i['imageId'] = ec2utils.glance_id_to_ec2_id(context, image_uuid)
            self._format_kernel_id(context, instance, i, 'kernelId')
            self._format_ramdisk_id(context, instance, i, 'ramdiskId')
            i['instanceState'] = _state_description(
                instance['vm_state'], instance['shutdown_terminate'])

            fixed_ip = None
            floating_ip = None
            ip_info = ec2utils.get_ip_info_for_instance(context, instance)
            if ip_info['fixed_ips']:
                fixed_ip = ip_info['fixed_ips'][0]
            if ip_info['floating_ips']:
                floating_ip = ip_info['floating_ips'][0]
            if ip_info['fixed_ip6s']:
                i['dnsNameV6'] = ip_info['fixed_ip6s'][0]
            if CONF.ec2_private_dns_show_ip:
                i['privateDnsName'] = fixed_ip
            else:
                i['privateDnsName'] = instance['hostname']
            i['privateIpAddress'] = fixed_ip
            i['publicDnsName'] = floating_ip
            i['ipAddress'] = floating_ip or fixed_ip
            i['dnsName'] = i['publicDnsName'] or i['privateDnsName']
            i['keyName'] = instance['key_name']
            i['tagSet'] = []
            for k, v in self.compute_api.get_instance_metadata(
                    context, instance).iteritems():
                i['tagSet'].append({'key': k, 'value': v})

            if context.is_admin:
                i['keyName'] = '%s (%s, %s)' % (i['keyName'],
                    instance['project_id'],
                    instance['host'])
            i['productCodesSet'] = utils.convert_to_list_dict([],
                                                              'product_codes')
            self._format_instance_type(instance, i)
            i['launchTime'] = instance['created_at']
            i['amiLaunchIndex'] = instance['launch_index']
            self._format_instance_root_device_name(instance, i)
            self._format_instance_bdm(context, instance['uuid'],
                                      i['rootDeviceName'], i)
            host = instance['host']
            zone = ec2utils.get_availability_zone_by_host(host)
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

    def describe_addresses(self, context, public_ip=None, **kwargs):
        if public_ip:
            floatings = []
            for address in public_ip:
                floating = self.network_api.get_floating_ip_by_address(context,
                                                                       address)
                floatings.append(floating)
        else:
            floatings = self.network_api.get_floating_ips_by_project(context)
        addresses = [self._format_address(context, f) for f in floatings]
        return {'addressesSet': addresses}

    def _format_address(self, context, floating_ip):
        ec2_id = None
        if floating_ip['fixed_ip_id']:
            fixed_id = floating_ip['fixed_ip_id']
            fixed = self.network_api.get_fixed_ip(context, fixed_id)
            if fixed['instance_uuid'] is not None:
                ec2_id = ec2utils.id_to_ec2_inst_id(fixed['instance_uuid'])
        address = {'public_ip': floating_ip['address'],
                   'instance_id': ec2_id}
        if context.is_admin:
            details = "%s (%s)" % (address['instance_id'],
                                   floating_ip['project_id'])
            address['instance_id'] = details
        return address

    def allocate_address(self, context, **kwargs):
        LOG.audit(_("Allocate address"), context=context)
        try:
            public_ip = self.network_api.allocate_floating_ip(context)
        except exception.FloatingIpLimitExceeded:
            raise exception.EC2APIError(_('No more floating IPs available'))
        return {'publicIp': public_ip}

    def release_address(self, context, public_ip, **kwargs):
        LOG.audit(_('Release address %s'), public_ip, context=context)
        try:
            self.network_api.release_floating_ip(context, address=public_ip)
            return {'return': "true"}
        except exception.FloatingIpNotFound:
            raise exception.EC2APIError(_('Unable to release IP Address.'))

    def associate_address(self, context, instance_id, public_ip, **kwargs):
        LOG.audit(_("Associate address %(public_ip)s to instance "
                    "%(instance_id)s"),
                  {'public_ip': public_ip, 'instance_id': instance_id},
                  context=context)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, instance_id)
        instance = self.compute_api.get(context, instance_uuid)

        cached_ipinfo = ec2utils.get_ip_info_for_instance(context, instance)
        fixed_ips = cached_ipinfo['fixed_ips'] + cached_ipinfo['fixed_ip6s']
        if not fixed_ips:
            msg = _('Unable to associate IP Address, no fixed_ips.')
            raise exception.EC2APIError(msg)

        # TODO(tr3buchet): this will associate the floating IP with the
        # first fixed_ip an instance has. This should be
        # changed to support specifying a particular fixed_ip if
        # multiple exist but this may not apply to ec2..
        if len(fixed_ips) > 1:
            msg = _('multiple fixed_ips exist, using the first: %s')
            LOG.warning(msg, fixed_ips[0])

        try:
            self.network_api.associate_floating_ip(context, instance,
                                  floating_address=public_ip,
                                  fixed_address=fixed_ips[0])
            return {'return': 'true'}
        except exception.FloatingIpAssociated:
            msg = _('Floating ip is already associated.')
            raise exception.EC2APIError(msg)
        except exception.NoFloatingIpInterface:
            msg = _('l3driver call to add floating ip failed.')
            raise exception.EC2APIError(msg)
        except Exception:
            msg = _('Error, unable to associate floating ip.')
            LOG.exception(msg)
            raise exception.EC2APIError(msg)

    def disassociate_address(self, context, public_ip, **kwargs):
        instance_id = self.network_api.get_instance_id_by_floating_address(
                                                         context, public_ip)
        instance = self.compute_api.get(context, instance_id)
        LOG.audit(_("Disassociate address %s"), public_ip, context=context)
        try:
            self.network_api.disassociate_floating_ip(context, instance,
                                                      address=public_ip)
        except exception.FloatingIpNotAssociated:
            msg = _('Floating ip is not associated.')
            raise exception.EC2APIError(msg)
        except exception.CannotDisassociateAutoAssignedFloatingIP:
            msg = _('Cannot disassociate auto assigned floating ip')
            raise exception.EC2APIError(msg)

        return {'return': "true"}

    def run_instances(self, context, **kwargs):
        min_count = int(kwargs.get('min_count', 1))
        if kwargs.get('kernel_id'):
            kernel = self._get_image(context, kwargs['kernel_id'])
            kwargs['kernel_id'] = ec2utils.id_to_glance_id(context,
                                                           kernel['id'])
        if kwargs.get('ramdisk_id'):
            ramdisk = self._get_image(context, kwargs['ramdisk_id'])
            kwargs['ramdisk_id'] = ec2utils.id_to_glance_id(context,
                                                            ramdisk['id'])
        for bdm in kwargs.get('block_device_mapping', []):
            _parse_block_device_mapping(bdm)

        image = self._get_image(context, kwargs['image_id'])
        image_uuid = ec2utils.id_to_glance_id(context, image['id'])

        if image:
            image_state = self._get_image_state(image)
        else:
            raise exception.ImageNotFoundEC2(image_id=kwargs['image_id'])

        if image_state != 'available':
            raise exception.EC2APIError(_('Image must be available'))

        (instances, resv_id) = self.compute_api.create(context,
            instance_type=flavors.get_instance_type_by_name(
                kwargs.get('instance_type', None)),
            image_href=image_uuid,
            max_count=int(kwargs.get('max_count', min_count)),
            min_count=min_count,
            kernel_id=kwargs.get('kernel_id'),
            ramdisk_id=kwargs.get('ramdisk_id'),
            key_name=kwargs.get('key_name'),
            user_data=kwargs.get('user_data'),
            security_group=kwargs.get('security_group'),
            availability_zone=kwargs.get('placement', {}).get(
                                  'availability_zone'),
            block_device_mapping=kwargs.get('block_device_mapping', {}))
        return self._format_run_instances(context, resv_id)

    def _ec2_ids_to_instances(self, context, instance_id):
        """Get all instances first, to prevent partial executions."""
        instances = []
        for ec2_id in instance_id:
            validate_ec2_id(ec2_id)
            instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
            instance = self.compute_api.get(context, instance_uuid)
            instances.append(instance)
        return instances

    def terminate_instances(self, context, instance_id, **kwargs):
        """Terminate each instance in instance_id, which is a list of ec2 ids.
        instance_id is a kwarg so its name cannot be modified."""
        previous_states = self._ec2_ids_to_instances(context, instance_id)
        LOG.debug(_("Going to start terminating instances"))
        for instance in previous_states:
            self.compute_api.delete(context, instance)
        return self._format_terminate_instances(context,
                                                instance_id,
                                                previous_states)

    def reboot_instances(self, context, instance_id, **kwargs):
        """instance_id is a list of instance ids."""
        instances = self._ec2_ids_to_instances(context, instance_id)
        LOG.audit(_("Reboot instance %r"), instance_id, context=context)
        for instance in instances:
            self.compute_api.reboot(context, instance, 'HARD')
        return True

    def stop_instances(self, context, instance_id, **kwargs):
        """Stop each instances in instance_id.
        Here instance_id is a list of instance ids"""
        instances = self._ec2_ids_to_instances(context, instance_id)
        LOG.debug(_("Going to stop instances"))
        for instance in instances:
            self.compute_api.stop(context, instance)
        return True

    def start_instances(self, context, instance_id, **kwargs):
        """Start each instances in instance_id.
        Here instance_id is a list of instance ids"""
        instances = self._ec2_ids_to_instances(context, instance_id)
        LOG.debug(_("Going to start instances"))
        for instance in instances:
            self.compute_api.start(context, instance)
        return True

    def _get_image(self, context, ec2_id):
        try:
            internal_id = ec2utils.ec2_id_to_id(ec2_id)
            image = self.image_service.show(context, internal_id)
        except (exception.InvalidEc2Id, exception.ImageNotFound):
            filters = {'name': ec2_id}
            images = self.image_service.detail(context, filters=filters)
            try:
                return images[0]
            except IndexError:
                raise exception.ImageNotFound(image_id=ec2_id)
        image_type = ec2_id.split('-')[0]
        if ec2utils.image_type(image.get('container_format')) != image_type:
            raise exception.ImageNotFound(image_id=ec2_id)
        return image

    def _format_image(self, image):
        """Convert from format defined by GlanceImageService to S3 format."""
        i = {}
        image_type = ec2utils.image_type(image.get('container_format'))
        ec2_id = ec2utils.image_ec2_id(image.get('id'), image_type)
        name = image.get('name')
        i['imageId'] = ec2_id
        kernel_id = image['properties'].get('kernel_id')
        if kernel_id:
            i['kernelId'] = ec2utils.image_ec2_id(kernel_id, 'aki')
        ramdisk_id = image['properties'].get('ramdisk_id')
        if ramdisk_id:
            i['ramdiskId'] = ec2utils.image_ec2_id(ramdisk_id, 'ari')
        i['imageOwnerId'] = image.get('owner')

        img_loc = image['properties'].get('image_location')
        if img_loc:
            i['imageLocation'] = img_loc
        else:
            i['imageLocation'] = "%s (%s)" % (img_loc, name)

        i['name'] = name
        if not name and img_loc:
            # This should only occur for images registered with ec2 api
            # prior to that api populating the glance name
            i['name'] = img_loc

        i['imageState'] = self._get_image_state(image)
        i['description'] = image.get('description')
        display_mapping = {'aki': 'kernel',
                           'ari': 'ramdisk',
                           'ami': 'machine'}
        i['imageType'] = display_mapping.get(image_type)
        i['isPublic'] = not not image.get('is_public')
        i['architecture'] = image['properties'].get('architecture')

        properties = image['properties']
        root_device_name = block_device.properties_root_device_name(properties)
        root_device_type = 'instance-store'

        for bdm in properties.get('block_device_mapping', []):
            if (block_device.strip_dev(bdm.get('device_name')) ==
                block_device.strip_dev(root_device_name) and
                ('snapshot_id' in bdm or 'volume_id' in bdm) and
                not bdm.get('no_device')):
                root_device_type = 'ebs'
        i['rootDeviceName'] = (root_device_name or
                               block_device.DEFAULT_ROOT_DEV_NAME)
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
        return True

    def _register_image(self, context, metadata):
        image = self.image_service.create(context, metadata)
        image_type = ec2utils.image_type(image.get('container_format'))
        image_id = ec2utils.image_ec2_id(image['id'], image_type)
        return image_id

    def register_image(self, context, image_location=None, **kwargs):
        if image_location is None and kwargs.get('name'):
            image_location = kwargs['name']
        if image_location is None:
            raise exception.EC2APIError(_('imageLocation is required'))

        metadata = {'properties': {'image_location': image_location}}

        if kwargs.get('name'):
            metadata['name'] = kwargs['name']
        else:
            metadata['name'] = image_location

        if 'root_device_name' in kwargs:
            metadata['properties']['root_device_name'] = kwargs.get(
                                                         'root_device_name')

        mappings = [_parse_block_device_mapping(bdm) for bdm in
                    kwargs.get('block_device_mapping', [])]
        if mappings:
            metadata['properties']['block_device_mapping'] = mappings

        image_id = self._register_image(context, metadata)
        LOG.audit(_('Registered image %(image_location)s with id '
                    '%(image_id)s'),
                  {'image_location': image_location, 'image_id': image_id},
                  context=context)
        return {'imageId': image_id}

    def describe_image_attribute(self, context, image_id, attribute, **kwargs):
        def _block_device_mapping_attribute(image, result):
            _format_mappings(image['properties'], result)

        def _launch_permission_attribute(image, result):
            result['launchPermission'] = []
            if image['is_public']:
                result['launchPermission'].append({'group': 'all'})

        def _root_device_name_attribute(image, result):
            _prop_root_dev_name = block_device.properties_root_device_name
            result['rootDeviceName'] = _prop_root_dev_name(image['properties'])
            if result['rootDeviceName'] is None:
                result['rootDeviceName'] = block_device.DEFAULT_ROOT_DEV_NAME

        def _kernel_attribute(image, result):
            kernel_id = image['properties'].get('kernel_id')
            if kernel_id:
                result['kernel'] = {
                    'value': ec2utils.image_ec2_id(kernel_id, 'aki')
                }

        def _ramdisk_attribute(image, result):
            ramdisk_id = image['properties'].get('ramdisk_id')
            if ramdisk_id:
                result['ramdisk'] = {
                    'value': ec2utils.image_ec2_id(ramdisk_id, 'ari')
                }

        supported_attributes = {
            'blockDeviceMapping': _block_device_mapping_attribute,
            'launchPermission': _launch_permission_attribute,
            'rootDeviceName': _root_device_name_attribute,
            'kernel': _kernel_attribute,
            'ramdisk': _ramdisk_attribute,
            }

        fn = supported_attributes.get(attribute)
        if fn is None:
            raise exception.EC2APIError(_('attribute not supported: %s')
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
            raise exception.EC2APIError(_('attribute not supported: %s')
                                     % attribute)
        if 'user_group' not in kwargs:
            raise exception.EC2APIError(_('user or group not specified'))
        if len(kwargs['user_group']) != 1 and kwargs['user_group'][0] != 'all':
            raise exception.EC2APIError(_('only group "all" is supported'))
        if operation_type not in ['add', 'remove']:
            msg = _('operation_type must be add or remove')
            raise exception.EC2APIError(msg)
        LOG.audit(_("Updating image %s publicity"), image_id, context=context)

        try:
            image = self._get_image(context, image_id)
        except exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        internal_id = image['id']
        del(image['id'])

        image['is_public'] = (operation_type == 'add')
        try:
            return self.image_service.update(context, internal_id, image)
        except exception.ImageNotAuthorized:
            msg = _('Not allowed to modify attributes for image %s')
            raise exception.EC2APIError(msg % image_id)

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
        name = kwargs.get('name')
        validate_ec2_id(instance_id)
        ec2_instance_id = instance_id
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_instance_id)
        instance = self.compute_api.get(context, instance_uuid)

        bdms = self.compute_api.get_instance_bdms(context, instance)

        # CreateImage only supported for the analogue of EBS-backed instances
        if not self.compute_api.is_volume_backed_instance(context, instance,
                                                          bdms):
            msg = _("Invalid value '%(ec2_instance_id)s' for instanceId. "
                    "Instance does not have a volume attached at root "
                    "(%(root)s)") % {'root': instance['root_device_name'],
                                     'ec2_instance_id': ec2_instance_id}
            raise exception.InvalidParameterValue(err=msg)

        # stop the instance if necessary
        restart_instance = False
        if not no_reboot:
            vm_state = instance['vm_state']

            # if the instance is in subtle state, refuse to proceed.
            if vm_state not in (vm_states.ACTIVE, vm_states.STOPPED):
                raise exception.InstanceNotRunning(instance_id=ec2_instance_id)

            if vm_state == vm_states.ACTIVE:
                restart_instance = True
                self.compute_api.stop(context, instance)

            # wait instance for really stopped
            start_time = time.time()
            while vm_state != vm_states.STOPPED:
                time.sleep(1)
                instance = self.compute_api.get(context, instance_uuid)
                vm_state = instance['vm_state']
                # NOTE(yamahata): timeout and error. 1 hour for now for safety.
                #                 Is it too short/long?
                #                 Or is there any better way?
                timeout = 1 * 60 * 60
                if time.time() > start_time + timeout:
                    raise exception.EC2APIError(
                        _('Couldn\'t stop instance with in %d sec') % timeout)

        glance_uuid = instance['image_ref']
        ec2_image_id = ec2utils.glance_id_to_ec2_id(context, glance_uuid)
        src_image = self._get_image(context, ec2_image_id)
        image_meta = dict(src_image)

        def _unmap_id_property(properties, name):
            if properties[name]:
                properties[name] = ec2utils.id_to_glance_id(context,
                                                            properties[name])

        # ensure the ID properties are unmapped back to the glance UUID
        _unmap_id_property(image_meta['properties'], 'kernel_id')
        _unmap_id_property(image_meta['properties'], 'ramdisk_id')

        # meaningful image name
        name_map = dict(instance=instance['uuid'], now=timeutils.isotime())
        name = name or _('image of %(instance)s at %(now)s') % name_map

        new_image = self.compute_api.snapshot_volume_backed(context,
                                                            instance,
                                                            image_meta,
                                                            name)

        ec2_id = ec2utils.glance_id_to_ec2_id(context, new_image['id'])

        if restart_instance:
            self.compute_api.start(context, instance)

        return {'imageId': ec2_id}

    def create_tags(self, context, **kwargs):
        """Add tags to a resource

        Returns True on success, error on failure.

        :param context: context under which the method is called
        """
        resources = kwargs.get('resource_id', None)
        tags = kwargs.get('tag', None)
        if resources is None or tags is None:
            raise exception.EC2APIError(_('resource_id and tag are required'))

        if not isinstance(resources, (tuple, list, set)):
            raise exception.EC2APIError(_('Expecting a list of resources'))

        for r in resources:
            if ec2utils.resource_type_from_id(context, r) != 'instance':
                raise exception.EC2APIError(_('Only instances implemented'))

        if not isinstance(tags, (tuple, list, set)):
            raise exception.EC2APIError(_('Expecting a list of tagSets'))

        metadata = {}
        for tag in tags:
            if not isinstance(tag, dict):
                raise exception.EC2APIError(_
                        ('Expecting tagSet to be key/value pairs'))

            key = tag.get('key', None)
            val = tag.get('value', None)

            if key is None or val is None:
                raise exception.EC2APIError(_
                        ('Expecting both key and value to be set'))

            metadata[key] = val

        for ec2_id in resources:
            instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
            instance = self.compute_api.get(context, instance_uuid)
            self.compute_api.update_instance_metadata(context,
                instance, metadata)

        return True

    def delete_tags(self, context, **kwargs):
        """Delete tags

        Returns True on success, error on failure.

        :param context: context under which the method is called
        """
        resources = kwargs.get('resource_id', None)
        tags = kwargs.get('tag', None)
        if resources is None or tags is None:
            raise exception.EC2APIError(_('resource_id and tag are required'))

        if not isinstance(resources, (tuple, list, set)):
            raise exception.EC2APIError(_('Expecting a list of resources'))

        for r in resources:
            if ec2utils.resource_type_from_id(context, r) != 'instance':
                raise exception.EC2APIError(_('Only instances implemented'))

        if not isinstance(tags, (tuple, list, set)):
            raise exception.EC2APIError(_('Expecting a list of tagSets'))

        for ec2_id in resources:
            instance_uuid = ec2utils.ec2_inst_id_to_uuid(context, ec2_id)
            instance = self.compute_api.get(context, instance_uuid)
            for tag in tags:
                if not isinstance(tag, dict):
                    raise exception.EC2APIError(_
                            ('Expecting tagSet to be key/value pairs'))

                key = tag.get('key', None)
                if key is None:
                    raise exception.EC2APIError(_('Expecting key to be set'))

                self.compute_api.delete_instance_metadata(context,
                        instance, key)

        return True

    def describe_tags(self, context, **kwargs):
        """List tags

        Returns a dict with a single key 'tagSet' on success, error on failure.

        :param context: context under which the method is called
        """
        filters = kwargs.get('filter', None)

        search_filts = []
        if filters:
            for filter_block in filters:
                key_name = filter_block.get('name', None)
                val = filter_block.get('value', None)
                if val:
                    if isinstance(val, dict):
                        val = val.values()
                    if not isinstance(val, (tuple, list, set)):
                        val = (val,)
                if key_name:
                    search_block = {}
                    if key_name == 'resource_id':
                        search_block['resource_id'] = []
                        for res_id in val:
                            search_block['resource_id'].append(
                                ec2utils.ec2_inst_id_to_uuid(context, res_id))
                    elif key_name in ['key', 'value']:
                        search_block[key_name] = val
                    elif key_name == 'resource_type':
                        for res_type in val:
                            if res_type != 'instance':
                                raise exception.EC2APIError(_
                                        ('Only instances implemented'))
                            search_block[key_name] = 'instance'
                    if len(search_block.keys()) > 0:
                        search_filts.append(search_block)
        ts = []
        for tag in self.compute_api.get_all_instance_metadata(context,
                                                              search_filts):
            ts.append({
                'resource_id': ec2utils.id_to_ec2_inst_id(tag['instance_id']),
                'resource_type': 'instance',
                'key': tag['key'],
                'value': tag['value']
            })
        return {"tagSet": ts}


class EC2SecurityGroupExceptions(object):
    @staticmethod
    def raise_invalid_property(msg):
        raise exception.InvalidParameterValue(err=msg)

    @staticmethod
    def raise_group_already_exists(msg):
        raise exception.EC2APIError(message=msg)

    @staticmethod
    def raise_invalid_group(msg):
        raise exception.InvalidGroup(reason=msg)

    @staticmethod
    def raise_invalid_cidr(cidr, decoding_exception=None):
        if decoding_exception:
            raise decoding_exception
        else:
            raise exception.EC2APIError(_("Invalid CIDR"))

    @staticmethod
    def raise_over_quota(msg):
        raise exception.EC2APIError(message=msg)

    @staticmethod
    def raise_not_found(msg):
        pass


class CloudSecurityGroupNovaAPI(EC2SecurityGroupExceptions,
                                compute_api.SecurityGroupAPI):
    pass


class CloudSecurityGroupQuantumAPI(EC2SecurityGroupExceptions,
                                   quantum_driver.SecurityGroupAPI):
    pass


def get_cloud_security_group_api():
    if cfg.CONF.security_group_api.lower() == 'nova':
        return CloudSecurityGroupNovaAPI()
    elif cfg.CONF.security_group_api.lower() == 'quantum':
        return CloudSecurityGroupQuantumAPI()
    else:
        raise NotImplementedError()
