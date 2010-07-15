#!/usr/bin/env python
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
dhcpleasor.py

Handle lease database updates from DHCP servers.
"""

import sys
import os
import logging
sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))

logging.debug(sys.path)
import getopt
from os import environ
from nova.compute import linux_net
from nova.compute import network
from nova import rpc

from nova import flags
FLAGS = flags.FLAGS


def add_lease(mac, ip, hostname, interface):
    if FLAGS.fake_rabbit:
        network.lease_ip(ip)
    else:
        rpc.cast(FLAGS.cloud_topic, {"method": "lease_ip",
                "args" : {"address": ip}})

def old_lease(mac, ip, hostname, interface):
    logging.debug("Adopted old lease or got a change of mac/hostname")

def del_lease(mac, ip, hostname, interface):
    if FLAGS.fake_rabbit:
        network.release_ip(ip)
    else:
        rpc.cast(FLAGS.cloud_topic, {"method": "release_ip",
                "args" : {"address": ip}})

def init_leases(interface):
    net = network.get_network_by_interface(interface)
    res = ""
    for host_name in net.hosts:
        res += "%s\n" % linux_net.hostDHCP(net, host_name, net.hosts[host_name])
    return res


def main(argv=None):
    if argv is None:
        argv = sys.argv
    interface = environ.get('DNSMASQ_INTERFACE', 'br0')
    if int(environ.get('TESTING', '0')):
        FLAGS.fake_rabbit = True
        FLAGS.redis_db = 8
        FLAGS.network_size = 32
        FLAGS.fake_libvirt=True
        FLAGS.fake_network=True
        FLAGS.fake_users = True
    action = argv[1]
    if action in ['add','del','old']:
        mac = argv[2]
        ip = argv[3]
        hostname = argv[4]
        logging.debug("Called %s for mac %s with ip %s and hostname %s on interface %s" % (action, mac, ip, hostname, interface))
        globals()[action+'_lease'](mac, ip, hostname, interface)
    else:
        print init_leases(interface)
    exit(0)

if __name__ == "__main__":
    sys.exit(main())
