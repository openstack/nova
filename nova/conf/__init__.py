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

# from nova.conf import api
# from nova.conf import api_database
# from nova.conf import availability_zone
# from nova.conf import aws
# from nova.conf import barbican
# from nova.conf import base
# from nova.conf import cells
from nova.conf import cert
# from nova.conf import cinder
# from nova.conf import cloudpipe
from nova.conf import compute
# from nova.conf import conductor
# from nova.conf import configdrive
# from nova.conf import console
# from nova.conf import cors
# from nova.conf import cors.subdomain
# from nova.conf import crypto
# from nova.conf import database
# from nova.conf import disk
from nova.conf import ephemeral_storage
# from nova.conf import floating_ip
# from nova.conf import glance
# from nova.conf import guestfs
# from nova.conf import host
# from nova.conf import hyperv
# from nova.conf import image
# from nova.conf import imagecache
# from nova.conf import image_file_url
from nova.conf import ironic
# from nova.conf import keymgr
# from nova.conf import keystone_authtoken
# from nova.conf import libvirt
# from nova.conf import matchmaker_redis
# from nova.conf import metadata
# from nova.conf import metrics
# from nova.conf import network
# from nova.conf import neutron
# from nova.conf import notification
# from nova.conf import osapi_v21
from nova.conf import pci
# from nova.conf import rdp
from nova.conf import scheduler
# from nova.conf import security
from nova.conf import serial_console
# from nova.conf import spice
# from nova.conf import ssl
# from nova.conf import trusted_computing
# from nova.conf import upgrade_levels
from nova.conf import virt
# from nova.conf import vmware
# from nova.conf import vnc
# from nova.conf import volume
# from nova.conf import workarounds
# from nova.conf import wsgi
# from nova.conf import xenserver
# from nova.conf import xvp
# from nova.conf import zookeeper

CONF = cfg.CONF

# api.register_opts(CONF)
# api_database.register_opts(CONF)
# availability_zone.register_opts(CONF)
# aws.register_opts(CONF)
# barbican.register_opts(CONF)
# base.register_opts(CONF)
# cells.register_opts(CONF)
cert.register_opts(CONF)
# cinder.register_opts(CONF)
# cloudpipe.register_opts(CONF)
compute.register_opts(CONF)
# conductor.register_opts(CONF)
# configdrive.register_opts(CONF)
# console.register_opts(CONF)
# cors.register_opts(CONF)
# cors.subdomain.register_opts(CONF)
# crypto.register_opts(CONF)
# database.register_opts(CONF)
# disk.register_opts(CONF)
ephemeral_storage.register_opts(CONF)
# floating_ip.register_opts(CONF)
# glance.register_opts(CONF)
# guestfs.register_opts(CONF)
# host.register_opts(CONF)
# hyperv.register_opts(CONF)
# image.register_opts(CONF)
# imagecache.register_opts(CONF)
# image_file_url.register_opts(CONF)
ironic.register_opts(CONF)
# keymgr.register_opts(CONF)
# keystone_authtoken.register_opts(CONF)
# libvirt.register_opts(CONF)
# matchmaker_redis.register_opts(CONF)
# metadata.register_opts(CONF)
# metrics.register_opts(CONF)
# network.register_opts(CONF)
# neutron.register_opts(CONF)
# notification.register_opts(CONF)
# osapi_v21.register_opts(CONF)
pci.register_opts(CONF)
# rdp.register_opts(CONF)
scheduler.register_opts(CONF)
# security.register_opts(CONF)
serial_console.register_opts(CONF)
# spice.register_opts(CONF)
# ssl.register_opts(CONF)
# trusted_computing.register_opts(CONF)
# upgrade_levels.register_opts(CONF)
virt.register_opts(CONF)
# vmware.register_opts(CONF)
# vnc.register_opts(CONF)
# volume.register_opts(CONF)
# workarounds.register_opts(CONF)
# wsgi.register_opts(CONF)
# xenserver.register_opts(CONF)
# xvp.register_opts(CONF)
# zookeeper.register_opts(CONF)
