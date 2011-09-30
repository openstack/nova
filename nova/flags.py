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

"""Command-line flag library.

Wraps gflags.

Package-level global flags are defined here, the rest are defined
where they're used.

"""

import getopt
import os
import socket
import string
import sys

import gflags


class FlagValues(gflags.FlagValues):
    """Extension of gflags.FlagValues that allows undefined and runtime flags.

    Unknown flags will be ignored when parsing the command line, but the
    command line will be kept so that it can be replayed if new flags are
    defined after the initial parsing.

    """

    def __init__(self, extra_context=None):
        gflags.FlagValues.__init__(self)
        self.__dict__['__dirty'] = []
        self.__dict__['__was_already_parsed'] = False
        self.__dict__['__stored_argv'] = []
        self.__dict__['__extra_context'] = extra_context

    def __call__(self, argv):
        # We're doing some hacky stuff here so that we don't have to copy
        # out all the code of the original verbatim and then tweak a few lines.
        # We're hijacking the output of getopt so we can still return the
        # leftover args at the end
        sneaky_unparsed_args = {"value": None}
        original_argv = list(argv)

        if self.IsGnuGetOpt():
            orig_getopt = getattr(getopt, 'gnu_getopt')
            orig_name = 'gnu_getopt'
        else:
            orig_getopt = getattr(getopt, 'getopt')
            orig_name = 'getopt'

        def _sneaky(*args, **kw):
            optlist, unparsed_args = orig_getopt(*args, **kw)
            sneaky_unparsed_args['value'] = unparsed_args
            return optlist, unparsed_args

        try:
            setattr(getopt, orig_name, _sneaky)
            args = gflags.FlagValues.__call__(self, argv)
        except gflags.UnrecognizedFlagError:
            # Undefined args were found, for now we don't care so just
            # act like everything went well
            # (these three lines are copied pretty much verbatim from the end
            # of the __call__ function we are wrapping)
            unparsed_args = sneaky_unparsed_args['value']
            if unparsed_args:
                if self.IsGnuGetOpt():
                    args = argv[:1] + unparsed_args
                else:
                    args = argv[:1] + original_argv[-len(unparsed_args):]
            else:
                args = argv[:1]
        finally:
            setattr(getopt, orig_name, orig_getopt)

        # Store the arguments for later, we'll need them for new flags
        # added at runtime
        self.__dict__['__stored_argv'] = original_argv
        self.__dict__['__was_already_parsed'] = True
        self.ClearDirty()
        return args

    def Reset(self):
        gflags.FlagValues.Reset(self)
        self.__dict__['__dirty'] = []
        self.__dict__['__was_already_parsed'] = False
        self.__dict__['__stored_argv'] = []

    def SetDirty(self, name):
        """Mark a flag as dirty so that accessing it will case a reparse."""
        self.__dict__['__dirty'].append(name)

    def IsDirty(self, name):
        return name in self.__dict__['__dirty']

    def ClearDirty(self):
        self.__dict__['__dirty'] = []

    def WasAlreadyParsed(self):
        return self.__dict__['__was_already_parsed']

    def ParseNewFlags(self):
        if '__stored_argv' not in self.__dict__:
            return
        new_flags = FlagValues(self)
        for k in self.FlagDict().iterkeys():
            new_flags[k] = gflags.FlagValues.__getitem__(self, k)

        new_flags.Reset()
        new_flags(self.__dict__['__stored_argv'])
        for k in new_flags.FlagDict().iterkeys():
            setattr(self, k, getattr(new_flags, k))
        self.ClearDirty()

    def __setitem__(self, name, flag):
        gflags.FlagValues.__setitem__(self, name, flag)
        if self.WasAlreadyParsed():
            self.SetDirty(name)

    def __getitem__(self, name):
        if self.IsDirty(name):
            self.ParseNewFlags()
        return gflags.FlagValues.__getitem__(self, name)

    def __getattr__(self, name):
        if self.IsDirty(name):
            self.ParseNewFlags()
        val = gflags.FlagValues.__getattr__(self, name)
        if type(val) is str:
            tmpl = string.Template(val)
            context = [self, self.__dict__['__extra_context']]
            return tmpl.substitute(StrWrapper(context))
        return val


class StrWrapper(object):
    """Wrapper around FlagValues objects.

    Wraps FlagValues objects for string.Template so that we're
    sure to return strings.

    """
    def __init__(self, context_objs):
        self.context_objs = context_objs

    def __getitem__(self, name):
        for context in self.context_objs:
            val = getattr(context, name, False)
            if val:
                return str(val)
        raise KeyError(name)


# Copied from gflags with small mods to get the naming correct.
# Originally gflags checks for the first module that is not gflags that is
# in the call chain, we want to check for the first module that is not gflags
# and not this module.
def _GetCallingModule():
    """Returns the name of the module that's calling into this module.

    We generally use this function to get the name of the module calling a
    DEFINE_foo... function.

    """
    # Walk down the stack to find the first globals dict that's not ours.
    for depth in range(1, sys.getrecursionlimit()):
        if not sys._getframe(depth).f_globals is globals():
            module_name = __GetModuleName(sys._getframe(depth).f_globals)
            if module_name == 'gflags':
                continue
            if module_name is not None:
                return module_name
    raise AssertionError("No module was found")


# Copied from gflags because it is a private function
def __GetModuleName(globals_dict):
    """Given a globals dict, returns the name of the module that defines it.

    Args:
    globals_dict: A dictionary that should correspond to an environment
      providing the values of the globals.

    Returns:
    A string (the name of the module) or None (if the module could not
    be identified.

    """
    for name, module in sys.modules.iteritems():
        if getattr(module, '__dict__', None) is globals_dict:
            if name == '__main__':
                return sys.argv[0]
            return name
    return None


def _wrapper(func):
    def _wrapped(*args, **kw):
        kw.setdefault('flag_values', FLAGS)
        func(*args, **kw)
    _wrapped.func_name = func.func_name
    return _wrapped


FLAGS = FlagValues()
gflags.FLAGS = FLAGS
gflags._GetCallingModule = _GetCallingModule


DEFINE = _wrapper(gflags.DEFINE)
DEFINE_string = _wrapper(gflags.DEFINE_string)
DEFINE_integer = _wrapper(gflags.DEFINE_integer)
DEFINE_bool = _wrapper(gflags.DEFINE_bool)
DEFINE_boolean = _wrapper(gflags.DEFINE_boolean)
DEFINE_float = _wrapper(gflags.DEFINE_float)
DEFINE_enum = _wrapper(gflags.DEFINE_enum)
DEFINE_list = _wrapper(gflags.DEFINE_list)
DEFINE_spaceseplist = _wrapper(gflags.DEFINE_spaceseplist)
DEFINE_multistring = _wrapper(gflags.DEFINE_multistring)
DEFINE_multi_int = _wrapper(gflags.DEFINE_multi_int)
DEFINE_flag = _wrapper(gflags.DEFINE_flag)
HelpFlag = gflags.HelpFlag
HelpshortFlag = gflags.HelpshortFlag
HelpXMLFlag = gflags.HelpXMLFlag


def DECLARE(name, module_string, flag_values=FLAGS):
    if module_string not in sys.modules:
        __import__(module_string, globals(), locals())
    if name not in flag_values:
        raise gflags.UnrecognizedFlag(
                "%s not defined by %s" % (name, module_string))


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
DEFINE_list('glance_api_servers',
            ['%s:9292' % _get_my_ip()],
            'list of glance api servers available to nova (host:port)')
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
DEFINE_string('ajax_console_proxy_port',
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
DEFINE_list('enabled_apis', ['ec2', 'osapi'],
            'list of APIs to enable by default')
DEFINE_string('ec2_host', '$my_ip', 'ip of api server')
DEFINE_string('ec2_dmz_host', '$my_ip', 'internal ip of api server')
DEFINE_integer('ec2_port', 8773, 'cloud controller port')
DEFINE_string('ec2_scheme', 'http', 'prefix for ec2')
DEFINE_string('ec2_path', '/services/Cloud', 'suffix for ec2')
DEFINE_string('osapi_extensions_path', '/var/lib/nova/extensions',
               'default directory for nova extensions')
DEFINE_string('osapi_host', '$my_ip', 'ip of api server')
DEFINE_string('osapi_scheme', 'http', 'prefix for openstack')
DEFINE_integer('osapi_port', 8774, 'OpenStack API port')
DEFINE_string('osapi_path', '/v1.1/', 'suffix for openstack')
DEFINE_integer('osapi_max_limit', 1000,
               'max number of items returned in a collection response')

DEFINE_string('default_project', 'openstack', 'default project for openstack')
DEFINE_string('default_image', 'ami-11111',
              'default image to use, testing only')
DEFINE_string('default_instance_type', 'm1.small',
              'default instance type to use, testing only')
DEFINE_string('null_kernel', 'nokernel',
              'kernel image that indicates not to use a kernel,'
              ' but to use a raw disk image instead')

DEFINE_integer('vpn_image_id', 0, 'integer id for cloudpipe vpn server')
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

# The service to use for image search and retrieval
DEFINE_string('image_service', 'nova.image.glance.GlanceImageService',
              'The service to use for retrieving and searching for images.')

DEFINE_string('host', socket.gethostname(),
              'name of this node')

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

DEFINE_bool('start_guests_on_host_boot', False,
            'Whether to restart guests when the host reboots')
DEFINE_bool('resume_guests_state_on_host_boot', False,
            'Whether to start guests, that was running before the host reboot')

DEFINE_string('root_helper', 'sudo',
              'Command prefix to use for running commands as root')

DEFINE_bool('use_ipv6', False, 'use ipv6')

DEFINE_bool('monkey_patch', False,
              'Whether to log monkey patching')

DEFINE_list('monkey_patch_modules',
        ['nova.api.ec2.cloud:nova.notifier.api.notify_decorator',
        'nova.compute.api:nova.notifier.api.notify_decorator'],
        'Module list representing monkey '
        'patched module and decorator')
