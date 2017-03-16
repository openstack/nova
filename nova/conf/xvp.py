# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg

from nova.conf import paths

xvp_group = cfg.OptGroup(
    'xvp',
    title='XVP options',
    help="""
Configuration options for XVP.

xvp (Xen VNC Proxy) is a proxy server providing password-protected VNC-based
access to the consoles of virtual machines hosted on Citrix XenServer.
"""
)

xvp_opts = [
    cfg.StrOpt('console_xvp_conf_template',
               default=paths.basedir_def('nova/console/xvp.conf.template'),
               deprecated_group='DEFAULT',
               help='XVP conf template'),
    cfg.StrOpt('console_xvp_conf',
               default='/etc/xvp.conf',
               deprecated_group='DEFAULT',
               help='Generated XVP conf file'),
    cfg.StrOpt('console_xvp_pid',
               default='/var/run/xvp.pid',
               deprecated_group='DEFAULT',
               help='XVP master process pid file'),
    cfg.StrOpt('console_xvp_log',
               default='/var/log/xvp.log',
               deprecated_group='DEFAULT',
               help='XVP log file'),
    cfg.PortOpt('console_xvp_multiplex_port',
                default=5900,
                deprecated_group='DEFAULT',
                help='Port for XVP to multiplex VNC connections on'),
    ]


def register_opts(conf):
    conf.register_group(xvp_group)
    conf.register_opts(xvp_opts, group=xvp_group)


def list_opts():
    return {
        xvp_group: xvp_opts
    }
