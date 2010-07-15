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

import logging
import StringIO
import time
import unittest
from xml.etree import ElementTree

from nova import vendor
from tornado import ioloop
from twisted.internet import defer

from nova import flags
from nova import rpc
from nova import test
from nova.auth import users
from nova.compute import node
from nova.endpoint import api
from nova.endpoint import cloud


FLAGS = flags.FLAGS


class CloudTestCase(test.BaseTestCase):
    def setUp(self):
        super(CloudTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_storage=True,
                   fake_users=True)

        self.conn = rpc.Connection.instance()
        logging.getLogger().setLevel(logging.DEBUG)

        # set up our cloud
        self.cloud = cloud.CloudController()
        self.cloud_consumer = rpc.AdapterConsumer(connection=self.conn,
                                                      topic=FLAGS.cloud_topic,
                                                      proxy=self.cloud)
        self.injected.append(self.cloud_consumer.attach_to_tornado(self.ioloop))

        # set up a node
        self.node = node.Node()
        self.node_consumer = rpc.AdapterConsumer(connection=self.conn,
                                                     topic=FLAGS.compute_topic,
                                                     proxy=self.node)
        self.injected.append(self.node_consumer.attach_to_tornado(self.ioloop))

        try:
            users.UserManager.instance().create_user('admin', 'admin', 'admin')
        except: pass
        admin = users.UserManager.instance().get_user('admin')
        project = users.UserManager.instance().create_project('proj', 'admin', 'proj')
        self.context = api.APIRequestContext(handler=None,project=project,user=admin)

    def tearDown(self):
        users.UserManager.instance().delete_project('proj')
        users.UserManager.instance().delete_user('admin')

    def test_console_output(self):
        if FLAGS.fake_libvirt:
            logging.debug("Can't test instances without a real virtual env.")
            return
        instance_id = 'foo'
        inst = yield self.node.run_instance(instance_id)
        output = yield self.cloud.get_console_output(self.context, [instance_id])
        logging.debug(output)
        self.assert_(output)
        rv = yield self.node.terminate_instance(instance_id)

    def test_run_instances(self):
        if FLAGS.fake_libvirt:
            logging.debug("Can't test instances without a real virtual env.")
            return
        image_id = FLAGS.default_image
        instance_type = FLAGS.default_instance_type
        max_count = 1
        kwargs = {'image_id': image_id,
                  'instance_type': instance_type,
                  'max_count': max_count}
        rv = yield self.cloud.run_instances(self.context, **kwargs)
        # TODO: check for proper response
        instance = rv['reservationSet'][0][rv['reservationSet'][0].keys()[0]][0]
        logging.debug("Need to watch instance %s until it's running..." % instance['instance_id'])
        while True:
            rv = yield defer.succeed(time.sleep(1))
            info = self.cloud._get_instance(instance['instance_id'])
            logging.debug(info['state'])
            if info['state'] == node.Instance.RUNNING:
                break
        self.assert_(rv)

        if not FLAGS.fake_libvirt:
            time.sleep(45) # Should use boto for polling here
        for reservations in rv['reservationSet']:
            # for res_id in reservations.keys():
            #  logging.debug(reservations[res_id])
             # for instance in reservations[res_id]:
           for instance in reservations[reservations.keys()[0]]:
               logging.debug("Terminating instance %s" % instance['instance_id'])
               rv = yield self.node.terminate_instance(instance['instance_id'])

    def test_instance_update_state(self):
        def instance(num):
            return {
                'reservation_id': 'r-1',
                'instance_id': 'i-%s' % num,
                'image_id': 'ami-%s' % num,
                'private_dns_name': '10.0.0.%s' % num,
                'dns_name': '10.0.0%s' % num,
                'ami_launch_index': str(num),
                'instance_type': 'fake',
                'availability_zone': 'fake',
                'key_name': None,
                'kernel_id': 'fake',
                'ramdisk_id': 'fake',
                'groups': ['default'],
                'product_codes': None,
                'state': 0x01,
                'user_data': ''
            }
        rv = self.cloud._format_instances(self.context)
        self.assert_(len(rv['reservationSet']) == 0)

        # simulate launch of 5 instances
        # self.cloud.instances['pending'] = {}
        #for i in xrange(5):
        #    inst = instance(i)
        #    self.cloud.instances['pending'][inst['instance_id']] = inst

        #rv = self.cloud._format_instances(self.admin)
        #self.assert_(len(rv['reservationSet']) == 1)
        #self.assert_(len(rv['reservationSet'][0]['instances_set']) == 5)
        # report 4 nodes each having 1 of the instances
        #for i in xrange(4):
        #    self.cloud.update_state('instances', {('node-%s' % i): {('i-%s' % i): instance(i)}})

        # one instance should be pending still
        #self.assert_(len(self.cloud.instances['pending'].keys()) == 1)

        # check that the reservations collapse
        #rv = self.cloud._format_instances(self.admin)
        #self.assert_(len(rv['reservationSet']) == 1)
        #self.assert_(len(rv['reservationSet'][0]['instances_set']) == 5)

        # check that we can get metadata for each instance
        #for i in xrange(4):
        #    data = self.cloud.get_metadata(instance(i)['private_dns_name'])
        #    self.assert_(data['meta-data']['ami-id'] == 'ami-%s' % i)
