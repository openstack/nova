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
Unit Tests for flat network code
"""
import netaddr
import os
import unittest

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.auth import manager
from nova.tests.network import base


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class FlatNetworkTestCase(base.NetworkTestCase):
    """Test cases for network code"""
    def test_public_network_association(self):
        """Makes sure that we can allocate a public ip"""
        # TODO(vish): better way of adding floating ips

        self.context._project = self.projects[0]
        self.context.project_id = self.projects[0].id
        pubnet = netaddr.IPRange(flags.FLAGS.floating_range)
        address = str(list(pubnet)[0])
        try:
            db.floating_ip_get_by_address(context.get_admin_context(), address)
        except exception.NotFound:
            db.floating_ip_create(context.get_admin_context(),
                                  {'address': address,
                                   'host': FLAGS.host})

        self.assertRaises(NotImplementedError,
                          self.network.allocate_floating_ip,
                          self.context, self.projects[0].id)

        fix_addr = self._create_address(0)
        float_addr = address
        self.assertRaises(NotImplementedError,
                          self.network.associate_floating_ip,
                          self.context, float_addr, fix_addr)

        address = db.instance_get_floating_address(context.get_admin_context(),
                                                   self.instance_id)
        self.assertEqual(address, None)

        self.assertRaises(NotImplementedError,
                          self.network.disassociate_floating_ip,
                          self.context, float_addr)

        address = db.instance_get_floating_address(context.get_admin_context(),
                                                   self.instance_id)
        self.assertEqual(address, None)

        self.assertRaises(NotImplementedError,
                          self.network.deallocate_floating_ip,
                          self.context, float_addr)

        self.network.deallocate_fixed_ip(self.context, fix_addr)
        db.floating_ip_destroy(context.get_admin_context(), float_addr)

    def test_allocate_deallocate_fixed_ip(self):
        """Makes sure that we can allocate and deallocate a fixed ip"""
        address = self._create_address(0)
        self.assertTrue(self._is_allocated_in_project(address,
                                                      self.projects[0].id))
        self._deallocate_address(0, address)

        # check if the fixed ip address is really deallocated
        self.assertFalse(self._is_allocated_in_project(address,
                                                       self.projects[0].id))

    def test_side_effects(self):
        """Ensures allocating and releasing has no side effects"""
        address = self._create_address(0)
        address2 = self._create_address(1, self.instance2_id)

        self.assertTrue(self._is_allocated_in_project(address,
                                                      self.projects[0].id))
        self.assertTrue(self._is_allocated_in_project(address2,
                                                      self.projects[1].id))

        self._deallocate_address(0, address)
        self.assertFalse(self._is_allocated_in_project(address,
                                                       self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertTrue(self._is_allocated_in_project(address2,
                                                      self.projects[0].id))

        self._deallocate_address(1, address2)
        self.assertFalse(self._is_allocated_in_project(address2,
                                                 self.projects[1].id))

    def test_ips_are_reused(self):
        """Makes sure that ip addresses that are deallocated get reused"""
        address = self._create_address(0)
        self.network.deallocate_fixed_ip(self.context, address)

        address2 = self._create_address(0)
        self.assertEqual(address, address2)

        self.network.deallocate_fixed_ip(self.context, address2)

    def test_too_many_addresses(self):
        """Test for a NoMoreAddresses exception when all fixed ips are used.
        """
        admin_context = context.get_admin_context()
        network = db.project_get_network(admin_context, self.projects[0].id)
        num_available_ips = db.network_count_available_ips(admin_context,
                                                           network['id'])
        addresses = []
        instance_ids = []
        for i in range(num_available_ips):
            instance_ref = self._create_instance(0)
            instance_ids.append(instance_ref['id'])
            address = self._create_address(0, instance_ref['id'])
            addresses.append(address)

        ip_count = db.network_count_available_ips(context.get_admin_context(),
                                                  network['id'])
        self.assertEqual(ip_count, 0)
        self.assertRaises(db.NoMoreAddresses,
                          self.network.allocate_fixed_ip,
                          self.context,
                          'foo')

        for i in range(num_available_ips):
            self.network.deallocate_fixed_ip(self.context, addresses[i])
            db.instance_destroy(context.get_admin_context(), instance_ids[i])
        ip_count = db.network_count_available_ips(context.get_admin_context(),
                                                  network['id'])
        self.assertEqual(ip_count, num_available_ips)

    def run(self, result=None):
        if(FLAGS.network_manager == 'nova.network.manager.FlatManager'):
            super(FlatNetworkTestCase, self).run(result)
