# Copyright 2015 OpenStack Foundation
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

# This package got introduced during the Mitaka cycle in 2015 to
# have a central place where the config options of Nova can be maintained.
# For more background see the blueprint "centralize-config-options"

from oslo_config import cfg

from nova.conf import api
from nova.conf import availability_zone
from nova.conf import base
from nova.conf import cache
from nova.conf import cinder
from nova.conf import compute
from nova.conf import conductor
from nova.conf import configdrive
from nova.conf import console
from nova.conf import consoleauth
from nova.conf import cyborg
from nova.conf import database
from nova.conf import devices
from nova.conf import ephemeral_storage
from nova.conf import glance
from nova.conf import guestfs
from nova.conf import hyperv
from nova.conf import imagecache
from nova.conf import ironic
from nova.conf import key_manager
from nova.conf import keystone
from nova.conf import libvirt
from nova.conf import mks
from nova.conf import netconf
from nova.conf import neutron
from nova.conf import notifications
from nova.conf import novnc
from nova.conf import paths
from nova.conf import pci
from nova.conf import placement
from nova.conf import powervm
from nova.conf import quota
from nova.conf import rdp
from nova.conf import rpc
from nova.conf import scheduler
from nova.conf import serial_console
from nova.conf import service
from nova.conf import service_token
from nova.conf import servicegroup
from nova.conf import spice
from nova.conf import upgrade_levels
from nova.conf import vendordata
from nova.conf import vmware
from nova.conf import vnc
from nova.conf import workarounds
from nova.conf import wsgi
from nova.conf import zvm

CONF = cfg.CONF

api.register_opts(CONF)
availability_zone.register_opts(CONF)
base.register_opts(CONF)
cache.register_opts(CONF)
cinder.register_opts(CONF)
compute.register_opts(CONF)
conductor.register_opts(CONF)
configdrive.register_opts(CONF)
console.register_opts(CONF)
consoleauth.register_opts(CONF)
cyborg.register_opts(CONF)
database.register_opts(CONF)
devices.register_opts(CONF)
ephemeral_storage.register_opts(CONF)
glance.register_opts(CONF)
guestfs.register_opts(CONF)
hyperv.register_opts(CONF)
mks.register_opts(CONF)
imagecache.register_opts(CONF)
ironic.register_opts(CONF)
key_manager.register_opts(CONF)
keystone.register_opts(CONF)
libvirt.register_opts(CONF)
netconf.register_opts(CONF)
neutron.register_opts(CONF)
notifications.register_opts(CONF)
novnc.register_opts(CONF)
paths.register_opts(CONF)
pci.register_opts(CONF)
placement.register_opts(CONF)
powervm.register_opts(CONF)
quota.register_opts(CONF)
rdp.register_opts(CONF)
rpc.register_opts(CONF)
scheduler.register_opts(CONF)
serial_console.register_opts(CONF)
service.register_opts(CONF)
service_token.register_opts(CONF)
servicegroup.register_opts(CONF)
spice.register_opts(CONF)
upgrade_levels.register_opts(CONF)
vendordata.register_opts(CONF)
vmware.register_opts(CONF)
vnc.register_opts(CONF)
workarounds.register_opts(CONF)
wsgi.register_opts(CONF)
zvm.register_opts(CONF)
