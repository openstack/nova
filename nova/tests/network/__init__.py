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
Utility methods
"""
import os

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


def binpath(script):
    """Returns the absolute path to a script in bin"""
    return os.path.abspath(os.path.join(__file__, "../../../../bin", script))


def lease_ip(private_ip):
    """Run add command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(context.get_admin_context(),
                                          private_ip)
    instance_ref = db.fixed_ip_get_instance(context.get_admin_context(),
                                            private_ip)
    cmd = (binpath('nova-dhcpbridge'), 'add',
           instance_ref['mac_address'],
           private_ip, 'fake')
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(*cmd, addl_env=env)
    LOG.debug("ISSUE_IP: %s, %s ", out, err)


def release_ip(private_ip):
    """Run del command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(context.get_admin_context(),
                                          private_ip)
    instance_ref = db.fixed_ip_get_instance(context.get_admin_context(),
                                            private_ip)
    cmd = (binpath('nova-dhcpbridge'), 'del',
           instance_ref['mac_address'],
           private_ip, 'fake')
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(*cmd, addl_env=env)
    LOG.debug("RELEASE_IP: %s, %s ", out, err)
