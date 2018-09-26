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
import functools
import os
import re
import sys
import traceback

import decorator
import netaddr
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import importutils
from oslo_utils import uuidutils
import prettytable

import six
import six.moves.urllib.parse as urlparse
from sqlalchemy.engine import url as sqla_url

from nova.api.ec2 import ec2utils
from nova import availability_zones
from nova.cmd import common as cmd_common
import nova.conf
from nova import config
from nova import context
from nova import db
from nova.db import migration
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import aggregate as aggregate_obj
from nova.objects import build_request as build_request_obj
from nova.objects import flavor as flavor_obj
from nova.objects import host_mapping as host_mapping_obj
from nova.objects import instance as instance_obj
from nova.objects import instance_group as instance_group_obj
from nova.objects import keypair as keypair_obj
from nova.objects import quotas as quotas_obj
from nova.objects import request_spec
from nova import quota
from nova import rpc
from nova import utils
from nova import version
from nova.virt import ironic

CONF = nova.conf.CONF

QUOTAS = quota.QUOTAS

# Keep this list sorted and one entry per line for readability.
_EXTRA_DEFAULT_LOG_LEVELS = ['oslo_concurrency=INFO',
                             'oslo_db=INFO',
                             'oslo_policy=INFO']


# Decorators for actions
args = cmd_common.args
action_description = cmd_common.action_description


def param2id(object_id):
    """Helper function to convert various volume id types to internal id.
    args: [object_id], e.g. 'vol-0000000a' or 'volume-0000000a' or '10'
    """
    if '-' in object_id:
        return ec2utils.ec2_vol_id_to_uuid(object_id)
    else:
        return object_id


def mask_passwd_in_url(url):
    parsed = urlparse.urlparse(url)
    safe_netloc = re.sub(':.*@', ':****@', parsed.netloc)
    new_parsed = urlparse.ParseResult(
        parsed.scheme, safe_netloc,
        parsed.path, parsed.params,
        parsed.query, parsed.fragment)
    return urlparse.urlunparse(new_parsed)


class ShellCommands(object):

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The shell commands are deprecated since '
                   'Pike as they serve no useful purpose in modern nova. '
                   'They will be removed in an upcoming release.')

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
    sys.exit(1)


class QuotaCommands(object):
    """Class for managing quotas."""

    # TODO(melwitt): Remove this during the Queens cycle
    description = ('DEPRECATED: The quota commands are deprecated since '
                   'Pike as quota usage is counted from resources instead '
                   'of being tracked separately. They will be removed in an '
                   'upcoming release.')

    @args('--project', dest='project_id', metavar='<Project Id>',
            help='Project Id', required=True)
    @args('--user', dest='user_id', metavar='<User Id>',
            help='User Id')
    @args('--key', metavar='<key>', help='Key')
    def refresh(self, project_id, user_id=None, key=None):
        """DEPRECATED: This command is deprecated and no longer does anything.
        """
        pass


class ProjectCommands(object):
    """Class for managing projects."""

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The project commands are deprecated since '
                   'Pike as this information is available over the API. They '
                   'will be removed in an upcoming release.')

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
                    return 2
                if ((int(value) < minimum) and
                   (maximum != -1 or (maximum == -1 and int(value) != -1))):
                    print(_('Quota limit must be greater than %s.') % minimum)
                    return 2
                if maximum != -1 and int(value) > maximum:
                    print(_('Quota limit must be less than %s.') % maximum)
                    return 2
                try:
                    objects.Quotas.create_limit(ctxt, project_id, key, value,
                                                user_id=user_id)
                except exception.QuotaExists:
                    objects.Quotas.update_limit(ctxt, project_id, key, value,
                                                user_id=user_id)
            else:
                print(_('%(key)s is not a valid quota key. Valid options are: '
                        '%(options)s.') % {'key': key,
                                           'options': ', '.join(quota)})
                return 2
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
        for key, value in quota.items():
            if value['limit'] is None or value['limit'] < 0:
                value['limit'] = 'unlimited'
            print(print_format % (key, value['limit'], value['in_use'],
                                  value['reserved']))

    @args('--project', dest='project_id', metavar='<Project Id>',
            help='Project Id', required=True)
    @args('--user', dest='user_id', metavar='<User Id>',
            help='User Id')
    @args('--key', metavar='<key>', help='Key')
    def quota_usage_refresh(self, project_id, user_id=None, key=None):
        """DEPRECATED: This command is deprecated and no longer does anything.
        """
        # TODO(melwitt): Remove this during the Queens cycle
        pass


class AccountCommands(ProjectCommands):
    """Class for managing projects."""

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The account commands are deprecated since '
                   'Pike as this information is available over the API. They '
                   'will be removed in an upcoming release.')


class FloatingIpCommands(object):
    """Class for managing floating IP."""

    # TODO(stephenfin): Remove these when we remove cells v1
    description = ('DEPRECATED: Floating IP commands are deprecated since '
                   'nova-network is deprecated in favor of Neutron. The '
                   'floating IP commands will be removed in an upcoming '
                   'release.')

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
        """Creates floating IPs for zone by range."""
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
            return 1

    @args('--ip_range', metavar='<range>', help='IP range')
    def delete(self, ip_range):
        """Deletes floating IPs by range."""
        admin_context = context.get_admin_context()

        ips = ({'address': str(address)}
               for address in self.address_to_hosts(ip_range))
        db.floating_ip_bulk_destroy(admin_context, ips)

    @args('--host', metavar='<host>', help='Host')
    def list(self, host=None):
        """Lists all floating IPs (optionally by host).

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
        return 2
    return f(*args, **kwargs)


class NetworkCommands(object):
    """Class for managing networks."""

    # TODO(stephenfin): Remove these when we remove cells v1
    description = ('DEPRECATED: Network commands are deprecated since '
                   'nova-network is deprecated in favor of Neutron. The '
                   'network commands will be removed in an upcoming release.')

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
            help='IPv4 subnet for fixed IPs (ex: 10.20.0.0/16)')
    @args('--project_id', metavar="<project id>",
          help='Project id')
    @args('--priority', metavar="<number>", help='Network interface priority')
    def create(self, label=None, cidr=None, num_networks=None,
               network_size=None, multi_host=None, vlan=None,
               vlan_start=None, vpn_start=None, cidr_v6=None, gateway=None,
               gateway_v6=None, bridge=None, bridge_interface=None,
               dns1=None, dns2=None, project_id=None, priority=None,
               uuid=None, fixed_cidr=None):
        """Creates fixed IPs for host by range."""

        # NOTE(gmann): These checks are moved here as API layer does all these
        # validation through JSON schema.
        if not label:
            raise exception.NetworkNotCreated(req="label")
        if len(label) > 255:
            raise exception.LabelTooLong()
        if not (cidr or cidr_v6):
            raise exception.NetworkNotCreated(req="cidr or cidr_v6")

        kwargs = {k: v for k, v in locals().items()
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
        # and be erroneously interpreted as some other parameter (e.g.
        # a project instead of host value). The safest thing to do is error-out
        # with a message indicating that there is probably a problem with
        # how the disassociate modifications are being used.
        if dis_project or dis_host:
            if project or host:
                error_msg = "ERROR: Unexpected arguments provided. Please " \
                    "use separate commands."
                print(error_msg)
                return 1
            db.network_update(admin_context, network['id'], net)
            return

        if project:
            net['project_id'] = project
        if host:
            net['host'] = host

        db.network_update(admin_context, network['id'], net)


class HostCommands(object):
    """List hosts."""

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The host commands are deprecated since '
                   'Pike as this information is available over the API. They '
                   'will be removed in an upcoming release.')

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
    """Class for managing the main database."""

    online_migrations = (
        # Added in Newton
        flavor_obj.migrate_flavors,
        # Added in Newton
        flavor_obj.migrate_flavor_reset_autoincrement,
        # Added in Newton
        instance_obj.migrate_instance_keypairs,
        # Added in Newton
        request_spec.migrate_instances_add_request_spec,
        # Added in Newton
        keypair_obj.migrate_keypairs_to_api_db,
        # Added in Newton
        aggregate_obj.migrate_aggregates,
        # Added in Newton
        aggregate_obj.migrate_aggregate_reset_autoincrement,
        # Added in Newton
        instance_group_obj.migrate_instance_groups_to_api_db,
        # Added in Ocata
        # NOTE(mriedem): This online migration is going to be backported to
        # Newton also since it's an upgrade issue when upgrading from Mitaka.
        build_request_obj.delete_build_requests_with_no_instance_uuid,
        # Added in Pike
        db.service_uuids_online_data_migration,
        # Added in Pike
        quotas_obj.migrate_quota_limits_to_api_db,
        # Added in Pike
        quotas_obj.migrate_quota_classes_to_api_db,
        # Added in Rocky
        # NOTE(tssurya): This online migration is going to be backported to
        # Queens and Pike since instance.avz of instances before Pike
        # need to be populated if it was not specified during boot time.
        instance_obj.populate_missing_availability_zones,
    )

    def __init__(self):
        pass

    @args('--version', metavar='<version>', help=argparse.SUPPRESS)
    @args('--local_cell', action='store_true',
          help='Only sync db in the local cell: do not attempt to fan-out'
               'to all cells')
    @args('version2', metavar='VERSION', nargs='?', help='Database version')
    def sync(self, version=None, local_cell=False, version2=None):
        """Sync the database up to the most recent version."""
        if version and not version2:
            print(_("DEPRECATED: The '--version' parameter was deprecated in "
                    "the Pike cycle and will not be supported in future "
                    "versions of nova. Use the 'VERSION' positional argument "
                    "instead"))
            version2 = version

        if not local_cell:
            ctxt = context.RequestContext()
            # NOTE(mdoff): Multiple cells not yet implemented. Currently
            # fanout only looks for cell0.
            try:
                cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                                            objects.CellMapping.CELL0_UUID)
                with context.target_cell(ctxt, cell_mapping) as cctxt:
                    migration.db_sync(version2, context=cctxt)
            except exception.CellMappingNotFound:
                print(_('WARNING: cell0 mapping not found - not'
                        ' syncing cell0.'))
            except Exception as e:
                print(_("""ERROR: Could not access cell0.
Has the nova_api database been created?
Has the nova_cell0 database been created?
Has "nova-manage api_db sync" been run?
Has "nova-manage cell_v2 map_cell0" been run?
Is [api_database]/connection set in nova.conf?
Is the cell0 database connection URL correct?
Error: %s""") % six.text_type(e))
        return migration.db_sync(version)

    def version(self):
        """Print the current database version."""
        print(migration.db_version())

    @args('--max_rows', type=int, metavar='<number>', dest='max_rows',
          help='Maximum number of deleted rows to archive. Defaults to 1000.')
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Print how many rows were archived per table.')
    @args('--until-complete', action='store_true', dest='until_complete',
          default=False,
          help=('Run continuously until all deleted rows are archived. Use '
                'max_rows as a batch size for each iteration.'))
    def archive_deleted_rows(self, max_rows=1000, verbose=False,
                             until_complete=False):
        """Move deleted rows from production tables to shadow tables.

        Returns 0 if nothing was archived, 1 if some number of rows were
        archived, 2 if max_rows is invalid. If automating, this should be
        run continuously while the result is 1, stopping at 0.
        """
        max_rows = int(max_rows)
        if max_rows < 0:
            print(_("Must supply a positive value for max_rows"))
            return 2
        if max_rows > db.MAX_INT:
            print(_('max rows must be <= %(max_value)d') %
                  {'max_value': db.MAX_INT})
            return 2

        table_to_rows_archived = {}
        deleted_instance_uuids = []
        if until_complete and verbose:
            sys.stdout.write(_('Archiving') + '..')  # noqa
        while True:
            try:
                run, deleted_instance_uuids = db.archive_deleted_rows(max_rows)
            except KeyboardInterrupt:
                run = {}
                if until_complete and verbose:
                    print('.' + _('stopped'))  # noqa
                    break
            for k, v in run.items():
                table_to_rows_archived.setdefault(k, 0)
                table_to_rows_archived[k] += v
            if deleted_instance_uuids:
                table_to_rows_archived.setdefault('instance_mappings', 0)
                table_to_rows_archived.setdefault('request_specs', 0)
                ctxt = context.get_admin_context()
                deleted_mappings = objects.InstanceMappingList.destroy_bulk(
                                            ctxt, deleted_instance_uuids)
                table_to_rows_archived['instance_mappings'] += deleted_mappings
                deleted_specs = objects.RequestSpec.destroy_bulk(
                                            ctxt, deleted_instance_uuids)
                table_to_rows_archived['request_specs'] += deleted_specs
            if not until_complete:
                break
            elif not run:
                if verbose:
                    print('.' + _('complete'))  # noqa
                break
            if verbose:
                sys.stdout.write('.')
        if verbose:
            if table_to_rows_archived:
                utils.print_dict(table_to_rows_archived, _('Table'),
                                 dict_value=_('Number of Rows Archived'))
            else:
                print(_('Nothing was archived.'))
        # NOTE(danms): Return nonzero if we archived something
        return int(bool(table_to_rows_archived))

    @args('--delete', action='store_true', dest='delete',
          help='If specified, automatically delete any records found where '
               'instance_uuid is NULL.')
    def null_instance_uuid_scan(self, delete=False):
        """Lists and optionally deletes database records where
        instance_uuid is NULL.
        """
        hits = migration.db_null_instance_uuid_scan(delete)
        records_found = False
        for table_name, records in hits.items():
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

    def _run_migration(self, ctxt, max_count):
        ran = 0
        migrations = {}
        for migration_meth in self.online_migrations:
            count = max_count - ran
            try:
                found, done = migration_meth(ctxt, count)
            except Exception:
                print(_("Error attempting to run %(method)s") % dict(
                      method=migration_meth))
                found = done = 0

            name = migration_meth.__name__
            if found:
                print(_('%(total)i rows matched query %(meth)s, %(done)i '
                        'migrated') % {'total': found,
                                       'meth': name,
                                       'done': done})
            migrations[name] = found, done
            if max_count is not None:
                ran += done
                if ran >= max_count:
                    break
        return migrations

    @args('--max-count', metavar='<number>', dest='max_count',
          help='Maximum number of objects to consider')
    def online_data_migrations(self, max_count=None):
        ctxt = context.get_admin_context()
        if max_count is not None:
            try:
                max_count = int(max_count)
            except ValueError:
                max_count = -1
            unlimited = False
            if max_count < 1:
                print(_('Must supply a positive value for max_number'))
                return 127
        else:
            unlimited = True
            max_count = 50
            print(_('Running batches of %i until complete') % max_count)

        ran = None
        migration_info = {}
        while ran is None or ran != 0:
            migrations = self._run_migration(ctxt, max_count)
            ran = 0
            for name in migrations:
                migration_info.setdefault(name, (0, 0))
                migration_info[name] = (
                    migration_info[name][0] + migrations[name][0],
                    migration_info[name][1] + migrations[name][1],
                )
                ran += migrations[name][1]
            if not unlimited:
                break

        t = prettytable.PrettyTable([_('Migration'),
                                     _('Total Needed'),
                                     _('Completed')])
        for name in sorted(migration_info.keys()):
            info = migration_info[name]
            t.add_row([name, info[0], info[1]])
        print(t)

        return ran and 1 or 0

    @args('--resource_class', metavar='<class>', required=True,
          help='Ironic node class to set on instances')
    @args('--host', metavar='<host>', required=False,
          help='Compute service name to migrate nodes on')
    @args('--node', metavar='<node>', required=False,
          help='Ironic node UUID to migrate (all on the host if omitted)')
    @args('--all', action='store_true', default=False, dest='all_hosts',
          help='Run migrations for all ironic hosts and nodes')
    @args('--verbose', action='store_true', default=False,
          help='Print information about migrations being performed')
    def ironic_flavor_migration(self, resource_class, host=None, node=None,
                                all_hosts=False, verbose=False):
        """Migrate flavor information for ironic instances.

        This will manually push the instance flavor migration required
        for ironic-hosted instances in Pike. The best way to accomplish
        this migration is to run your ironic computes normally in Pike.
        However, if you need to push the migration manually, then use
        this.

        This is idempotent, but not trivial to start/stop/resume. It is
        recommended that you do this with care and not from a script
        assuming it is trivial.

        Running with --all may generate a large amount of DB traffic
        all at once. Running at least one host at a time is recommended
        for batching.

        Return values:

        0: All work is completed (or none is needed)
        1: Specified host and/or node is not found, or no ironic nodes present
        2: Internal accounting error shows more than one instance per node
        3: Invalid combination of required arguments
        """
        if not resource_class:
            # Note that if --resource_class is not specified on the command
            # line it will actually result in a return code of 2, but we
            # leave 3 here for testing purposes.
            print(_('A resource_class is required for all modes of operation'))
            return 3

        ctx = context.get_admin_context()

        if all_hosts:
            if host or node:
                print(_('--all with --host and/or --node does not make sense'))
                return 3
            cns = objects.ComputeNodeList.get_by_hypervisor_type(ctx, 'ironic')
        elif host and node:
            try:
                cn = objects.ComputeNode.get_by_host_and_nodename(ctx, host,
                                                                  node)
                cns = [cn]
            except exception.ComputeHostNotFound:
                cns = []
        elif host:
            try:
                cns = objects.ComputeNodeList.get_all_by_host(ctx, host)
            except exception.ComputeHostNotFound:
                cns = []
        else:
            print(_('Either --all, --host, or --host and --node are required'))
            return 3

        if len(cns) == 0:
            print(_('No ironic compute nodes found that match criteria'))
            return 1

        # Check that we at least got one ironic compute and we can pretty
        # safely assume the rest are
        if cns[0].hypervisor_type != 'ironic':
            print(_('Compute node(s) specified is not of type ironic'))
            return 1

        for cn in cns:
            # NOTE(danms): The instance.node is the
            # ComputeNode.hypervisor_hostname, which in the case of ironic is
            # the node uuid. Since only one instance can be on a node in
            # ironic, do another sanity check here to make sure we look legit.
            inst = objects.InstanceList.get_by_filters(
                ctx, {'node': cn.hypervisor_hostname,
                      'deleted': False})
            if len(inst) > 1:
                print(_('Ironic node %s has multiple instances? '
                        'Something is wrong.') % cn.hypervisor_hostname)
                return 2
            elif len(inst) == 1:
                result = ironic.IronicDriver._pike_flavor_migration_for_node(
                    ctx, resource_class, inst[0].uuid)
                if result and verbose:
                    print(_('Migrated instance %(uuid)s on node %(node)s') % {
                        'uuid': inst[0].uuid,
                        'node': cn.hypervisor_hostname})
        return 0


class ApiDbCommands(object):
    """Class for managing the api database."""

    def __init__(self):
        pass

    @args('--version', metavar='<version>', help=argparse.SUPPRESS)
    @args('version2', metavar='VERSION', nargs='?', help='Database version')
    def sync(self, version=None, version2=None):
        """Sync the database up to the most recent version."""
        if version and not version2:
            print(_("DEPRECATED: The '--version' parameter was deprecated in "
                    "the Pike cycle and will not be supported in future "
                    "versions of nova. Use the 'VERSION' positional argument "
                    "instead"))
            version2 = version

        return migration.db_sync(version2, database='api')

    def version(self):
        """Print the current database version."""
        print(migration.db_version(database='api'))


class AgentBuildCommands(object):
    """Class for managing agent builds."""

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The agent commands are deprecated since '
                   'Pike as this information is available over the API. They '
                   'will be removed in an upcoming release.')

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

        for key, buildlist in by_hypervisor.items():
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

    # TODO(stephenfin): Remove this during the Queens cycle
    description = ('DEPRECATED: The log commands are deprecated since '
                   'Pike as they are not maintained. They will be removed '
                   'in an upcoming release.')

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
            return 1
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
            return 2

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
                  'transport_url': urlparse.unquote(str(transport_url)),
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


class CellV2Commands(object):
    """Commands for managing cells v2."""

    def _validate_transport_url(self, transport_url):
        transport_url = transport_url or CONF.transport_url
        if not transport_url:
            print('Must specify --transport-url if [DEFAULT]/transport_url '
                  'is not set in the configuration file.')
        return transport_url

    @args('--transport-url', metavar='<transport_url>', dest='transport_url',
          help='The transport url for the cell message queue')
    def simple_cell_setup(self, transport_url=None):
        """Simple cellsv2 setup.

        This simplified command is for use by existing non-cells users to
        configure the default environment. If you are using CellsV1, this
        will not work for you. Returns 0 if setup is completed (or has
        already been done), 1 if no hosts are reporting (and this cannot
        be mapped) and 2 if run in a CellsV1 environment.
        """
        if CONF.cells.enable:
            print('CellsV1 users cannot use this simplified setup command')
            return 2
        transport_url = self._validate_transport_url(transport_url)
        if not transport_url:
            return 1
        ctxt = context.RequestContext()
        try:
            cell0_mapping = self._map_cell0()
        except db_exc.DBDuplicateEntry:
            print(_('Cell0 is already setup'))
            cell0_mapping = objects.CellMapping.get_by_uuid(
                ctxt, objects.CellMapping.CELL0_UUID)

        # Run migrations so cell0 is usable
        with context.target_cell(ctxt, cell0_mapping) as cctxt:
            try:
                migration.db_sync(None, context=cctxt)
            except db_exc.DBError as ex:
                print(_('Unable to sync cell0 schema: %s') % ex)

        cell_uuid = self._map_cell_and_hosts(transport_url)
        if cell_uuid is None:
            # There are no compute hosts which means no cell_mapping was
            # created. This should also mean that there are no instances.
            return 1
        self.map_instances(cell_uuid)
        return 0

    @args('--database_connection',
          metavar='<database_connection>',
          help='The database connection url for cell0. '
               'This is optional. If not provided, a standard database '
               'connection will be used based on the main database connection '
               'from the Nova configuration.'
         )
    def map_cell0(self, database_connection=None):
        """Create a cell mapping for cell0.

        cell0 is used for instances that have not been scheduled to any cell.
        This generally applies to instances that have encountered an error
        before they have been scheduled.

        This command creates a cell mapping for this special cell which
        requires a database to store the instance data.

        Returns 0 if cell0 created successfully or already setup.
        """
        try:
            self._map_cell0(database_connection=database_connection)
        except db_exc.DBDuplicateEntry:
            print(_('Cell0 is already setup'))
        return 0

    def _map_cell0(self, database_connection=None):
        """Faciliate creation of a cell mapping for cell0.
        See map_cell0 for more.
        """
        def cell0_default_connection():
            # If no database connection is provided one is generated
            # based on the database connection url.
            # The cell0 database will use the same database scheme and
            # netloc as the main database, with a related path.
            # NOTE(sbauza): The URL has to be RFC1738 compliant in order to
            # be usable by sqlalchemy.
            connection = CONF.database.connection
            # sqlalchemy has a nice utility for parsing database connection
            # URLs so we use that here to get the db name so we don't have to
            # worry about parsing and splitting a URL which could have special
            # characters in the password, which makes parsing a nightmare.
            url = sqla_url.make_url(connection)
            url.database = url.database + '_cell0'
            return urlparse.unquote(str(url))

        dbc = database_connection or cell0_default_connection()
        ctxt = context.RequestContext()
        # A transport url of 'none://' is provided for cell0. RPC should not
        # be used to access cell0 objects. Cells transport switching will
        # ignore any 'none' transport type.
        cell_mapping = objects.CellMapping(
                ctxt, uuid=objects.CellMapping.CELL0_UUID, name="cell0",
                transport_url="none:///",
                database_connection=dbc)
        cell_mapping.create()
        return cell_mapping

    def _get_and_map_instances(self, ctxt, cell_mapping, limit, marker):
        filters = {}
        instances = objects.InstanceList.get_by_filters(
                ctxt.elevated(read_deleted='yes'), filters,
                sort_key='created_at', sort_dir='asc', limit=limit,
                marker=marker)

        for instance in instances:
            try:
                mapping = objects.InstanceMapping(ctxt)
                mapping.instance_uuid = instance.uuid
                mapping.cell_mapping = cell_mapping
                mapping.project_id = instance.project_id
                mapping.create()
            except db_exc.DBDuplicateEntry:
                continue

        if len(instances) == 0 or len(instances) < limit:
            # We've hit the end of the instances table
            marker = None
        else:
            marker = instances[-1].uuid
        return marker

    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=True,
          help='Unmigrated instances will be mapped to the cell with the '
               'uuid provided.')
    @args('--max-count', metavar='<max_count>', dest='max_count',
          help='Maximum number of instances to map')
    def map_instances(self, cell_uuid, max_count=None):
        """Map instances into the provided cell.

        This assumes that Nova on this host is still configured to use the nova
        database not just the nova-api database. Instances in the nova database
        will be queried from oldest to newest and mapped to the provided cell.
        A max-count can be set on the number of instance to map in a single
        run. Repeated runs of the command will start from where the last run
        finished so it is not necessary to increase max-count to finish. An
        exit code of 0 indicates that all instances have been mapped.
        """

        if max_count is not None:
            try:
                max_count = int(max_count)
            except ValueError:
                max_count = -1
            map_all = False
            if max_count < 1:
                print(_('Must supply a positive value for max-count'))
                return 127
        else:
            map_all = True
            max_count = 50

        ctxt = context.RequestContext()
        marker_project_id = 'INSTANCE_MIGRATION_MARKER'

        # Validate the cell exists, this will raise if not
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)

        # Check for a marker from a previous run
        marker_mapping = objects.InstanceMappingList.get_by_project_id(ctxt,
                marker_project_id)
        if len(marker_mapping) == 0:
            marker = None
        else:
            # There should be only one here
            marker = marker_mapping[0].instance_uuid.replace(' ', '-')
            marker_mapping[0].destroy()

        next_marker = True
        while next_marker is not None:
            next_marker = self._get_and_map_instances(ctxt, cell_mapping,
                    max_count, marker)
            marker = next_marker
            if not map_all:
                break

        if next_marker:
            # Don't judge me. There's already an InstanceMapping with this UUID
            # so the marker needs to be non destructively modified.
            next_marker = next_marker.replace('-', ' ')
            objects.InstanceMapping(ctxt, instance_uuid=next_marker,
                    project_id=marker_project_id).create()
            return 1
        return 0

    def _map_cell_and_hosts(self, transport_url, name=None, verbose=False):
        ctxt = context.RequestContext()
        cell_mapping_uuid = cell_mapping = None
        # First, try to detect if a CellMapping has already been created
        compute_nodes = objects.ComputeNodeList.get_all(ctxt)
        if not compute_nodes:
            print(_('No hosts found to map to cell, exiting.'))
            return None
        missing_nodes = set()
        for compute_node in compute_nodes:
            try:
                host_mapping = objects.HostMapping.get_by_host(
                    ctxt, compute_node.host)
            except exception.HostMappingNotFound:
                missing_nodes.add(compute_node.host)
            else:
                if verbose:
                    print(_(
                        'Host %(host)s is already mapped to cell %(uuid)s'
                        ) % {'host': host_mapping.host,
                             'uuid': host_mapping.cell_mapping.uuid})
                # Re-using the existing UUID in case there is already a mapping
                # NOTE(sbauza): There could be possibly multiple CellMappings
                # if the operator provides another configuration file and moves
                # the hosts to another cell v2, but that's not really something
                # we should support.
                cell_mapping_uuid = host_mapping.cell_mapping.uuid
        if not missing_nodes:
            print(_('All hosts are already mapped to cell(s), exiting.'))
            return cell_mapping_uuid
        # Create the cell mapping in the API database
        if cell_mapping_uuid is not None:
            cell_mapping = objects.CellMapping.get_by_uuid(
                ctxt, cell_mapping_uuid)
        if cell_mapping is None:
            cell_mapping_uuid = uuidutils.generate_uuid()
            cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_mapping_uuid, name=name,
                transport_url=transport_url,
                database_connection=CONF.database.connection)
            cell_mapping.create()
        # Pull the hosts from the cell database and create the host mappings
        for compute_host in missing_nodes:
            host_mapping = objects.HostMapping(
                ctxt, host=compute_host, cell_mapping=cell_mapping)
            host_mapping.create()
        if verbose:
            print(cell_mapping_uuid)
        return cell_mapping_uuid

    @args('--transport-url', metavar='<transport_url>', dest='transport_url',
          help='The transport url for the cell message queue')
    @args('--name', metavar='<cell_name>', help='The name of the cell')
    @args('--verbose', action='store_true',
          help='Output the cell mapping uuid for any newly mapped hosts.')
    def map_cell_and_hosts(self, transport_url=None, name=None, verbose=False):
        """EXPERIMENTAL. Create a cell mapping and host mappings for a cell.

        Users not dividing their cloud into multiple cells will be a single
        cell v2 deployment and should specify:

          nova-manage cell_v2 map_cell_and_hosts --config-file <nova.conf>

        Users running multiple cells can add a cell v2 by specifying:

          nova-manage cell_v2 map_cell_and_hosts --config-file <cell nova.conf>
        """
        transport_url = self._validate_transport_url(transport_url)
        if not transport_url:
            return 1
        self._map_cell_and_hosts(transport_url, name, verbose)
        # online_data_migrations established a pattern of 0 meaning everything
        # is done, 1 means run again to do more work. This command doesn't do
        # partial work so 0 is appropriate.
        return 0

    @args('--uuid', metavar='<instance_uuid>', dest='uuid', required=True,
          help=_('The instance UUID to verify'))
    @args('--quiet', action='store_true', dest='quiet',
          help=_('Do not print anything'))
    def verify_instance(self, uuid, quiet=False):
        """Verify instance mapping to a cell.

        This command is useful to determine if the cellsv2 environment is
        properly setup, specifically in terms of the cell, host, and instance
        mapping records required.

        This prints one of three strings (and exits with a code) indicating
        whether the instance is successfully mapped to a cell (0), is unmapped
        due to an incomplete upgrade (1), unmapped due to normally transient
        state (2), it is a deleted instance which has instance mapping (3),
        or it is an archived instance which still has an instance mapping (4).
        """
        def say(string):
            if not quiet:
                print(string)

        ctxt = context.get_admin_context()
        try:
            mapping = objects.InstanceMapping.get_by_instance_uuid(
                ctxt, uuid)
        except exception.InstanceMappingNotFound:
            say('Instance %s is not mapped to a cell '
                '(upgrade is incomplete) or instance '
                'does not exist' % uuid)
            return 1
        if mapping.cell_mapping is None:
            say('Instance %s is not mapped to a cell' % uuid)
            return 2
        else:
            with context.target_cell(ctxt, mapping.cell_mapping) as cctxt:
                try:
                    instance = objects.Instance.get_by_uuid(cctxt, uuid)
                except exception.InstanceNotFound:
                    try:
                        el_ctx = cctxt.elevated(read_deleted='yes')
                        instance = objects.Instance.get_by_uuid(el_ctx, uuid)
                        # instance is deleted
                        if instance:
                            say('The instance with uuid %s has been deleted.'
                                % uuid)
                            say('Execute `nova-manage db archive_deleted_rows`'
                                'command to archive this deleted instance and'
                                'remove its instance_mapping.')
                            return 3
                    except exception.InstanceNotFound:
                        # instance is archived
                        say('The instance with uuid %s has been archived.'
                            % uuid)
                        say('However its instance_mapping remains.')
                        return 4
            # instance is alive and mapped to a cell
            say('Instance %s is in cell: %s (%s)' % (
                uuid,
                mapping.cell_mapping.name,
                mapping.cell_mapping.uuid))
            return 0

    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          help='If provided only this cell will be searched for new hosts to '
               'map.')
    @args('--verbose', action='store_true',
          help=_('Provide detailed output when discovering hosts.'))
    @args('--strict', action='store_true',
          help=_('Considered successful (exit code 0) only when an unmapped '
                 'host is discovered. Any other outcome will be considered a '
                 'failure (exit code 1).'))
    @args('--by-service', action='store_true', default=False,
          dest='by_service',
          help=_('Discover hosts by service instead of compute node'))
    def discover_hosts(self, cell_uuid=None, verbose=False, strict=False,
                       by_service=False):
        """Searches cells, or a single cell, and maps found hosts.

        When a new host is added to a deployment it will add a service entry
        to the db it's configured to use. This command will check the db for
        each cell, or a single one if passed in, and map any hosts which are
        not currently mapped. If a host is already mapped nothing will be done.
        """
        def status_fn(msg):
            if verbose:
                print(msg)

        ctxt = context.RequestContext()
        hosts = host_mapping_obj.discover_hosts(ctxt, cell_uuid, status_fn,
                                                by_service)
        # discover_hosts will return an empty list if no hosts are discovered
        if strict:
            return int(not hosts)

    @action_description(
        _("Add a new cell to nova API database. "
          "DB and MQ urls can be provided directly "
          "or can be taken from config. The result is cell uuid."))
    @args('--name', metavar='<cell_name>', help=_('The name of the cell'))
    @args('--database_connection', metavar='<database_connection>',
          dest='database_connection',
          help=_('The database url for the cell database'))
    @args('--transport-url', metavar='<transport_url>', dest='transport_url',
          help=_('The transport url for the cell message queue'))
    @args('--verbose', action='store_true',
          help=_('Output the uuid of the created cell'))
    def create_cell(self, name=None, database_connection=None,
                    transport_url=None, verbose=False):
        ctxt = context.get_context()
        transport_url = transport_url or CONF.transport_url
        if not transport_url:
            print(_('Must specify --transport-url if [DEFAULT]/transport_url '
                    'is not set in the configuration file.'))
            return 1
        database_connection = database_connection or CONF.database.connection
        if not database_connection:
            print(_('Must specify --database_connection '
                    'if [database]/connection is not set '
                    'in the configuration file.'))
            return 1
        if any(cell.database_connection == database_connection
               and cell.transport_url == transport_url
               for cell in objects.CellMappingList.get_all(ctxt)):
            print(_('Cell with the specified transport_url '
                    'and database_connection combination already exists'))
            return 2
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
            ctxt,
            uuid=cell_mapping_uuid, name=name,
            transport_url=transport_url,
            database_connection=database_connection)
        cell_mapping.create()
        if verbose:
            print(cell_mapping_uuid)
        return 0

    @args('--verbose', action='store_true',
          help=_('Show sensitive details, such as passwords'))
    def list_cells(self, verbose=False):
        """Lists the v2 cells in the deployment.

        By default only the cell name and uuid are shown. Use the --verbose
        option to see transport URL and database connection details.
        """
        cell_mappings = objects.CellMappingList.get_all(
            context.get_admin_context())

        field_names = [_('Name'), _('UUID'), _('Transport URL'),
                       _('Database Connection')]

        t = prettytable.PrettyTable(field_names)
        for cell in sorted(cell_mappings, key=lambda _cell: _cell.name):
            fields = [cell.name, cell.uuid]
            if verbose:
                fields.extend([cell.transport_url, cell.database_connection])
            else:
                fields.extend([
                    mask_passwd_in_url(cell.transport_url),
                    mask_passwd_in_url(cell.database_connection)])
            t.add_row(fields)
        print(t)
        return 0

    @args('--force', action='store_true', default=False,
          help=_('Delete hosts that belong to the cell as well.'))
    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=True, help=_('The uuid of the cell to delete.'))
    def delete_cell(self, cell_uuid, force=False):
        """Delete an empty cell by the given uuid.

        This command will return a non-zero exit code in the following cases.

        * The cell is not found by uuid.
        * It has hosts and force is False.
        * It has instance mappings.

        If force is True and the cell has host, hosts are deleted as well.

        Returns 0 in the following cases.

        * The empty cell is found and deleted successfully.
        * The cell has hosts and force is True and the cell and the hosts are
          deleted successfully.
        """
        ctxt = context.get_admin_context()
        # Find the CellMapping given the uuid.
        try:
            cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
        except exception.CellMappingNotFound:
            print(_('Cell with uuid %s was not found.') % cell_uuid)
            return 1

        # Check to see if there are any HostMappings for this cell.
        host_mappings = objects.HostMappingList.get_by_cell_id(
            ctxt, cell_mapping.id)
        nodes = []
        if host_mappings:
            if not force:
                print(_('There are existing hosts mapped to cell with uuid '
                        '%s.') % cell_uuid)
                return 2
            # We query for the compute nodes in the cell,
            # so that they can be unmapped.
            with context.target_cell(ctxt, cell_mapping) as cctxt:
                nodes = objects.ComputeNodeList.get_all(cctxt)

        # Check to see if there are any InstanceMappings for this cell.
        instance_mappings = objects.InstanceMappingList.get_by_cell_id(
            ctxt, cell_mapping.id)
        if instance_mappings:
            print(_('There are existing instances mapped to cell with '
                    'uuid %s.') % cell_uuid)
            return 3

        # Unmap the compute nodes so that they can be discovered
        # again in future, if needed.
        for node in nodes:
            node.mapped = 0
            node.save()

        # Delete hosts mapped to the cell.
        for host_mapping in host_mappings:
            host_mapping.destroy()

        # There are no hosts or instances mapped to the cell so delete it.
        cell_mapping.destroy()
        return 0

    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=True, help=_('The uuid of the cell to update.'))
    @args('--name', metavar='<cell_name>', dest='name',
          help=_('Set the cell name.'))
    @args('--transport-url', metavar='<transport_url>', dest='transport_url',
          help=_('Set the cell transport_url. NOTE that running nodes '
                 'will not see the change until restart!'))
    @args('--database_connection', metavar='<database_connection>',
          dest='db_connection',
          help=_('Set the cell database_connection. NOTE that running nodes '
                 'will not see the change until restart!'))
    def update_cell(self, cell_uuid, name=None, transport_url=None,
                    db_connection=None):
        """Updates the properties of a cell by the given uuid.

        If the cell is not found by uuid, this command will return an exit
        code of 1. If the properties cannot be set, this will return 2.
        Otherwise, the exit code will be 0.

        NOTE: Updating the transport_url or database_connection fields on
        a running system will NOT result in all nodes immediately using the
        new values. Use caution when changing these values.
        """
        ctxt = context.get_admin_context()
        try:
            cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
        except exception.CellMappingNotFound:
            print(_('Cell with uuid %s was not found.') % cell_uuid)
            return 1

        if name:
            cell_mapping.name = name

        transport_url = transport_url or CONF.transport_url
        if transport_url:
            cell_mapping.transport_url = transport_url

        db_connection = db_connection or CONF.database.connection
        if db_connection:
            cell_mapping.database_connection = db_connection

        try:
            cell_mapping.save()
        except Exception as e:
            print(_('Unable to update CellMapping: %s') % e)
            return 2

        return 0

    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=True, help=_('The uuid of the cell.'))
    @args('--host', metavar='<host>', dest='host',
          required=True, help=_('The host to delete.'))
    def delete_host(self, cell_uuid, host):
        """Delete a host in a cell (host mappings) by the given host name

        This command will return a non-zero exit code in the following cases.

        * The cell is not found by uuid.
        * The host is not found by host name.
        * The host is not in the cell.
        * The host has instances.

        Returns 0 if the host is deleted successfully.
        """
        ctxt = context.get_admin_context()
        # Find the CellMapping given the uuid.
        try:
            cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
        except exception.CellMappingNotFound:
            print(_('Cell with uuid %s was not found.') % cell_uuid)
            return 1

        try:
            host_mapping = objects.HostMapping.get_by_host(ctxt, host)
        except exception.HostMappingNotFound:
            print(_('The host %s was not found.') % host)
            return 2

        if host_mapping.cell_mapping.uuid != cell_mapping.uuid:
            print(_('The host %(host)s was not found '
                    'in the cell %(cell_uuid)s.') % {'host': host,
                                                     'cell_uuid': cell_uuid})
            return 3

        with context.target_cell(ctxt, cell_mapping) as cctxt:
            instances = objects.InstanceList.get_by_host(cctxt, host)
            nodes = objects.ComputeNodeList.get_all_by_host(cctxt, host)

        if instances:
            print(_('There are instances on the host %s.') % host)
            return 4

        for node in nodes:
            node.mapped = 0
            node.save()

        host_mapping.destroy()
        return 0


CATEGORIES = {
    'account': AccountCommands,
    'agent': AgentBuildCommands,
    'api_db': ApiDbCommands,
    'cell': CellCommands,
    'cell_v2': CellV2Commands,
    'db': DbCommands,
    'floating': FloatingIpCommands,
    'host': HostCommands,
    'logs': GetLogCommands,
    'network': NetworkCommands,
    'project': ProjectCommands,
    'shell': ShellCommands,
    'quota': QuotaCommands,
}


add_command_parsers = functools.partial(cmd_common.add_command_parsers,
                                        categories=CATEGORIES)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)

post_mortem_opt = cfg.BoolOpt('post-mortem',
                              default=False,
                              help='Allow post-mortem debugging')


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opts([category_opt, post_mortem_opt])
    config.parse_args(sys.argv)
    logging.set_defaults(
        default_log_levels=logging.get_default_log_levels() +
        _EXTRA_DEFAULT_LOG_LEVELS)
    logging.setup(CONF, "nova")
    objects.register_all()

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        rpc.cleanup()
        return ret
    except Exception:
        if CONF.post_mortem:
            import pdb
            pdb.post_mortem()
        else:
            print(_("An error has occurred:\n%s") % traceback.format_exc())
        return 1
