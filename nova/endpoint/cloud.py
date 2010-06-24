# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Cloud Controller: Implementation of EC2 REST API calls, which are
dispatched to other nodes via AMQP RPC. State is via distributed
datastore.
"""

import base64
import json
import logging
import os
import time

from nova import vendor
from twisted.internet import defer

from nova import datastore
from nova import flags
from nova import rpc
from nova import utils
from nova import exception
from nova.auth import rbac
from nova.auth import users
from nova.compute import model
from nova.compute import network
from nova.endpoint import images
from nova.volume import storage

FLAGS = flags.FLAGS

flags.DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')

def _gen_key(user_id, key_name):
    """ Tuck this into UserManager """
    try:
        manager = users.UserManager.instance()
        private_key, fingerprint = manager.generate_key_pair(user_id, key_name)
    except Exception as ex:
        return {'exception': ex}
    return {'private_key': private_key, 'fingerprint': fingerprint}


class CloudController(object):
    """ CloudController provides the critical dispatch between
 inbound API calls through the endpoint and messages
 sent to the other nodes.
"""
    def __init__(self):
        self.instdir = model.InstanceDirectory()
        self.network = network.PublicNetworkController()
        self.setup()

    @property
    def instances(self):
        """ All instances in the system, as dicts """
        return self.instdir.all

    @property
    def volumes(self):
        """ returns a list of all volumes """
        for volume_id in datastore.Redis.instance().smembers("storage-volumes"):
            volume = storage.Volume(volume_id=volume_id)
            yield volume

    def __str__(self):
        return 'CloudController'

    def setup(self):
        """ Ensure the keychains and folders exist. """
        # Create keys folder, if it doesn't exist
        if not os.path.exists(FLAGS.keys_path):
            os.makedirs(os.path.abspath(FLAGS.keys_path))
        # Gen root CA, if we don't have one
        root_ca_path = os.path.join(FLAGS.ca_path, FLAGS.ca_file)
        if not os.path.exists(root_ca_path):
            start = os.getcwd()
            os.chdir(FLAGS.ca_path)
            utils.runthis("Generating root CA: %s", "sh genrootca.sh")
            os.chdir(start)
            # TODO: Do this with M2Crypto instead

    def get_instance_by_ip(self, ip):
        return self.instdir.by_ip(ip)

    def _get_mpi_data(self, project_id):
        result = {}
        for instance in self.instdir.all:
            if instance['project_id'] == project_id:
                line = '%s slots=%d' % (instance['private_dns_name'], instance.get('vcpus', 0))
                if instance['key_name'] in result:
                    result[instance['key_name']].append(line)
                else:
                    result[instance['key_name']] = [line]
        return result

    def get_metadata(self, ip):
        i = self.get_instance_by_ip(ip)
        mpi = self._get_mpi_data(i['project_id'])
        if i is None:
            return None
        if i['key_name']:
            keys = {
                '0': {
                    '_name': i['key_name'],
                    'openssh-key': i['key_data']
                }
            }
        else:
            keys = ''
        data = {
            'user-data': base64.b64decode(i['user_data']),
            'meta-data': {
                'ami-id': i['image_id'],
                'ami-launch-index': i['ami_launch_index'],
                'ami-manifest-path': 'FIXME', # image property
                'block-device-mapping': { # TODO: replace with real data
                    'ami': 'sda1',
                    'ephemeral0': 'sda2',
                    'root': '/dev/sda1',
                    'swap': 'sda3'
                },
                'hostname': i['private_dns_name'], # is this public sometimes?
                'instance-action': 'none',
                'instance-id': i['instance_id'],
                'instance-type': i.get('instance_type', ''),
                'local-hostname': i['private_dns_name'],
                'local-ipv4': i['private_dns_name'], # TODO: switch to IP
                'kernel-id': i.get('kernel_id', ''),
                'placement': {
                    'availaibility-zone': i.get('availability_zone', 'nova'),
                },
                'public-hostname': i.get('dns_name', ''),
                'public-ipv4': i.get('dns_name', ''), # TODO: switch to IP
                'public-keys' : keys,
                'ramdisk-id': i.get('ramdisk_id', ''),
                'reservation-id': i['reservation_id'],
                'security-groups': i.get('groups', ''),
                'mpi': mpi
            }
        }
        if False: # TODO: store ancestor ids
            data['ancestor-ami-ids'] = []
        if i.get('product_codes', None):
            data['product-codes'] = i['product_codes']
        return data

    @rbac.allow('all')
    def describe_availability_zones(self, context, **kwargs):
        return {'availabilityZoneInfo': [{'zoneName': 'nova',
                                          'zoneState': 'available'}]}

    @rbac.allow('all')
    def describe_key_pairs(self, context, key_name=None, **kwargs):
        key_pairs = []
        key_names = key_name and key_name or []
        if len(key_names) > 0:
            for key_name in key_names:
                key_pair = context.user.get_key_pair(key_name)
                if key_pair != None:
                    key_pairs.append({
                        'keyName': key_pair.name,
                        'keyFingerprint': key_pair.fingerprint,
                    })
        else:
            for key_pair in context.user.get_key_pairs():
                key_pairs.append({
                    'keyName': key_pair.name,
                    'keyFingerprint': key_pair.fingerprint,
                })

        return { 'keypairsSet': key_pairs }

    @rbac.allow('all')
    def create_key_pair(self, context, key_name, **kwargs):
        try:
            d = defer.Deferred()
            p = context.handler.application.settings.get('pool')
            def _complete(kwargs):
                if 'exception' in kwargs:
                    d.errback(kwargs['exception'])
                    return
                d.callback({'keyName': key_name,
                    'keyFingerprint': kwargs['fingerprint'],
                    'keyMaterial': kwargs['private_key']})
            p.apply_async(_gen_key, [context.user.id, key_name],
                callback=_complete)
            return d

        except users.UserError, e:
            raise

    @rbac.allow('all')
    def delete_key_pair(self, context, key_name, **kwargs):
        context.user.delete_key_pair(key_name)
        # aws returns true even if the key doens't exist
        return True

    @rbac.allow('all')
    def describe_security_groups(self, context, group_names, **kwargs):
        groups = { 'securityGroupSet': [] }

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
        instance = self._get_instance(context, instance_id[0])
        if instance['state'] == 'pending':
            raise exception.ApiError('Cannot get output for pending instance')
        return rpc.call('%s.%s' % (FLAGS.compute_topic, instance['node_name']),
            {"method": "get_console_output",
             "args" : {"instance_id": instance_id[0]}})

    def _get_user_id(self, context):
        if context and context.user:
            return context.user.id
        else:
            return None

    @rbac.allow('projectmanager', 'sysadmin')
    def describe_volumes(self, context, **kwargs):
        volumes = []
        for volume in self.volumes:
            if context.user.is_admin() or volume['project_id'] == context.project.id:
                v = self.format_volume(context, volume)
                volumes.append(v)
        return defer.succeed({'volumeSet': volumes})

    def format_volume(self, context, volume):
        v = {}
        v['volumeId'] = volume['volume_id']
        v['status'] = volume['status']
        v['size'] = volume['size']
        v['availabilityZone'] = volume['availability_zone']
        v['createTime'] = volume['create_time']
        if context.user.is_admin():
            v['status'] = '%s (%s, %s, %s, %s)' % (
                volume.get('status', None),
                volume.get('user_id', None),
                volume.get('node_name', None),
                volume.get('instance_id', ''),
                volume.get('mountpoint', ''))
        if volume['status'] == 'attached':
            v['attachmentSet'] = [{'attachTime': volume['attachTime'],
                                   'deleteOnTermination': volume['deleteOnTermination'],
                                   'device' : volume['mountpoint'],
                                   'instanceId' : volume['instance_id'],
                                   'status' : 'attached',
                                   'volume_id' : volume['volume_id']}]
        else:
            v['attachmentSet'] = [{}]
        return v

    @rbac.allow('projectmanager', 'sysadmin')
    def create_volume(self, context, size, **kwargs):
        # TODO(vish): refactor this to create the volume object here and tell storage to create it
        res = rpc.call(FLAGS.storage_topic, {"method": "create_volume",
                                 "args" : {"size": size,
                                           "user_id": context.user.id}})
        def _format_result(result):
            volume = self._get_volume(context, result['result'])
            return {'volumeSet': [self.format_volume(context, volume)]}
        res.addCallback(_format_result)
        return res

    def _get_address(self, context, public_ip):
        # FIXME(vish) this should move into network.py
        for address in self.network.hosts:
            if address['address'] == public_ip:
                if context.user.is_admin() or address['project_id'] == context.project.id:
                    return address
        raise exception.NotFound("Address at ip %s not found" % public_ip)

    def _get_image(self, context, image_id):
        """passes in context because
        objectstore does its own authorization"""
        result = images.list(context, [image_id])
        if not result:
            raise exception.NotFound('Image %s could not be found' % image_id)
        image = result[0]
        return image

    def _get_instance(self, context, instance_id):
        for instance in self.instances:
            if instance['instance_id'] == instance_id:
                if context.user.is_admin() or instance['project_id'] == context.project.id:
                    return instance
        raise exception.NotFound('Instance %s could not be found' % instance_id)

    def _get_volume(self, context, volume_id):
        volume = storage.get_volume(volume_id)
        if context.user.is_admin() or volume['project_id'] == context.project.id:
            return volume
        raise exception.NotFound('Volume %s could not be found' % volume_id)

    @rbac.allow('projectmanager', 'sysadmin')
    def attach_volume(self, context, volume_id, instance_id, device, **kwargs):
        volume = self._get_volume(context, volume_id)
        if volume['status'] == "attached":
            raise exception.Error("Volume is already attached")
        volume.start_attach(instance_id, device)
        instance = self._get_instance(context, instance_id)
        compute_node = instance['node_name']
        rpc.cast('%s.%s' % (FLAGS.compute_topic, compute_node),
                                {"method": "attach_volume",
                                 "args" : {"volume_id": volume_id,
                                           "instance_id" : instance_id,
                                           "mountpoint" : device}})
        return defer.succeed({'attachTime' : volume['attachTime'],
                              'device' : volume['mountpoint'],
                              'instanceId' : instance_id,
                              'requestId' : context.request_id,
                              'status' : volume['attachStatus'],
                              'volumeId' : volume_id})


    @rbac.allow('projectmanager', 'sysadmin')
    def detach_volume(self, context, volume_id, **kwargs):
        volume = self._get_volume(context, volume_id)
        instance_id = volume.get('instance_id', None)
        if volume['status'] == "available":
            raise exception.Error("Volume is already detached")
        volume.start_detach()
        if instance_id:
            try:
                instance = self._get_instance(context, instance_id)
                rpc.cast('%s.%s' % (FLAGS.compute_topic, instance['node_name']),
                                {"method": "detach_volume",
                                 "args" : {"instance_id": instance_id,
                                           "mountpoint": volume['mountpoint']}})
            except exception.NotFound:
                # If the instance doesn't exist anymore,
                # then we need to call detach blind
                volume.finish_detach()
        else:
            raise exception.Error("Volume isn't attached to anything!")
        return defer.succeed({'attachTime' : volume['attachTime'],
                              'device' : volume['mountpoint'],
                              'instanceId' : instance_id,
                              'requestId' : context.request_id,
                              'status' : volume['attachStatus'],
                              'volumeId' : volume_id})

    def _convert_to_set(self, lst, str):
        if lst == None or lst == []:
            return None
        return [{str: x} for x in lst]

    @rbac.allow('all')
    def describe_instances(self, context, **kwargs):
        return defer.succeed(self._format_instances(context))

    def _format_instances(self, context, reservation_id = None):
        reservations = {}
        for instance in self.instdir.all:
            res_id = instance.get('reservation_id', 'Unknown')
            if ((context.user.is_admin() or context.project.id == instance['project_id'])
                and (reservation_id == None or reservation_id == res_id)):
                i = {}
                i['instance_id'] = instance.get('instance_id', None)
                i['image_id'] = instance.get('image_id', None)
                i['instance_state'] = {
                    'code': 42,
                    'name': instance.get('state', 'pending')
                }
                i['public_dns_name'] = self.network.get_public_ip_for_instance(
                                                            i['instance_id'])
                i['private_dns_name'] = instance.get('private_dns_name', None)
                if not i['public_dns_name']:
                    i['public_dns_name'] = i['private_dns_name']
                i['dns_name'] = instance.get('dns_name', None)
                i['key_name'] = instance.get('key_name', None)
                if context.user.is_admin():
                    i['key_name'] = '%s (%s, %s)' % (i['key_name'],
                        instance.get('owner_id', None), instance.get('node_name',''))
                i['product_codes_set'] = self._convert_to_set(
                    instance.get('product_codes', None), 'product_code')
                i['instance_type'] = instance.get('instance_type', None)
                i['launch_time'] = instance.get('launch_time', None)
                i['ami_launch_index'] = instance.get('ami_launch_index',
                                                     None)
                if not reservations.has_key(res_id):
                    r = {}
                    r['reservation_id'] = res_id
                    r['owner_id'] = instance.get('project_id', None)
                    r['group_set'] = self._convert_to_set(
                        instance.get('groups', None), 'group_id')
                    r['instances_set'] = []
                    reservations[res_id] = r
                reservations[res_id]['instances_set'].append(i)

        instance_response = {'reservationSet' : list(reservations.values()) }
        return instance_response

    @rbac.allow('all')
    def describe_addresses(self, context, **kwargs):
        return self.format_addresses(context)

    def format_addresses(self, context):
        addresses = []
        # TODO(vish): move authorization checking into network.py
        for address in self.network.hosts:
            #logging.debug(address_record)
            address_rv = {
                'public_ip': address['address'],
                'instance_id' : address.get('instance_id', 'free')
            }
            if context.user.is_admin():
                address_rv['instance_id'] = "%s (%s, %s)" % (
                    address['instance_id'],
                    address['user_id'],
                    address['project_id'],
                )
            addresses.append(address_rv)
        # logging.debug(addresses)
        return {'addressesSet': addresses}

    @rbac.allow('netadmin')
    def allocate_address(self, context, **kwargs):
        address = self.network.allocate_ip(
                                context.user.id, context.project.id, 'public')
        return defer.succeed({'addressSet': [{'publicIp' : address}]})

    @rbac.allow('netadmin')
    def release_address(self, context, public_ip, **kwargs):
        self.network.deallocate_ip(public_ip)
        return defer.succeed({'releaseResponse': ["Address released."]})

    @rbac.allow('netadmin')
    def associate_address(self, context, instance_id, **kwargs):
        instance = self._get_instance(context, instance_id)
        self.network.associate_address(
                            kwargs['public_ip'],
                            instance['private_dns_name'],
                            instance_id)
        return defer.succeed({'associateResponse': ["Address associated."]})

    @rbac.allow('netadmin')
    def disassociate_address(self, context, public_ip, **kwargs):
        address = self._get_address(public_ip)
        self.network.disassociate_address(public_ip)
        # TODO - Strip the IP from the instance
        return defer.succeed({'disassociateResponse': ["Address disassociated."]})

    @rbac.allow('projectmanager', 'sysadmin')
    def run_instances(self, context, **kwargs):
        image = self._get_image(context, kwargs['image_id'])
        logging.debug("Going to run instances...")
        reservation_id = utils.generate_uid('r')
        launch_time = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        key_data = None
        if kwargs.has_key('key_name'):
            key_pair = context.user.get_key_pair(kwargs['key_name'])
            if not key_pair:
                raise exception.ApiError('Key Pair %s not found' %
                                         kwargs['key_name'])
            key_data = key_pair.public_key

        for num in range(int(kwargs['max_count'])):
            inst = self.instdir.new()
            # TODO(ja): add ari, aki
            inst['image_id'] = kwargs['image_id']
            inst['user_data'] = kwargs.get('user_data', '')
            inst['instance_type'] = kwargs.get('instance_type', '')
            inst['reservation_id'] = reservation_id
            inst['launch_time'] = launch_time
            inst['key_data'] = key_data or ''
            inst['key_name'] = kwargs.get('key_name', '')
            inst['user_id'] = context.user.id
            inst['project_id'] = context.project.id
            inst['mac_address'] = utils.generate_mac()
            inst['ami_launch_index'] = num
            address = network.allocate_ip(
                        inst['user_id'], inst['project_id'], mac=inst['mac_address'])
            inst['private_dns_name'] = str(address)
            inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(inst['user_id'], inst['project_id'], 'default')['bridge_name']
            # TODO: allocate expresses on the router node
            inst.save()
            rpc.cast(FLAGS.compute_topic,
                 {"method": "run_instance",
                  "args": {"instance_id" : inst.instance_id}})
            logging.debug("Casting to node for %s's instance with IP of %s" %
                      (context.user.name, inst['private_dns_name']))
        # TODO: Make the NetworkComputeNode figure out the network name from ip.
        return defer.succeed(self._format_instances(
                                context, reservation_id))

    @rbac.allow('projectmanager', 'sysadmin')
    def terminate_instances(self, context, instance_id, **kwargs):
        logging.debug("Going to start terminating instances")
        for i in instance_id:
            logging.debug("Going to try and terminate %s" % i)
            try:
                instance = self._get_instance(context, i)
            except exception.NotFound:
                logging.warning("Instance %s was not found during terminate" % i)
                continue
            try:
                self.network.disassociate_address(
                    instance.get('public_dns_name', 'bork'))
            except:
                pass
            if instance.get('private_dns_name', None):
                logging.debug("Deallocating address %s" % instance.get('private_dns_name', None))
                try:
                    self.network.deallocate_ip(instance.get('private_dns_name', None))
                except Exception, _err:
                    pass
            if instance.get('node_name', 'unassigned') != 'unassigned':  #It's also internal default
                rpc.cast('%s.%s' % (FLAGS.compute_topic, instance['node_name']),
                             {"method": "terminate_instance",
                              "args" : {"instance_id": i}})
            else:
                instance.destroy()
        return defer.succeed(True)

    @rbac.allow('projectmanager', 'sysadmin')
    def reboot_instances(self, context, instance_id, **kwargs):
        """instance_id is a list of instance ids"""
        for i in instance_id:
            instance = self._get_instance(context, i)
            if instance['state'] == 'pending':
                raise exception.ApiError('Cannot reboot pending instance')
            rpc.cast('%s.%s' % (FLAGS.node_topic, instance['node_name']),
                             {"method": "reboot_instance",
                              "args" : {"instance_id": i}})
        return defer.succeed(True)

    @rbac.allow('projectmanager', 'sysadmin')
    def delete_volume(self, context, volume_id, **kwargs):
        # TODO: return error if not authorized
        volume = self._get_volume(context, volume_id)
        storage_node = volume['node_name']
        rpc.cast('%s.%s' % (FLAGS.storage_topic, storage_node),
                            {"method": "delete_volume",
                             "args" : {"volume_id": volume_id}})
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

    def describe_image_attribute(self, context, image_id, attribute, **kwargs):
        if attribute != 'launchPermission':
            raise exception.ApiError('attribute not supported: %s' % attribute)
        try:
            image = images.list(context, image_id)[0]
        except IndexError:
            raise exception.ApiError('invalid id: %s' % image_id)
        result = { 'image_id': image_id, 'launchPermission': [] }
        if image['isPublic']:
            result['launchPermission'].append({ 'group': 'all' })
        
        return defer.succeed(result)
        
    @rbac.allow('projectmanager', 'sysadmin')
    def modify_image_attribute(self, context, image_id, attribute, operation_type, **kwargs):
        # TODO(devcamcar): Support users and groups other than 'all'.
        if attribute != 'launchPermission':
            raise exception.ApiError('attribute not supported: %s' % attribute)
        if len(kwargs['user_group']) != 1 and kwargs['user_group'][0] != 'all':
            raise exception.ApiError('only group "all" is supported')
        if not operation_type in ['add', 'delete']:
            raise exception.ApiError('operation_type must be add or delete')
        result = images.modify(context, image_id, operation_type)
        return defer.succeed(result)

    def update_state(self, topic, value):
        """ accepts status reports from the queue and consolidates them """
        # TODO(jmc): if an instance has disappeared from
        # the node, call instance_death
        if topic == "instances":
            return defer.succeed(True)
        aggregate_state = getattr(self, topic)
        node_name = value.keys()[0]
        items = value[node_name]

        logging.debug("Updating %s state for %s" % (topic, node_name))

        for item_id in items.keys():
            if (aggregate_state.has_key('pending') and
                aggregate_state['pending'].has_key(item_id)):
                del aggregate_state['pending'][item_id]
        aggregate_state[node_name] = items

        return defer.succeed(True)
