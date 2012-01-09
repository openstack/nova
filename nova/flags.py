# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2011 Red Hat, Inc.
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

"""Command-line flag library.

Emulates gflags by wrapping cfg.ConfigOpts.

The idea is to move fully to cfg eventually, and this wrapper is a
stepping stone.

"""

import os
import socket
import sys

import gflags

from nova.common import cfg


class FlagValues(object):
    class Flag:
        def __init__(self, name, value, update_default=None):
            self.name = name
            self.value = value
            self._update_default = update_default

        def SetDefault(self, default):
            if self._update_default:
                self._update_default(self.name, default)

    class ErrorCatcher:
        def __init__(self, orig_error):
            self.orig_error = orig_error
            self.reset()

        def reset(self):
            self._error_msg = None

        def catch(self, msg):
            if ": --" in msg:
                self._error_msg = msg
            else:
                self.orig_error(msg)

        def get_unknown_arg(self, args):
            if not self._error_msg:
                return None
            # Error message is e.g. "no such option: --runtime_answer"
            a = self._error_msg[self._error_msg.rindex(": --") + 2:]
            return filter(lambda i: i == a or i.startswith(a + "="), args)[0]

    def __init__(self):
        self._conf = cfg.ConfigOpts()
        self._conf._oparser.disable_interspersed_args()
        self._opts = {}
        self.Reset()

    def _parse(self):
        if self._extra is not None:
            return

        args = gflags.FlagValues().ReadFlagsFromFiles(self._args)

        extra = None

        #
        # This horrendous hack allows us to stop optparse
        # exiting when it encounters an unknown option
        #
        error_catcher = self.ErrorCatcher(self._conf._oparser.error)
        self._conf._oparser.error = error_catcher.catch
        try:
            while True:
                error_catcher.reset()

                extra = self._conf(args)

                unknown = error_catcher.get_unknown_arg(args)
                if not unknown:
                    break

                args.remove(unknown)
        finally:
            self._conf._oparser.error = error_catcher.orig_error

        self._extra = extra

    def __call__(self, argv):
        self.Reset()
        self._args = argv[1:]
        self._parse()
        return [argv[0]] + self._extra

    def __getattr__(self, name):
        self._parse()
        return getattr(self._conf, name)

    def get(self, name, default):
        value = getattr(self, name)
        if value is not None:  # value might be '0' or ""
            return value
        else:
            return default

    def __contains__(self, name):
        self._parse()
        return hasattr(self._conf, name)

    def _update_default(self, name, default):
        self._conf.set_default(name, default)

    def __iter__(self):
        return self.FlagValuesDict().iterkeys()

    def __getitem__(self, name):
        self._parse()
        if not self.__contains__(name):
            return None
        return self.Flag(name, getattr(self, name), self._update_default)

    def Reset(self):
        self._conf.reset()
        self._args = []
        self._extra = None

    def ParseNewFlags(self):
        pass

    def FlagValuesDict(self):
        self._parse()
        ret = {}
        for opt in self._opts.values():
            ret[opt.dest] = getattr(self, opt.dest)
        return ret

    def _add_option(self, opt):
        if opt.dest in self._opts:
            return

        self._opts[opt.dest] = opt

        try:
            self._conf.register_cli_opts(self._opts.values())
        except cfg.ArgsAlreadyParsedError:
            self._conf.reset()
            self._conf.register_cli_opts(self._opts.values())
            self._extra = None

    def define_string(self, name, default, help):
        self._add_option(cfg.StrOpt(name, default=default, help=help))

    def define_integer(self, name, default, help):
        self._add_option(cfg.IntOpt(name, default=default, help=help))

    def define_float(self, name, default, help):
        self._add_option(cfg.FloatOpt(name, default=default, help=help))

    def define_bool(self, name, default, help):
        self._add_option(cfg.BoolOpt(name, default=default, help=help))

    def define_list(self, name, default, help):
        self._add_option(cfg.ListOpt(name, default=default, help=help))

    def define_multistring(self, name, default, help):
        self._add_option(cfg.MultiStrOpt(name, default=default, help=help))


FLAGS = FlagValues()


def DEFINE_string(name, default, help, flag_values=FLAGS):
    flag_values.define_string(name, default, help)


def DEFINE_integer(name, default, help, lower_bound=None, flag_values=FLAGS):
    # FIXME(markmc): ignoring lower_bound
    flag_values.define_integer(name, default, help)


def DEFINE_bool(name, default, help, flag_values=FLAGS):
    flag_values.define_bool(name, default, help)


def DEFINE_boolean(name, default, help, flag_values=FLAGS):
    DEFINE_bool(name, default, help, flag_values)


def DEFINE_list(name, default, help, flag_values=FLAGS):
    flag_values.define_list(name, default, help)


def DEFINE_float(name, default, help, flag_values=FLAGS):
    flag_values.define_float(name, default, help)


def DEFINE_multistring(name, default, help, flag_values=FLAGS):
    flag_values.define_multistring(name, default, help)


class UnrecognizedFlag(Exception):
    pass


def DECLARE(name, module_string, flag_values=FLAGS):
    if module_string not in sys.modules:
        __import__(module_string, globals(), locals())
    if name not in flag_values:
        raise UnrecognizedFlag('%s not defined by %s' % (name, module_string))


def DEFINE_flag(flag):
    pass


class HelpFlag:
    pass


class HelpshortFlag:
    pass


class HelpXMLFlag:
    pass


def _get_my_ip():
    """Returns the actual ip of the local machine."""
    try:
        csock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        csock.connect(('8.8.8.8', 80))
        (addr, port) = csock.getsockname()
        csock.close()
        return addr
    except socket.error as ex:
        return "127.0.0.1"


# __GLOBAL FLAGS ONLY__
# Define any app-specific flags in their own files, docs at:
# http://code.google.com/p/python-gflags/source/browse/trunk/gflags.py#a9
DEFINE_string('my_ip', _get_my_ip(), 'host ip address')
DEFINE_list('region_list',
            [],
            'list of region=fqdn pairs separated by commas')
DEFINE_string('connection_type', 'libvirt', 'libvirt, xenapi or fake')
DEFINE_string('aws_access_key_id', 'admin', 'AWS Access ID')
DEFINE_string('aws_secret_access_key', 'admin', 'AWS Access Key')
# NOTE(sirp): my_ip interpolation doesn't work within nested structures
DEFINE_string('glance_host', _get_my_ip(), 'default glance host')
DEFINE_integer('glance_port', 9292, 'default glance port')
DEFINE_list('glance_api_servers',
            ['%s:%d' % (FLAGS.glance_host, FLAGS.glance_port)],
            'list of glance api servers available to nova (host:port)')
DEFINE_integer('glance_num_retries', 0,
               'The number of times to retry downloading an image from glance')
DEFINE_integer('s3_port', 3333, 's3 port')
DEFINE_string('s3_host', '$my_ip', 's3 host (for infrastructure)')
DEFINE_string('s3_dmz', '$my_ip', 's3 dmz ip (for instances)')
DEFINE_string('compute_topic', 'compute', 'the topic compute nodes listen on')
DEFINE_string('console_topic', 'console',
              'the topic console proxy nodes listen on')
DEFINE_string('scheduler_topic', 'scheduler',
              'the topic scheduler nodes listen on')
DEFINE_string('volume_topic', 'volume', 'the topic volume nodes listen on')
DEFINE_string('network_topic', 'network', 'the topic network nodes listen on')
DEFINE_string('ajax_console_proxy_topic', 'ajax_proxy',
              'the topic ajax proxy nodes listen on')
DEFINE_string('ajax_console_proxy_url',
              'http://127.0.0.1:8000',
              'location of ajax console proxy, \
               in the form "http://127.0.0.1:8000"')
DEFINE_integer('ajax_console_proxy_port',
               8000, 'port that ajax_console_proxy binds')
DEFINE_string('vsa_topic', 'vsa', 'the topic that nova-vsa service listens on')
DEFINE_bool('verbose', False, 'show debug output')
DEFINE_boolean('fake_rabbit', False, 'use a fake rabbit')
DEFINE_bool('fake_network', False,
            'should we use fake network devices and addresses')
DEFINE_string('rabbit_host', 'localhost', 'rabbit host')
DEFINE_integer('rabbit_port', 5672, 'rabbit port')
DEFINE_bool('rabbit_use_ssl', False, 'connect over SSL')
DEFINE_string('rabbit_userid', 'guest', 'rabbit userid')
DEFINE_string('rabbit_password', 'guest', 'rabbit password')
DEFINE_string('rabbit_virtual_host', '/', 'rabbit virtual host')
DEFINE_integer('rabbit_retry_interval', 1,
        'rabbit connection retry interval to start')
DEFINE_integer('rabbit_retry_backoff', 2,
        'rabbit connection retry backoff in seconds')
DEFINE_integer('rabbit_max_retries', 0,
        'maximum rabbit connection attempts (0=try forever)')
DEFINE_string('control_exchange', 'nova', 'the main exchange to connect to')
DEFINE_boolean('rabbit_durable_queues', False, 'use durable queues')
DEFINE_list('enabled_apis',
            ['ec2', 'osapi_compute', 'osapi_volume', 'metadata'],
            'list of APIs to enable by default')
DEFINE_string('ec2_host', '$my_ip', 'ip of api server')
DEFINE_string('ec2_dmz_host', '$my_ip', 'internal ip of api server')
DEFINE_integer('ec2_port', 8773, 'cloud controller port')
DEFINE_string('ec2_scheme', 'http', 'prefix for ec2')
DEFINE_string('ec2_path', '/services/Cloud', 'suffix for ec2')
DEFINE_multistring('osapi_compute_extension',
                   ['nova.api.openstack.compute.contrib.standard_extensions'],
                   'osapi compute extension to load')
DEFINE_multistring('osapi_volume_extension',
                   ['nova.api.openstack.volume.contrib.standard_extensions'],
                   'osapi volume extension to load')
DEFINE_string('osapi_scheme', 'http', 'prefix for openstack')
DEFINE_string('osapi_path', '/v1.1/', 'suffix for openstack')
DEFINE_integer('osapi_max_limit', 1000,
               'max number of items returned in a collection response')
DEFINE_string('metadata_host', '$my_ip', 'ip of metadata server')
DEFINE_integer('metadata_port', 8775, 'Metadata API port')
DEFINE_string('default_project', 'openstack', 'default project for openstack')
DEFINE_string('default_image', 'ami-11111',
              'default image to use, testing only')
DEFINE_string('default_instance_type', 'm1.small',
              'default instance type to use, testing only')
DEFINE_string('null_kernel', 'nokernel',
              'kernel image that indicates not to use a kernel,'
              ' but to use a raw disk image instead')

DEFINE_string('vpn_image_id', '0', 'image id for cloudpipe vpn server')
DEFINE_string('vpn_key_suffix',
              '-vpn',
              'Suffix to add to project name for vpn key and secgroups')

DEFINE_integer('auth_token_ttl', 3600, 'Seconds for auth tokens to linger')

DEFINE_string('state_path', os.path.join(os.path.dirname(__file__), '../'),
              "Top-level directory for maintaining nova's state")
DEFINE_string('lock_path', os.path.join(os.path.dirname(__file__), '../'),
              'Directory for lock files')
DEFINE_string('logdir', None, 'output to a per-service log file in named '
                              'directory')
DEFINE_string('logfile_mode', '0644', 'Default file mode of the logs.')
DEFINE_string('sqlite_db', 'nova.sqlite', 'file name for sqlite')
DEFINE_bool('sqlite_synchronous', True, 'Synchronous mode for sqlite')
DEFINE_string('sql_connection',
              'sqlite:///$state_path/$sqlite_db',
              'connection string for sql database')
DEFINE_integer('sql_idle_timeout',
              3600,
              'timeout for idle sql database connections')
DEFINE_integer('sql_max_retries', 12, 'sql connection attempts')
DEFINE_integer('sql_retry_interval', 10, 'sql connection retry interval')

DEFINE_string('compute_manager', 'nova.compute.manager.ComputeManager',
              'Manager for compute')
DEFINE_string('console_manager', 'nova.console.manager.ConsoleProxyManager',
              'Manager for console proxy')
DEFINE_string('instance_dns_manager',
              'nova.network.dns_driver.DNSDriver',
              'DNS Manager for instance IPs')
DEFINE_string('instance_dns_zone', '',
              'DNS Zone for instance IPs')
DEFINE_string('floating_ip_dns_manager',
              'nova.network.dns_driver.DNSDriver',
              'DNS Manager for floating IPs')
DEFINE_multistring('floating_ip_dns_zones', '',
                   'DNS zones for floating IPs.'
                   'e.g. "example.org"')
DEFINE_string('network_manager', 'nova.network.manager.VlanManager',
              'Manager for network')
DEFINE_string('volume_manager', 'nova.volume.manager.VolumeManager',
              'Manager for volume')
DEFINE_string('scheduler_manager', 'nova.scheduler.manager.SchedulerManager',
              'Manager for scheduler')
DEFINE_string('vsa_manager', 'nova.vsa.manager.VsaManager',
              'Manager for vsa')
DEFINE_string('vc_image_name', 'vc_image',
              'the VC image ID (for a VC image that exists in DB Glance)')
# VSA constants and enums
DEFINE_string('default_vsa_instance_type', 'm1.small',
              'default instance type for VSA instances')
DEFINE_integer('max_vcs_in_vsa', 32,
               'maxinum VCs in a VSA')
DEFINE_integer('vsa_part_size_gb', 100,
               'default partition size for shared capacity')
# Default firewall driver for security groups and provider firewall
DEFINE_string('firewall_driver',
              'nova.virt.libvirt.firewall.IptablesFirewallDriver',
              'Firewall driver (defaults to iptables)')
# The service to use for image search and retrieval
DEFINE_string('image_service', 'nova.image.glance.GlanceImageService',
              'The service to use for retrieving and searching for images.')

DEFINE_string('host', socket.gethostname(),
              'Name of this node.  This can be an opaque identifier.  It is '
              'not necessarily a hostname, FQDN, or IP address.')

DEFINE_string('node_availability_zone', 'nova',
              'availability zone of this node')

DEFINE_string('notification_driver',
              'nova.notifier.no_op_notifier',
              'Default driver for sending notifications')
DEFINE_list('memcached_servers', None,
            'Memcached servers or None for in process cache.')

DEFINE_string('zone_name', 'nova', 'name of this zone')
DEFINE_list('zone_capabilities',
                ['hypervisor=xenserver;kvm', 'os=linux;windows'],
                 'Key/Multi-value list representng capabilities of this zone')
DEFINE_string('build_plan_encryption_key', None,
        '128bit (hex) encryption key for scheduler build plans.')
DEFINE_string('instance_usage_audit_period', 'month',
              'time period to generate instance usages for.')
DEFINE_integer('bandwith_poll_interval', 600,
               'interval to pull bandwidth usage info')

DEFINE_bool('start_guests_on_host_boot', False,
            'Whether to restart guests when the host reboots')
DEFINE_bool('resume_guests_state_on_host_boot', False,
            'Whether to start guests, that was running before the host reboot')

DEFINE_string('root_helper', 'sudo',
              'Command prefix to use for running commands as root')

DEFINE_string('network_driver', 'nova.network.linux_net',
              'Driver to use for network creation')

DEFINE_bool('use_ipv6', False, 'use ipv6')

DEFINE_integer('password_length', 12,
                    'Length of generated instance admin passwords')

DEFINE_bool('monkey_patch', False,
              'Whether to log monkey patching')

DEFINE_list('monkey_patch_modules',
        ['nova.api.ec2.cloud:nova.notifier.api.notify_decorator',
        'nova.compute.api:nova.notifier.api.notify_decorator'],
        'Module list representing monkey '
        'patched module and decorator')

DEFINE_bool('allow_resize_to_same_host', False,
            'Allow destination machine to match source for resize. Useful'
            ' when testing in environments with only one host machine.')

DEFINE_string('stub_network', False,
              'Stub network related code')

DEFINE_integer('reclaim_instance_interval', 0,
               'Interval in seconds for reclaiming deleted instances')

DEFINE_integer('zombie_instance_updated_at_window', 172800,
               'Limit in seconds that a zombie instance can exist before '
               'being cleaned up.')

DEFINE_boolean('allow_ec2_admin_api', False, 'Enable/Disable EC2 Admin API')
