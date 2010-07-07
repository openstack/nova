#!/opt/local/bin/python

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
from nova.compute import network
from nova import flags
FLAGS = flags.FLAGS


def add_lease(mac, ip, hostname, interface):
    pass

def old_lease(mac, ip, hostname, interface):
    pass
    
def del_lease(mac, ip, hostname, interface):
    # TODO - get net from interface instead
    net = network.get_network_by_address(ip)
    net.release_ip(ip)    
    
def init_leases(interface):
    return ""


def main(argv=None):
    if argv is None:
        argv = sys.argv
    interface = environ.get('DNSMASQ_INTERFACE', 'br0')
    old_redis_db = FLAGS.redis_db
    FLAGS.redis_db = int(environ.get('REDIS_DB', '0'))
    action = argv[1]
    if action in ['add','del','old']:
        mac = argv[2]
        ip = argv[3]
        hostname = argv[4]
        logging.debug("Called %s for mac %s with ip %s and hostname %s on interface %s" % (action, mac, ip, hostname, interface))
        globals()[action+'_lease'](mac, ip, hostname, interface)
    else:
        print init_leases(interface)
    FLAGS.redis_db = old_redis_db

if __name__ == "__main__":
    sys.exit(main())
