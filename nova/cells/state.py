# Copyright (c) 2012 Rackspace Hosting
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

"""
CellState Manager
"""
import collections
import copy
import datetime
import functools
import time

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import units
import six

from nova.cells import rpc_driver
import nova.conf
from nova import context
from nova.db import base
from nova import exception
from nova import objects
from nova import rpc
from nova import servicegroup
from nova import utils


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class CellState(object):
    """Holds information for a particular cell."""
    def __init__(self, cell_name, is_me=False):
        self.name = cell_name
        self.is_me = is_me
        self.last_seen = datetime.datetime.min
        self.capabilities = {}
        self.capacities = {}
        self.db_info = {}
        # TODO(comstud): The DB will specify the driver to use to talk
        # to this cell, but there's no column for this yet.  The only
        # available driver is the rpc driver.
        self.driver = rpc_driver.CellsRPCDriver()

    def update_db_info(self, cell_db_info):
        """Update cell credentials from db."""
        self.db_info = {k: v for k, v in cell_db_info.items()
                        if k != 'name'}

    def update_capabilities(self, cell_metadata):
        """Update cell capabilities for a cell."""
        self.last_seen = timeutils.utcnow()
        self.capabilities = cell_metadata

    def update_capacities(self, capacities):
        """Update capacity information for a cell."""
        self.last_seen = timeutils.utcnow()
        self.capacities = capacities

    def get_cell_info(self):
        """Return subset of cell information for OS API use."""
        db_fields_to_return = ['is_parent', 'weight_scale', 'weight_offset']
        url_fields_to_return = {
            'username': 'username',
            'hostname': 'rpc_host',
            'port': 'rpc_port',
        }
        cell_info = dict(name=self.name, capabilities=self.capabilities)
        if self.db_info:
            for field in db_fields_to_return:
                cell_info[field] = self.db_info[field]

            url = rpc.get_transport_url(self.db_info['transport_url'])
            if url.hosts:
                for field, canonical in url_fields_to_return.items():
                    cell_info[canonical] = getattr(url.hosts[0], field)
        return cell_info

    def send_message(self, message):
        """Send a message to a cell.  Just forward this to the driver,
        passing ourselves and the message as arguments.
        """
        self.driver.send_message_to_cell(self, message)

    def __repr__(self):
        me = "me" if self.is_me else "not_me"
        return "Cell '%s' (%s)" % (self.name, me)


def sync_before(f):
    """Use as a decorator to wrap methods that use cell information to
    make sure they sync the latest information from the DB periodically.
    """
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        self._cell_data_sync()
        return f(self, *args, **kwargs)
    return wrapper


def sync_after(f):
    """Use as a decorator to wrap methods that update cell information
    in the database to make sure the data is synchronized immediately.
    """
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        result = f(self, *args, **kwargs)
        self._cell_data_sync(force=True)
        return result
    return wrapper


_unset = object()


class CellStateManager(base.Base):
    def __new__(cls, cell_state_cls=None, cells_config=_unset):
        if cls is not CellStateManager:
            return super(CellStateManager, cls).__new__(cls)

        if cells_config is _unset:
            cells_config = CONF.cells.cells_config

        if cells_config:
            return CellStateManagerFile(cell_state_cls)

        return CellStateManagerDB(cell_state_cls)

    def __init__(self, cell_state_cls=None):
        super(CellStateManager, self).__init__()
        if not cell_state_cls:
            cell_state_cls = CellState
        self.cell_state_cls = cell_state_cls
        self.my_cell_state = cell_state_cls(CONF.cells.name, is_me=True)
        self.parent_cells = {}
        self.child_cells = {}
        self.last_cell_db_check = datetime.datetime.min
        self.servicegroup_api = servicegroup.API()

        attempts = 0
        while True:
            try:
                self._cell_data_sync(force=True)
                break
            except db_exc.DBError:
                attempts += 1
                if attempts > 120:
                    raise
                LOG.exception('DB error')
                time.sleep(30)

        my_cell_capabs = {}
        for cap in CONF.cells.capabilities:
            name, value = cap.split('=', 1)
            if ';' in value:
                values = set(value.split(';'))
            else:
                values = set([value])
            my_cell_capabs[name] = values
        self.my_cell_state.update_capabilities(my_cell_capabs)

    def _refresh_cells_from_dict(self, db_cells_dict):
        """Make our cell info map match the db."""

        # Update current cells.  Delete ones that disappeared
        for cells_dict in (self.parent_cells, self.child_cells):
            for cell_name, cell_info in cells_dict.items():
                is_parent = cell_info.db_info['is_parent']
                db_dict = db_cells_dict.get(cell_name)
                if db_dict and is_parent == db_dict['is_parent']:
                    cell_info.update_db_info(db_dict)
                else:
                    del cells_dict[cell_name]

        # Add new cells
        for cell_name, db_info in db_cells_dict.items():
            if db_info['is_parent']:
                cells_dict = self.parent_cells
            else:
                cells_dict = self.child_cells
            if cell_name not in cells_dict:
                cells_dict[cell_name] = self.cell_state_cls(cell_name)
                cells_dict[cell_name].update_db_info(db_info)

    def _time_to_sync(self):
        """Is it time to sync the DB against our memory cache?"""
        diff = timeutils.utcnow() - self.last_cell_db_check
        return diff.seconds >= CONF.cells.db_check_interval

    def _update_our_capacity(self, ctxt=None):
        """Update our capacity in the self.my_cell_state CellState.

        This will add/update 2 entries in our CellState.capacities,
        'ram_free' and 'disk_free'.

        The values of these are both dictionaries with the following
        format:

        {'total_mb': <total_memory_free_in_the_cell>,
         'units_by_mb: <units_dictionary>}

        <units_dictionary> contains the number of units that we can build for
        every distinct memory or disk requirement that we have based on
        instance types.  This number is computed by looking at room available
        on every compute_node.

        Take the following instance_types as an example:

        [{'memory_mb': 1024, 'root_gb': 10, 'ephemeral_gb': 100},
         {'memory_mb': 2048, 'root_gb': 20, 'ephemeral_gb': 200}]

        capacities['ram_free']['units_by_mb'] would contain the following:

        {'1024': <number_of_instances_that_will_fit>,
         '2048': <number_of_instances_that_will_fit>}

        capacities['disk_free']['units_by_mb'] would contain the following:

        {'122880': <number_of_instances_that_will_fit>,
         '225280': <number_of_instances_that_will_fit>}

        Units are in MB, so 122880 = (10 + 100) * 1024.

        NOTE(comstud): Perhaps we should only report a single number
        available per instance_type.
        """

        if not ctxt:
            ctxt = context.get_admin_context()

        reserve_level = CONF.cells.reserve_percent / 100.0

        def _defaultdict_int():
            return collections.defaultdict(int)
        compute_hosts = collections.defaultdict(_defaultdict_int)

        def _get_compute_hosts():
            service_refs = {service.host: service
                            for service in objects.ServiceList.get_by_binary(
                                ctxt, 'nova-compute')}

            compute_nodes = objects.ComputeNodeList.get_all(ctxt)
            for compute in compute_nodes:
                host = compute.host
                service = service_refs.get(host)
                if not service or service['disabled']:
                    continue

                # NOTE: This works because it is only used for computes found
                # in the cell this is run in. It can not be used to check on
                # computes in a child cell from the api cell. If this is run
                # in the api cell objects.ComputeNodeList.get_all() above will
                # return an empty list.
                alive = self.servicegroup_api.service_is_up(service)
                if not alive:
                    continue

                chost = compute_hosts[host]
                chost['free_ram_mb'] += max(0, compute.free_ram_mb)
                chost['free_disk_mb'] += max(0, compute.free_disk_gb) * 1024
                chost['total_ram_mb'] += max(0, compute.memory_mb)
                chost['total_disk_mb'] += max(0, compute.local_gb) * 1024

        _get_compute_hosts()
        if not compute_hosts:
            self.my_cell_state.update_capacities({})
            return

        ram_mb_free_units = {}
        disk_mb_free_units = {}
        total_ram_mb_free = 0
        total_disk_mb_free = 0

        def _free_units(total, free, per_inst):
            if per_inst:
                min_free = total * reserve_level
                free = max(0, free - min_free)
                return int(free / per_inst)
            else:
                return 0

        flavors = objects.FlavorList.get_all(ctxt)
        memory_mb_slots = frozenset(
                [flavor.memory_mb for flavor in flavors])
        disk_mb_slots = frozenset(
                [(flavor.root_gb + flavor.ephemeral_gb) * units.Ki
                    for flavor in flavors])

        for compute_values in compute_hosts.values():
            total_ram_mb_free += compute_values['free_ram_mb']
            total_disk_mb_free += compute_values['free_disk_mb']
            for memory_mb_slot in memory_mb_slots:
                ram_mb_free_units.setdefault(str(memory_mb_slot), 0)
                free_units = _free_units(compute_values['total_ram_mb'],
                        compute_values['free_ram_mb'], memory_mb_slot)
                ram_mb_free_units[str(memory_mb_slot)] += free_units
            for disk_mb_slot in disk_mb_slots:
                disk_mb_free_units.setdefault(str(disk_mb_slot), 0)
                free_units = _free_units(compute_values['total_disk_mb'],
                        compute_values['free_disk_mb'], disk_mb_slot)
                disk_mb_free_units[str(disk_mb_slot)] += free_units

        capacities = {'ram_free': {'total_mb': total_ram_mb_free,
                                   'units_by_mb': ram_mb_free_units},
                      'disk_free': {'total_mb': total_disk_mb_free,
                                    'units_by_mb': disk_mb_free_units}}
        self.my_cell_state.update_capacities(capacities)

    @sync_before
    def get_cell_info_for_neighbors(self):
        """Return cell information for all neighbor cells."""
        cell_list = [cell.get_cell_info()
                for cell in six.itervalues(self.child_cells)]
        cell_list.extend([cell.get_cell_info()
                for cell in six.itervalues(self.parent_cells)])
        return cell_list

    @sync_before
    def get_my_state(self):
        """Return information for my (this) cell."""
        return self.my_cell_state

    @sync_before
    def get_child_cells(self):
        """Return list of child cell_infos."""
        return list(self.child_cells.values())

    @sync_before
    def get_parent_cells(self):
        """Return list of parent cell_infos."""
        return list(self.parent_cells.values())

    @sync_before
    def get_parent_cell(self, cell_name):
        return self.parent_cells.get(cell_name)

    @sync_before
    def get_child_cell(self, cell_name):
        return self.child_cells.get(cell_name)

    @sync_before
    def update_cell_capabilities(self, cell_name, capabilities):
        """Update capabilities for a cell."""
        cell = (self.child_cells.get(cell_name) or
                self.parent_cells.get(cell_name))
        if not cell:
            LOG.error("Unknown cell '%(cell_name)s' when trying to "
                      "update capabilities",
                      {'cell_name': cell_name})
            return
        # Make sure capabilities are sets.
        for capab_name, values in capabilities.items():
            capabilities[capab_name] = set(values)
        cell.update_capabilities(capabilities)

    @sync_before
    def update_cell_capacities(self, cell_name, capacities):
        """Update capacities for a cell."""
        cell = (self.child_cells.get(cell_name) or
                self.parent_cells.get(cell_name))
        if not cell:
            LOG.error("Unknown cell '%(cell_name)s' when trying to "
                      "update capacities",
                      {'cell_name': cell_name})
            return
        cell.update_capacities(capacities)

    @sync_before
    def get_our_capabilities(self, include_children=True):
        capabs = copy.deepcopy(self.my_cell_state.capabilities)
        if include_children:
            for cell in self.child_cells.values():
                if timeutils.is_older_than(cell.last_seen,
                                CONF.cells.mute_child_interval):
                    continue
                for capab_name, values in cell.capabilities.items():
                    if capab_name not in capabs:
                        capabs[capab_name] = set([])
                    capabs[capab_name] |= values
        return capabs

    def _add_to_dict(self, target, src):
        for key, value in src.items():
            if isinstance(value, dict):
                target.setdefault(key, {})
                self._add_to_dict(target[key], value)
                continue
            target.setdefault(key, 0)
            target[key] += value

    @sync_before
    def get_our_capacities(self, include_children=True):
        capacities = copy.deepcopy(self.my_cell_state.capacities)
        if include_children:
            for cell in self.child_cells.values():
                self._add_to_dict(capacities, cell.capacities)
        return capacities

    @sync_before
    def get_capacities(self, cell_name=None):
        if not cell_name or cell_name == self.my_cell_state.name:
            return self.get_our_capacities()
        if cell_name in self.child_cells:
            return self.child_cells[cell_name].capacities
        raise exception.CellNotFound(cell_name=cell_name)

    @sync_before
    def cell_get(self, ctxt, cell_name):
        for cells_dict in (self.parent_cells, self.child_cells):
            if cell_name in cells_dict:
                return cells_dict[cell_name]

        raise exception.CellNotFound(cell_name=cell_name)


class CellStateManagerDB(CellStateManager):
    @utils.synchronized('cell-db-sync')
    def _cell_data_sync(self, force=False):
        """Update cell status for all cells from the backing data store
        when necessary.

        :param force: If True, cell status will be updated regardless
                      of whether it's time to do so.
        """
        if force or self._time_to_sync():
            LOG.debug("Updating cell cache from db.")
            self.last_cell_db_check = timeutils.utcnow()
            ctxt = context.get_admin_context()
            db_cells = self.db.cell_get_all(ctxt)
            db_cells_dict = {cell['name']: cell for cell in db_cells}
            self._refresh_cells_from_dict(db_cells_dict)
            self._update_our_capacity(ctxt)

    @sync_after
    def cell_create(self, ctxt, values):
        return self.db.cell_create(ctxt, values)

    @sync_after
    def cell_update(self, ctxt, cell_name, values):
        return self.db.cell_update(ctxt, cell_name, values)

    @sync_after
    def cell_delete(self, ctxt, cell_name):
        return self.db.cell_delete(ctxt, cell_name)


class CellStateManagerFile(CellStateManager):
    def __init__(self, cell_state_cls=None):
        cells_config = CONF.cells.cells_config
        self.cells_config_path = CONF.find_file(cells_config)
        if not self.cells_config_path:
            raise cfg.ConfigFilesNotFoundError(config_files=[cells_config])
        super(CellStateManagerFile, self).__init__(cell_state_cls)

    def _cell_data_sync(self, force=False):
        """Update cell status for all cells from the backing data store
        when necessary.

        :param force: If True, cell status will be updated regardless
                      of whether it's time to do so.
        """
        reloaded, data = utils.read_cached_file(self.cells_config_path,
                                                force_reload=force)

        if reloaded:
            LOG.debug("Updating cell cache from config file.")
            self.cells_config_data = jsonutils.loads(data)
            self._refresh_cells_from_dict(self.cells_config_data)

        if force or self._time_to_sync():
            self.last_cell_db_check = timeutils.utcnow()
            self._update_our_capacity()

    def cell_create(self, ctxt, values):
        raise exception.CellsUpdateUnsupported()

    def cell_update(self, ctxt, cell_name, values):
        raise exception.CellsUpdateUnsupported()

    def cell_delete(self, ctxt, cell_name):
        raise exception.CellsUpdateUnsupported()
