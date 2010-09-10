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
import logging
import os
import time

from twisted.internet import defer

from nova import db
from nova import exception
from nova import flags
from nova import rpc
from nova import utils
from nova.auth import rbac
from nova.auth import manager
from nova.compute.instance_types import INSTANCE_TYPES
from nova.endpoint import images


FLAGS = flags.FLAGS
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')


def _gen_key(user_id, key_name):
    """ Tuck this into AuthManager """
    try:
        mgr = manager.AuthManager()
        private_key, fingerprint = mgr.generate_key_pair(user_id, key_name)
    except Exception as ex:
        return {'exception': ex}
    return {'private_key': private_key, 'fingerprint': fingerprint}


class CloudController(object):
    """ CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self.network_manager = utils.import_object(FLAGS.network_manager)
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
            utils.runthis("Generating root CA: %s", "sh genrootca.sh")
            os.chdir(start)

    def _get_mpi_data(self, project_id):
        result = {}
        for instance in db.instance_get_by_project(None, project_id):
            line = '%s slots=%d' % (instance.fixed_ip['str_id'],
                INSTANCE_TYPES[instance['instance_type']]['vcpus'])
            if instance['key_name'] in result:
                result[instance['key_name']].append(line)
            else:
                result[instance['key_name']] = [line]
        return result

    def get_metadata(self, address):
        instance_ref = db.fixed_ip_get_instance(None, address)
        if instance_ref is None:
            return None
        mpi = self._get_mpi_data(instance_ref['project_id'])
        if instance_ref['key_name']:
            keys = {
                '0': {
                    '_name': instance_ref['key_name'],
                    'openssh-key': instance_ref['key_data']
                }
            }
        else:
            keys = ''
        hostname = instance_ref['hostname']
        floating_ip = db.instance_get_floating_address(None,
                                                       instance_ref['id'])
        data = {
            'user-data': base64.b64decode(instance_ref['user_data']),
            'meta-data': {
                'ami-id': instance_ref['image_id'],
                'ami-launch-index': instance_ref['launch_index'],
                'ami-manifest-path': 'FIXME',
                'block-device-mapping': {  # TODO(vish): replace with real data
                    'ami': 'sda1',
                    'ephemeral0': 'sda2',
                    'root': '/dev/sda1',
                    'swap': 'sda3'
                },
                'hostname': hostname,
                'instance-action': 'none',
                'instance-id': instance_ref['str_id'],
                'instance-type': instance_ref['instance_type'],
                'local-hostname': hostname,
                'local-ipv4': address,
                'kernel-id': instance_ref['kernel_id'],
                'placement': {
                    'availability-zone': 'nova' # TODO(vish): real zone
                },
                'public-hostname': hostname,
                'public-ipv4': floating_ip or '',
                'public-keys': keys,
                'ramdisk-id': instance_ref['ramdisk_id'],
                'reservation-id': instance_ref['reservation_id'],
                'security-groups': '',
                'mpi': mpi
            }
        }
        if False:  # TODO(vish): store ancestor ids
            data['ancestor-ami-ids'] = []
        if False:  # TODO(vish): store product codes
            data['product-codes'] = []
        return data

    @rbac.allow('all')
    def describe_availability_zones(self, context, **kwargs):
        return {'availabilityZoneInfo': [{'zoneName': 'nova',
                                          'zoneState': 'available'}]}

    @rbac.allow('all')
    def describe_regions(self, context, region_name=None, **kwargs):
        # TODO(vish): region_name is an array.  Support filtering
        return {'regionInfo': [{'regionName': 'nova',
                                'regionUrl': FLAGS.ec2_url}]}

    @rbac.allow('all')
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

    @rbac.allow('all')
    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = context.user.get_key_pairs()
        if not key_name is None:
            key_pairs = [x for x in key_pairs if x.name in key_name]

        result = []
        for key_pair in key_pairs:
            # filter out the vpn keys
            suffix = FLAGS.vpn_key_suffix
            if context.user.is_admin() or not key_pair.name.endswith(suffix):
                result.append({
                    'keyName': key_pair.name,
                    'keyFingerprint': key_pair.fingerprint,
                })

        return {'keypairsSet': result}

    @rbac.allow('all')
    def create_key_pair(self, context, key_name, **kwargs):
        dcall = defer.Deferred()
        pool = context.handler.application.settings.get('pool')
        def _complete(kwargs):
            if 'exception' in kwargs:
                dcall.errback(kwargs['exception'])
                return
            dcall.callback({'keyName': key_name,
                'keyFingerprint': kwargs['fingerprint'],
                'keyMaterial': kwargs['private_key']})
        pool.apply_async(_gen_key, [context.user.id, key_name],
            callback=_complete)
        return dcall

    @rbac.allow('all')
    def delete_key_pair(self, context, key_name, **kwargs):
        context.user.delete_key_pair(key_name)
        # aws returns true even if the key doens't exist
        return True

    @rbac.allow('all')
    def describe_security_groups(self, context, group_names, **kwargs):
        groups = {'securityGroupSet': []}

        # Stubbed for now to unblock other things.
        return groups

    @rbac.allow('netadmin')
    def create_security_group(self, context, group_name, **kwargs):
        return True

    @rbac.allow('netadmin')
    def delete_security_group(self, context, group_name, **kwargs):
        return True

    @rbac.allow('projectmanager', 'sysadmin')
    def get_console_output(self, context, instance_id, **kwargs):
        # instance_id is passed in as a list of instances
        instance_ref = db.instance_get_by_str(context, instance_id[0])
        return rpc.call('%s.%s' % (FLAGS.compute_topic,
                                   instance_ref['host']),
                        {"method": "get_console_output",
                         "args": {"context": None,
                                  "instance_id": instance_ref['id']}})

    @rbac.allow('projectmanager', 'sysadmin')
    def describe_volumes(self, context, **kwargs):
        if context.user.is_admin():
            volumes = db.volume_get_all(context)
        else:
            volumes = db.volume_get_by_project(context, context.project.id)

        volumes = [self._format_volume(context, v) for v in volumes]

        return {'volumeSet': volumes}

    def _format_volume(self, context, volume):
        v = {}
        v['volumeId'] = volume['str_id']
        v['status'] = volume['status']
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['created_at']
        if context.user.is_admin():
            v['status'] = '%s (%s, %s, %s, %s)' % (
                volume['status'],
                volume['user_id'],
                volume['host'],
                volume['instance_id'],
                volume['mountpoint'])
        if volume['attach_status'] == 'attached':
            v['attachmentSet'] = [{'attachTime': volume['attach_time'],
                                   'deleteOnTermination': False,
                                   'device': volume['mountpoint'],
                                   'instanceId': volume['instance_id'],
                                   'status': 'attached',
                                   'volume_id': volume['str_id']}]
        else:
            v['attachmentSet'] = [{}]
        return v

    @rbac.allow('projectmanager', 'sysadmin')
    def create_volume(self, context, size, **kwargs):
        vol = {}
        vol['size'] = size
        vol['user_id'] = context.user.id
        vol['project_id'] = context.project.id
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        volume_ref = db.volume_create(context, vol)

        rpc.cast(FLAGS.volume_topic, {"method": "create_volume",
                                      "args": {"context": None,
                                               "volume_id": volume_ref['id']}})

        return {'volumeSet': [self._format_volume(context, volume_ref)]}


    @rbac.allow('projectmanager', 'sysadmin')
    def attach_volume(self, context, volume_id, instance_id, device, **kwargs):
        volume_ref = db.volume_get_by_str(context, volume_id)
        # TODO(vish): abstract status checking?
        if volume_ref['attach_status'] == "attached":
            raise exception.ApiError("Volume is already attached")
        instance_ref = db.instance_get_by_str(context, instance_id)
        host = instance_ref['host']
        rpc.cast(db.queue_get_for(context, FLAGS.compute_topic, host),
                                {"method": "attach_volume",
                                 "args": {"context": None,
                                          "volume_id": volume_ref['id'],
                                          "instance_id": instance_ref['id'],
                                          "mountpoint": device}})
        return defer.succeed({'attachTime': volume_ref['attach_time'],
                              'device': volume_ref['mountpoint'],
                              'instanceId': instance_ref['id'],
                              'requestId': context.request_id,
                              'status': volume_ref['attach_status'],
                              'volumeId': volume_ref['id']})

    @rbac.allow('projectmanager', 'sysadmin')
    def detach_volume(self, context, volume_id, **kwargs):
        volume_ref = db.volume_get_by_str(context, volume_id)
        instance_ref = db.volume_get_instance(context, volume_ref['id'])
        if not instance_ref:
            raise exception.Error("Volume isn't attached to anything!")
        # TODO(vish): abstract status checking?
        if volume_ref['status'] == "available":
            raise exception.Error("Volume is already detached")
        try:
            host = instance_ref['host']
            rpc.cast(db.queue_get_for(context, FLAGS.compute_topic, host),
                                {"method": "detach_volume",
                                 "args": {"context": None,
                                          "instance_id": instance_ref['id'],
                                          "volume_id": volume_ref['id']}})
        except exception.NotFound:
            # If the instance doesn't exist anymore,
            # then we need to call detach blind
            db.volume_detached(context)
        return defer.succeed({'attachTime': volume_ref['attach_time'],
                              'device': volume_ref['mountpoint'],
                              'instanceId': instance_ref['str_id'],
                              'requestId': context.request_id,
                              'status': volume_ref['attach_status'],
                              'volumeId': volume_ref['id']})

    def _convert_to_set(self, lst, label):
        if lst == None or lst == []:
            return None
        if not isinstance(lst, list):
            lst = [lst]
        return [{label: x} for x in lst]

    @rbac.allow('all')
    def describe_instances(self, context, **kwargs):
        return defer.succeed(self._format_describe_instances(context))

    def _format_describe_instances(self, context):
        return { 'reservationSet': self._format_instances(context) }

    def _format_run_instances(self, context, reservation_id):
        i = self._format_instances(context, reservation_id)
        assert len(i) == 1
        return i[0]

    def _format_instances(self, context, reservation_id=None):
        reservations = {}
        if reservation_id:
            instances = db.instance_get_by_reservation(context,
                                                       reservation_id)
        else:
            if not context.user.is_admin():
                instances = db.instance_get_all(context)
            else:
                instances = db.instance_get_by_project(context,
                                                       context.project.id)
        for instance in instances:
            if not context.user.is_admin():
                if instance['image_id'] == FLAGS.vpn_image_id:
                    continue
            i = {}
            i['instanceId'] = instance['str_id']
            i['imageId'] = instance['image_id']
            i['instanceState'] = {
                'code': instance['state'],
                'name': instance['state_description']
            }
            fixed_addr = None
            floating_addr = None
            if instance['fixed_ip']:
                fixed_addr = instance['fixed_ip']['str_id']
                if instance['fixed_ip']['floating_ips']:
                    fixed = instance['fixed_ip']
                    floating_addr = fixed['floating_ips'][0]['str_id']
            i['privateDnsName'] = fixed_addr
            i['publicDnsName'] = floating_addr
            if not i['publicDnsName']:
                i['publicDnsName'] = i['privateDnsName']
            i['dnsName'] = None
            i['keyName'] = instance['key_name']
            if context.user.is_admin():
                i['keyName'] = '%s (%s, %s)' % (i['keyName'],
                    instance['project_id'],
                    instance['host'])
            i['productCodesSet'] = self._convert_to_set([], 'product_codes')
            i['instanceType'] = instance['instance_type']
            i['launchTime'] = instance['created_at']
            i['amiLaunchIndex'] = instance['launch_index']
            if not reservations.has_key(instance['reservation_id']):
                r = {}
                r['reservationId'] = instance['reservation_id']
                r['ownerId'] = instance['project_id']
                r['groupSet'] = self._convert_to_set([], 'groups')
                r['instancesSet'] = []
                reservations[instance['reservation_id']] = r
            reservations[instance['reservation_id']]['instancesSet'].append(i)

        return list(reservations.values())

    @rbac.allow('all')
    def describe_addresses(self, context, **kwargs):
        return self.format_addresses(context)

    def format_addresses(self, context):
        addresses = []
        if context.user.is_admin():
            iterator = db.floating_ip_get_all(context)
        else:
            iterator = db.floating_ip_get_by_project(context,
                                                     context.project.id)
        for floating_ip_ref in iterator:
            address = floating_ip_ref['str_id']
            instance_id = None
            if (floating_ip_ref['fixed_ip']
                and floating_ip_ref['fixed_ip']['instance']):
                instance_id = floating_ip_ref['fixed_ip']['instance']['str_id']
            address_rv = {'public_ip': address,
                          'instance_id': instance_id}
            if context.user.is_admin():
                details = "%s (%s)" % (address_rv['instance_id'],
                                       floating_ip_ref['project_id'])
                address_rv['instance_id'] = details
            addresses.append(address_rv)
        return {'addressesSet': addresses}

    @rbac.allow('netadmin')
    @defer.inlineCallbacks
    def allocate_address(self, context, **kwargs):
        network_topic = yield self._get_network_topic(context)
        public_ip = yield rpc.call(network_topic,
                         {"method": "allocate_floating_ip",
                          "args": {"context": None,
                                   "project_id": context.project.id}})
        defer.returnValue({'addressSet': [{'publicIp': public_ip}]})

    @rbac.allow('netadmin')
    @defer.inlineCallbacks
    def release_address(self, context, public_ip, **kwargs):
        # NOTE(vish): Should we make sure this works?
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        network_topic = yield self._get_network_topic(context)
        rpc.cast(network_topic,
                 {"method": "deallocate_floating_ip",
                  "args": {"context": None,
                           "floating_address": floating_ip_ref['str_id']}})
        defer.returnValue({'releaseResponse': ["Address released."]})

    @rbac.allow('netadmin')
    @defer.inlineCallbacks
    def associate_address(self, context, instance_id, public_ip, **kwargs):
        instance_ref = db.instance_get_by_str(context, instance_id)
        fixed_ip_ref = db.fixed_ip_get_by_instance(context, instance_ref['id'])
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        network_topic = yield self._get_network_topic(context)
        rpc.cast(network_topic,
                 {"method": "associate_floating_ip",
                  "args": {"context": None,
                           "floating_address": floating_ip_ref['str_id'],
                           "fixed_address": fixed_ip_ref['str_id']}})
        defer.returnValue({'associateResponse': ["Address associated."]})

    @rbac.allow('netadmin')
    @defer.inlineCallbacks
    def disassociate_address(self, context, public_ip, **kwargs):
        floating_ip_ref = db.floating_ip_get_by_address(context, public_ip)
        network_topic = yield self._get_network_topic(context)
        rpc.cast(network_topic,
                 {"method": "disassociate_floating_ip",
                  "args": {"context": None,
                           "floating_address": floating_ip_ref['str_id']}})
        defer.returnValue({'disassociateResponse': ["Address disassociated."]})

    @defer.inlineCallbacks
    def _get_network_topic(self, context):
        """Retrieves the network host for a project"""
        network_ref = db.project_get_network(context, context.project.id)
        host = network_ref['host']
        if not host:
            host = yield rpc.call(FLAGS.network_topic,
                                  {"method": "set_network_host",
                                   "args": {"context": None,
                                            "project_id": context.project.id}})
        defer.returnValue(db.queue_get_for(context, FLAGS.network_topic, host))

    @rbac.allow('projectmanager', 'sysadmin')
    @defer.inlineCallbacks
    def run_instances(self, context, **kwargs):
        # make sure user can access the image
        # vpn image is private so it doesn't show up on lists
        vpn = kwargs['image_id'] == FLAGS.vpn_image_id

        if not vpn:
            image = images.get(context, kwargs['image_id'])

        # FIXME(ja): if image is vpn, this breaks
        # get defaults from imagestore
        image_id = image['imageId']
        kernel_id = image.get('kernelId', FLAGS.default_kernel)
        ramdisk_id = image.get('ramdiskId', FLAGS.default_ramdisk)

        # API parameters overrides of defaults
        kernel_id = kwargs.get('kernel_id', kernel_id)
        ramdisk_id = kwargs.get('ramdisk_id', ramdisk_id)

        # make sure we have access to kernel and ramdisk
        images.get(context, kernel_id)
        images.get(context, ramdisk_id)

        logging.debug("Going to run instances...")
        launch_time = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        key_data = None
        if kwargs.has_key('key_name'):
            key_pair = context.user.get_key_pair(kwargs['key_name'])
            if not key_pair:
                raise exception.ApiError('Key Pair %s not found' %
                                         kwargs['key_name'])
            key_data = key_pair.public_key

        # TODO: Get the real security group of launch in here
        security_group = "default"

        reservation_id = utils.generate_uid('r')
        base_options = {}
        base_options['image_id'] = image_id
        base_options['kernel_id'] = kernel_id
        base_options['ramdisk_id'] = ramdisk_id
        base_options['reservation_id'] = reservation_id
        base_options['key_data'] = key_data
        base_options['key_name'] = kwargs.get('key_name', None)
        base_options['user_id'] = context.user.id
        base_options['project_id'] = context.project.id
        base_options['user_data'] = kwargs.get('user_data', '')
        base_options['instance_type'] = kwargs.get('instance_type', 'm1.small')
        base_options['security_group'] = security_group

        for num in range(int(kwargs['max_count'])):
            inst_id = db.instance_create(context, base_options)['id']

            inst = {}
            inst['mac_address'] = utils.generate_mac()
            inst['launch_index'] = num
            inst['hostname'] = inst_id
            db.instance_update(context, inst_id, inst)
            address = self.network_manager.allocate_fixed_ip(context,
                                                             inst_id,
                                                             vpn)

            # TODO(vish): This probably should be done in the scheduler
            #             network is setup when host is assigned
            network_topic = yield self._get_network_topic(context)
            rpc.call(network_topic,
                     {"method": "setup_fixed_ip",
                      "args": {"context": None,
                               "address": address}})

            rpc.cast(FLAGS.compute_topic,
                 {"method": "run_instance",
                  "args": {"context": None,
                           "instance_id": inst_id}})
            logging.debug("Casting to node for %s/%s's instance %s" %
                      (context.project.name, context.user.name, inst_id))
        defer.returnValue(self._format_run_instances(context,
                                                     reservation_id))


    @rbac.allow('projectmanager', 'sysadmin')
    @defer.inlineCallbacks
    def terminate_instances(self, context, instance_id, **kwargs):
        logging.debug("Going to start terminating instances")
        for id_str in instance_id:
            logging.debug("Going to try and terminate %s" % id_str)
            try:
                instance_ref = db.instance_get_by_str(context, id_str)
            except exception.NotFound:
                logging.warning("Instance %s was not found during terminate"
                                % id_str)
                continue

            # FIXME(ja): where should network deallocate occur?
            address = db.instance_get_floating_address(context,
                                                       instance_ref['id'])
            if address:
                logging.debug("Disassociating address %s" % address)
                # NOTE(vish): Right now we don't really care if the ip is
                #             disassociated.  We may need to worry about
                #             checking this later.  Perhaps in the scheduler?
                network_topic = yield self._get_network_topic(context)
                rpc.cast(network_topic,
                         {"method": "disassociate_floating_ip",
                          "args": {"context": None,
                                   "address": address}})

            address = db.instance_get_fixed_address(context,
                                                    instance_ref['id'])
            if address:
                logging.debug("Deallocating address %s" % address)
                # NOTE(vish): Currently, nothing needs to be done on the
                #             network node until release. If this changes,
                #             we will need to cast here.
                db.fixed_ip_deallocate(context, address)

            host = instance_ref['host']
            if host:
                rpc.cast(db.queue_get_for(context, FLAGS.compute_topic, host),
                         {"method": "terminate_instance",
                          "args": {"context": None,
                                   "instance_id": instance_ref['id']}})
            else:
                db.instance_destroy(context, instance_ref['id'])
        defer.returnValue(True)

    @rbac.allow('projectmanager', 'sysadmin')
    def reboot_instances(self, context, instance_id, **kwargs):
        """instance_id is a list of instance ids"""
        for id_str in instance_id:
            instance_ref = db.instance_get_by_str(context, id_str)
            host = instance_ref['host']
            rpc.cast(db.queue_get_for(context, FLAGS.compute_topic, host),
                     {"method": "reboot_instance",
                      "args": {"context": None,
                               "instance_id": instance_ref['id']}})
        return defer.succeed(True)

    @rbac.allow('projectmanager', 'sysadmin')
    def delete_volume(self, context, volume_id, **kwargs):
        # TODO: return error if not authorized
        volume_ref = db.volume_get_by_str(context, volume_id)
        host = volume_ref['host']
        rpc.cast(db.queue_get_for(context, FLAGS.volume_topic, host),
                            {"method": "delete_volume",
                             "args": {"context": None,
                                      "volume_id": volume_ref['id']}})
        return defer.succeed(True)

    @rbac.allow('all')
    def describe_images(self, context, image_id=None, **kwargs):
        # The objectstore does its own authorization for describe
        imageSet = images.list(context, image_id)
        return defer.succeed({'imagesSet': imageSet})

    @rbac.allow('projectmanager', 'sysadmin')
    def deregister_image(self, context, image_id, **kwargs):
        # FIXME: should the objectstore be doing these authorization checks?
        images.deregister(context, image_id)
        return defer.succeed({'imageId': image_id})

    @rbac.allow('projectmanager', 'sysadmin')
    def register_image(self, context, image_location=None, **kwargs):
        # FIXME: should the objectstore be doing these authorization checks?
        if image_location is None and kwargs.has_key('name'):
            image_location = kwargs['name']
        image_id = images.register(context, image_location)
        logging.debug("Registered %s as %s" % (image_location, image_id))

        return defer.succeed({'imageId': image_id})

    @rbac.allow('all')
    def describe_image_attribute(self, context, image_id, attribute, **kwargs):
        if attribute != 'launchPermission':
            raise exception.ApiError('attribute not supported: %s' % attribute)
        try:
            image = images.list(context, image_id)[0]
        except IndexError:
            raise exception.ApiError('invalid id: %s' % image_id)
        result = {'image_id': image_id, 'launchPermission': []}
        if image['isPublic']:
            result['launchPermission'].append({'group': 'all'})
        return defer.succeed(result)

    @rbac.allow('projectmanager', 'sysadmin')
    def modify_image_attribute(self, context, image_id, attribute, operation_type, **kwargs):
        # TODO(devcamcar): Support users and groups other than 'all'.
        if attribute != 'launchPermission':
            raise exception.ApiError('attribute not supported: %s' % attribute)
        if not 'user_group' in kwargs:
            raise exception.ApiError('user or group not specified')
        if len(kwargs['user_group']) != 1 and kwargs['user_group'][0] != 'all':
            raise exception.ApiError('only group "all" is supported')
        if not operation_type in ['add', 'remove']:
            raise exception.ApiError('operation_type must be add or remove')
        result = images.modify(context, image_id, operation_type)
        return defer.succeed(result)
