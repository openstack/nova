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

from oslo_config import cfg

DEFAULT_PORT_RANGE = '10000:20000'

enabled_opt = cfg.BoolOpt('enabled',
                          default=False,
                          help='Enable serial console related features')

port_range_opt = cfg.StrOpt('port_range',
                            default=DEFAULT_PORT_RANGE,
                            help='Range of TCP ports to use for serial ports '
                                 'on compute hosts')

base_url_opt = cfg.StrOpt('base_url',
                          default='ws://127.0.0.1:6083/',
                          help='Location of serial console proxy.')

listen_opt = cfg.StrOpt('listen',
                        default='127.0.0.1',
                        deprecated_for_removal=True,
                        help='IP address on which instance serial console '
                             'should listen')

proxyclient_address_opt = cfg.StrOpt('proxyclient_address',
                                     default='127.0.0.1',
                                     help='The address to which proxy clients '
                                          '(like nova-serialproxy) should '
                                          'connect')

serialproxy_host_opt = cfg.StrOpt('serialproxy_host',
                                  default='0.0.0.0',
                                  help='Host on which to listen for incoming '
                                       'requests')

serialproxy_port_opt = cfg.IntOpt('serialproxy_port',
                                  default=6083,
                                  min=1,
                                  max=65535,
                                  help='Port on which to listen for incoming '
                                       'requests')

ALL_OPTS = [enabled_opt,
            port_range_opt,
            base_url_opt,
            listen_opt,
            proxyclient_address_opt,
            serialproxy_host_opt,
            serialproxy_port_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group="serial_console")


def register_cli_opts(conf):
    conf.register_cli_opt(serialproxy_host_opt, "serial_console")
    conf.register_cli_opt(serialproxy_port_opt, "serial_console")


def list_opts():
    return ("serial_console", ALL_OPTS)
