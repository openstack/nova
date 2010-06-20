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
Rackspace API
"""

import base64
import json
import logging
import multiprocessing
import os
import time

from nova import vendor
import tornado.web
from twisted.internet import defer

from nova import datastore
from nova import flags
from nova import rpc
from nova import utils
from nova import exception
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


class ServersController(object):
    """ ServersController provides the critical dispatch between
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
        for instance in self.instdir.all:
            yield {instance['instance_id']: instance}

    @property
    def volumes(self):
        """ returns a list of all volumes """
        for volume_id in datastore.Redis.instance().smembers("volumes"):
            volume = storage.Volume(volume_id=volume_id)
            yield volume

    def __str__(self):
        return 'ServersController'

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

    def get_metadata(self, ip):
        i = self.get_instance_by_ip(ip)
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
                'security-groups': i.get('groups', '')
            }
        }
        if False: # TODO: store ancestor ids
            data['ancestor-ami-ids'] = []
        if i.get('product_codes', None):
            data['product-codes'] = i['product_codes']
        return data

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

class RackspaceAPIServerApplication(tornado.web.Application):
    def __init__(self, user_manager, controllers):
        tornado.web.Application.__init__(self, [
            (r'/servers/?(.*)', RackspaceServerRequestHandler),
        ], pool=multiprocessing.Pool(4))
        self.user_manager = user_manager
        self.controllers = controllers

class RackspaceServerRequestHandler(tornado.web.RequestHandler):

    def get(self, controller_name):
        self.execute(controller_name)

    @tornado.web.asynchronous
    def execute(self, controller_name):
        controller = self.application.controllers['Servers']

        # Obtain the appropriate controller for this request.
#        try:
#            controller = self.application.controllers[controller_name]
#        except KeyError:
#            self._error('unhandled', 'no controller named %s' % controller_name)
#            return
#
        args = self.request.arguments
        logging.error("ARGS: %s" % args)

        # Read request signature.
        try:
            signature = args.pop('Signature')[0]
        except:
            raise tornado.web.HTTPError(400)

        # Make a copy of args for authentication and signature verification.
        auth_params = {}
        for key, value in args.items():
            auth_params[key] = value[0]

        # Get requested action and remove authentication args for final request.
        try:
            action = args.pop('Action')[0]
            access = args.pop('AWSAccessKeyId')[0]
            args.pop('SignatureMethod')
            args.pop('SignatureVersion')
            args.pop('Version')
            args.pop('Timestamp')
        except:
            raise tornado.web.HTTPError(400)

        # Authenticate the request.
        try:
            (user, project) = users.UserManager.instance().authenticate(
                access,
                signature,
                auth_params,
                self.request.method,
                self.request.host,
                self.request.path
            )

        except exception.Error, ex:
            logging.debug("Authentication Failure: %s" % ex)
            raise tornado.web.HTTPError(403)

        _log.debug('action: %s' % action)

        for key, value in args.items():
            _log.debug('arg: %s\t\tval: %s' % (key, value))

        request = APIRequest(controller, action)
        context = APIRequestContext(self, user, project)
        d = request.send(context, **args)
        # d.addCallback(utils.debug)

        # TODO: Wrap response in AWS XML format
        d.addCallbacks(self._write_callback, self._error_callback)

    def _write_callback(self, data):
        self.set_header('Content-Type', 'text/xml')
        self.write(data)
        self.finish()

    def _error_callback(self, failure):
        try:
            failure.raiseException()
        except exception.ApiError as ex:
            self._error(type(ex).__name__ + "." + ex.code, ex.message)
        # TODO(vish): do something more useful with unknown exceptions
        except Exception as ex:
            self._error(type(ex).__name__, str(ex))
            raise

    def post(self, controller_name):
        self.execute(controller_name)

    def _error(self, code, message):
        self._status_code = 400
        self.set_header('Content-Type', 'text/xml')
        self.write('<?xml version="1.0"?>\n')
        self.write('<Response><Errors><Error><Code>%s</Code>'
                   '<Message>%s</Message></Error></Errors>'
                   '<RequestID>?</RequestID></Response>' % (code, message))
        self.finish()

