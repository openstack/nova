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

import collections
from contextlib import contextmanager
import functools
import os
import re
import sys
import time
import traceback
import typing as ty
from urllib import parse as urlparse

from dateutil import parser as dateutil_parser
from keystoneauth1 import exceptions as ks_exc
from neutronclient.common import exceptions as neutron_client_exc
from os_brick.initiator import connector
import os_resource_classes as orc
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import uuidutils
import prettytable
from sqlalchemy.engine import url as sqla_url

from nova.cmd import common as cmd_common
from nova.compute import api
from nova.compute import instance_actions
from nova.compute import rpcapi
import nova.conf
from nova import config
from nova import context
from nova.db import constants as db_const
from nova.db.main import api as db
from nova.db import migration
from nova import exception
from nova.i18n import _
from nova.limit import local as local_limit
from nova.limit import placement as placement_limit
from nova.network import constants
from nova.network import neutron as neutron_api
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.objects import compute_node as compute_node_obj
from nova.objects import fields as obj_fields
from nova.objects import host_mapping as host_mapping_obj
from nova.objects import instance as instance_obj
from nova.objects import instance_mapping as instance_mapping_obj
from nova.objects import pci_device as pci_device_obj
from nova.objects import quotas as quotas_obj
from nova.objects import virtual_interface as virtual_interface_obj
import nova.quota
from nova import rpc
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils
from nova import utils
from nova import version
from nova.virt.libvirt import machine_type_utils
from nova.volume import cinder

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

# Keep this list sorted and one entry per line for readability.
_EXTRA_DEFAULT_LOG_LEVELS = [
    'nova=ERROR',
    'oslo_concurrency=INFO',
    'oslo_db=INFO',
    'oslo_policy=INFO',
    'oslo.privsep=ERROR',
    'os_brick=ERROR',
]

# Consts indicating whether allocations need to be healed by creating them or
# by updating existing allocations.
_CREATE = 'create'
_UPDATE = 'update'

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


def format_dict(dct, dict_property="Property", dict_value='Value',
                sort_key=None):
    """Print a `dict` as a table of two columns.

    :param dct: `dict` to print
    :param dict_property: name of the first column
    :param dict_value: header label for the value (second) column
    :param sort_key: key used for sorting the dict
    """
    pt = prettytable.PrettyTable([dict_property, dict_value])
    pt.align = 'l'
    # starting in PrettyTable 3.4.0 we need to also set the header
    # as align now only applies to the data.
    if hasattr(pt, 'header_align'):
        pt.header_align = 'l'
    for k, v in sorted(dct.items(), key=sort_key):
        # convert dict to str to check length
        if isinstance(v, dict):
            v = str(v)
        # if value has a newline, add in multiple rows
        # e.g. fault with stacktrace
        if v and isinstance(v, str) and r'\n' in v:
            lines = v.strip().split(r'\n')
            col1 = k
            for line in lines:
                pt.add_row([col1, line])
                col1 = ''
        else:
            pt.add_row([k, v])

    return encodeutils.safe_encode(pt.get_string()).decode()


@contextmanager
def locked_instance(cell_mapping, instance, reason):
    """Context manager to lock and unlock instance,
    lock state will be restored regardless of the success or failure
    of target functionality.

    :param cell_mapping: instance-cell-mapping
    :param instance: instance to be lock and unlock
    :param reason: reason, why lock is required
    """

    compute_api = api.API()

    initial_state = 'locked' if instance.locked else 'unlocked'
    if not instance.locked:
        with context.target_cell(
                context.get_admin_context(), cell_mapping) as cctxt:
            compute_api.lock(cctxt, instance, reason=reason)
    try:
        yield
    finally:
        if initial_state == 'unlocked':
            with context.target_cell(
                    context.get_admin_context(), cell_mapping) as cctxt:
                compute_api.unlock(cctxt, instance)


class DbCommands(object):
    """Class for managing the main database."""

    # NOTE(danms): These functions are called with a DB context and a
    # count, which is the maximum batch size requested by the
    # user. They must be idempotent. At most $count records should be
    # migrated. The function must return a tuple of (found, done). The
    # found value indicates how many unmigrated/candidate records existed in
    # the database prior to the migration (either total, or up to the
    # $count limit provided), and a nonzero found value may tell the user
    # that there is still work to do. The done value indicates whether
    # or not any records were actually migrated by the function. Thus
    # if both (found, done) are nonzero, work was done and some work
    # remains. If found is nonzero and done is zero, some records are
    # not migratable (or don't need migrating), but all migrations that can
    # complete have finished.
    # NOTE(stephenfin): These names must be unique
    online_migrations = (
        # Added in Pike
        quotas_obj.migrate_quota_limits_to_api_db,
        # Added in Pike
        quotas_obj.migrate_quota_classes_to_api_db,
        # Added in Queens
        db.migration_migrate_to_uuid,
        # Added in Queens
        block_device_obj.BlockDeviceMapping.populate_uuids,
        # Added in Rocky
        # NOTE(tssurya): This online migration is going to be backported to
        # Queens and Pike since instance.avz of instances before Pike
        # need to be populated if it was not specified during boot time.
        instance_obj.populate_missing_availability_zones,
        # Added in Rocky
        instance_mapping_obj.populate_queued_for_delete,
        # Added in Stein
        compute_node_obj.migrate_empty_ratio,
        # Added in Stein
        virtual_interface_obj.fill_virtual_interface_list,
        # Added in Stein
        instance_mapping_obj.populate_user_id,
        # Added in Victoria
        pci_device_obj.PciDevice.populate_dev_uuids,
        # Added in 2023.2
        instance_obj.populate_instance_compute_id,
    )

    @args('--local_cell', action='store_true',
          help='Only sync db in the local cell: do not attempt to fan-out '
               'to all cells')
    @args('version', metavar='VERSION', nargs='?', help='Database version')
    def sync(self, version=None, local_cell=False):
        """Sync the database up to the most recent version."""
        if not local_cell:
            ctxt = context.RequestContext()
            # NOTE(mdoff): Multiple cells not yet implemented. Currently
            # fanout only looks for cell0.
            try:
                cell_mapping = objects.CellMapping.get_by_uuid(
                    ctxt, objects.CellMapping.CELL0_UUID,
                )
                with context.target_cell(ctxt, cell_mapping) as cctxt:
                    migration.db_sync(version, context=cctxt)
            except exception.CellMappingNotFound:
                msg = _(
                    'WARNING: cell0 mapping not found - not syncing cell0.'
                )
                print(msg)
            except Exception as e:
                msg = _(
                    'ERROR: Could not access cell0.\n'
                    'Has the nova_api database been created?\n'
                    'Has the nova_cell0 database been created?\n'
                    'Has "nova-manage api_db sync" been run?\n'
                    'Has "nova-manage cell_v2 map_cell0" been run?\n'
                    'Is [api_database]/connection set in nova.conf?\n'
                    'Is the cell0 database connection URL correct?\n'
                    'Error: %s'
                )
                print(msg % str(e))
                return 1

        return migration.db_sync(version)

    def version(self):
        """Print the current database version."""
        print(migration.db_version())

    @args('--max_rows', type=int, metavar='<number>', dest='max_rows',
          help='Maximum number of deleted rows to archive per table. Defaults '
               'to 1000. Note that this number is a soft limit and does not '
               'include the corresponding rows, if any, that are removed '
               'from the API database for deleted instances.')
    @args('--before', metavar='<date>',
          help=('Archive rows that have been deleted before this date. '
                'Accepts date strings in the default format output by the '
                '``date`` command, as well as ``YYYY-MM-DD [HH:mm:ss]``.'))
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Print how many rows were archived per table.')
    @args('--until-complete', action='store_true', dest='until_complete',
          default=False,
          help=('Run continuously until all deleted rows are archived. Use '
                'max_rows as a batch size for each iteration.'))
    @args('--purge', action='store_true', dest='purge', default=False,
          help='Purge all data from shadow tables after archive completes')
    @args('--all-cells', action='store_true', dest='all_cells',
          default=False, help='Run command across all cells.')
    @args('--task-log', action='store_true', dest='task_log', default=False,
          help=('Also archive ``task_log`` table records. Note that '
                '``task_log`` records are never deleted, so archiving them '
                'will move all of the ``task_log`` records up to now into the '
                'shadow tables. It is recommended to also specify the '
                '``--before`` option to avoid races for those consuming '
                '``task_log`` record data via the '
                '``/os-instance_usage_audit_log`` API (example: Telemetry).'))
    @args('--sleep', type=int, metavar='<seconds>', dest='sleep',
          help='The amount of time in seconds to sleep between batches when '
               '``--until-complete`` is used. Defaults to 0.')
    def archive_deleted_rows(
        self, max_rows=1000, verbose=False,
        until_complete=False, purge=False,
        before=None, all_cells=False, task_log=False, sleep=0,
    ):
        """Move deleted rows from production tables to shadow tables.

        Returns 0 if nothing was archived, 1 if some number of rows were
        archived, 2 if max_rows is invalid, 3 if no connection could be
        established to the API DB, 4 if before date is invalid. If automating,
        this should be run continuously while the result
        is 1, stopping at 0.
        """
        max_rows = int(max_rows)
        if max_rows < 0:
            print(_("Must supply a positive value for max_rows"))
            return 2
        if max_rows > db_const.MAX_INT:
            print(_('max rows must be <= %(max_value)d') %
                  {'max_value': db_const.MAX_INT})
            return 2

        ctxt = context.get_admin_context()
        try:
            # NOTE(tssurya): This check has been added to validate if the API
            # DB is reachable or not as this is essential for purging the
            # related API database records of the deleted instances.
            cell_mappings = objects.CellMappingList.get_all(ctxt)
        except db_exc.CantStartEngineError:
            print(_('Failed to connect to API DB so aborting this archival '
                    'attempt. Please check your config file to make sure that '
                    '[api_database]/connection is set and run this '
                    'command again.'))
            return 3

        if before:
            try:
                before_date = dateutil_parser.parse(before, fuzzy=True)
            except ValueError as e:
                print(_('Invalid value for --before: %s') % e)
                return 4
        else:
            before_date = None

        table_to_rows_archived = {}
        if until_complete and verbose:
            sys.stdout.write(_('Archiving') + '..')  # noqa

        interrupt = False

        if all_cells:
            # Sort first by cell name, then by table:
            # +--------------------------------+-------------------------+
            # | Table                          | Number of Rows Archived |
            # +--------------------------------+-------------------------+
            # | cell0.block_device_mapping     | 1                       |
            # | cell1.block_device_mapping     | 1                       |
            # | cell1.instance_actions         | 2                       |
            # | cell1.instance_actions_events  | 2                       |
            # | cell2.block_device_mapping     | 1                       |
            # | cell2.instance_actions         | 2                       |
            # | cell2.instance_actions_events  | 2                       |
            # ...
            def sort_func(item):
                cell_name, table = item[0].split('.')
                return cell_name, table
            print_sort_func = sort_func
        else:
            cell_mappings = [None]
            print_sort_func = None
        total_rows_archived = 0
        for cell_mapping in cell_mappings:
            # NOTE(Kevin_Zheng): No need to calculate limit for each
            # cell if until_complete=True.
            # We need not adjust max rows to avoid exceeding a specified total
            # limit because with until_complete=True, we have no total limit.
            if until_complete:
                max_rows_to_archive = max_rows
            elif max_rows > total_rows_archived:
                # We reduce the max rows to archive based on what we've
                # archived so far to avoid potentially exceeding the specified
                # total limit.
                max_rows_to_archive = max_rows - total_rows_archived
            else:
                break
            # If all_cells=False, cell_mapping is None
            with context.target_cell(ctxt, cell_mapping) as cctxt:
                cell_name = cell_mapping.name if cell_mapping else None
                try:
                    rows_archived = self._do_archive(
                        table_to_rows_archived,
                        cctxt,
                        max_rows_to_archive,
                        until_complete,
                        verbose,
                        before_date,
                        cell_name,
                        task_log,
                        sleep)
                except KeyboardInterrupt:
                    interrupt = True
                    break
                # TODO(melwitt): Handle skip/warn for unreachable cells. Note
                # that cell_mappings = [None] if not --all-cells
                total_rows_archived += rows_archived

        if until_complete and verbose:
            if interrupt:
                print('.' + _('stopped'))  # noqa
            else:
                print('.' + _('complete'))  # noqa

        if verbose:
            if table_to_rows_archived:
                print(format_dict(
                    table_to_rows_archived,
                    dict_property=_('Table'),
                    dict_value=_('Number of Rows Archived'),
                    sort_key=print_sort_func,
                ))
            else:
                print(_('Nothing was archived.'))

        if table_to_rows_archived and purge:
            if verbose:
                print(_('Rows were archived, running purge...'))
            self.purge(purge_all=True, verbose=verbose, all_cells=all_cells)

        # NOTE(danms): Return nonzero if we archived something
        return int(bool(table_to_rows_archived))

    def _do_archive(
        self, table_to_rows_archived, cctxt, max_rows,
        until_complete, verbose, before_date, cell_name, task_log, sleep,
    ):
        """Helper function for archiving deleted rows for a cell.

        This will archive deleted rows for a cell database and remove the
        associated API database records for deleted instances.

        :param table_to_rows_archived: Dict tracking the number of rows
            archived by <cell_name>.<table name>. Example:
            {'cell0.instances': 2,
             'cell1.instances': 5}
        :param cctxt: Cell-targeted nova.context.RequestContext if archiving
            across all cells
        :param max_rows: Maximum number of deleted rows to archive per table.
            Note that this number is a soft limit and does not include the
            corresponding rows, if any, that are removed from the API database
            for deleted instances.
        :param until_complete: Whether to run continuously until all deleted
            rows are archived
        :param verbose: Whether to print how many rows were archived per table
        :param before_date: Archive rows that were deleted before this date
        :param cell_name: Name of the cell or None if not archiving across all
            cells
        :param task_log: Whether to archive task_log table rows
        :param sleep: The amount of time in seconds to sleep between batches
            when ``until_complete`` is True.
        """
        ctxt = context.get_admin_context()
        while True:
            # table_to_rows = {table_name: number_of_rows_archived}
            # deleted_instance_uuids = ['uuid1', 'uuid2', ...]
            table_to_rows, deleted_instance_uuids, total_rows_archived = \
                db.archive_deleted_rows(
                    cctxt, max_rows, before=before_date, task_log=task_log)

            for table_name, rows_archived in table_to_rows.items():
                if cell_name:
                    table_name = cell_name + '.' + table_name
                table_to_rows_archived.setdefault(table_name, 0)
                table_to_rows_archived[table_name] += rows_archived

            # deleted_instance_uuids does not necessarily mean that any
            # instances rows were archived because it is obtained by a query
            # separate from the archive queries. For example, if a
            # DBReferenceError was raised while processing the instances table,
            # we would have skipped the table and had 0 rows archived even
            # though deleted instances rows were found.
            instances_archived = table_to_rows.get('instances', 0)
            if deleted_instance_uuids and instances_archived:
                table_to_rows_archived.setdefault(
                    'API_DB.instance_mappings', 0)
                table_to_rows_archived.setdefault(
                    'API_DB.request_specs', 0)
                table_to_rows_archived.setdefault(
                    'API_DB.instance_group_member', 0)
                deleted_mappings = objects.InstanceMappingList.destroy_bulk(
                            ctxt, deleted_instance_uuids)
                table_to_rows_archived[
                    'API_DB.instance_mappings'] += deleted_mappings
                deleted_specs = objects.RequestSpec.destroy_bulk(
                    ctxt, deleted_instance_uuids)
                table_to_rows_archived[
                    'API_DB.request_specs'] += deleted_specs
                deleted_group_members = (
                    objects.InstanceGroup.destroy_members_bulk(
                        ctxt, deleted_instance_uuids))
                table_to_rows_archived[
                    'API_DB.instance_group_member'] += deleted_group_members

            # If we're not archiving until there is nothing more to archive, we
            # have reached max_rows in this cell DB or there was nothing to
            # archive. We check the values() in case we get something like
            # table_to_rows = {'instances': 0} back somehow.
            if not until_complete or not any(table_to_rows.values()):
                break
            if verbose:
                sys.stdout.write('.')
            # Optionally sleep between batches to throttle the archiving.
            time.sleep(sleep)
        return total_rows_archived

    @args('--before', metavar='<before>', dest='before',
          help='If specified, purge rows from shadow tables that are older '
               'than this. Accepts date strings in the default format output '
               'by the ``date`` command, as well as ``YYYY-MM-DD '
               '[HH:mm:ss]``.')
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
                    deleted += db.purge_shadow_tables(
                        cctxt, before_date, status_fn=status)
        else:
            identity = _('DB')
            deleted = db.purge_shadow_tables(
                admin_ctxt, before_date, status_fn=status)
        if deleted:
            return 0
        else:
            return 3

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
            # This is the per-migration method result for this batch, and
            # _run_migration will either continue on to the next migration,
            # or stop if up to this point we've processed max_count of
            # records across all migration methods.
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
            # For each batch of migration method results, build the cumulative
            # set of results.
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
                                     _('Total Needed'),  # Really: Total Found
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

    @args('--ironic-node-uuid', metavar='<uuid>', dest='compute_node_uuid',
          help='UUID of Ironic node to be moved between services')
    @args('--destination-host', metavar='<host>',
          dest='destination_service_host',
          help='Destination ironic nova-compute service CONF.host')
    def ironic_compute_node_move(self, compute_node_uuid,
                                 destination_service_host):
        ctxt = context.get_admin_context()

        destination_service = objects.Service.get_by_compute_host(
            ctxt, destination_service_host)
        if destination_service.forced_down:
            raise exception.NovaException(
                "Destination compute is forced down!")

        target_compute_node = objects.ComputeNode.get_by_uuid(
            ctxt, compute_node_uuid)
        source_service = objects.Service.get_by_id(
            ctxt, target_compute_node.service_id)
        if not source_service.forced_down:
            raise exception.NovaException(
                "Source service is not yet forced down!")

        instances = objects.InstanceList.get_by_host_and_node(
            ctxt, target_compute_node.host,
            target_compute_node.hypervisor_hostname)
        if len(instances) > 1:
            raise exception.NovaException(
                "Found an ironic host with more than one instance! "
                "Please delete all Nova instances that do not match "
                "the instance uuid recorded on the Ironic node.")

        target_compute_node.service_id = destination_service.id
        target_compute_node.host = destination_service.host
        target_compute_node.save()

        for instance in instances:
            # this is a bit like evacuate, except no need to rebuild
            instance.host = destination_service.host
            instance.save()


class ApiDbCommands(object):
    """Class for managing the api database."""

    def __init__(self):
        pass

    @args('version', metavar='VERSION', nargs='?', help='Database version')
    def sync(self, version=None):
        """Sync the database up to the most recent version."""
        return migration.db_sync(version, database='api')

    def version(self):
        """Print the current database version."""
        print(migration.db_version(database='api'))


class CellV2Commands(object):
    """Commands for managing cells v2."""

    def _validate_transport_url(self, transport_url, warn_about_none=True):
        if not transport_url:
            if not CONF.transport_url:
                if warn_about_none:
                    print(_(
                        'Must specify --transport-url if '
                        '[DEFAULT]/transport_url is not set in the '
                        'configuration file.'))
                return None
            print(_('--transport-url not provided in the command line, '
                    'using the value [DEFAULT]/transport_url from the '
                    'configuration file'))
            transport_url = CONF.transport_url

        try:
            messaging.TransportURL.parse(conf=CONF,
                                         url=objects.CellMapping.format_mq_url(
                                             transport_url))
        except (messaging.InvalidTransportURL, ValueError) as e:
            print(_('Invalid transport URL: %s') % str(e))
            return None

        return transport_url

    def _validate_database_connection(
            self, database_connection, warn_about_none=True):
        if not database_connection:
            if not CONF.database.connection:
                if warn_about_none:
                    print(_(
                        'Must specify --database_connection if '
                        '[database]/connection is not set in the '
                        'configuration file.'))
                return None
            print(_('--database_connection not provided in the command line, '
                    'using the value [database]/connection from the '
                    'configuration file'))
            return CONF.database.connection
        return database_connection

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
        configure the default environment. Returns 0 if setup is completed (or
        has already been done) and 1 if no hosts are reporting (and this cannot
        be mapped).
        """
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
        """Facilitate creation of a cell mapping for cell0.
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
            url = url.set(database=url.database + '_cell0')

            return urlparse.unquote(url.render_as_string(hide_password=False))

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
                mapping.user_id = instance.user_id
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
        # the UUID field and we need something reversible. For more
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
            # This is just the marker record, so set user_id to the special
            # marker name as well.
            objects.InstanceMapping(ctxt, instance_uuid=next_marker,
                    project_id=marker_project_id,
                    user_id=marker_project_id).create()
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
            print(_('All hosts are already mapped to cell(s).'))
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
                            say('Execute '
                                '`nova-manage db archive_deleted_rows` '
                                'command to archive this deleted '
                                'instance and remove its instance_mapping.')
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
                 'failure (non-zero exit code).'))
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

        This command should be run once after all compute hosts have been
        deployed and should not be run in parallel. When run in parallel,
        the commands will collide with each other trying to map the same hosts
        in the database at the same time.
        """
        def status_fn(msg):
            if verbose:
                print(msg)

        ctxt = context.RequestContext()
        try:
            hosts = host_mapping_obj.discover_hosts(ctxt, cell_uuid, status_fn,
                                                    by_service)
        except exception.HostMappingExists as exp:
            print(_('ERROR: Duplicate host mapping was encountered. This '
                    'command should be run once after all compute hosts have '
                    'been deployed and should not be run in parallel. When '
                    'run in parallel, the commands will collide with each '
                    'other trying to map the same hosts in the database at '
                    'the same time. Error: %s') % exp)
            return 2
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

        database_connection = self._validate_database_connection(
            database_connection)
        if not database_connection:
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
        for cell in sorted(cell_mappings,
                           # CellMapping.name is optional
                           key=lambda _cell: _cell.name or ''):
            fields = [cell.name or '', cell.uuid]
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

        # Having empty transport_url and db_connection means leaving the
        # existing values
        transport_url = self._validate_transport_url(
            transport_url, warn_about_none=False)
        db_connection = self._validate_database_connection(
            db_connection, warn_about_none=False)

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

        NOTE: The scheduler caches host-to-cell mapping information so when
        deleting a host the scheduler may need to be restarted or sent the
        SIGHUP signal.
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

    @staticmethod
    def _get_ports(ctxt, instance, neutron):
        """Return the ports that are bound to the instance

        :param ctxt: nova.context.RequestContext
        :param instance: the instance to return the ports for
        :param neutron: nova.network.neutron.ClientWrapper to
            communicate with Neutron
        :return: a list of neutron port dict objects
        :raise UnableToQueryPorts: If the neutron list ports query fails.
        """
        try:
            return neutron.list_ports(
                ctxt, device_id=instance.uuid,
                fields=['id', constants.RESOURCE_REQUEST,
                        constants.BINDING_PROFILE]
            )['ports']
        except neutron_client_exc.NeutronClientException as e:
            raise exception.UnableToQueryPorts(
                instance_uuid=instance.uuid, error=str(e))

    @staticmethod
    def _has_request_but_no_allocation(port, neutron):
        has_res_req = neutron_api.API()._has_resource_request(
            context.get_admin_context(), port, neutron)

        binding_profile = neutron_api.get_binding_profile(port)
        allocation = binding_profile.get(constants.ALLOCATION)
        return has_res_req and not allocation

    @staticmethod
    def _merge_allocations(alloc1, alloc2):
        """Return a new allocation dict that contains the sum of alloc1 and
        alloc2.

        :param alloc1: a dict in the form of
            {
                <rp_uuid>: {'resources': {<resource class>: amount,
                                          <resource class>: amount},
                <rp_uuid>: {'resources': {<resource class>: amount},
            }
        :param alloc2: a dict in the same form as alloc1
        :return: the merged allocation of alloc1 and alloc2 in the same format
        """

        allocations = collections.defaultdict(
            lambda: {'resources': collections.defaultdict(int)})

        for alloc in [alloc1, alloc2]:
            for rp_uuid in alloc:
                for rc, amount in alloc[rp_uuid]['resources'].items():
                    allocations[rp_uuid]['resources'][rc] += amount
        return allocations

    @staticmethod
    def _get_resource_request_from_ports(
        ctxt: context.RequestContext,
        ports: ty.List[ty.Dict[str, ty.Any]]
    ) -> ty.Tuple[
            ty.Dict[str, ty.List['objects.RequestGroup']],
            'objects.RequestLevelParams']:
        """Collect RequestGroups and RequestLevelParams for all ports

        :param ctxt: the request context
        :param ports: a list of port dicts
        :returns: A two tuple where the first item is a dict mapping port
            uuids to a list of request groups coming from that port, the
            second item is a combined RequestLevelParams object from all ports.
        """
        groups = {}
        request_level_params = objects.RequestLevelParams()
        extended_res_req = (
            neutron_api.API().has_extended_resource_request_extension(
                ctxt)
        )

        for port in ports:
            resource_request = port.get(constants.RESOURCE_REQUEST)
            if extended_res_req:
                groups[port['id']] = (
                    objects.RequestGroup.from_extended_port_request(
                        ctxt, resource_request
                    )
                )
                request_level_params.extend_with(
                    objects.RequestLevelParams.from_port_request(
                        resource_request
                    )
                )
            else:
                # This is the legacy format, only one group per port and no
                # request level param support
                # TODO(gibi): remove this path once the extended resource
                # request extension is mandatory in neutron
                groups[port['id']] = [
                    objects.RequestGroup.from_port_request(
                        ctxt, port['id'], resource_request
                    )
                ]

        return groups, request_level_params

    @staticmethod
    def _get_port_binding_profile_allocation(
        ctxt: context.RequestContext,
        neutron: neutron_api.ClientWrapper,
        port: ty.Dict[str, ty.Any],
        request_groups: ty.List['objects.RequestGroup'],
        resource_provider_mapping: ty.Dict[str, ty.List[str]],
    ) -> ty.Dict[str, str]:
        """Generate the value of the allocation key of the port binding profile
        based on the provider mapping returned from placement

        :param ctxt: the request context
        :param neutron: the neutron client
        :param port: the port dict from neutron
        :param request_groups: the list of RequestGroups object generated from
            the port resource request
        :param resource_provider_mapping: The dict of request group to resource
            provider mapping returned by the Placement allocation candidate
            query
        :returns: a dict mapping request group ids to resource provider uuids
            in the form as Neutron expects in the port binding profile.
        """
        if neutron_api.API().has_extended_resource_request_extension(
            ctxt, neutron
        ):
            # The extended resource request format also means that a
            # port has more than a one request groups.
            # Each request group id from the port needs to be mapped to
            # a single provider id from the provider mappings. Each
            # group from the port is mapped to a numbered request group
            # in placement so we can assume that they are mapped to
            # a single provider and therefore the provider mapping list
            # has a single provider id.
            allocation = {
                group.requester_id: resource_provider_mapping[
                    group.requester_id][0]
                for group in request_groups
            }
        else:
            # This is the legacy resource request format where a port
            # is mapped to a single request group
            # NOTE(gibi): In the resource provider mapping there can be
            # more than one RP fulfilling a request group. But resource
            # requests of a Neutron port is always mapped to a
            # numbered request group that is always fulfilled by one
            # resource provider. So we only pass that single RP UUID
            # here.
            allocation = resource_provider_mapping[
                port['id']][0]

        return allocation

    def _get_port_allocations_to_heal(
            self, ctxt, instance, node_cache, placement, neutron, output):
        """Return the needed extra allocation for the ports of the instance.

        :param ctxt: nova.context.RequestContext
        :param instance: instance to get the port allocations for
        :param node_cache: dict of Instance.node keys to ComputeNode.uuid
            values; this cache is updated if a new node is processed.
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param neutron: nova.network.neutron.ClientWrapper to
            communicate with Neutron
        :param output: function that takes a single message for verbose output
        :raise UnableToQueryPorts: If the neutron list ports query fails.
        :raise nova.exception.ComputeHostNotFound: if compute node of the
            instance not found in the db.
        :raise PlacementAPIConnectFailure: if placement API cannot be reached
        :raise AllocationUpdateFailed: if there is either no allocation
            candidate returned from placement for the missing port allocations
            or there are more than one candidates making the healing
            ambiguous.
        :return: A two tuple where the first item is a dict of resources keyed
            by RP uuid to be included in the instance allocation dict. The
            second item is a list of port dicts to be updated in Neutron.
        """
        # We need to heal port allocations for ports that have resource_request
        # but do not have an RP uuid in the binding:profile.allocation field.
        # We cannot use the instance info_cache to check the binding profile
        # as this code needs to be able to handle ports that were attached
        # before nova in stein started updating the allocation key in the
        # binding:profile.
        # In theory a port can be assigned to an instance without it being
        # bound to any host (e.g. in case of shelve offload) but
        # _heal_allocations_for_instance() already filters out instances that
        # are not on any host.
        ports_to_heal = [
            port for port in self._get_ports(ctxt, instance, neutron)
            if self._has_request_but_no_allocation(port, neutron)]

        if not ports_to_heal:
            # nothing to do, return early
            return {}, []

        node_uuid = self._get_compute_node_uuid(
            ctxt, instance, node_cache)

        # NOTE(gibi): We need to handle both legacy and extended resource
        # request. So we need to handle ports with multiple request groups
        # allocating from multiple providers.
        # The logic what we follow here is pretty similar to the logic
        # implemented in ComputeManager._allocate_port_resource_for_instance
        # for the interface attach case. We just apply it to more then one
        # ports here.
        request_groups_per_port, req_lvl_params = (
            self._get_resource_request_from_ports(ctxt, ports_to_heal)
        )
        # flatten the list of list of groups
        request_groups = [
            group
            for groups in request_groups_per_port.values()
            for group in groups
        ]

        # we can have multiple request groups, it would be enough to restrict
        # only one of them to the compute tree but for symmetry we restrict
        # all of them
        for request_group in request_groups:
            request_group.in_tree = node_uuid

        # If there are multiple groups then the group_policy is mandatory in
        # the allocation candidate query. We can assume that if this instance
        # booted successfully then we have the policy in the flavor. If there
        # is only one group and therefore no policy then the value of the
        # policy in the allocation candidate query is ignored, so we simply
        # default it here.
        group_policy = instance.flavor.extra_specs.get("group_policy", "none")

        rr = scheduler_utils.ResourceRequest.from_request_groups(
            request_groups, req_lvl_params, group_policy)
        res = placement.get_allocation_candidates(ctxt, rr)
        # NOTE(gibi): the get_allocation_candidates method has the
        # @safe_connect decorator applied. Such decorator will return None
        # if the connection to Placement is failed. So we raise an exception
        # here. The case when Placement successfully return a response, even
        # if it is a negative or empty response, the method will return a three
        # tuple. That case is handled couple of lines below.
        if not res:
            raise exception.PlacementAPIConnectFailure()
        alloc_reqs, __, __ = res

        if not alloc_reqs:
            port_ids = [port['id'] for port in ports_to_heal]
            raise exception.AllocationUpdateFailed(
                consumer_uuid=instance.uuid,
                error=f'Placement returned no allocation candidate to fulfill '
                      f'the resource request of the port(s) {port_ids}'
            )
        if len(alloc_reqs) > 1:
            # If there is more than one candidates then it is an ambiguous
            # situation that we cannot handle here because selecting the right
            # one might need extra information from the compute node. For
            # example which PCI PF the VF is allocated from and which RP
            # represents that PCI PF in placement.
            # TODO(gibi): One way to get that missing information to resolve
            # ambiguity would be to load up the InstancePciRequest objects and
            # try to use the parent_if_name in their spec to find the proper
            # candidate that allocates for the same port from the PF RP that
            # has the same name.
            port_ids = [port['id'] for port in ports_to_heal]
            raise exception.AllocationUpdateFailed(
                consumer_uuid=instance.uuid,
                error=f'Placement returned more than one possible allocation '
                      f'candidates to fulfill the resource request of the '
                      f'port(s) {port_ids}. This script does not have enough '
                      f'information to select the proper candidate to heal the'
                      f'missing allocations. A possible way to heal the'
                      f'allocation of this instance is to migrate it to '
                      f'another compute as the migration process re-creates '
                      f'the full allocation on the target host.'
            )

        # so we have one candidate, lets use that to get the needed allocations
        # and the provider mapping for the ports' binding profile
        alloc_req = alloc_reqs[0]
        allocations = alloc_req["allocations"]
        provider_mappings = alloc_req["mappings"]

        for port in ports_to_heal:
            # We also need to record the RPs we are allocated from in the
            # port. This will be sent back to Neutron before the allocation
            # is updated in placement
            profile_allocation = self._get_port_binding_profile_allocation(
                ctxt, neutron, port, request_groups_per_port[port['id']],
                provider_mappings
            )
            binding_profile = neutron_api.get_binding_profile(port)
            binding_profile[constants.ALLOCATION] = profile_allocation
            port[constants.BINDING_PROFILE] = binding_profile

            output(_(
                "Found a request group : resource provider mapping "
                "%(mapping)s for the port %(port_uuid)s with resource request "
                "%(request)s attached to the instance %(instance_uuid)s") %
                {"mapping": profile_allocation, "port_uuid": port['id'],
                 "request": port.get(constants.RESOURCE_REQUEST),
                 "instance_uuid": instance.uuid}
            )

        return allocations, ports_to_heal

    def _update_ports(self, neutron, ports_to_update, output):
        succeeded = []
        try:
            for port in ports_to_update:
                profile = neutron_api.get_binding_profile(port)
                body = {
                    'port': {
                        constants.BINDING_PROFILE: profile
                    }
                }
                output(
                    _('Updating port %(port_uuid)s with attributes '
                      '%(attributes)s') %
                      {'port_uuid': port['id'], 'attributes': body['port']})
                neutron.update_port(port['id'], body=body)
                succeeded.append(port)
        except neutron_client_exc.NeutronClientException as e:
            output(
                _('Updating port %(port_uuid)s failed: %(error)s') %
                {'port_uuid': port['id'], 'error': str(e)})
            # one of the port updates failed. We need to roll back the updates
            # that succeeded before
            self._rollback_port_updates(neutron, succeeded, output)
            # we failed to heal so we need to stop but we successfully rolled
            # back the partial updates so the admin can retry the healing.
            raise exception.UnableToUpdatePorts(error=str(e))

    @staticmethod
    def _rollback_port_updates(neutron, ports_to_rollback, output):
        # _update_ports() added the allocation key to these ports, so we need
        # to remove them during the rollback.
        manual_rollback_needed = []
        last_exc = None
        for port in ports_to_rollback:
            profile = neutron_api.get_binding_profile(port)
            profile.pop(constants.ALLOCATION)
            body = {
                'port': {
                    constants.BINDING_PROFILE: profile
                }
            }
            try:
                output(_('Rolling back port update for %(port_uuid)s') %
                       {'port_uuid': port['id']})
                neutron.update_port(port['id'], body=body)
            except neutron_client_exc.NeutronClientException as e:
                output(
                    _('Rolling back update for port %(port_uuid)s failed: '
                      '%(error)s') % {'port_uuid': port['id'],
                                      'error': str(e)})
                # TODO(gibi): We could implement a retry mechanism with
                # back off.
                manual_rollback_needed.append(port['id'])
                last_exc = e

        if manual_rollback_needed:
            # At least one of the port operation failed so we failed to roll
            # back. There are partial updates in neutron. Human intervention
            # needed.
            raise exception.UnableToRollbackPortUpdates(
                error=str(last_exc),
                port_uuids=manual_rollback_needed)

    def _heal_missing_alloc(self, ctxt, instance, node_cache):
        node_uuid = self._get_compute_node_uuid(
            ctxt, instance, node_cache)

        # Now get the resource allocations for the instance based
        # on its embedded flavor.
        resources = scheduler_utils.resources_from_flavor(
            instance, instance.flavor)

        payload = {
            'allocations': {
                node_uuid: {'resources': resources},
            },
            'project_id': instance.project_id,
            'user_id': instance.user_id,
            'consumer_generation': None
        }
        return payload

    def _heal_missing_project_and_user_id(self, allocations, instance):
        allocations['project_id'] = instance.project_id
        allocations['user_id'] = instance.user_id
        return allocations

    @staticmethod
    def ensure_instance_has_no_vgpu_request(instance):
        if instance.flavor.extra_specs.get("resources:VGPU"):
            raise exception.HealvGPUAllocationNotSupported(
                instance_uuid=instance.uuid)

    @staticmethod
    def ensure_instance_has_no_cyborg_device_profile_request(instance):
        if instance.flavor.extra_specs.get("accel:device_profile"):
            raise exception.HealDeviceProfileAllocationNotSupported(
                instance_uuid=instance.uuid)

    def _heal_allocations_for_instance(self, ctxt, instance, node_cache,
                                       output, placement, dry_run,
                                       heal_port_allocations, neutron,
                                       force):
        """Checks the given instance to see if it needs allocation healing

        :param ctxt: cell-targeted nova.context.RequestContext
        :param instance: the instance to check for allocation healing
        :param node_cache: dict of Instance.node keys to ComputeNode.uuid
            values; this cache is updated if a new node is processed.
        :param output: function that takes a single message for verbose output
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param dry_run: Process instances and print output but do not commit
            any changes.
        :param heal_port_allocations: True if healing port allocation is
            requested, False otherwise.
        :param neutron: nova.network.neutron.ClientWrapper to
            communicate with Neutron
        :param force: True if force healing is requested for particular
            instance, False otherwise.
        :return: True if allocations were created or updated for the instance,
            None if nothing needed to be done
        :raises: nova.exception.ComputeHostNotFound if a compute node for a
            given instance cannot be found
        :raises: AllocationCreateFailed if unable to create allocations for
            a given instance against a given compute node resource provider
        :raises: AllocationUpdateFailed if unable to update allocations for
            a given instance with consumer project/user information
        :raise UnableToQueryPorts: If the neutron list ports query fails.
        :raise PlacementAPIConnectFailure: if placement API cannot be reached
        :raise UnableToUpdatePorts: if a port update failed in neutron but any
            partial update was rolled back successfully.
        :raise UnableToRollbackPortUpdates: if a port update failed in neutron
            and the rollback of the partial updates also failed.
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

        self.ensure_instance_has_no_vgpu_request(instance)
        self.ensure_instance_has_no_cyborg_device_profile_request(instance)

        try:
            allocations = placement.get_allocs_for_consumer(
                ctxt, instance.uuid)
        except (ks_exc.ClientException,
                exception.ConsumerAllocationRetrievalFailed) as e:
            raise exception.AllocationUpdateFailed(
                consumer_uuid=instance.uuid,
                error=_("Allocation retrieval failed: %s") % e)

        need_healing = False

        # Placement response can have an empty {'allocations': {}} in it if
        # there are no allocations for the instance
        if not allocations.get('allocations'):
            # This instance doesn't have allocations
            need_healing = _CREATE
            allocations = self._heal_missing_alloc(ctxt, instance, node_cache)

        if (allocations.get('project_id') != instance.project_id or
                allocations.get('user_id') != instance.user_id):
            # We have an instance with allocations but not the correct
            # project_id/user_id, so we want to update the allocations
            # and re-put them. We don't use put_allocations here
            # because we don't want to mess up shared or nested
            # provider allocations.
            need_healing = _UPDATE
            allocations = self._heal_missing_project_and_user_id(
                allocations, instance)

        if force:
            output(_('Force flag passed for instance %s') % instance.uuid)
            need_healing = _UPDATE
            # get default allocations
            alloc = self._heal_missing_alloc(ctxt, instance, node_cache)
            # set consumer generation of existing allocations
            alloc["consumer_generation"] = allocations["consumer_generation"]
            # set allocations
            allocations = alloc

        if heal_port_allocations:
            to_heal = self._get_port_allocations_to_heal(
                ctxt, instance, node_cache, placement, neutron, output)
            port_allocations, ports_to_update = to_heal
        else:
            port_allocations, ports_to_update = {}, []

        if port_allocations:
            need_healing = need_healing or _UPDATE
            # Merge in any missing port allocations
            allocations['allocations'] = self._merge_allocations(
                allocations['allocations'], port_allocations)

        if need_healing:
            if dry_run:
                # json dump the allocation dict as it contains nested default
                # dicts that is pretty hard to read in the verbose output
                alloc = jsonutils.dumps(allocations)
                if need_healing == _CREATE:
                    output(_('[dry-run] Create allocations for instance '
                             '%(instance)s: %(allocations)s') %
                           {'instance': instance.uuid,
                            'allocations': alloc})
                elif need_healing == _UPDATE:
                    output(_('[dry-run] Update allocations for instance '
                             '%(instance)s: %(allocations)s') %
                           {'instance': instance.uuid,
                            'allocations': alloc})
            else:
                # First update ports in neutron. If any of those operations
                # fail, then roll back the successful part of it and fail the
                # healing. We do this first because rolling back the port
                # updates is more straight-forward than rolling back allocation
                # changes.
                self._update_ports(neutron, ports_to_update, output)

                # Now that neutron update succeeded we can try to update
                # placement. If it fails we need to rollback every neutron port
                # update done before.
                resp = placement.put_allocations(ctxt, instance.uuid,
                                                 allocations)
                if resp:
                    if need_healing == _CREATE:
                        output(_('Successfully created allocations for '
                                 'instance %(instance)s.') %
                               {'instance': instance.uuid})
                    elif need_healing == _UPDATE:
                        output(_('Successfully updated allocations for '
                                 'instance %(instance)s.') %
                               {'instance': instance.uuid})
                    return True
                else:
                    # Rollback every neutron update. If we succeed to
                    # roll back then it is safe to stop here and let the admin
                    # retry. If the rollback fails then
                    # _rollback_port_updates() will raise another exception
                    # that instructs the operator how to clean up manually
                    # before the healing can be retried
                    self._rollback_port_updates(
                        neutron, ports_to_update, output)
                    raise exception.AllocationUpdateFailed(
                        consumer_uuid=instance.uuid, error='')
        else:
            output(_('The allocation of instance %s is up-to-date. '
                     'Nothing to be healed.') % instance.uuid)
            return

    def _heal_instances_in_cell(self, ctxt, max_count, unlimited, output,
                                placement, dry_run, instance_uuid,
                                heal_port_allocations, neutron,
                                force):
        """Checks for instances to heal in a given cell.

        :param ctxt: cell-targeted nova.context.RequestContext
        :param max_count: batch size (limit per instance query)
        :param unlimited: True if all instances in the cell should be
            processed, else False to just process $max_count instances
        :param output: function that takes a single message for verbose output
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param dry_run: Process instances and print output but do not commit
            any changes.
        :param instance_uuid: UUID of a specific instance to process.
        :param heal_port_allocations: True if healing port allocation is
            requested, False otherwise.
        :param neutron: nova.network.neutron.ClientWrapper to
            communicate with Neutron
        :param force: True if force healing is requested for particular
            instance, False otherwise.
        :return: Number of instances that had allocations created.
        :raises: nova.exception.ComputeHostNotFound if a compute node for a
            given instance cannot be found
        :raises: AllocationCreateFailed if unable to create allocations for
            a given instance against a given compute node resource provider
        :raises: AllocationUpdateFailed if unable to update allocations for
            a given instance with consumer project/user information
        :raise UnableToQueryPorts: If the neutron list ports query fails.
        :raise PlacementAPIConnectFailure: if placement API cannot be reached
        :raise UnableToUpdatePorts: if a port update failed in neutron but any
            partial update was rolled back successfully.
        :raise UnableToRollbackPortUpdates: if a port update failed in neutron
            and the rollback of the partial updates also failed.
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
        if instance_uuid:
            filters['uuid'] = instance_uuid
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
                        ctxt, instance, node_cache, output, placement,
                        dry_run, heal_port_allocations, neutron, force):
                    num_processed += 1

            # Make sure we don't go over the max count. Note that we
            # don't include instances that already have allocations in the
            # max_count number, only the number of instances that have
            # successfully created allocations.
            # If a specific instance was requested we return here as well.
            if (not unlimited and num_processed == max_count) or instance_uuid:
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
          "consumer project_id/user_id values in existing allocations or "
          "missing allocations for ports having resource request, and "
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
    @args('--dry-run', action='store_true', dest='dry_run', default=False,
          help='Runs the command and prints output but does not commit any '
               'changes. The return code should be 4.')
    @args('--instance', metavar='<instance_uuid>', dest='instance_uuid',
          help='UUID of a specific instance to process. If specified '
               '--max-count has no effect. '
               'The --cell and --instance options are mutually exclusive.')
    @args('--skip-port-allocations', action='store_true',
          dest='skip_port_allocations', default=False,
          help='Skip the healing of the resource allocations of bound ports. '
               'E.g. healing bandwidth resource allocation for ports having '
               'minimum QoS policy rules attached. If your deployment does '
               'not use such a feature then the performance impact of '
               'querying neutron ports for each instance can be avoided with '
               'this flag.')
    @args('--cell', metavar='<cell_uuid>', dest='cell_uuid',
          help='Heal allocations within a specific cell. '
               'The --cell and --instance options are mutually exclusive.')
    @args('--force', action='store_true', dest='force', default=False,
          help='Force heal allocations. Requires the --instance argument.')
    def heal_allocations(self, max_count=None, verbose=False, dry_run=False,
                         instance_uuid=None, skip_port_allocations=False,
                         cell_uuid=None, force=False):
        """Heals instance allocations in the Placement service

        Return codes:

        * 0: Command completed successfully and allocations were created.
        * 1: --max-count was reached and there are more instances to process.
        * 2: Unable to find a compute node record for a given instance.
        * 3: Unable to create (or update) allocations for an instance against
             its compute node resource provider.
        * 4: Command completed successfully but no allocations were created.
        * 5: Unable to query ports from neutron
        * 6: Unable to update ports in neutron
        * 7: Cannot roll back neutron port updates. Manual steps needed.
        * 8: Cannot heal instance with vGPU or Cyborg resource request
        * 127: Invalid input.
        """
        # NOTE(mriedem): Thoughts on ways to expand this:
        # - allow filtering on enabled/disabled cells
        # - add a force option to force allocations for instances which have
        #   task_state is not None (would get complicated during a migration);
        #   for example, this could cleanup ironic instances that have
        #   allocations on VCPU/MEMORY_MB/DISK_GB but are now using a custom
        #   resource class
        # - deal with nested resource providers?

        heal_port_allocations = not skip_port_allocations

        output = lambda msg: None
        if verbose:
            output = lambda msg: print(msg)

        # If user has provided both cell and instance
        # Throw an error
        if instance_uuid and cell_uuid:
            print(_('The --cell and --instance options '
                    'are mutually exclusive.'))
            return 127

        if force and not instance_uuid:
            print(_('The --instance flag is required '
                    'when using --force flag.'))
            return 127

        # TODO(mriedem): Rather than --max-count being both a total and batch
        # count, should we have separate options to be specific, i.e. --total
        # and --batch-size? Then --batch-size defaults to 50 and --total
        # defaults to None to mean unlimited.
        if instance_uuid:
            max_count = 1
            unlimited = False
        elif max_count is not None:
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
        # If we are going to process a specific instance, just get the cell
        # it is in up front.
        if instance_uuid:
            try:
                im = objects.InstanceMapping.get_by_instance_uuid(
                    ctxt, instance_uuid)
                cells = objects.CellMappingList(objects=[im.cell_mapping])
            except exception.InstanceMappingNotFound:
                print('Unable to find cell for instance %s, is it mapped? Try '
                      'running "nova-manage cell_v2 verify_instance" or '
                      '"nova-manage cell_v2 map_instances".' %
                      instance_uuid)
                return 127
        elif cell_uuid:
            try:
                # validate cell_uuid
                cell = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
                # create CellMappingList
                cells = objects.CellMappingList(objects=[cell])
            except exception.CellMappingNotFound:
                print(_('Cell with uuid %s was not found.') % cell_uuid)
                return 127
        else:
            cells = objects.CellMappingList.get_all(ctxt)
            if not cells:
                output(_('No cells to process.'))
                return 4

        placement = report.report_client_singleton()

        neutron = None
        if heal_port_allocations:
            neutron = neutron_api.get_client(ctxt, admin=True)

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
                        cctxt, limit_per_cell, unlimited, output, placement,
                        dry_run, instance_uuid, heal_port_allocations, neutron,
                        force)
                except exception.ComputeHostNotFound as e:
                    print(e.format_message())
                    return 2
                except (
                    exception.AllocationCreateFailed,
                    exception.AllocationUpdateFailed,
                    exception.PlacementAPIConnectFailure
                ) as e:
                    print(e.format_message())
                    return 3
                except exception.UnableToQueryPorts as e:
                    print(e.format_message())
                    return 5
                except exception.UnableToUpdatePorts as e:
                    print(e.format_message())
                    return 6
                except exception.UnableToRollbackPortUpdates as e:
                    print(e.format_message())
                    return 7
                except (
                    exception.HealvGPUAllocationNotSupported,
                    exception.HealDeviceProfileAllocationNotSupported,
                ) as e:
                    print(e.format_message())
                    return 8

                # Make sure we don't go over the max count. Note that we
                # don't include instances that already have allocations in the
                # max_count number, only the number of instances that have
                # successfully created allocations.
                # If a specific instance was provided then we'll just exit
                # the loop and process it below (either return 4 or 0).
                if num_processed == max_count and not instance_uuid:
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
        aggregate_api = api.AggregateAPI()
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

                # We've got our compute node record, so now we can ensure that
                # the matching resource provider, found via compute node uuid,
                # is in the same aggregate in placement, found via aggregate
                # uuid.
                try:
                    placement.aggregate_add_host(ctxt, aggregate.uuid,
                                                 rp_uuid=rp_uuid)
                    output(_('Successfully added host (%(host)s) and '
                             'provider (%(provider)s) to aggregate '
                             '(%(aggregate)s).') %
                           {'host': host, 'provider': rp_uuid,
                            'aggregate': aggregate.uuid})
                except exception.ResourceProviderNotFound:
                    # The resource provider wasn't found. Store this for later.
                    providers_not_found[host] = rp_uuid
                except exception.ResourceProviderAggregateRetrievalFailed as e:
                    print(e.message)
                    return 2
                except exception.NovaException as e:
                    # The exception message is too generic in this case
                    print(_('Failed updating provider aggregates for '
                            'host (%(host)s), provider (%(provider)s) '
                            'and aggregate (%(aggregate)s). Error: '
                            '%(error)s') %
                          {'host': host, 'provider': rp_uuid,
                           'aggregate': aggregate.uuid,
                           'error': e.message})
                    return 3

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

    def _get_instances_and_current_migrations(self, ctxt, cn_uuid):
        if self.cn_uuid_mapping.get(cn_uuid):
            cell_uuid, cn_host, cn_node = self.cn_uuid_mapping[cn_uuid]
        else:
            # We need to find the compute node record from all cells.
            results = context.scatter_gather_skip_cell0(
                ctxt, objects.ComputeNode.get_by_uuid, cn_uuid)
            for result_cell_uuid, result in results.items():
                if not context.is_cell_failure_sentinel(result):
                    cn = result
                    cell_uuid = result_cell_uuid
                    break
            else:
                return False
            cn_host, cn_node = (cn.host, cn.hypervisor_hostname)
            self.cn_uuid_mapping[cn_uuid] = (cell_uuid, cn_host, cn_node)
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)

        # Get all the active instances from this compute node
        if self.instances_mapping.get(cn_uuid):
            inst_uuids = self.instances_mapping[cn_uuid]
        else:
            # Get the instance list record from the cell.
            with context.target_cell(ctxt, cell_mapping) as cctxt:
                instances = objects.InstanceList.get_by_host_and_node(
                    cctxt, cn_host, cn_node, expected_attrs=[])
            inst_uuids = [instance.uuid for instance in instances]
            self.instances_mapping[cn_uuid] = inst_uuids

        # Get all *active* migrations for this compute node
        # NOTE(sbauza): Since migrations are transient, it's better to not
        # cache the results as they could be stale
        with context.target_cell(ctxt, cell_mapping) as cctxt:
            migs = objects.MigrationList.get_in_progress_by_host_and_node(
                cctxt, cn_host, cn_node)
        mig_uuids = [migration.uuid for migration in migs]

        return (inst_uuids, mig_uuids)

    def _delete_allocations_from_consumer(self, ctxt, placement, provider,
                                          consumer_uuid, consumer_type):
        """Deletes allocations from a resource provider with consumer UUID.

        :param ctxt: nova.context.RequestContext
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param provider: Resource Provider to look at.
        :param consumer_uuid: the consumer UUID having allocations.
        :param consumer_type: the type of consumer,
            either 'instance' or 'migration'
        :returns: bool whether the allocations were deleted.
        """
        # We need to be careful and only remove the allocations
        # against this specific RP or we would delete the
        # whole instance usage and then it would require some
        # healing.
        # TODO(sbauza): Remove this extra check once placement
        # supports querying allocation delete on both
        # consumer and resource provider parameters.
        allocations = placement.get_allocs_for_consumer(
            ctxt, consumer_uuid)
        if len(allocations['allocations']) > 1:
            # This consumer has resources spread among multiple RPs (think
            # nested or shared for example)
            # We then need to just update the usage to remove
            # the orphaned resources on the specific RP
            del allocations['allocations'][provider['uuid']]
            try:
                placement.put_allocations(
                    ctxt, consumer_uuid, allocations)
            except exception.AllocationUpdateFailed:
                return False

        else:
            try:
                placement.delete_allocation_for_instance(
                    ctxt, consumer_uuid, consumer_type, force=True)
            except exception.AllocationDeleteFailed:
                return False
        return True

    def _check_orphaned_allocations_for_provider(self, ctxt, placement,
                                                 output, provider,
                                                 delete):
        """Finds orphaned allocations for a specific resource provider.

        :param ctxt: nova.context.RequestContext
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param output: function that takes a single message for verbose output
        :param provider: Resource Provider to look at.
        :param delete: deletes the found orphaned allocations.
        :return: a tuple (<number of orphaned allocs>, <number of faults>)
        """
        num_processed = 0
        faults = 0

        # TODO(sbauza): Are we sure we have all Nova RCs ?
        # FIXME(sbauza): Possibly use consumer types once Placement API
        # supports them.
        # NOTE(sbauza): We check allocations having *any* below RC, not having
        # *all* of them.
        NOVA_RCS = [orc.VCPU, orc.MEMORY_MB, orc.DISK_GB, orc.VGPU,
                    orc.NET_BW_EGR_KILOBIT_PER_SEC,
                    orc.NET_BW_IGR_KILOBIT_PER_SEC,
                    orc.PCPU, orc.MEM_ENCRYPTION_CONTEXT]

        # Since the RP can be a child RP, we need to get the root RP as it's
        # the compute node UUID
        # NOTE(sbauza): In case Placement doesn't support 1.14 microversion,
        # that means we don't have nested RPs.
        # Since we ask for microversion 1.14, all RPs have a root RP UUID.
        cn_uuid = provider.get("root_provider_uuid")
        # Now get all the existing instances and active migrations for this
        # compute node
        result = self._get_instances_and_current_migrations(ctxt, cn_uuid)
        if result is False:
            # We don't want to hard stop here because the compute service could
            # have disappear while we could still have orphaned allocations.
            output(_('The compute node for UUID %s can not be '
                     'found') % cn_uuid)
        inst_uuids, mig_uuids = result or ([], [])
        try:
            pallocs = placement.get_allocations_for_resource_provider(
                ctxt, provider['uuid'])
        except exception.ResourceProviderAllocationRetrievalFailed:
            print(_('Not able to find allocations for resource '
                    'provider %s.') % provider['uuid'])
            raise

        # Verify every allocations for each consumer UUID
        for consumer_uuid, consumer_resources in pallocs.allocations.items():
            consumer_allocs = consumer_resources['resources']
            if any(rc in NOVA_RCS
                   for rc in consumer_allocs):
                # We reset the consumer type for each allocation
                consumer_type = None
                # This is an allocation for Nova resources
                # We need to guess whether the instance was deleted
                # or if the instance is currently migrating
                if not (consumer_uuid in inst_uuids or
                        consumer_uuid in mig_uuids):
                    # By default we suspect the orphaned allocation was for a
                    # migration...
                    consumer_type = 'migration'
                    if consumer_uuid not in inst_uuids:
                        # ... but if we can't find it either for an instance,
                        # that means it was for this.
                        consumer_type = 'instance'
                if consumer_type is not None:
                    output(_('Allocations were set against consumer UUID '
                             '%(consumer_uuid)s but no existing instances or '
                             'active migrations are related. ')
                           % {'consumer_uuid': consumer_uuid})
                    if delete:
                        deleted = self._delete_allocations_from_consumer(
                            ctxt, placement, provider, consumer_uuid,
                            consumer_type)
                        if not deleted:
                            print(_('Not able to delete allocations '
                                    'for consumer UUID %s')
                                  % consumer_uuid)
                            faults += 1
                            continue
                        output(_('Deleted allocations for consumer UUID '
                                 '%(consumer_uuid)s on Resource Provider '
                                 '%(rp)s: %(allocations)s')
                               % {'consumer_uuid': consumer_uuid,
                                  'rp': provider['uuid'],
                                  'allocations': consumer_allocs})
                    else:
                        output(_('Allocations for consumer UUID '
                                 '%(consumer_uuid)s on Resource Provider '
                                 '%(rp)s can be deleted: '
                                 '%(allocations)s')
                               % {'consumer_uuid': consumer_uuid,
                                  'rp': provider['uuid'],
                                  'allocations': consumer_allocs})
                    num_processed += 1
        return (num_processed, faults)

    # TODO(sbauza): Move this to the scheduler report client ?
    def _get_resource_provider(self, context, placement, uuid):
        """Returns a single Resource Provider by its UUID.

        :param context: The nova.context.RequestContext auth context
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param uuid: A specific Resource Provider UUID
        :return: the existing resource provider.
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        """

        resource_providers = self._get_resource_providers(context, placement,
                                                          uuid=uuid)
        if not resource_providers:
            # The endpoint never returns a 404, it rather returns an empty list
            raise exception.ResourceProviderNotFound(name_or_uuid=uuid)
        return resource_providers[0]

    def _get_resource_providers(self, context, placement, **kwargs):
        """Returns all resource providers regardless of their relationships.

        :param context: The nova.context.RequestContext auth context
        :param placement: nova.scheduler.client.report.SchedulerReportClient
            to communicate with the Placement service API.
        :param kwargs: extra attributes for the query string
        :return: list of resource providers.
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        """
        url = '/resource_providers'
        if 'uuid' in kwargs:
            url += '?uuid=%s' % kwargs['uuid']

        resp = placement.get(url, global_request_id=context.global_id,
                             version='1.14')
        if resp is None:
            raise exception.PlacementAPIConnectFailure()

        data = resp.json()
        resource_providers = data.get('resource_providers')

        return resource_providers

    @action_description(
        _("Audits orphaned allocations that are no longer corresponding to "
          "existing instance resources. This command requires that "
          "the [api_database]/connection and [placement] configuration "
          "options are set."))
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Provide verbose output during execution.')
    @args('--resource_provider', metavar='<provider_uuid>',
          dest='provider_uuid',
          help='UUID of a specific resource provider to verify.')
    @args('--delete', action='store_true', dest='delete', default=False,
          help='Deletes orphaned allocations that were found.')
    def audit(self, verbose=False, provider_uuid=None, delete=False):
        """Provides information about orphaned allocations that can be removed

        Return codes:

        * 0: Command completed successfully and no orphaned allocations exist.
        * 1: An unexpected error happened during run.
        * 3: Orphaned allocations were detected.
        * 4: Orphaned allocations were detected and deleted.
        * 127: Invalid input.
        """

        ctxt = context.get_admin_context()
        output = lambda msg: None
        if verbose:
            output = lambda msg: print(msg)

        placement = report.report_client_singleton()
        # Resets two in-memory dicts for knowing instances per compute node
        self.cn_uuid_mapping = collections.defaultdict(tuple)
        self.instances_mapping = collections.defaultdict(list)

        num_processed = 0
        faults = 0

        if provider_uuid:
            try:
                resource_provider = self._get_resource_provider(
                    ctxt, placement, provider_uuid)
            except exception.ResourceProviderNotFound:
                print(_('Resource provider with UUID %s does not exist.') %
                      provider_uuid)
                return 127
            resource_providers = [resource_provider]
        else:
            resource_providers = self._get_resource_providers(ctxt, placement)

        for provider in resource_providers:
            nb_p, faults = self._check_orphaned_allocations_for_provider(
                ctxt, placement, output, provider, delete)
            num_processed += nb_p
            if faults > 0:
                print(_('The Resource Provider %s had problems when '
                        'deleting allocations. Stopping now. Please fix the '
                        'problem by hand and run again.') %
                      provider['uuid'])
                return 1
        if num_processed > 0:
            suffix = 's.' if num_processed > 1 else '.'
            output(_('Processed %(num)s allocation%(suffix)s')
                   % {'num': num_processed,
                      'suffix': suffix})
            return 4 if delete else 3
        return 0


class LibvirtCommands(object):
    """Commands for managing libvirt instances"""

    @action_description(
        _("Fetch the stored machine type of the instance from the database."))
    @args('instance_uuid', metavar='<instance_uuid>',
          help='UUID of instance to fetch the machine type for')
    def get_machine_type(self, instance_uuid=None):
        """Fetch the stored machine type of the instance from the database.

        Return codes:

        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Unable to find instance or instance mapping.
        * 3: No machine type found for the instance.

        """
        try:
            ctxt = context.get_admin_context()
            mtype = machine_type_utils.get_machine_type(ctxt, instance_uuid)
            if mtype:
                print(mtype)
                return 0
            else:
                print(_('No machine type registered for instance %s') %
                      instance_uuid)
                return 3
        except (exception.InstanceNotFound,
                exception.InstanceMappingNotFound) as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1

    @action_description(
        _("Set or update the stored machine type of the instance in the "
          "database. This is only allowed for instances with a STOPPED, "
          "SHELVED or SHELVED_OFFLOADED vm_state."))
    @args('instance_uuid', metavar='<instance_uuid>',
          help='UUID of instance to update')
    @args('machine_type', metavar='<machine_type>',
          help='Machine type to set')
    @args('--force', action='store_true', default=False, dest='force',
          help='Force the update of the stored machine type')
    def update_machine_type(
        self,
        instance_uuid=None,
        machine_type=None,
        force=False
    ):
        """Set or update the machine type of a given instance.

        Return codes:

        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Unable to find the instance or instance cell mapping.
        * 3: Invalid instance vm_state.
        * 4: Unable to move between underlying machine types (pc to q35 etc)
             or to older versions.
        * 5: Unsupported machine type.
        """
        ctxt = context.get_admin_context()
        if force:
            print(_("Forcing update of machine type."))

        try:
            rtype, ptype = machine_type_utils.update_machine_type(
                ctxt, instance_uuid, machine_type, force=force)
        except exception.UnsupportedMachineType as e:
            print(str(e))
            return 5
        except exception.InvalidMachineTypeUpdate as e:
            print(str(e))
            return 4
        except exception.InstanceInvalidState as e:
            print(str(e))
            return 3
        except (
            exception.InstanceNotFound,
            exception.InstanceMappingNotFound,
        ) as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1

        print(_("Updated instance %(instance_uuid)s machine type to "
                "%(machine_type)s (previously %(previous_type)s)") %
                {'instance_uuid': instance_uuid,
                 'machine_type': rtype,
                 'previous_type': ptype})
        return 0

    @action_description(
        _("List the UUIDs of instances that do not have hw_machine_type set "
          "in their image metadata"))
    @args('--cell-uuid', metavar='<cell_uuid>', dest='cell_uuid',
          required=False, help='UUID of cell from which to list instances')
    def list_unset_machine_type(self, cell_uuid=None):
        """List the UUIDs of instances without image_hw_machine_type set

        Return codes:
        * 0: Command completed successfully, no instances found.
        * 1: An unexpected error happened.
        * 2: Unable to find cell mapping.
        * 3: Instances found without hw_machine_type set.
        """
        try:
            instance_list = machine_type_utils.get_instances_without_type(
                context.get_admin_context(), cell_uuid)
        except exception.CellMappingNotFound as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1

        if instance_list:
            print('\n'.join(i.uuid for i in instance_list))
            return 3
        else:
            print(_("No instances found without hw_machine_type set."))
            return 0


class VolumeAttachmentCommands(object):

    @action_description(_("Show the details of a given volume attachment."))
    @args(
        'instance_uuid', metavar='<instance_uuid>',
        help='UUID of the instance')
    @args(
        'volume_id', metavar='<volume_id>',
        help='UUID of the volume')
    @args(
        '--connection_info', action='store_true',
        default=False, dest='connection_info', required=False,
        help='Only display the connection_info of the volume attachment.')
    @args(
        '--json', action='store_true',
        default=False, dest='json', required=False,
        help='Display output as json without a table.')
    def show(
        self,
        instance_uuid=None,
        volume_id=None,
        connection_info=False,
        json=False
    ):
        """Show attributes of a given volume attachment.

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Instance not found.
        * 3: Volume is not attached to instance.
        """
        try:
            ctxt = context.get_admin_context()
            im = objects.InstanceMapping.get_by_instance_uuid(
                ctxt, instance_uuid)
            with context.target_cell(ctxt, im.cell_mapping) as cctxt:
                bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                    cctxt, volume_id, instance_uuid)
                if connection_info and json:
                    print(bdm.connection_info)
                elif connection_info:
                    print(format_dict(jsonutils.loads(bdm.connection_info)))
                elif json:
                    print(jsonutils.dumps(bdm))
                else:
                    print(format_dict(bdm))
                return 0
        except exception.VolumeBDMNotFound as e:
            print(str(e))
            return 3
        except (
            exception.InstanceNotFound,
            exception.InstanceMappingNotFound,
        ) as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1

    @action_description(_('Show the host connector for this host'))
    @args(
        '--json', action='store_true',
        default=False, dest='json', required=False,
        help='Display output as json without a table.')
    def get_connector(self, json=False):
        """Show the host connector for this host.

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        """
        try:
            root_helper = utils.get_root_helper()
            host_connector = connector.get_connector_properties(
                root_helper, CONF.my_block_storage_ip,
                CONF.libvirt.volume_use_multipath,
                enforce_multipath=True,
                host=CONF.host)
            if json:
                print(jsonutils.dumps(host_connector))
            else:
                print(format_dict(host_connector))
            return 0
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1

    def _refresh(self, instance_uuid, volume_id, connector):
        """Refresh the bdm.connection_info associated with a volume attachment

        Unlike the current driver BDM implementation under
        nova.virt.block_device.DriverVolumeBlockDevice.refresh_connection_info
        that simply GETs an existing volume attachment from cinder this method
        cleans up any existing volume connections from the host before creating
        a fresh attachment in cinder and populates the underlying BDM with
        connection_info from the new attachment.

        We can do that here as the command requires that the instance is
        stopped, something that isn't always the case with the current driver
        BDM approach and thus the two are kept separate for the time being.

        :param instance_uuid: UUID of instance
        :param volume_id: ID of volume attached to the instance
        :param connector: Connector with which to create the new attachment
        :return status_code: volume-refresh status_code 0 on success
        """

        ctxt = context.get_admin_context()
        im = objects.InstanceMapping.get_by_instance_uuid(ctxt, instance_uuid)
        with context.target_cell(ctxt, im.cell_mapping) as cctxt:

            instance = objects.Instance.get_by_uuid(cctxt, instance_uuid)
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                    cctxt, volume_id, instance_uuid)

            if instance.vm_state != obj_fields.InstanceState.STOPPED:
                raise exception.InstanceInvalidState(
                    instance_uuid=instance_uuid, attr='vm_state',
                    state=instance.vm_state,
                    method='refresh connection_info (must be stopped)')

            locking_reason = (
                f'Refreshing connection_info for BDM {bdm.uuid} '
                f'associated with instance {instance_uuid} and volume '
                f'{volume_id}.')

            with locked_instance(im.cell_mapping, instance, locking_reason):
                return self._do_refresh(
                    cctxt, instance, volume_id, bdm, connector)

    def _do_refresh(self, cctxt, instance,
            volume_id, bdm, connector):
        volume_api = cinder.API()
        compute_rpcapi = rpcapi.ComputeAPI()

        new_attachment_id = None
        try:
            # Log this as an instance action so operators and users are
            # aware that this has happened.
            instance_action = objects.InstanceAction.action_start(
                cctxt, instance.uuid,
                instance_actions.NOVA_MANAGE_REFRESH_VOLUME_ATTACHMENT)

            # Create a blank attachment to keep the volume reserved
            new_attachment_id = volume_api.attachment_create(
                cctxt, volume_id, instance.uuid)['id']

            # RPC call to the compute to cleanup the connections, which
            # will in turn unmap the volume from the compute host
            if instance.host == connector['host']:
                compute_rpcapi.remove_volume_connection(
                    cctxt, instance, volume_id, instance.host,
                    delete_attachment=True)
            else:
                msg = (
                    f"The compute host '{connector['host']}' in the "
                    f"connector does not match the instance host "
                    f"'{instance.host}'.")
                raise exception.HostConflict(_(msg))

            # Update the attachment with host connector, this regenerates
            # the connection_info that we can now stash in the bdm.
            new_connection_info = volume_api.attachment_update(
                cctxt, new_attachment_id, connector,
                bdm.device_name)['connection_info']

            # Before we save it to the BDM ensure the serial is stashed as
            # is done in various other codepaths when attaching volumes.
            if 'serial' not in new_connection_info:
                new_connection_info['serial'] = bdm.volume_id

            # Save the new attachment id and connection_info to the DB
            bdm.attachment_id = new_attachment_id
            bdm.connection_info = jsonutils.dumps(new_connection_info)
            bdm.save()

            # Finally mark the attachment as complete, moving the volume
            # status from attaching to in-use ahead of the instance
            # restarting
            volume_api.attachment_complete(cctxt, new_attachment_id)
            return 0

        finally:
            # If the bdm.attachment_id wasn't updated make sure we clean
            # up any attachments created during the run.
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                cctxt, volume_id, instance.uuid)
            if (
                new_attachment_id and
                bdm.attachment_id != new_attachment_id
            ):
                volume_api.attachment_delete(cctxt, new_attachment_id)

            # If we failed during attachment_update the bdm.attachment_id
            # has already been deleted so recreate it now to ensure the
            # volume is still associated with the instance and clear the
            # now stale connection_info.
            try:
                volume_api.attachment_get(cctxt, bdm.attachment_id)
            except exception.VolumeAttachmentNotFound:
                bdm.attachment_id = volume_api.attachment_create(
                    cctxt, volume_id, instance.uuid)['id']
                bdm.connection_info = None
                bdm.save()

            # Finish the instance action if it was created and started
            # TODO(lyarwood): While not really required we should store
            # the exec and traceback in here on failure.
            if instance_action:
                instance_action.finish()

    @action_description(
        _("Refresh the connection info for a given volume attachment"))
    @args(
        'instance_uuid', metavar='<instance_uuid>',
        help='UUID of the instance')
    @args(
        'volume_id', metavar='<volume_id>',
        help='UUID of the volume')
    @args(
        'connector_path', metavar='<connector_path>',
        help='Path to file containing the host connector in json format.')
    def refresh(self, instance_uuid=None, volume_id=None, connector_path=None):
        """Refresh the connection_info associated with a volume attachment

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Connector path does not exist.
        * 3: Failed to open connector path.
        * 4: Instance does not exist.
        * 5: Instance state invalid.
        * 6: Volume is not attached to instance.
        * 7: Connector host is not correct.
        """
        try:
            # TODO(lyarwood): Make this optional and provide a rpcapi capable
            # of pulling this down from the target compute during this flow.
            if not os.path.exists(connector_path):
                raise exception.InvalidInput(
                    reason=f'Connector file not found at {connector_path}')

            # Read in the json connector file
            with open(connector_path, 'rb') as connector_file:
                connector = jsonutils.load(connector_file)

            # Refresh the volume attachment
            return self._refresh(instance_uuid, volume_id, connector)

        except exception.HostConflict as e:
            print(
                f"The command 'nova-manage volume_attachment get_connector' "
                f"may have been run on the wrong compute host. Or the "
                f"instance host may be wrong and in need of repair.\n{e}")
            return 7
        except exception.VolumeBDMNotFound as e:
            print(str(e))
            return 6
        except exception.InstanceInvalidState as e:
            print(str(e))
            return 5
        except (
            exception.InstanceNotFound,
            exception.InstanceMappingNotFound,
        ) as e:
            print(str(e))
            return 4
        except ValueError as e:
            print(
                f'Failed to open {connector_path}. Does it contain valid '
                f'connector_info data?\nError: {str(e)}'
            )
            return 3
        except OSError as e:
            print(str(e))
            return 3
        except exception.InvalidInput as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1


class ImagePropertyCommands:

    @action_description(_("Show the value of an instance image property."))
    @args(
        'instance_uuid', metavar='<instance_uuid>',
        help='UUID of the instance')
    @args(
        'image_property', metavar='<image_property>',
        help='Image property to show')
    def show(self, instance_uuid=None, image_property=None):
        """Show value of a given instance image property.

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Instance not found.
        * 3: Image property not found.
        """
        try:
            ctxt = context.get_admin_context()
            im = objects.InstanceMapping.get_by_instance_uuid(
                ctxt, instance_uuid)
            with context.target_cell(ctxt, im.cell_mapping) as cctxt:
                instance = objects.Instance.get_by_uuid(
                    cctxt, instance_uuid, expected_attrs=['system_metadata'])
                property_value = instance.system_metadata.get(
                    f'image_{image_property}')
                if property_value:
                    print(property_value)
                    return 0
                else:
                    print(f'Image property {image_property} not found '
                          f'for instance {instance_uuid}.')
                    return 3
        except (
            exception.InstanceNotFound,
            exception.InstanceMappingNotFound,
        ) as e:
            print(str(e))
            return 2
        except Exception as e:
            print(f'Unexpected error, see nova-manage.log for the full '
                  f'trace: {str(e)}')
            LOG.exception('Unexpected error')
            return 1

    def _validate_image_properties(self, image_properties):
        """Validate the provided image property names and values

        :param image_properties: List of image property names and values
        """
        # Sanity check the format of the provided properties, this should be
        # in the format of name=value.
        if any(x for x in image_properties if '=' not in x):
            raise exception.InvalidInput(
                "--property should use the format key=value")

        # Transform the list of delimited properties to a dict
        image_properties = dict(prop.split('=') for prop in image_properties)

        # Validate the names of each property by checking against the o.vo
        # fields currently listed by ImageProps. We can't use from_dict to
        # do this as it silently ignores invalid property keys.
        for image_property_name in image_properties.keys():
            if image_property_name not in objects.ImageMetaProps.fields:
                raise exception.InvalidImagePropertyName(
                    image_property_name=image_property_name)

        # Validate the values by creating an object from the provided dict.
        objects.ImageMetaProps.from_dict(image_properties)

        # Return the dict so we can update the instance system_metadata
        return image_properties

    def _update_image_properties(self, ctxt, instance, image_properties):
        """Update instance image properties

        :param ctxt: nova.context.RequestContext
        :param instance: The instance to update
        :param image_properties: List of image properties and values to update
        """
        # Check the state of the instance
        allowed_states = [
            obj_fields.InstanceState.STOPPED,
            obj_fields.InstanceState.SHELVED,
            obj_fields.InstanceState.SHELVED_OFFLOADED,
        ]
        if instance.vm_state not in allowed_states:
            raise exception.InstanceInvalidState(
                instance_uuid=instance.uuid, attr='vm_state',
                state=instance.vm_state,
                method='image_property set (must be STOPPED, SHELVED, OR '
                       'SHELVED_OFFLOADED).')

        # Validate the property names and values
        image_properties = self._validate_image_properties(image_properties)

        # Update the image properties and save the instance record
        for image_property, value in image_properties.items():
            instance.system_metadata[f'image_{image_property}'] = value

        request_spec = objects.RequestSpec.get_by_instance_uuid(
            ctxt, instance.uuid)
        request_spec.image = instance.image_meta

        # Save and return 0
        instance.save()
        request_spec.save()
        return 0

    @action_description(_(
        "Set the values of instance image properties stored in the database. "
        "This is only allowed for " "instances with a STOPPED, SHELVED or "
        "SHELVED_OFFLOADED vm_state."))
    @args(
        'instance_uuid', metavar='<instance_uuid>',
        help='UUID of the instance')
    @args(
        '--property', metavar='<image_property>', action='append',
        dest='image_properties',
        help='Image property to set using the format name=value. For example: '
             '--property hw_disk_bus=virtio --property hw_cdrom_bus=sata')
    def set(self, instance_uuid=None, image_properties=None):
        """Set instance image property values

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error happened.
        * 2: Unable to find instance.
        * 3: Instance is in an invalid state.
        * 4: Invalid input format.
        * 5: Invalid image property name.
        * 6: Invalid image property value.
        """
        try:
            ctxt = context.get_admin_context()
            im = objects.InstanceMapping.get_by_instance_uuid(
                ctxt, instance_uuid)
            with context.target_cell(ctxt, im.cell_mapping) as cctxt:
                instance = objects.Instance.get_by_uuid(
                    cctxt, instance_uuid, expected_attrs=['system_metadata'])
                return self._update_image_properties(
                    ctxt, instance, image_properties)
        except ValueError as e:
            print(str(e))
            return 6
        except exception.InvalidImagePropertyName as e:
            print(str(e))
            return 5
        except exception.InvalidInput as e:
            print(str(e))
            return 4
        except exception.InstanceInvalidState as e:
            print(str(e))
            return 3
        except (
            exception.InstanceNotFound,
            exception.InstanceMappingNotFound,
        ) as e:
            print(str(e))
            return 2
        except Exception as e:
            print('Unexpected error, see nova-manage.log for the full '
                  'trace: %s ' % str(e))
            LOG.exception('Unexpected error')
            return 1


class LimitsCommands():

    def _create_unified_limits(self, ctxt, legacy_defaults, project_id,
                               region_id, output, dry_run):
        return_code = 0

        # Create registered (default) limits first.
        unified_to_legacy_names = dict(
            **local_limit.LEGACY_LIMITS, **placement_limit.LEGACY_LIMITS)

        legacy_to_unified_names = dict(
            zip(unified_to_legacy_names.values(),
                unified_to_legacy_names.keys()))

        # Handle the special case of PCPU. With legacy quotas, there is no
        # dedicated quota limit for PCPUs, so they share the quota limit for
        # VCPUs: 'cores'. With unified limits, class:PCPU has its own dedicated
        # quota limit, so we will just mirror the limit for class:VCPU and
        # create a limit with the same value for class:PCPU.
        if 'cores' in legacy_defaults:
            # Just make up a dummy legacy resource 'pcores' for this.
            legacy_defaults['pcores'] = legacy_defaults['cores']
            unified_to_legacy_names['class:PCPU'] = 'pcores'
            legacy_to_unified_names['pcores'] = 'class:PCPU'

        # For auth, a section for [keystone] is required in the config:
        #
        # [keystone]
        # region_name = RegionOne
        # user_domain_name = Default
        # password = <password>
        # username = <username>
        # auth_url = http://127.0.0.1/identity
        # auth_type = password
        # system_scope = all
        #
        # The configured user needs 'role:admin and system_scope:all' by
        # default in order to create limits in Keystone.
        keystone_api = utils.get_sdk_adapter('identity')

        # Service ID is required in unified limits APIs.
        service_id = keystone_api.find_service('nova').id

        # Retrieve the existing resource limits from Keystone.
        registered_limits = keystone_api.registered_limits(region_id=region_id)

        unified_defaults = {
            rl.resource_name: rl.default_limit for rl in registered_limits}

        # f-strings don't seem to work well with the _() translation function.
        msg = f'Found default limits in Keystone: {unified_defaults} ...'
        output(_(msg))

        # Determine which resource limits are missing in Keystone so that we
        # can create them.
        output(_('Creating default limits in Keystone ...'))
        for resource, rlimit in legacy_defaults.items():
            resource_name = legacy_to_unified_names[resource]
            if resource_name not in unified_defaults:
                msg = f'Creating default limit: {resource_name} = {rlimit}'
                if region_id:
                    msg += f' in region {region_id}'
                output(_(msg))
                if not dry_run:
                    try:
                        keystone_api.create_registered_limit(
                            resource_name=resource_name,
                            default_limit=rlimit, region_id=region_id,
                            service_id=service_id)
                    except Exception as e:
                        msg = f'Failed to create default limit: {str(e)}'
                        print(_(msg))
                        return_code = 1
            else:
                existing_rlimit = unified_defaults[resource_name]
                msg = (f'A default limit: {resource_name} = {existing_rlimit} '
                        'already exists in Keystone, skipping ...')
                output(_(msg))

        # Create project limits if there are any.
        if not project_id:
            return return_code

        output(_('Reading project limits from the Nova API database ...'))
        legacy_projects = objects.Quotas.get_all_by_project(ctxt, project_id)
        legacy_projects.pop('project_id', None)
        msg = f'Found project limits in the database: {legacy_projects} ...'
        output(_(msg))

        # Handle the special case of PCPU again for project limits.
        if 'cores' in legacy_projects:
            # Just make up a dummy legacy resource 'pcores' for this.
            legacy_projects['pcores'] = legacy_projects['cores']

        # Retrieve existing limits from Keystone.
        project_limits = keystone_api.limits(
            project_id=project_id, region_id=region_id)
        unified_projects = {
            pl.resource_name: pl.resource_limit for pl in project_limits}
        msg = f'Found project limits in Keystone: {unified_projects} ...'
        output(_(msg))

        output(_('Creating project limits in Keystone ...'))
        for resource, plimit in legacy_projects.items():
            resource_name = legacy_to_unified_names[resource]
            if resource_name not in unified_projects:
                msg = (
                    f'Creating project limit: {resource_name} = {plimit} '
                    f'for project {project_id}')
                if region_id:
                    msg += f' in region {region_id}'
                output(_(msg))
                if not dry_run:
                    try:
                        keystone_api.create_limit(
                            resource_name=resource_name,
                            resource_limit=plimit, project_id=project_id,
                            region_id=region_id, service_id=service_id)
                    except Exception as e:
                        msg = f'Failed to create project limit: {str(e)}'
                        print(_(msg))
                        return_code = 1
            else:
                existing_plimit = unified_projects[resource_name]
                msg = (f'A project limit: {resource_name} = {existing_plimit} '
                        'already exists in Keystone, skipping ...')
                output(_(msg))

        return return_code

    @action_description(
        _("Copy quota limits from the Nova API database to Keystone."))
    @args('--project-id', metavar='<project-id>', dest='project_id',
          help='Project ID for which to migrate quota limits')
    @args('--region-id', metavar='<region-id>', dest='region_id',
          help='Region ID for which to migrate quota limits')
    @args('--verbose', action='store_true', dest='verbose', default=False,
          help='Provide verbose output during execution.')
    @args('--dry-run', action='store_true', dest='dry_run', default=False,
          help='Show what limits would be created without actually '
               'creating them.')
    def migrate_to_unified_limits(self, project_id=None, region_id=None,
                                  verbose=False, dry_run=False):
        """Migrate quota limits from legacy quotas to unified limits.

        Return codes:
        * 0: Command completed successfully.
        * 1: An unexpected error occurred.
        * 2: Failed to connect to the database.
        """
        ctxt = context.get_admin_context()

        output = lambda msg: None
        if verbose:
            output = lambda msg: print(msg)

        output(_('Reading default limits from the Nova API database ...'))

        try:
            # This will look for limits in the 'default' quota class first and
            # then fall back to the [quota] config options.
            legacy_defaults = nova.quota.QUOTAS.get_defaults(ctxt)
        except db_exc.CantStartEngineError:
            print(_('Failed to connect to the database so aborting this '
                    'migration attempt. Please check your config file to make '
                    'sure that [api_database]/connection and '
                    '[database]/connection are set and run this '
                    'command again.'))
            return 2

        # Remove obsolete resource limits.
        for resource in ('fixed_ips', 'floating_ips', 'security_groups',
                         'security_group_rules'):
            if resource in legacy_defaults:
                msg = f'Skipping obsolete limit for {resource} ...'
                output(_(msg))
                legacy_defaults.pop(resource)

        msg = (
            f'Found default limits in the database: {legacy_defaults} ...')
        output(_(msg))

        try:
            return self._create_unified_limits(
                ctxt, legacy_defaults, project_id, region_id, output, dry_run)
        except Exception as e:
            msg = (f'Unexpected error, see nova-manage.log for the full '
                   f'trace: {str(e)}')
            print(_(msg))
            LOG.exception('Unexpected error')
            return 1


CATEGORIES = {
    'api_db': ApiDbCommands,
    'cell_v2': CellV2Commands,
    'db': DbCommands,
    'placement': PlacementCommands,
    'libvirt': LibvirtCommands,
    'volume_attachment': VolumeAttachmentCommands,
    'image_property': ImagePropertyCommands,
    'limits': LimitsCommands,
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
        return 255
