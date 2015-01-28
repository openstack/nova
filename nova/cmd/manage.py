# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

# Interactive shell based on Django:
#
# Copyright (c) 2005, the Lawrence Journal-World
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#
#     3. Neither the name of Django nor the names of its contributors may be
#        used to endorse or promote products derived from this software without
#        specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""
  CLI interface for nova management.
"""

from __future__ import print_function

import argparse
import os
import sys

import decorator
import netaddr
from oslo_config import cfg
import oslo_messaging as messaging
from oslo_utils import importutils
import six

from nova.api.ec2 import ec2utils
from nova import availability_zones
from nova import config
from nova import context
from nova import db
from nova.db import migration
from nova import exception
from nova.i18n import _
from nova import objects
from nova.openstack.common import cliutils
from nova.openstack.common import log as logging
from nova import quota
from nova import rpc
from nova import servicegroup
from nova import utils
from nova import version

CONF = cfg.CONF
CONF.import_opt('network_manager', 'nova.service')
CONF.import_opt('service_down_time', 'nova.service')
CONF.import_opt('flat_network_bridge', 'nova.network.manager')
CONF.import_opt('num_networks', 'nova.network.manager')
CONF.import_opt('multi_host', 'nova.network.manager')
CONF.import_opt('network_size', 'nova.network.manager')
CONF.import_opt('vlan_start', 'nova.network.manager')
CONF.import_opt('vpn_start', 'nova.network.manager')
CONF.import_opt('default_floating_pool', 'nova.network.floating_ips')
CONF.import_opt('public_interface', 'nova.network.linux_net')

QUOTAS = quota.QUOTAS


# Decorators for actions
def args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


def param2id(object_id):
    """Helper function to convert various volume id types to internal id.
    args: [object_id], e.g. 'vol-0000000a' or 'volume-0000000a' or '10'
    """
    if '-' in object_id:
        return ec2utils.ec2_vol_id_to_uuid(object_id)
    else:
        return object_id


class VpnCommands(object):
    """Class for managing VPNs."""

    @args('--project', dest='project_id', metavar='<Project name>',
            help='Project name')
    @args('--ip', metavar='<IP Address>', help='IP Address')
    @args('--port', metavar='<Port>', help='Port')
    def change(self, project_id, ip, port):
        """Change the ip and port for a vpn.

        this will update all networks associated with a project
        not sure if that's the desired behavior or not, patches accepted

        """
        # TODO(tr3buchet): perhaps this shouldn't update all networks
        # associated with a project in the future
        admin_context = context.get_admin_context()
        networks = db.project_get_networks(admin_context, project_id)
        for network in networks:
            db.network_update(admin_context,
                              network['id'],
                              {'vpn_public_address': ip,
                               'vpn_public_port': int(port)})


class ShellCommands(object):
    def bpython(self):
        """Runs a bpython shell.

        Falls back to Ipython/python shell if unavailable
        """
        self.run('bpython')

    def ipython(self):
        """Runs an Ipython shell.

        Falls back to Python shell if unavailable
        """
        self.run('ipython')

    def python(self):
        """Runs a python shell.

        Falls back to Python shell if unavailable
        """
        self.run('python')

    @args('--shell', metavar='<bpython|ipython|python >',
            help='Python shell')
    def run(self, shell=None):
        """Runs a Python interactive interpreter."""
        if not shell:
            shell = 'bpython'

        if shell == 'bpython':
            try:
                import bpython
                bpython.embed()
            except ImportError:
                shell = 'ipython'
        if shell == 'ipython':
            try:
                from IPython import embed
                embed()
            except ImportError:
                try:
                    # Ipython < 0.11
                    # Explicitly pass an empty list as arguments, because
                    # otherwise IPython would use sys.argv from this script.
                    import IPython

                    shell = IPython.Shell.IPShell(argv=[])
                    shell.mainloop()
                except ImportError:
                    # no IPython module
                    shell = 'python'

        if shell == 'python':
            import code
            try:
                # Try activating rlcompleter, because it's handy.
                import readline
            except ImportError:
                pass
            else:
                # We don't have to wrap the following import in a 'try',
                # because we already know 'readline' was imported successfully.
                readline.parse_and_bind("tab:complete")
            code.interact()

    @args('--path', metavar='<path>', help='Script path')
    def script(self, path):
        """Runs the script from the specified path with flags set properly.

        arguments: path
        """
        exec(compile(open(path).read(), path, 'exec'), locals(), globals())


def _db_error(caught_exception):
    print(caught_exception)
    print(_("The above error may show that the database has not "
            "been created.\nPlease create a database using "
            "'nova-manage db sync' before running this command."))
    exit(1)


class ProjectCommands(object):
    """Class for managing projects."""

    @args('--project', dest='project_id', metavar='<Project name>',
            help='Project name')
    @args('--user', dest='user_id', metavar='<User name>',
            help='User name')
    @args('--key', metavar='<key>', help='Key')
    @args('--value', metavar='<value>', help='Value')
    def quota(self, project_id, user_id=None, key=None, value=None):
        """Create, update or display quotas for project/user

        If no quota key is provided, the quota will be displayed.
        If a valid quota key is provided and it does not exist,
        it will be created. Otherwise, it will be updated.
        """

        ctxt = context.get_admin_context()
        if user_id:
            quota = QUOTAS.get_user_quotas(ctxt, project_id, user_id)
        else:
            user_id = None
            quota = QUOTAS.get_project_quotas(ctxt, project_id)
        # if key is None, that means we need to show the quotas instead
        # of updating them
        if key:
            settable_quotas = QUOTAS.get_settable_quotas(ctxt,
                                                         project_id,
                                                         user_id=user_id)
            if key in quota:
                minimum = settable_quotas[key]['minimum']
                maximum = settable_quotas[key]['maximum']
                if value.lower() == 'unlimited':
                    value = -1
                if int(value) < -1:
                    print(_('Quota limit must be -1 or greater.'))
                    return(2)
                if ((int(value) < minimum) and
                   (maximum != -1 or (maximum == -1 and int(value) != -1))):
                    print(_('Quota limit must be greater than %s.') % minimum)
                    return(2)
                if maximum != -1 and int(value) > maximum:
                    print(_('Quota limit must be less than %s.') % maximum)
                    return(2)
                try:
                    db.quota_create(ctxt, project_id, key, value,
                                    user_id=user_id)
                except exception.QuotaExists:
                    db.quota_update(ctxt, project_id, key, value,
                                    user_id=user_id)
            else:
                print(_('%(key)s is not a valid quota key. Valid options are: '
                        '%(options)s.') % {'key': key,
                                           'options': ', '.join(quota)})
                return(2)
        print_format = "%-36s %-10s %-10s %-10s"
        print(print_format % (
                    _('Quota'),
                    _('Limit'),
                    _('In Use'),
                    _('Reserved')))
        # Retrieve the quota after update
        if user_id:
            quota = QUOTAS.get_user_quotas(ctxt, project_id, user_id)
        else:
            quota = QUOTAS.get_project_quotas(ctxt, project_id)
        for key, value in quota.iteritems():
            if value['limit'] < 0 or value['limit'] is None:
                value['limit'] = 'unlimited'
            print(print_format % (key, value['limit'], value['in_use'],
                                  value['reserved']))

    @args('--project', dest='project_id', metavar='<Project name>',
            help='Project name')
    def scrub(self, project_id):
        """Deletes data associated with project."""
        admin_context = context.get_admin_context()
        networks = db.project_get_networks(admin_context, project_id)
        for network in networks:
            db.network_disassociate(admin_context, network['id'])
        groups = db.security_group_get_by_project(admin_context, project_id)
        for group in groups:
            db.security_group_destroy(admin_context, group['id'])


AccountCommands = ProjectCommands


class FixedIpCommands(object):
    """Class for managing fixed ip."""

    @args('--host', metavar='<host>', help='Host')
    def list(self, host=None):
        """Lists all fixed ips (optionally by host)."""
        ctxt = context.get_admin_context()

        try:
            if host is None:
                fixed_ips = db.fixed_ip_get_all(ctxt)
            else:
                fixed_ips = db.fixed_ip_get_by_host(ctxt, host)

        except exception.NotFound as ex:
            print(_("error: %s") % ex)
            return(2)

        instances = db.instance_get_all(context.get_admin_context())
        instances_by_uuid = {}
        for instance in instances:
            instances_by_uuid[instance['uuid']] = instance

        print("%-18s\t%-15s\t%-15s\t%s" % (_('network'),
                                              _('IP address'),
                                              _('hostname'),
                                              _('host')))

        all_networks = {}
        try:
            # use network_get_all to retrieve all existing networks
            # this is to ensure that IPs associated with deleted networks
            # will not throw exceptions.
            for network in db.network_get_all(context.get_admin_context()):
                all_networks[network.id] = network
        except exception.NoNetworksFound:
            # do not have any networks, so even if there are IPs, these
            # IPs should have been deleted ones, so return.
            print(_('No fixed IP found.'))
            return

        has_ip = False
        for fixed_ip in fixed_ips:
            hostname = None
            host = None
            network = all_networks.get(fixed_ip['network_id'])
            if network:
                has_ip = True
                if fixed_ip.get('instance_uuid'):
                    instance = instances_by_uuid.get(fixed_ip['instance_uuid'])
                    if instance:
                        hostname = instance['hostname']
                        host = instance['host']
                    else:
                        print(_('WARNING: fixed ip %s allocated to missing'
                                ' instance') % str(fixed_ip['address']))
                print("%-18s\t%-15s\t%-15s\t%s" % (
                        network['cidr'],
                        fixed_ip['address'],
                        hostname, host))

        if not has_ip:
            print(_('No fixed IP found.'))

    @args('--address', metavar='<ip address>', help='IP address')
    def reserve(self, address):
        """Mark fixed ip as reserved

        arguments: address
        """
        return self._set_reserved(address, True)

    @args('--address', metavar='<ip address>', help='IP address')
    def unreserve(self, address):
        """Mark fixed ip as free to use

        arguments: address
        """
        return self._set_reserved(address, False)

    def _set_reserved(self, address, reserved):
        ctxt = context.get_admin_context()

        try:
            fixed_ip = db.fixed_ip_get_by_address(ctxt, address)
            if fixed_ip is None:
                raise exception.NotFound('Could not find address')
            db.fixed_ip_update(ctxt, fixed_ip['address'],
                                {'reserved': reserved})
        except exception.NotFound as ex:
            print(_("error: %s") % ex)
            return(2)


class FloatingIpCommands(object):
    """Class for managing floating ip."""

    @staticmethod
    def address_to_hosts(addresses):
        """Iterate over hosts within an address range.

        If an explicit range specifier is missing, the parameter is
        interpreted as a specific individual address.
        """
        try:
            return [netaddr.IPAddress(addresses)]
        except ValueError:
            net = netaddr.IPNetwork(addresses)
            if net.size < 4:
                reason = _("/%s should be specified as single address(es) "
                           "not in cidr format") % net.prefixlen
                raise exception.InvalidInput(reason=reason)
            elif net.size >= 1000000:
                # NOTE(dripton): If we generate a million IPs and put them in
                # the database, the system will slow to a crawl and/or run
                # out of memory and crash.  This is clearly a misconfiguration.
                reason = _("Too many IP addresses will be generated.  Please "
                           "increase /%s to reduce the number generated."
                          ) % net.prefixlen
                raise exception.InvalidInput(reason=reason)
            else:
                return net.iter_hosts()

    @args('--ip_range', metavar='<range>', help='IP range')
    @args('--pool', metavar='<pool>', help='Optional pool')
    @args('--interface', metavar='<interface>', help='Optional interface')
    def create(self, ip_range, pool=None, interface=None):
        """Creates floating ips for zone by range."""
        admin_context = context.get_admin_context()
        if not pool:
            pool = CONF.default_floating_pool
        if not interface:
            interface = CONF.public_interface

        ips = [{'address': str(address), 'pool': pool, 'interface': interface}
               for address in self.address_to_hosts(ip_range)]
        try:
            db.floating_ip_bulk_create(admin_context, ips, want_result=False)
        except exception.FloatingIpExists as exc:
            # NOTE(simplylizz): Maybe logging would be better here
            # instead of printing, but logging isn't used here and I
            # don't know why.
            print('error: %s' % exc)
            return(1)

    @args('--ip_range', metavar='<range>', help='IP range')
    def delete(self, ip_range):
        """Deletes floating ips by range."""
        admin_context = context.get_admin_context()

        ips = ({'address': str(address)}
               for address in self.address_to_hosts(ip_range))
        db.floating_ip_bulk_destroy(admin_context, ips)

    @args('--host', metavar='<host>', help='Host')
    def list(self, host=None):
        """Lists all floating ips (optionally by host).

        Note: if host is given, only active floating IPs are returned
        """
        ctxt = context.get_admin_context()
        try:
            if host is None:
                floating_ips = db.floating_ip_get_all(ctxt)
            else:
                floating_ips = db.floating_ip_get_all_by_host(ctxt, host)
        except exception.NoFloatingIpsDefined:
            print(_("No floating IP addresses have been defined."))
            return
        for floating_ip in floating_ips:
            instance_uuid = None
            if floating_ip['fixed_ip_id']:
                fixed_ip = db.fixed_ip_get(ctxt, floating_ip['fixed_ip_id'])
                instance_uuid = fixed_ip['instance_uuid']

            print("%s\t%s\t%s\t%s\t%s" % (floating_ip['project_id'],
                                          floating_ip['address'],
                                          instance_uuid,
                                          floating_ip['pool'],
                                          floating_ip['interface']))


@decorator.decorator
def validate_network_plugin(f, *args, **kwargs):
    """Decorator to validate the network plugin."""
    if utils.is_neutron():
        print(_("ERROR: Network commands are not supported when using the "
                "Neutron API.  Use python-neutronclient instead."))
        return(2)
    return f(*args, **kwargs)


class NetworkCommands(object):
    """Class for managing networks."""

    @validate_network_plugin
    @args('--label', metavar='<label>', help='Label for network (ex: public)')
    @args('--fixed_range_v4', dest='cidr', metavar='<x.x.x.x/yy>',
            help='IPv4 subnet (ex: 10.0.0.0/8)')
    @args('--num_networks', metavar='<number>',
            help='Number of networks to create')
    @args('--network_size', metavar='<number>',
            help='Number of IPs per network')
    @args('--vlan', metavar='<vlan id>', help='vlan id')
    @args('--vlan_start', dest='vlan_start', metavar='<vlan start id>',
          help='vlan start id')
    @args('--vpn', dest='vpn_start', help='vpn start')
    @args('--fixed_range_v6', dest='cidr_v6',
          help='IPv6 subnet (ex: fe80::/64')
    @args('--gateway', help='gateway')
    @args('--gateway_v6', help='ipv6 gateway')
    @args('--bridge', metavar='<bridge>',
            help='VIFs on this network are connected to this bridge')
    @args('--bridge_interface', metavar='<bridge interface>',
            help='the bridge is connected to this interface')
    @args('--multi_host', metavar="<'T'|'F'>",
            help='Multi host')
    @args('--dns1', metavar="<DNS Address>", help='First DNS')
    @args('--dns2', metavar="<DNS Address>", help='Second DNS')
    @args('--uuid', metavar="<network uuid>", help='Network UUID')
    @args('--fixed_cidr', metavar='<x.x.x.x/yy>',
            help='IPv4 subnet for fixed IPS (ex: 10.20.0.0/16)')
    @args('--project_id', metavar="<project id>",
          help='Project id')
    @args('--priority', metavar="<number>", help='Network interface priority')
    def create(self, label=None, cidr=None, num_networks=None,
               network_size=None, multi_host=None, vlan=None,
               vlan_start=None, vpn_start=None, cidr_v6=None, gateway=None,
               gateway_v6=None, bridge=None, bridge_interface=None,
               dns1=None, dns2=None, project_id=None, priority=None,
               uuid=None, fixed_cidr=None):
        """Creates fixed ips for host by range."""
        kwargs = {k: v for k, v in locals().iteritems()
                  if v and k != "self"}
        if multi_host is not None:
            kwargs['multi_host'] = multi_host == 'T'
        net_manager = importutils.import_object(CONF.network_manager)
        net_manager.create_networks(context.get_admin_context(), **kwargs)

    @validate_network_plugin
    def list(self):
        """List all created networks."""
        _fmt = "%-5s\t%-18s\t%-15s\t%-15s\t%-15s\t%-15s\t%-15s\t%-15s\t%-15s"
        print(_fmt % (_('id'),
                          _('IPv4'),
                          _('IPv6'),
                          _('start address'),
                          _('DNS1'),
                          _('DNS2'),
                          _('VlanID'),
                          _('project'),
                          _("uuid")))
        try:
            # Since network_get_all can throw exception.NoNetworksFound
            # for this command to show a nice result, this exception
            # should be caught and handled as such.
            networks = db.network_get_all(context.get_admin_context())
        except exception.NoNetworksFound:
            print(_('No networks found'))
        else:
            for network in networks:
                print(_fmt % (network.id,
                              network.cidr,
                              network.cidr_v6,
                              network.dhcp_start,
                              network.dns1,
                              network.dns2,
                              network.vlan,
                              network.project_id,
                              network.uuid))

    @validate_network_plugin
    @args('--fixed_range', metavar='<x.x.x.x/yy>', help='Network to delete')
    @args('--uuid', metavar='<uuid>', help='UUID of network to delete')
    def delete(self, fixed_range=None, uuid=None):
        """Deletes a network."""
        if fixed_range is None and uuid is None:
            raise Exception(_("Please specify either fixed_range or uuid"))

        net_manager = importutils.import_object(CONF.network_manager)
        if "NeutronManager" in CONF.network_manager:
            if uuid is None:
                raise Exception(_("UUID is required to delete "
                                  "Neutron Networks"))
            if fixed_range:
                raise Exception(_("Deleting by fixed_range is not supported "
                                "with the NeutronManager"))
        # delete the network
        net_manager.delete_network(context.get_admin_context(),
            fixed_range, uuid)

    @validate_network_plugin
    @args('--fixed_range', metavar='<x.x.x.x/yy>', help='Network to modify')
    @args('--project', metavar='<project name>',
            help='Project name to associate')
    @args('--host', metavar='<host>', help='Host to associate')
    @args('--disassociate-project', action="store_true", dest='dis_project',
          default=False, help='Disassociate Network from Project')
    @args('--disassociate-host', action="store_true", dest='dis_host',
          default=False, help='Disassociate Host from Project')
    def modify(self, fixed_range, project=None, host=None,
               dis_project=None, dis_host=None):
        """Associate/Disassociate Network with Project and/or Host
        arguments: network project host
        leave any field blank to ignore it
        """
        admin_context = context.get_admin_context()
        network = db.network_get_by_cidr(admin_context, fixed_range)
        net = {}
        # User can choose the following actions each for project and host.
        # 1) Associate (set not None value given by project/host parameter)
        # 2) Disassociate (set None by disassociate parameter)
        # 3) Keep unchanged (project/host key is not added to 'net')
        if dis_project:
            net['project_id'] = None
        if dis_host:
            net['host'] = None

        # The --disassociate-X are boolean options, but if they user
        # mistakenly provides a value, it will be used as a positional argument
        # and be erroneously interepreted as some other parameter (e.g.
        # a project instead of host value). The safest thing to do is error-out
        # with a message indicating that there is probably a problem with
        # how the disassociate modifications are being used.
        if dis_project or dis_host:
            if project or host:
                error_msg = "ERROR: Unexpected arguments provided. Please " \
                    "use separate commands."
                print(error_msg)
                return(1)
            db.network_update(admin_context, network['id'], net)
            return

        if project:
            net['project_id'] = project
        if host:
            net['host'] = host

        db.network_update(admin_context, network['id'], net)


class VmCommands(object):
    """Class for mangaging VM instances."""

    @args('--host', metavar='<host>', help='Host')
    def list(self, host=None):
        """Show a list of all instances."""

        print(("%-10s %-15s %-10s %-10s %-26s %-9s %-9s %-9s"
               "  %-10s %-10s %-10s %-5s" % (_('instance'),
                                             _('node'),
                                             _('type'),
                                             _('state'),
                                             _('launched'),
                                             _('image'),
                                             _('kernel'),
                                             _('ramdisk'),
                                             _('project'),
                                             _('user'),
                                             _('zone'),
                                             _('index'))))

        if host is None:
            instances = objects.InstanceList.get_by_filters(
                context.get_admin_context(), {}, expected_attrs=['flavor'])
        else:
            instances = objects.InstanceList.get_by_host(
                context.get_admin_context(), host, expected_attrs=['flavor'])

        for instance in instances:
            instance_type = instance.get_flavor()
            print(("%-10s %-15s %-10s %-10s %-26s %-9s %-9s %-9s"
                   " %-10s %-10s %-10s %-5d" % (instance.display_name,
                                                instance.host,
                                                instance_type.name,
                                                instance.vm_state,
                                                instance.launched_at,
                                                instance.image_ref,
                                                instance.kernel_id,
                                                instance.ramdisk_id,
                                                instance.project_id,
                                                instance.user_id,
                                                instance.availability_zone,
                                                instance.launch_index or 0)))


class ServiceCommands(object):
    """Enable and disable running services."""

    @args('--host', metavar='<host>', help='Host')
    @args('--service', metavar='<service>', help='Nova service')
    def list(self, host=None, service=None):
        """Show a list of all running services. Filter by host & service
        name
        """
        servicegroup_api = servicegroup.API()
        ctxt = context.get_admin_context()
        services = db.service_get_all(ctxt)
        services = availability_zones.set_availability_zones(ctxt, services)
        if host:
            services = [s for s in services if s['host'] == host]
        if service:
            services = [s for s in services if s['binary'] == service]
        print_format = "%-16s %-36s %-16s %-10s %-5s %-10s"
        print(print_format % (
                    _('Binary'),
                    _('Host'),
                    _('Zone'),
                    _('Status'),
                    _('State'),
                    _('Updated_At')))
        for svc in services:
            alive = servicegroup_api.service_is_up(svc)
            art = (alive and ":-)") or "XXX"
            active = 'enabled'
            if svc['disabled']:
                active = 'disabled'
            print(print_format % (svc['binary'], svc['host'],
                                  svc['availability_zone'], active, art,
                                  svc['updated_at']))

    @args('--host', metavar='<host>', help='Host')
    @args('--service', metavar='<service>', help='Nova service')
    def enable(self, host, service):
        """Enable scheduling for a service."""
        ctxt = context.get_admin_context()
        try:
            svc = db.service_get_by_args(ctxt, host, service)
            db.service_update(ctxt, svc['id'], {'disabled': False})
        except exception.NotFound as ex:
            print(_("error: %s") % ex)
            return(2)
        print((_("Service %(service)s on host %(host)s enabled.") %
               {'service': service, 'host': host}))

    @args('--host', metavar='<host>', help='Host')
    @args('--service', metavar='<service>', help='Nova service')
    def disable(self, host, service):
        """Disable scheduling for a service."""
        ctxt = context.get_admin_context()
        try:
            svc = db.service_get_by_args(ctxt, host, service)
            db.service_update(ctxt, svc['id'], {'disabled': True})
        except exception.NotFound as ex:
            print(_("error: %s") % ex)
            return(2)
        print((_("Service %(service)s on host %(host)s disabled.") %
               {'service': service, 'host': host}))

    def _show_host_resources(self, context, host):
        """Shows the physical/usage resource given by hosts.

        :param context: security context
        :param host: hostname
        :returns:
            example format is below::

                {'resource':D, 'usage':{proj_id1:D, proj_id2:D}}
                D: {'vcpus': 3, 'memory_mb': 2048, 'local_gb': 2048,
                    'vcpus_used': 12, 'memory_mb_used': 10240,
                    'local_gb_used': 64}

        """
        # Getting compute node info and related instances info
        service_ref = db.service_get_by_compute_host(context, host)
        instance_refs = db.instance_get_all_by_host(context,
                                                    service_ref['host'])

        # Getting total available/used resource
        compute_ref = service_ref['compute_node'][0]
        resource = {'vcpus': compute_ref['vcpus'],
                    'memory_mb': compute_ref['memory_mb'],
                    'local_gb': compute_ref['local_gb'],
                    'vcpus_used': compute_ref['vcpus_used'],
                    'memory_mb_used': compute_ref['memory_mb_used'],
                    'local_gb_used': compute_ref['local_gb_used']}
        usage = dict()
        if not instance_refs:
            return {'resource': resource, 'usage': usage}

        # Getting usage resource per project
        project_ids = [i['project_id'] for i in instance_refs]
        project_ids = list(set(project_ids))
        for project_id in project_ids:
            vcpus = [i['vcpus'] for i in instance_refs
                     if i['project_id'] == project_id]

            mem = [i['memory_mb'] for i in instance_refs
                   if i['project_id'] == project_id]

            root = [i['root_gb'] for i in instance_refs
                    if i['project_id'] == project_id]

            ephemeral = [i['ephemeral_gb'] for i in instance_refs
                         if i['project_id'] == project_id]

            usage[project_id] = {'vcpus': sum(vcpus),
                                 'memory_mb': sum(mem),
                                 'root_gb': sum(root),
                                 'ephemeral_gb': sum(ephemeral)}

        return {'resource': resource, 'usage': usage}

    @args('--host', metavar='<host>', help='Host')
    def describe_resource(self, host):
        """Describes cpu/memory/hdd info for host.

        :param host: hostname.

        """
        try:
            result = self._show_host_resources(context.get_admin_context(),
                                               host=host)
        except exception.NovaException as ex:
            print(_("error: %s") % ex)
            return 2

        if not isinstance(result, dict):
            print(_('An unexpected error has occurred.'))
            print(_('[Result]'), result)
        else:
            # Printing a total and used_now
            # (NOTE)The host name width 16 characters
            print('%(a)-25s%(b)16s%(c)8s%(d)8s%(e)8s' % {"a": _('HOST'),
                                                         "b": _('PROJECT'),
                                                         "c": _('cpu'),
                                                         "d": _('mem(mb)'),
                                                         "e": _('hdd')})
            print(('%(a)-16s(total)%(b)26s%(c)8s%(d)8s' %
                   {"a": host,
                    "b": result['resource']['vcpus'],
                    "c": result['resource']['memory_mb'],
                    "d": result['resource']['local_gb']}))

            print(('%(a)-16s(used_now)%(b)23s%(c)8s%(d)8s' %
                   {"a": host,
                    "b": result['resource']['vcpus_used'],
                    "c": result['resource']['memory_mb_used'],
                    "d": result['resource']['local_gb_used']}))

            # Printing a used_max
            cpu_sum = 0
            mem_sum = 0
            hdd_sum = 0
            for p_id, val in result['usage'].items():
                cpu_sum += val['vcpus']
                mem_sum += val['memory_mb']
                hdd_sum += val['root_gb']
                hdd_sum += val['ephemeral_gb']
            print('%(a)-16s(used_max)%(b)23s%(c)8s%(d)8s' % {"a": host,
                                                             "b": cpu_sum,
                                                             "c": mem_sum,
                                                             "d": hdd_sum})

            for p_id, val in result['usage'].items():
                print('%(a)-25s%(b)16s%(c)8s%(d)8s%(e)8s' % {
                        "a": host,
                        "b": p_id,
                        "c": val['vcpus'],
                        "d": val['memory_mb'],
                        "e": val['root_gb'] + val['ephemeral_gb']})


class HostCommands(object):
    """List hosts."""

    def list(self, zone=None):
        """Show a list of all physical hosts. Filter by zone.
        args: [zone]
        """
        print("%-25s\t%-15s" % (_('host'),
                                _('zone')))
        ctxt = context.get_admin_context()
        services = db.service_get_all(ctxt)
        services = availability_zones.set_availability_zones(ctxt, services)
        if zone:
            services = [s for s in services if s['availability_zone'] == zone]
        hosts = []
        for srv in services:
            if not [h for h in hosts if h['host'] == srv['host']]:
                hosts.append(srv)

        for h in hosts:
            print("%-25s\t%-15s" % (h['host'], h['availability_zone']))


class DbCommands(object):
    """Class for managing the database."""

    def __init__(self):
        pass

    @args('--version', metavar='<version>', help='Database version')
    def sync(self, version=None):
        """Sync the database up to the most recent version."""
        return migration.db_sync(version)

    def version(self):
        """Print the current database version."""
        print(migration.db_version())

    @args('--max_rows', metavar='<number>',
            help='Maximum number of deleted rows to archive')
    def archive_deleted_rows(self, max_rows):
        """Move up to max_rows deleted rows from production tables to shadow
        tables.
        """
        if max_rows is not None:
            max_rows = int(max_rows)
            if max_rows < 0:
                print(_("Must supply a positive value for max_rows"))
                return(1)
        admin_context = context.get_admin_context()
        db.archive_deleted_rows(admin_context, max_rows)

    @args('--delete', action='store_true', dest='delete',
          help='If specified, automatically delete any records found where '
               'instance_uuid is NULL.')
    def null_instance_uuid_scan(self, delete=False):
        """Lists and optionally deletes database records where
        instance_uuid is NULL.
        """
        hits = migration.db_null_instance_uuid_scan(delete)
        records_found = False
        for table_name, records in six.iteritems(hits):
            # Don't print anything for 0 hits
            if records:
                records_found = True
                if delete:
                    print(_("Deleted %(records)d records "
                            "from table '%(table_name)s'.") %
                          {'records': records, 'table_name': table_name})
                else:
                    print(_("There are %(records)d records in the "
                            "'%(table_name)s' table where the uuid or "
                            "instance_uuid column is NULL. Run this "
                            "command again with the --delete option after you "
                            "have backed up any necessary data.") %
                          {'records': records, 'table_name': table_name})
        # check to see if we didn't find anything
        if not records_found:
            print(_('There were no records found where '
                    'instance_uuid was NULL.'))

    @args('--max-number', metavar='<number>',
          help='Maximum number of instances to consider')
    def migrate_flavor_data(self, max_number):
        if max_number is not None:
            max_number = int(max_number)
            if max_number < 0:
                print(_('Must supply a positive value for max_number'))
                return(1)
        admin_context = context.get_admin_context()
        flavor_cache = {}
        match, done = db.migrate_flavor_data(admin_context, max_number,
                                             flavor_cache)
        print(_('%(total)i instances matched query, %(done)i completed'),
              {'total': match, 'done': done})


class AgentBuildCommands(object):
    """Class for managing agent builds."""

    @args('--os', metavar='<os>', help='os')
    @args('--architecture', dest='architecture',
            metavar='<architecture>', help='architecture')
    @args('--version', metavar='<version>', help='version')
    @args('--url', metavar='<url>', help='url')
    @args('--md5hash', metavar='<md5hash>', help='md5hash')
    @args('--hypervisor', metavar='<hypervisor>',
            help='hypervisor(default: xen)')
    def create(self, os, architecture, version, url, md5hash,
                hypervisor='xen'):
        """Creates a new agent build."""
        ctxt = context.get_admin_context()
        db.agent_build_create(ctxt, {'hypervisor': hypervisor,
                                     'os': os,
                                     'architecture': architecture,
                                     'version': version,
                                     'url': url,
                                     'md5hash': md5hash})

    @args('--os', metavar='<os>', help='os')
    @args('--architecture', dest='architecture',
            metavar='<architecture>', help='architecture')
    @args('--hypervisor', metavar='<hypervisor>',
            help='hypervisor(default: xen)')
    def delete(self, os, architecture, hypervisor='xen'):
        """Deletes an existing agent build."""
        ctxt = context.get_admin_context()
        agent_build_ref = db.agent_build_get_by_triple(ctxt,
                                  hypervisor, os, architecture)
        db.agent_build_destroy(ctxt, agent_build_ref['id'])

    @args('--hypervisor', metavar='<hypervisor>',
            help='hypervisor(default: None)')
    def list(self, hypervisor=None):
        """Lists all agent builds.

        arguments: <none>
        """
        fmt = "%-10s  %-8s  %12s  %s"
        ctxt = context.get_admin_context()
        by_hypervisor = {}
        for agent_build in db.agent_build_get_all(ctxt):
            buildlist = by_hypervisor.get(agent_build.hypervisor)
            if not buildlist:
                buildlist = by_hypervisor[agent_build.hypervisor] = []

            buildlist.append(agent_build)

        for key, buildlist in by_hypervisor.iteritems():
            if hypervisor and key != hypervisor:
                continue

            print(_('Hypervisor: %s') % key)
            print(fmt % ('-' * 10, '-' * 8, '-' * 12, '-' * 32))
            for agent_build in buildlist:
                print(fmt % (agent_build.os, agent_build.architecture,
                             agent_build.version, agent_build.md5hash))
                print('    %s' % agent_build.url)

            print()

    @args('--os', metavar='<os>', help='os')
    @args('--architecture', dest='architecture',
            metavar='<architecture>', help='architecture')
    @args('--version', metavar='<version>', help='version')
    @args('--url', metavar='<url>', help='url')
    @args('--md5hash', metavar='<md5hash>', help='md5hash')
    @args('--hypervisor', metavar='<hypervisor>',
            help='hypervisor(default: xen)')
    def modify(self, os, architecture, version, url, md5hash,
               hypervisor='xen'):
        """Update an existing agent build."""
        ctxt = context.get_admin_context()
        agent_build_ref = db.agent_build_get_by_triple(ctxt,
                                  hypervisor, os, architecture)
        db.agent_build_update(ctxt, agent_build_ref['id'],
                              {'version': version,
                               'url': url,
                               'md5hash': md5hash})


class GetLogCommands(object):
    """Get logging information."""

    def errors(self):
        """Get all of the errors from the log files."""
        error_found = 0
        if CONF.log_dir:
            logs = [x for x in os.listdir(CONF.log_dir) if x.endswith('.log')]
            for file in logs:
                log_file = os.path.join(CONF.log_dir, file)
                lines = [line.strip() for line in open(log_file, "r")]
                lines.reverse()
                print_name = 0
                for index, line in enumerate(lines):
                    if line.find(" ERROR ") > 0:
                        error_found += 1
                        if print_name == 0:
                            print(log_file + ":-")
                            print_name = 1
                        linenum = len(lines) - index
                        print((_('Line %(linenum)d : %(line)s') %
                               {'linenum': linenum, 'line': line}))
        if error_found == 0:
            print(_('No errors in logfiles!'))

    @args('--num_entries', metavar='<number of entries>',
            help='number of entries(default: 10)')
    def syslog(self, num_entries=10):
        """Get <num_entries> of the nova syslog events."""
        entries = int(num_entries)
        count = 0
        log_file = ''
        if os.path.exists('/var/log/syslog'):
            log_file = '/var/log/syslog'
        elif os.path.exists('/var/log/messages'):
            log_file = '/var/log/messages'
        else:
            print(_('Unable to find system log file!'))
            return(1)
        lines = [line.strip() for line in open(log_file, "r")]
        lines.reverse()
        print(_('Last %s nova syslog entries:-') % (entries))
        for line in lines:
            if line.find("nova") > 0:
                count += 1
                print("%s" % (line))
            if count == entries:
                break

        if count == 0:
            print(_('No nova entries in syslog!'))


class CellCommands(object):
    """Commands for managing cells."""

    def _create_transport_hosts(self, username, password,
                                broker_hosts=None, hostname=None, port=None):
        """Returns a list of oslo.messaging.TransportHost objects."""
        transport_hosts = []
        # Either broker-hosts or hostname should be set
        if broker_hosts:
            hosts = broker_hosts.split(',')
            for host in hosts:
                host = host.strip()
                broker_hostname, broker_port = utils.parse_server_string(host)
                if not broker_port:
                    msg = _('Invalid broker_hosts value: %s. It should be'
                            ' in hostname:port format') % host
                    raise ValueError(msg)
                try:
                    broker_port = int(broker_port)
                except ValueError:
                    msg = _('Invalid port value: %s. It should be '
                             'an integer') % broker_port
                    raise ValueError(msg)
                transport_hosts.append(
                               messaging.TransportHost(
                                   hostname=broker_hostname,
                                   port=broker_port,
                                   username=username,
                                   password=password))
        else:
            try:
                port = int(port)
            except ValueError:
                msg = _("Invalid port value: %s. Should be an integer") % port
                raise ValueError(msg)
            transport_hosts.append(
                           messaging.TransportHost(
                               hostname=hostname,
                               port=port,
                               username=username,
                               password=password))
        return transport_hosts

    @args('--name', metavar='<name>', help='Name for the new cell')
    @args('--cell_type', metavar='<parent|api|child|compute>',
         help='Whether the cell is parent/api or child/compute')
    @args('--username', metavar='<username>',
         help='Username for the message broker in this cell')
    @args('--password', metavar='<password>',
         help='Password for the message broker in this cell')
    @args('--broker_hosts', metavar='<broker_hosts>',
         help='Comma separated list of message brokers in this cell. '
              'Each Broker is specified as hostname:port with both '
              'mandatory. This option overrides the --hostname '
              'and --port options (if provided). ')
    @args('--hostname', metavar='<hostname>',
         help='Address of the message broker in this cell')
    @args('--port', metavar='<number>',
         help='Port number of the message broker in this cell')
    @args('--virtual_host', metavar='<virtual_host>',
         help='The virtual host of the message broker in this cell')
    @args('--woffset', metavar='<float>')
    @args('--wscale', metavar='<float>')
    def create(self, name, cell_type='child', username=None, broker_hosts=None,
               password=None, hostname=None, port=None, virtual_host=None,
               woffset=None, wscale=None):

        if cell_type not in ['parent', 'child', 'api', 'compute']:
            print("Error: cell type must be 'parent'/'api' or "
                "'child'/'compute'")
            return(2)

        # Set up the transport URL
        transport_hosts = self._create_transport_hosts(
                                                 username, password,
                                                 broker_hosts, hostname,
                                                 port)
        transport_url = rpc.get_transport_url()
        transport_url.hosts.extend(transport_hosts)
        transport_url.virtual_host = virtual_host

        is_parent = False
        if cell_type in ['api', 'parent']:
            is_parent = True
        values = {'name': name,
                  'is_parent': is_parent,
                  'transport_url': str(transport_url),
                  'weight_offset': float(woffset),
                  'weight_scale': float(wscale)}
        ctxt = context.get_admin_context()
        db.cell_create(ctxt, values)

    @args('--cell_name', metavar='<cell_name>',
          help='Name of the cell to delete')
    def delete(self, cell_name):
        ctxt = context.get_admin_context()
        db.cell_delete(ctxt, cell_name)

    def list(self):
        ctxt = context.get_admin_context()
        cells = db.cell_get_all(ctxt)
        fmt = "%3s  %-10s  %-6s  %-10s  %-15s  %-5s  %-10s"
        print(fmt % ('Id', 'Name', 'Type', 'Username', 'Hostname',
                'Port', 'VHost'))
        print(fmt % ('-' * 3, '-' * 10, '-' * 6, '-' * 10, '-' * 15,
                '-' * 5, '-' * 10))
        for cell in cells:
            url = rpc.get_transport_url(cell.transport_url)
            host = url.hosts[0] if url.hosts else messaging.TransportHost()
            print(fmt % (cell.id, cell.name,
                    'parent' if cell.is_parent else 'child',
                    host.username, host.hostname,
                    host.port, url.virtual_host))
        print(fmt % ('-' * 3, '-' * 10, '-' * 6, '-' * 10, '-' * 15,
                '-' * 5, '-' * 10))


CATEGORIES = {
    'account': AccountCommands,
    'agent': AgentBuildCommands,
    'cell': CellCommands,
    'db': DbCommands,
    'fixed': FixedIpCommands,
    'floating': FloatingIpCommands,
    'host': HostCommands,
    'logs': GetLogCommands,
    'network': NetworkCommands,
    'project': ProjectCommands,
    'service': ServiceCommands,
    'shell': ShellCommands,
    'vm': VmCommands,
    'vpn': VpnCommands,
}


def methods_of(obj):
    """Get all callable methods of an object that don't start with underscore

    returns a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if callable(getattr(obj, i)) and not i.startswith('_'):
            result.append((i, getattr(obj, i)))
    return result


def add_command_parsers(subparsers):
    parser = subparsers.add_parser('version')

    parser = subparsers.add_parser('bash-completion')
    parser.add_argument('query_category', nargs='?')

    for category in CATEGORIES:
        command_object = CATEGORIES[category]()

        desc = getattr(command_object, 'description', None)
        parser = subparsers.add_parser(category, description=desc)
        parser.set_defaults(command_object=command_object)

        category_subparsers = parser.add_subparsers(dest='action')

        for (action, action_fn) in methods_of(command_object):
            parser = category_subparsers.add_parser(action, description=desc)

            action_kwargs = []
            for args, kwargs in getattr(action_fn, 'args', []):
                # FIXME(markmc): hack to assume dest is the arg name without
                # the leading hyphens if no dest is supplied
                kwargs.setdefault('dest', args[0][2:])
                if kwargs['dest'].startswith('action_kwarg_'):
                    action_kwargs.append(
                            kwargs['dest'][len('action_kwarg_'):])
                else:
                    action_kwargs.append(kwargs['dest'])
                    kwargs['dest'] = 'action_kwarg_' + kwargs['dest']

                parser.add_argument(*args, **kwargs)

            parser.set_defaults(action_fn=action_fn)
            parser.set_defaults(action_kwargs=action_kwargs)

            parser.add_argument('action_args', nargs='*',
                                help=argparse.SUPPRESS)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opt(category_opt)
    try:
        config.parse_args(sys.argv)
        logging.setup("nova")
    except cfg.ConfigFilesNotFoundError:
        cfgfile = CONF.config_file[-1] if CONF.config_file else None
        if cfgfile and not os.access(cfgfile, os.R_OK):
            st = os.stat(cfgfile)
            print(_("Could not read %s. Re-running with sudo") % cfgfile)
            try:
                os.execvp('sudo', ['sudo', '-u', '#%s' % st.st_uid] + sys.argv)
            except Exception:
                print(_('sudo failed, continuing as if nothing happened'))

        print(_('Please re-run nova-manage as root.'))
        return(2)

    objects.register_all()

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return(0)

    if CONF.category.name == "bash-completion":
        if not CONF.category.query_category:
            print(" ".join(CATEGORIES.keys()))
        elif CONF.category.query_category in CATEGORIES:
            fn = CATEGORIES[CONF.category.query_category]
            command_object = fn()
            actions = methods_of(command_object)
            print(" ".join([k for (k, v) in actions]))
        return(0)

    fn = CONF.category.action_fn
    fn_args = [arg.decode('utf-8') for arg in CONF.category.action_args]
    fn_kwargs = {}
    for k in CONF.category.action_kwargs:
        v = getattr(CONF.category, 'action_kwarg_' + k)
        if v is None:
            continue
        if isinstance(v, six.string_types):
            v = v.decode('utf-8')
        fn_kwargs[k] = v

    # call the action with the remaining arguments
    # check arguments
    try:
        cliutils.validate_args(fn, *fn_args, **fn_kwargs)
    except cliutils.MissingArgs as e:
        # NOTE(mikal): this isn't the most helpful error message ever. It is
        # long, and tells you a lot of things you probably don't want to know
        # if you just got a single arg wrong.
        print(fn.__doc__)
        CONF.print_help()
        print(e)
        return(1)
    try:
        ret = fn(*fn_args, **fn_kwargs)
        rpc.cleanup()
        return(ret)
    except Exception:
        print(_("Command failed, please check log for more info"))
        raise
