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


"""
  CLI interface for nova management.
"""

from __future__ import print_function

import argparse
import functools
import re
import sys
import traceback

from dateutil import parser as dateutil_parser
import decorator
import netaddr
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import encodeutils
from oslo_utils import importutils
from oslo_utils import uuidutils
import prettytable
import six
import six.moves.urllib.parse as urlparse
from sqlalchemy.engine import url as sqla_url

from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.cmd import common as cmd_common
from nova.compute import api as compute_api
import nova.conf
from nova import config
from nova import context
from nova.db import api as db
from nova.db import migration
from nova.db.sqlalchemy import api as sa_db
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.objects import build_request as build_request_obj
from nova.objects import host_mapping as host_mapping_obj
from nova.objects import instance as instance_obj
from nova.objects import instance_mapping as instance_mapping_obj
from nova.objects import keypair as keypair_obj
from nova.objects import quotas as quotas_obj
from nova.objects import request_spec
from nova import quota
from nova import rpc
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils
from nova import utils
from nova import version
from nova.virt import ironic

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS

# Keep this list sorted and one entry per line for readability.
_EXTRA_DEFAULT_LOG_LEVELS = ['oslo_concurrency=INFO',
                             'oslo_db=INFO',
                             'oslo_policy=INFO']


# Decorators for actions
args = cmd_common.args
action_description = cmd_common.action_description


def mask_passwd_in_url(url):
    parsed = urlparse.urlparse(url)
    safe_netloc = re.sub(':.*@', ':****@', parsed.netloc)
    new_parsed = urlparse.ParseResult(
        parsed.scheme, safe_netloc,
        parsed.path, parsed.params,
        parsed.query, parsed.fragment)
    return urlparse.urlunparse(new_parsed)


def _db_error(caught_exception):
    print(caught_exception)
    print(_("The above error may show that the database has not "
            "been created.\nPlease create a database using "
            "'nova-manage db sync' before running this command."))
    sys.exit(1)


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


class DbCommands(object):
    """Class for managing the main database."""

    # NOTE(danms): These functions are called with a DB context and a
    # count, which is the maximum batch size requested by the
    # user. They must be idempotent. At most $count records should be
    # migrated. The function must return a tuple of (found, done). The
    # found value indicates how many unmigrated records existed in the
    # database prior to the migration (either total, or up to the
    # $count limit provided), and a nonzero found value tells the user
    # that there is still work to do. The done value indicates whether
    # or not any records were actually migrated by the function. Thus
    # if both (found, done) are nonzero, work was done and some work
    # remains. If found is nonzero and done is zero, some records are
    # not migratable, but all migrations that can complete have
    # finished.
    online_migrations = (
        # Added in Newton
        # TODO(mriedem): Remove this in Stein along with the compatibility
        # code in the api and conductor services; the nova-status upgrade check
        # added in Rocky is the tool operators can use to make sure they have
        # completed this migration.
        request_spec.migrate_instances_add_request_spec,
        # Added in Newton
        keypair_obj.migrate_keypairs_to_api_db,
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
        # Added in Queens
        sa_db.migration_migrate_to_uuid,
        # Added in Queens
        block_device_obj.BlockDeviceMapping.populate_uuids,
        # Added in Rocky
        # NOTE(tssurya): This online migration is going to be backported to
        # Queens and Pike since instance.avz of instances before Pike
        # need to be populated if it was not specified during boot time.
        instance_obj.populate_missing_availability_zones,
        # Added in Rocky
        consumer_obj.create_incomplete_consumers,
        # Added in Rocky
        instance_mapping_obj.populate_queued_for_delete,
    )

    def __init__(self):
        pass

    @staticmethod
    def _print_dict(dct, dict_property="Property", dict_value='Value'):
        """Print a `dict` as a table of two columns.

        :param dct: `dict` to print
        :param dict_property: name of the first column
        :param wrap: wrapping for the second column
        :param dict_value: header label for the value (second) column
        """
        pt = prettytable.PrettyTable([dict_property, dict_value])
        pt.align = 'l'
        for k, v in sorted(dct.items()):
            # convert dict to str to check length
            if isinstance(v, dict):
                v = six.text_type(v)
            # if value has a newline, add in multiple rows
            # e.g. fault with stacktrace
            if v and isinstance(v, six.string_types) and r'\n' in v:
                lines = v.strip().split(r'\n')
                col1 = k
                for line in lines:
                    pt.add_row([col1, line])
                    col1 = ''
            else:
                pt.add_row([k, v])

        if six.PY2:
            print(encodeutils.safe_encode(pt.get_string()))
        else:
            print(encodeutils.safe_encode(pt.get_string()).decode())

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
    @args('--purge', action='store_true', dest='purge', default=False,
          help='Purge all data from shadow tables after archive completes')
    def archive_deleted_rows(self, max_rows=1000, verbose=False,
                             until_complete=False, purge=False):
        """Move deleted rows from production tables to shadow tables.

        Returns 0 if nothing was archived, 1 if some number of rows were
        archived, 2 if max_rows is invalid, 3 if no connection could be
        established to the API DB. If automating, this should be
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

        ctxt = context.get_admin_context()
        try:
            # NOTE(tssurya): This check has been added to validate if the API
            # DB is reachable or not as this is essential for purging the
            # instance_mappings and request_specs of the deleted instances.
            objects.CellMappingList.get_all(ctxt)
        except db_exc.CantStartEngineError:
            print(_('Failed to connect to API DB so aborting this archival '
                    'attempt. Please check your config file to make sure that '
                    'CONF.api_database.connection is set and run this '
                    'command again.'))
            return 3

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
                table_to_rows_archived.setdefault('instance_group_member', 0)
                deleted_mappings = objects.InstanceMappingList.destroy_bulk(
                                            ctxt, deleted_instance_uuids)
                table_to_rows_archived['instance_mappings'] += deleted_mappings
                deleted_specs = objects.RequestSpec.destroy_bulk(
                                            ctxt, deleted_instance_uuids)
                table_to_rows_archived['request_specs'] += deleted_specs
                deleted_group_members = (
                    objects.InstanceGroup.destroy_members_bulk(
                        ctxt, deleted_instance_uuids))
                table_to_rows_archived['instance_group_member'] += (
                    deleted_group_members)
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
                self._print_dict(table_to_rows_archived, _('Table'),
                                 dict_value=_('Number of Rows Archived'))
            else:
                print(_('Nothing was archived.'))

        if table_to_rows_archived and purge:
            if verbose:
                print(_('Rows were archived, running purge...'))
            self.purge(purge_all=True, verbose=verbose)

        # NOTE(danms): Return nonzero if we archived something
        return int(bool(table_to_rows_archived))

    @args('--before', dest='before',
          help='If specified, purge rows from shadow tables that are older '
               'than this. Fuzzy time specs are allowed')
    @args('--all', dest='purge_all', action='store_true',
          help='Purge all rows in the shadow tables')
    @args('--verbose', dest='verbose', action='store_true', default=False,
          help='Print information about purged records')
    @args('--all-cells', dest='all_cells', action='store_true', default=False,
          help='Run against all cell databases')
    def purge(self, before=None, purge_all=False, verbose=False,
              all_cells=False):
        if before is None and purge_all is False:
            print(_('Either --before or --all is required'))
            return 1
        if before:
            try:
                before_date = dateutil_parser.parse(before, fuzzy=True)
            except ValueError as e:
                print(_('Invalid value for --before: %s') % e)
                return 2
        else:
            before_date = None

        def status(msg):
            if verbose:
                print('%s: %s' % (identity, msg))

        deleted = 0
        admin_ctxt = context.get_admin_context()

        if all_cells:
            try:
                cells = objects.CellMappingList.get_all(admin_ctxt)
            except db_exc.DBError:
                print(_('Unable to get cell list from API DB. '
                        'Is it configured?'))
                return 4
            for cell in cells:
                identity = _('Cell %s') % cell.identity
                with context.target_cell(admin_ctxt, cell) as cctxt:
                    deleted += sa_db.purge_shadow_tables(cctxt,
                                                         before_date,
                                                         status_fn=status)
        else:
            identity = _('DB')
            deleted = sa_db.purge_shadow_tables(admin_ctxt,
                                                before_date, status_fn=status)
        if deleted:
            return 0
        else:
            return 3

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
        exceptions = False
        migrations = {}
        for migration_meth in self.online_migrations:
            count = max_count - ran
            try:
                found, done = migration_meth(ctxt, count)
            except Exception:
                msg = (_("Error attempting to run %(method)s") % dict(
                       method=migration_meth))
                print(msg)
                LOG.exception(msg)
                exceptions = True
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
        return migrations, exceptions

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
        exceptions = False
        while ran is None or ran != 0:
            migrations, exceptions = self._run_migration(ctxt, max_count)
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

        # NOTE(imacdonn): In the "unlimited" case, the loop above will only
        # terminate when all possible migrations have been effected. If we're
        # still getting exceptions, there's a problem that requires
        # intervention. In the max-count case, exceptions are only considered
        # fatal if no work was done by any other migrations ("not ran"),
        # because otherwise work may still remain to be done, and that work
        # may resolve dependencies for the failing migrations.
        if exceptions and (unlimited or not ran):
            print(_("Some migrations failed unexpectedly. Check log for "
                    "details."))
            return 2

        # TODO(mriedem): Potentially add another return code for
        # "there are more migrations, but not completable right now"
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
        """Sync the database up to the most recent version.

        If placement_database.connection is not None, sync that
        database using the API database migrations.
        """
        if version and not version2:
            print(_("DEPRECATED: The '--version' parameter was deprecated in "
                    "the Pike cycle and will not be supported in future "
                    "versions of nova. Use the 'VERSION' positional argument "
                    "instead"))
            version2 = version

        # NOTE(cdent): At the moment, the migration code deep in the belly
        # of the migration package doesn't actually return anything, so
        # returning the result of db_sync is not particularly meaningful
        # here. But, in case that changes, we store the result from the
        # the placement sync to and with the api sync.
        result = True
        if CONF.placement_database.connection is not None:
            result = migration.db_sync(version2, database='placement')
        return migration.db_sync(version2, database='api') and result

    def version(self):
        """Print the current database version."""
        print(migration.db_version(database='api'))


class CellCommands(object):
    """Commands for managing cells v1 functionality."""

    # TODO(stephenfin): Remove this when cells v1 is removed
    description = ('DEPRECATED: The cell commands, which configure cells v1 '
                   'functionality, are deprecated as Cells v1 itself has '
                   'been deprecated. They will be removed in an upcoming '
                   'release.')

    @staticmethod
    def _parse_server_string(server_str):
        """Parses the given server_string and returns a tuple of host and port.
        If it's not a combination of host part and port, the port element is an
        empty string. If the input is invalid expression, return a tuple of two
        empty strings.
        """
        try:
            # First of all, exclude pure IPv6 address (w/o port).
            if netaddr.valid_ipv6(server_str):
                return (server_str, '')

            # Next, check if this is IPv6 address with a port number
            # combination.
            if server_str.find("]:") != -1:
                (address, port) = server_str.replace('[', '', 1).split(']:')
                return (address, port)

            # Third, check if this is a combination of an address and a port
            if server_str.find(':') == -1:
                return (server_str, '')

            # This must be a combination of an address and a port
            (address, port) = server_str.split(':')
            return (address, port)

        except (ValueError, netaddr.AddrFormatError):
            print('Invalid server_string: %s' % server_str)
            return ('', '')

    def _create_transport_hosts(self, username, password,
                                broker_hosts=None, hostname=None, port=None):
        """Returns a list of oslo.messaging.TransportHost objects."""
        transport_hosts = []
        # Either broker-hosts or hostname should be set
        if broker_hosts:
            hosts = broker_hosts.split(',')
            for host in hosts:
                host = host.strip()
                broker_hostname, broker_port = self._parse_server_string(host)
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
            return None

        try:
            messaging.TransportURL.parse(conf=CONF,
                                         url=objects.CellMapping.format_mq_url(
                                             transport_url))
        except (messaging.InvalidTransportURL, ValueError) as e:
            print(_('Invalid transport URL: %s') % six.text_type(e))
            return None

        return transport_url

    def _non_unique_transport_url_database_connection_checker(self, ctxt,
                            cell_mapping, transport_url, database_connection):
        for cell in objects.CellMappingList.get_all(ctxt):
            if cell_mapping and cell.uuid == cell_mapping.uuid:
                # If we're looking for a specific cell, then don't check
                # that one for same-ness to allow idempotent updates
                continue
            if (cell.database_connection == database_connection or
                cell.transport_url == transport_url):
                print(_('The specified transport_url and/or '
                        'database_connection combination already exists '
                        'for another cell with uuid %s.') % cell.uuid)
                return True
        return False

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
        with context.target_cell(ctxt, cell_mapping) as cctxt:
            instances = objects.InstanceList.get_by_filters(
                    cctxt.elevated(read_deleted='yes'), filters,
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
          help='Maximum number of instances to map. If not set, all instances '
               'in the cell will be mapped in batches of 50. If you have a '
               'large number of instances, consider specifying a custom value '
               'and run the command until it exits with 0.')
    @args('--reset', action='store_true', dest='reset_marker',
          help='The command will start from the beginning as opposed to the '
               'default behavior of starting from where the last run '
               'finished')
    def map_instances(self, cell_uuid, max_count=None, reset_marker=None):
        """Map instances into the provided cell.

        Instances in the nova database of the provided cell (nova database
        info is obtained from the nova-api database) will be queried from
        oldest to newest and if unmapped, will be mapped to the provided cell.
        A max-count can be set on the number of instance to map in a single
        run. Repeated runs of the command will start from where the last run
        finished so it is not necessary to increase max-count to finish. A
        reset option can be passed which will reset the marker, thus making the
        command start from the beginning as opposed to the default behavior of
        starting from where the last run finished. An exit code of 0 indicates
        that all instances have been mapped.
        """

        # NOTE(stephenfin): The support for batching in this command relies on
        # a bit of a hack. We initially process N instance-cell mappings, where
        # N is the value of '--max-count' if provided else 50. To ensure we
        # can continue from N on the next iteration, we store a instance-cell
        # mapping object with a special name and the UUID of the last
        # instance-cell mapping processed (N - 1) in munged form. On the next
        # iteration, we search for the special name and unmunge the UUID to
        # pick up where we left off. This is done until all mappings are
        # processed. The munging is necessary as there's a unique constraint on
        # the UUID field and we need something reversable. For more
        # information, see commit 9038738d0.

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
            if reset_marker:
                marker = None
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
    @args('--disabled', action='store_true',
          help=_('To create a pre-disabled cell.'))
    def create_cell(self, name=None, database_connection=None,
                    transport_url=None, verbose=False, disabled=False):
        ctxt = context.get_context()
        transport_url = self._validate_transport_url(transport_url)
        if not transport_url:
            return 1

        database_connection = database_connection or CONF.database.connection
        if not database_connection:
            print(_('Must specify --database_connection '
                    'if [database]/connection is not set '
                    'in the configuration file.'))
            return 1
        if (self._non_unique_transport_url_database_connection_checker(ctxt,
            None, transport_url, database_connection)):
            return 2
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
            ctxt,
            uuid=cell_mapping_uuid, name=name,
            transport_url=transport_url,
            database_connection=database_connection,
            disabled=disabled)
        cell_mapping.create()
        if verbose:
            print(cell_mapping_uuid)
        return 0

    @args('--verbose', action='store_true',
          help=_('Show sensitive details, such as passwords'))
    def list_cells(self, verbose=False):
        """Lists the v2 cells in the deployment.

        By default the cell name, uuid, disabled state, masked transport
        URL and database connection details are shown. Use the --verbose
        option to see transport URL and database connection with their
        sensitive details.
        """
        cell_mappings = objects.CellMappingList.get_all(
            context.get_admin_context())

        field_names = [_('Name'), _('UUID'), _('Transport URL'),
                       _('Database Connection'), _('Disabled')]

        t = prettytable.PrettyTable(field_names)
        for cell in sorted(cell_mappings, key=lambda _cell: _cell.name):
            fields = [cell.name, cell.uuid]
            if verbose:
                fields.extend([cell.transport_url, cell.database_connection])
            else:
                fields.extend([
                    mask_passwd_in_url(cell.transport_url),
                    mask_passwd_in_url(cell.database_connection)])
            fields.extend([cell.disabled])
            t.add_row(fields)
        print(t)
        return 0

    @args('--force', action='store_true', default=False,
          help=_('Delete hosts and instance_mappings that belong '
                 'to the cell as well.'))
    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=True, help=_('The uuid of the cell to delete.'))
    def delete_cell(self, cell_uuid, force=False):
        """Delete an empty cell by the given uuid.

        This command will return a non-zero exit code in the following cases.

        * The cell is not found by uuid.
        * It has hosts and force is False.
        * It has instance mappings and force is False.

        If force is True and the cell has hosts and/or instance_mappings, they
        are deleted as well (as long as there are no living instances).

        Returns 0 in the following cases.

        * The empty cell is found and deleted successfully.
        * The cell has hosts and force is True then the cell, hosts and
          instance_mappings are deleted successfully; if there are no
          living instances.
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
            with context.target_cell(ctxt, cell_mapping) as cctxt:
                instances = objects.InstanceList.get_all(cctxt)
            if instances:
                # There are instances in the cell.
                print(_('There are existing instances mapped to cell with '
                        'uuid %s.') % cell_uuid)
                return 3
            else:
                if not force:
                    # There are no instances in the cell but the records remain
                    # in the 'instance_mappings' table.
                    print(_("There are instance mappings to cell with uuid "
                            "%s, but all instances have been deleted "
                            "in the cell.") % cell_uuid)
                    print(_("So execute 'nova-manage db archive_deleted_rows' "
                            "to delete the instance mappings."))
                    return 4

        # Delete instance_mappings of the deleted instances
        for instance_mapping in instance_mappings:
            instance_mapping.destroy()

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
    @args('--disable', action='store_true', dest='disable',
          help=_('Disables the cell. Note that the scheduling will be blocked '
                 'to this cell until its enabled and followed by a SIGHUP of '
                 'nova-scheduler service.'))
    @args('--enable', action='store_true', dest='enable',
          help=_('Enables the cell. Note that this makes a disabled cell '
                 'available for scheduling after a SIGHUP of the '
                 'nova-scheduler service'))
    def update_cell(self, cell_uuid, name=None, transport_url=None,
                    db_connection=None, disable=False, enable=False):
        """Updates the properties of a cell by the given uuid.

        If the cell is not found by uuid, this command will return an exit
        code of 1. If the provided transport_url or/and database_connection
        is/are same as another cell, this command will return an exit code
        of 3. If the properties cannot be set, this will return 2. If an
        attempt is made to disable and enable a cell at the same time, this
        command will exit with a return code of 4. If an attempt is made to
        disable or enable cell0 this command will exit with a return code of 5.
        Otherwise, the exit code will be 0.

        NOTE: Updating the transport_url or database_connection fields on
        a running system will NOT result in all nodes immediately using the
        new values. Use caution when changing these values.
        NOTE (tssurya): The scheduler will not notice that a cell has been
        enabled/disabled until it is restarted or sent the SIGHUP signal.
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
        db_connection = db_connection or CONF.database.connection

        if (self._non_unique_transport_url_database_connection_checker(ctxt,
                cell_mapping, transport_url, db_connection)):
                # We use the return code 3 before 2 to avoid changing the
                # semantic meanings of return codes.
                return 3

        if transport_url:
            cell_mapping.transport_url = transport_url

        if db_connection:
            cell_mapping.database_connection = db_connection

        if disable and enable:
            print(_('Cell cannot be disabled and enabled at the same time.'))
            return 4
        if disable or enable:
            if cell_mapping.is_cell0():
                print(_('Cell0 cannot be disabled.'))
                return 5
            elif disable and not cell_mapping.disabled:
                cell_mapping.disabled = True
            elif enable and cell_mapping.disabled:
                cell_mapping.disabled = False
            elif disable and cell_mapping.disabled:
                print(_('Cell %s is already disabled') % cell_uuid)
            elif enable and not cell_mapping.disabled:
                print(_('Cell %s is already enabled') % cell_uuid)

        try:
            cell_mapping.save()
        except Exception as e:
            print(_('Unable to update CellMapping: %s') % e)
            return 2

        return 0

    @args('--cell_uuid', metavar='<cell_uuid>', dest='cell_uuid',
          help=_('The uuid of the cell.'))
    def list_hosts(self, cell_uuid=None):
        """Lists the hosts in one or all v2 cells."""
        ctxt = context.get_admin_context()
        if cell_uuid:
            # Find the CellMapping given the uuid.
            try:
                cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
            except exception.CellMappingNotFound:
                print(_('Cell with uuid %s was not found.') % cell_uuid)
                return 1

            host_mappings = objects.HostMappingList.get_by_cell_id(
                ctxt, cell_mapping.id)
        else:
            host_mappings = objects.HostMappingList.get_all(ctxt)

        field_names = [_('Cell Name'), _('Cell UUID'), _('Hostname')]

        t = prettytable.PrettyTable(field_names)
        for host in sorted(host_mappings, key=lambda _host: _host.host):
            fields = [host.cell_mapping.name, host.cell_mapping.uuid,
                      host.host]
            t.add_row(fields)
        print(t)
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
            try:
                nodes = objects.ComputeNodeList.get_all_by_host(cctxt, host)
            except exception.ComputeHostNotFound:
                nodes = []

        if instances:
            print(_('There are instances on the host %s.') % host)
            return 4

        for node in nodes:
            node.mapped = 0
            node.save()

        host_mapping.destroy()
        return 0


class PlacementCommands(object):
    """Commands for managing placement resources."""

    @staticmethod
    def _get_compute_node_uuid(ctxt, instance, node_cache):
        """Find the ComputeNode.uuid for the given Instance

        :param ctxt: cell-targeted nova.context.RequestContext
        :param instance: the instance to lookup a compute node
        :param node_cache: dict of Instance.node keys to ComputeNode.uuid
            values; this cache is updated if a new node is processed.
        :returns: ComputeNode.uuid for the given instance
        :raises: nova.exception.ComputeHostNotFound
        """
        if instance.node in node_cache:
            return node_cache[instance.node]

        compute_node = objects.ComputeNode.get_by_host_and_nodename(
            ctxt, instance.host, instance.node)
        node_uuid = compute_node.uuid
        node_cache[instance.node] = node_uuid
        return node_uuid

    def _heal_allocations_for_instance(self, ctxt, instance, node_cache,
                                       output, placement):
        """Checks the given instance to see if it needs allocation healing

        :param ctxt: cell-targeted nova.context.RequestContext
        :param instance: the instance to check for allocation healing
        :param node_cache: dict of Instance.node keys to ComputeNode.uuid
            values; this cache is updated if a new node is processed.
        :param outout: function that takes a single message for verbose output
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :return: True if allocations were created or updated for the instance,
            None if nothing needed to be done
        :raises: nova.exception.ComputeHostNotFound if a compute node for a
            given instance cannot be found
        :raises: AllocationCreateFailed if unable to create allocations for
            a given instance against a given compute node resource provider
        :raises: AllocationUpdateFailed if unable to update allocations for
            a given instance with consumer project/user information
        """
        if instance.task_state is not None:
            output(_('Instance %(instance)s is undergoing a task '
                     'state transition: %(task_state)s') %
                   {'instance': instance.uuid,
                    'task_state': instance.task_state})
            return

        if instance.node is None:
            output(_('Instance %s is not on a host.') % instance.uuid)
            return

        allocations = placement.get_allocations_for_consumer(
            ctxt, instance.uuid, include_generation=True)
        # get_allocations_for_consumer uses safe_connect which will
        # return None if we can't communicate with Placement, and the
        # response can have an empty {'allocations': {}} response if
        # there are no allocations for the instance so handle both
        if allocations and allocations.get('allocations'):
            # Check to see if the allocation project_id
            # and user_id matches the instance project and user and
            # fix the allocation project/user if they don't match.
            # Allocations created before Placement API version 1.8
            # did not have a project_id/user_id, and migrated records
            # could have sentinel values from config.
            if (allocations.get('project_id') ==
                    instance.project_id and
                    allocations.get('user_id') == instance.user_id):
                output(_('Instance %s already has allocations with '
                         'matching consumer project/user.') %
                       instance.uuid)
                return
            # We have an instance with allocations but not the correct
            # project_id/user_id, so we want to update the allocations
            # and re-put them. We don't use put_allocations here
            # because we don't want to mess up shared or nested
            # provider allocations.
            allocations['project_id'] = instance.project_id
            allocations['user_id'] = instance.user_id
            # We use 1.28 for PUT /allocations/{consumer_id} to mirror
            # the body structure from get_allocations_for_consumer.
            resp = placement.put('/allocations/%s' % instance.uuid,
                                 allocations, version='1.28')
            if resp:
                output(_('Successfully updated allocations for '
                         'instance %s.') % instance.uuid)
                return True
            else:
                raise exception.AllocationUpdateFailed(
                    instance=instance.uuid, error=resp.text)

        # This instance doesn't have allocations so we need to find
        # its compute node resource provider.
        node_uuid = self._get_compute_node_uuid(
            ctxt, instance, node_cache)

        # Now get the resource allocations for the instance based
        # on its embedded flavor.
        resources = scheduler_utils.resources_from_flavor(
            instance, instance.flavor)
        if placement.put_allocations(
                ctxt, node_uuid, instance.uuid, resources,
                instance.project_id, instance.user_id):
            output(_('Successfully created allocations for '
                     'instance %(instance)s against resource '
                     'provider %(provider)s.') %
                   {'instance': instance.uuid, 'provider': node_uuid})
            return True
        else:
            raise exception.AllocationCreateFailed(
                instance=instance.uuid, provider=node_uuid)

    def _heal_instances_in_cell(self, ctxt, max_count, unlimited, output,
                                placement):
        """Checks for instances to heal in a given cell.

        :param ctxt: cell-targeted nova.context.RequestContext
        :param max_count: batch size (limit per instance query)
        :param unlimited: True if all instances in the cell should be
            processed, else False to just process $max_count instances
        :param outout: function that takes a single message for verbose output
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :return: Number of instances that had allocations created.
        :raises: nova.exception.ComputeHostNotFound if a compute node for a
            given instance cannot be found
        :raises: AllocationCreateFailed if unable to create allocations for
            a given instance against a given compute node resource provider
        :raises: AllocationUpdateFailed if unable to update allocations for
            a given instance with consumer project/user information
        """
        # Keep a cache of instance.node to compute node resource provider UUID.
        # This will save some queries for non-ironic instances to the
        # compute_nodes table.
        node_cache = {}
        # Track the total number of instances that have allocations created
        # for them in this cell. We return when num_processed equals max_count
        # and unlimited=True or we exhaust the number of instances to process
        # in this cell.
        num_processed = 0
        # Get all instances from this cell which have a host and are not
        # undergoing a task state transition. Go from oldest to newest.
        # NOTE(mriedem): Unfortunately we don't have a marker to use
        # between runs where the user is specifying --max-count.
        # TODO(mriedem): Store a marker in system_metadata so we can
        # automatically pick up where we left off without the user having
        # to pass it in (if unlimited is False).
        filters = {'deleted': False}
        instances = objects.InstanceList.get_by_filters(
            ctxt, filters=filters, sort_key='created_at', sort_dir='asc',
            limit=max_count, expected_attrs=['flavor'])
        while instances:
            output(_('Found %s candidate instances.') % len(instances))
            # For each instance in this list, we need to see if it has
            # allocations in placement and if so, assume it's correct and
            # continue.
            for instance in instances:
                if self._heal_allocations_for_instance(
                        ctxt, instance, node_cache, output, placement):
                    num_processed += 1

            # Make sure we don't go over the max count. Note that we
            # don't include instances that already have allocations in the
            # max_count number, only the number of instances that have
            # successfully created allocations.
            if not unlimited and num_processed == max_count:
                return num_processed

            # Use a marker to get the next page of instances in this cell.
            # Note that InstanceList doesn't support slice notation.
            marker = instances[len(instances) - 1].uuid
            instances = objects.InstanceList.get_by_filters(
                ctxt, filters=filters, sort_key='created_at', sort_dir='asc',
                limit=max_count, marker=marker, expected_attrs=['flavor'])

        return num_processed

    @action_description(
        _("Iterates over non-cell0 cells looking for instances which do "
          "not have allocations in the Placement service, or have incomplete "
          "consumer project_id/user_id values in existing allocations, and "
          "which are not undergoing a task state transition. For each "
          "instance found, allocations are created (or updated) against the "
          "compute node resource provider for that instance based on the "
          "flavor associated with the instance. This command requires that "
          "the [api_database]/connection and [placement] configuration "
          "options are set."))
    @args('--max-count', metavar='<max_count>', dest='max_count',
          help='Maximum number of instances to process. If not specified, all '
               'instances in each cell will be mapped in batches of 50. '
               'If you have a large number of instances, consider specifying '
               'a custom value and run the command until it exits with '
               '0 or 4.')
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Provide verbose output during execution.')
    def heal_allocations(self, max_count=None, verbose=False):
        """Heals instance allocations in the Placement service

        Return codes:

        * 0: Command completed successfully and allocations were created.
        * 1: --max-count was reached and there are more instances to process.
        * 2: Unable to find a compute node record for a given instance.
        * 3: Unable to create (or update) allocations for an instance against
             its compute node resource provider.
        * 4: Command completed successfully but no allocations were created.
        * 127: Invalid input.
        """
        # NOTE(mriedem): Thoughts on ways to expand this:
        # - add a --dry-run option to just print which instances would have
        #   allocations created for them
        # - allow passing a specific cell to heal
        # - allow filtering on enabled/disabled cells
        # - allow passing a specific instance to heal
        # - add a force option to force allocations for instances which have
        #   task_state is not None (would get complicated during a migration);
        #   for example, this could cleanup ironic instances that have
        #   allocations on VCPU/MEMORY_MB/DISK_GB but are now using a custom
        #   resource class
        # - add an option to overwrite allocations for instances which already
        #   have allocations (but the operator thinks might be wrong?); this
        #   would probably only be safe with a specific instance.
        # - deal with nested resource providers?

        output = lambda msg: None
        if verbose:
            output = lambda msg: print(msg)

        # TODO(mriedem): Rather than --max-count being both a total and batch
        # count, should we have separate options to be specific, i.e. --total
        # and --batch-size? Then --batch-size defaults to 50 and --total
        # defaults to None to mean unlimited.
        if max_count is not None:
            try:
                max_count = int(max_count)
            except ValueError:
                max_count = -1
            unlimited = False
            if max_count < 1:
                print(_('Must supply a positive integer for --max-count.'))
                return 127
        else:
            max_count = 50
            unlimited = True
            output(_('Running batches of %i until complete') % max_count)

        ctxt = context.get_admin_context()
        cells = objects.CellMappingList.get_all(ctxt)
        if not cells:
            output(_('No cells to process.'))
            return 4

        placement = report.SchedulerReportClient()
        num_processed = 0
        # TODO(mriedem): Use context.scatter_gather_skip_cell0.
        for cell in cells:
            # Skip cell0 since that is where instances go that do not get
            # scheduled and hence would not have allocations against a host.
            if cell.uuid == objects.CellMapping.CELL0_UUID:
                continue
            output(_('Looking for instances in cell: %s') % cell.identity)

            limit_per_cell = max_count
            if not unlimited:
                # Adjust the limit for the next cell. For example, if the user
                # only wants to process a total of 100 instances and we did
                # 75 in cell1, then we only need 25 more from cell2 and so on.
                limit_per_cell = max_count - num_processed

            with context.target_cell(ctxt, cell) as cctxt:
                try:
                    num_processed += self._heal_instances_in_cell(
                        cctxt, limit_per_cell, unlimited, output, placement)
                except exception.ComputeHostNotFound as e:
                    print(e.format_message())
                    return 2
                except (exception.AllocationCreateFailed,
                        exception.AllocationUpdateFailed) as e:
                    print(e.format_message())
                    return 3

                # Make sure we don't go over the max count. Note that we
                # don't include instances that already have allocations in the
                # max_count number, only the number of instances that have
                # successfully created allocations.
                if num_processed == max_count:
                    output(_('Max count reached. Processed %s instances.')
                           % num_processed)
                    return 1

        output(_('Processed %s instances.') % num_processed)
        if not num_processed:
            return 4
        return 0

    @staticmethod
    def _get_rp_uuid_for_host(ctxt, host):
        """Finds the resource provider (compute node) UUID for the given host.

        :param ctxt: cell-targeted nova RequestContext
        :param host: name of the compute host
        :returns: The UUID of the resource provider (compute node) for the host
        :raises: nova.exception.HostMappingNotFound if no host_mappings record
            is found for the host; indicates
            "nova-manage cell_v2 discover_hosts" needs to be run on the cell.
        :raises: nova.exception.ComputeHostNotFound if no compute_nodes record
            is found in the cell database for the host; indicates the
            nova-compute service on that host might need to be restarted.
        :raises: nova.exception.TooManyComputesForHost if there are more than
            one compute_nodes records in the cell database for the host which
            is only possible (under normal circumstances) for ironic hosts but
            ironic hosts are not currently supported with host aggregates so
            if more than one compute node is found for the host, it is
            considered an error which the operator will need to resolve
            manually.
        """
        # Get the host mapping to determine which cell it's in.
        hm = objects.HostMapping.get_by_host(ctxt, host)
        # Now get the compute node record for the host from the cell.
        with context.target_cell(ctxt, hm.cell_mapping) as cctxt:
            # There should really only be one, since only ironic
            # hosts can have multiple nodes, and you can't have
            # ironic hosts in aggregates for that reason. If we
            # find more than one, it's an error.
            nodes = objects.ComputeNodeList.get_all_by_host(
                cctxt, host)

            if len(nodes) > 1:
                # This shouldn't happen, so we need to bail since we
                # won't know which node to use.
                raise exception.TooManyComputesForHost(
                    num_computes=len(nodes), host=host)
            return nodes[0].uuid

    @action_description(
        _("Mirrors compute host aggregates to resource provider aggregates "
          "in the Placement service. Requires the [api_database] and "
          "[placement] sections of the nova configuration file to be "
          "populated."))
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Provide verbose output during execution.')
    # TODO(mriedem): Add an option for the 'remove aggregate' behavior.
    # We know that we want to mirror hosts aggregate membership to
    # placement, but regarding removal, what if the operator or some external
    # tool added the resource provider to an aggregate but there is no matching
    # host aggregate, e.g. ironic nodes or shared storage provider
    # relationships?
    # TODO(mriedem): Probably want an option to pass a specific host instead of
    # doing all of them.
    def sync_aggregates(self, verbose=False):
        """Synchronizes nova host aggregates with resource provider aggregates

        Adds nodes to missing provider aggregates in Placement.

        NOTE: Depending on the size of your deployment and the number of
        compute hosts in aggregates, this command could cause a non-negligible
        amount of traffic to the placement service and therefore is
        recommended to be run during maintenance windows.

        Return codes:

        * 0: Successful run
        * 1: A host was found with more than one matching compute node record
        * 2: An unexpected error occurred while working with the placement API
        * 3: Failed updating provider aggregates in placement
        * 4: Host mappings not found for one or more host aggregate members
        * 5: Compute node records not found for one or more hosts
        * 6: Resource provider not found by uuid for a given host
        """
        # Start by getting all host aggregates.
        ctxt = context.get_admin_context()
        aggregate_api = compute_api.AggregateAPI()
        placement = aggregate_api.placement_client
        aggregates = aggregate_api.get_aggregate_list(ctxt)
        # Now we're going to loop over the existing compute hosts in aggregates
        # and check to see if their corresponding resource provider, found via
        # the host's compute node uuid, are in the same aggregate. If not, we
        # add the resource provider to the aggregate in Placement.
        output = lambda msg: None
        if verbose:
            output = lambda msg: print(msg)
        output(_('Filling in missing placement aggregates'))
        # Since hosts can be in more than one aggregate, keep track of the host
        # to its corresponding resource provider uuid to avoid redundant
        # lookups.
        host_to_rp_uuid = {}
        unmapped_hosts = set()  # keep track of any missing host mappings
        computes_not_found = set()  # keep track of missing nodes
        providers_not_found = {}  # map of hostname to missing provider uuid
        for aggregate in aggregates:
            output(_('Processing aggregate: %s') % aggregate.name)
            for host in aggregate.hosts:
                output(_('Processing host: %s') % host)
                rp_uuid = host_to_rp_uuid.get(host)
                if not rp_uuid:
                    try:
                        rp_uuid = self._get_rp_uuid_for_host(ctxt, host)
                        host_to_rp_uuid[host] = rp_uuid
                    except exception.HostMappingNotFound:
                        # Don't fail on this now, we can dump it at the end.
                        unmapped_hosts.add(host)
                        continue
                    except exception.ComputeHostNotFound:
                        # Don't fail on this now, we can dump it at the end.
                        computes_not_found.add(host)
                        continue
                    except exception.TooManyComputesForHost as e:
                        # TODO(mriedem): Should we treat this like the other
                        # errors and not fail immediately but dump at the end?
                        print(e.format_message())
                        return 1

                # We've got our compute node record, so now we can look to
                # see if the matching resource provider, found via compute
                # node uuid, is in the same aggregate in placement, found via
                # aggregate uuid.
                # NOTE(mriedem): We could re-use placement.aggregate_add_host
                # here although that has to do the provider lookup by host as
                # well, but it does handle generation conflicts.
                resp = placement.get(  # use 1.19 to get the generation
                    '/resource_providers/%s/aggregates' % rp_uuid,
                    version='1.19')
                if resp:
                    body = resp.json()
                    provider_aggregate_uuids = body['aggregates']
                    # The moment of truth: is the provider in the same host
                    # aggregate relationship?
                    aggregate_uuid = aggregate.uuid
                    if aggregate_uuid not in provider_aggregate_uuids:
                        # Add the resource provider to this aggregate.
                        provider_aggregate_uuids.append(aggregate_uuid)
                        # Now update the provider aggregates using the
                        # generation to ensure we're conflict-free.
                        aggregate_update_body = {
                            'aggregates': provider_aggregate_uuids,
                            'resource_provider_generation':
                                body['resource_provider_generation']
                        }
                        put_resp = placement.put(
                            '/resource_providers/%s/aggregates' % rp_uuid,
                            aggregate_update_body, version='1.19')
                        if put_resp:
                            output(_('Successfully added host (%(host)s) and '
                                     'provider (%(provider)s) to aggregate '
                                     '(%(aggregate)s).') %
                                   {'host': host, 'provider': rp_uuid,
                                    'aggregate': aggregate_uuid})
                        elif put_resp.status_code == 404:
                            # We must have raced with a delete on the resource
                            # provider.
                            providers_not_found[host] = rp_uuid
                        else:
                            # TODO(mriedem): Handle 409 conflicts by retrying
                            # the operation.
                            print(_('Failed updating provider aggregates for '
                                    'host (%(host)s), provider (%(provider)s) '
                                    'and aggregate (%(aggregate)s). Error: '
                                    '%(error)s') %
                                  {'host': host, 'provider': rp_uuid,
                                   'aggregate': aggregate_uuid,
                                   'error': put_resp.text})
                            return 3
                elif resp.status_code == 404:
                    # The resource provider wasn't found. Store this for later.
                    providers_not_found[host] = rp_uuid
                else:
                    print(_('An error occurred getting resource provider '
                            'aggregates from placement for provider '
                            '%(provider)s. Error: %(error)s') %
                          {'provider': rp_uuid, 'error': resp.text})
                    return 2

        # Now do our error handling. Note that there is no real priority on
        # the error code we return. We want to dump all of the issues we hit
        # so the operator can fix them before re-running the command, but
        # whether we return 4 or 5 or 6 doesn't matter.
        return_code = 0
        if unmapped_hosts:
            print(_('The following hosts were found in nova host aggregates '
                    'but no host mappings were found in the nova API DB. Run '
                    '"nova-manage cell_v2 discover_hosts" and then retry. '
                    'Missing: %s') % ','.join(unmapped_hosts))
            return_code = 4

        if computes_not_found:
            print(_('Unable to find matching compute_nodes record entries in '
                    'the cell database for the following hosts; does the '
                    'nova-compute service on each host need to be restarted? '
                    'Missing: %s') % ','.join(computes_not_found))
            return_code = 5

        if providers_not_found:
            print(_('Unable to find matching resource provider record in '
                    'placement with uuid for the following hosts: %s. Try '
                    'restarting the nova-compute service on each host and '
                    'then retry.') %
                  ','.join('(%s=%s)' % (host, providers_not_found[host])
                           for host in sorted(providers_not_found.keys())))
            return_code = 6

        return return_code


CATEGORIES = {
    'api_db': ApiDbCommands,
    'cell': CellCommands,
    'cell_v2': CellV2Commands,
    'db': DbCommands,
    'floating': FloatingIpCommands,
    'network': NetworkCommands,
    'placement': PlacementCommands
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
