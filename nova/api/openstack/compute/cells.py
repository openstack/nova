# Copyright 2011-2012 OpenStack Foundation
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

"""The cells extension."""

import oslo_messaging as messaging
from oslo_utils import strutils
import six
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import cells
from nova.api.openstack import wsgi
from nova.api import validation
from nova.cells import rpcapi as cells_rpcapi
import nova.conf
from nova import exception
from nova.i18n import _
from nova.policies import cells as cells_policies
from nova import rpc


CONF = nova.conf.CONF


def _filter_keys(item, keys):
    """Filters all model attributes except for keys
    item is a dict
    """
    return {k: v for k, v in item.items() if k in keys}


def _fixup_cell_info(cell_info, keys):
    """If the transport_url is present in the cell, derive username,
    rpc_host, and rpc_port from it.
    """

    if 'transport_url' not in cell_info:
        return

    # Disassemble the transport URL
    transport_url = cell_info.pop('transport_url')
    try:
        transport_url = rpc.get_transport_url(transport_url)
    except messaging.InvalidTransportURL:
        # Just go with None's
        for key in keys:
            cell_info.setdefault(key, None)
        return

    if not transport_url.hosts:
        return

    transport_host = transport_url.hosts[0]

    transport_field_map = {'rpc_host': 'hostname', 'rpc_port': 'port'}
    for key in keys:
        if key in cell_info:
            continue

        transport_field = transport_field_map.get(key, key)
        cell_info[key] = getattr(transport_host, transport_field)


def _scrub_cell(cell, detail=False):
    keys = ['name', 'username', 'rpc_host', 'rpc_port']
    if detail:
        keys.append('capabilities')

    cell_info = _filter_keys(cell, keys + ['transport_url'])
    _fixup_cell_info(cell_info, keys)
    cell_info['type'] = 'parent' if cell['is_parent'] else 'child'
    return cell_info


class CellsController(wsgi.Controller):
    """Controller for Cell resources."""

    def __init__(self):
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _get_cells(self, ctxt, req, detail=False):
        """Return all cells."""
        # Ask the CellsManager for the most recent data
        items = self.cells_rpcapi.get_cell_info_for_neighbors(ctxt)
        items = common.limited(items, req)
        items = [_scrub_cell(item, detail=detail) for item in items]
        return dict(cells=items)

    @wsgi.expected_errors(501)
    @common.check_cells_enabled
    def index(self, req):
        """Return all cells in brief."""
        ctxt = req.environ['nova.context']
        ctxt.can(cells_policies.BASE_POLICY_NAME)
        return self._get_cells(ctxt, req)

    @wsgi.expected_errors(501)
    @common.check_cells_enabled
    def detail(self, req):
        """Return all cells in detail."""
        ctxt = req.environ['nova.context']
        ctxt.can(cells_policies.BASE_POLICY_NAME)
        return self._get_cells(ctxt, req, detail=True)

    @wsgi.expected_errors(501)
    @common.check_cells_enabled
    def info(self, req):
        """Return name and capabilities for this cell."""
        context = req.environ['nova.context']
        context.can(cells_policies.BASE_POLICY_NAME)
        cell_capabs = {}
        my_caps = CONF.cells.capabilities
        for cap in my_caps:
            key, value = cap.split('=')
            cell_capabs[key] = value
        cell = {'name': CONF.cells.name,
                'type': 'self',
                'rpc_host': None,
                'rpc_port': 0,
                'username': None,
                'capabilities': cell_capabs}
        return dict(cell=cell)

    @wsgi.expected_errors((404, 501))
    @common.check_cells_enabled
    def capacities(self, req, id=None):
        """Return capacities for a given cell or all cells."""
        # TODO(kaushikc): return capacities as a part of cell info and
        # cells detail calls in v2.1, along with capabilities
        context = req.environ['nova.context']
        context.can(cells_policies.BASE_POLICY_NAME)
        try:
            capacities = self.cells_rpcapi.get_capacities(context,
                                                          cell_name=id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return dict(cell={"capacities": capacities})

    @wsgi.expected_errors((404, 501))
    @common.check_cells_enabled
    def show(self, req, id):
        """Return data about the given cell name.  'id' is a cell name."""
        context = req.environ['nova.context']
        context.can(cells_policies.BASE_POLICY_NAME)
        try:
            cell = self.cells_rpcapi.cell_get(context, id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 204
    # as this operation complete the deletion of aggregate resource and return
    # no response body.
    @wsgi.expected_errors((403, 404, 501))
    @common.check_cells_enabled
    def delete(self, req, id):
        """Delete a child or parent cell entry.  'id' is a cell name."""
        context = req.environ['nova.context']

        context.can(cells_policies.POLICY_ROOT % "delete")

        try:
            num_deleted = self.cells_rpcapi.cell_delete(context, id)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        if num_deleted == 0:
            raise exc.HTTPNotFound(
                explanation=_("Cell %s doesn't exist.") % id)

    def _normalize_cell(self, cell, existing=None):
        """Normalize input cell data.  Normalizations include:

        * Converting cell['type'] to is_parent boolean.
        * Merging existing transport URL with transport information.
        """

        if 'name' in cell:
            cell['name'] = common.normalize_name(cell['name'])

        # Start with the cell type conversion
        if 'type' in cell:
            cell['is_parent'] = cell.pop('type') == 'parent'
        # Avoid cell type being overwritten to 'child'
        elif existing:
            cell['is_parent'] = existing['is_parent']
        else:
            cell['is_parent'] = False

        # Now we disassemble the existing transport URL...
        transport_url = existing.get('transport_url') if existing else None
        transport_url = rpc.get_transport_url(transport_url)

        if 'rpc_virtual_host' in cell:
            transport_url.virtual_host = cell.pop('rpc_virtual_host')

        if not transport_url.hosts:
            transport_url.hosts.append(messaging.TransportHost())
        transport_host = transport_url.hosts[0]
        if 'rpc_port' in cell:
            cell['rpc_port'] = int(cell['rpc_port'])
        # Copy over the input fields
        transport_field_map = {
            'username': 'username',
            'password': 'password',
            'hostname': 'rpc_host',
            'port': 'rpc_port',
        }
        for key, input_field in transport_field_map.items():
            # Only override the value if we're given an override
            if input_field in cell:
                setattr(transport_host, key, cell.pop(input_field))

        # Now set the transport URL
        cell['transport_url'] = str(transport_url)

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 201
    # as this operation complete the creation of aggregates resource when
    # returning a response.
    @wsgi.expected_errors((400, 403, 501))
    @common.check_cells_enabled
    @validation.schema(cells.create_v20, '2.0', '2.0')
    @validation.schema(cells.create, '2.1')
    def create(self, req, body):
        """Create a child cell entry."""
        context = req.environ['nova.context']

        context.can(cells_policies.POLICY_ROOT % "create")

        cell = body['cell']
        self._normalize_cell(cell)
        try:
            cell = self.cells_rpcapi.cell_create(context, cell)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @wsgi.expected_errors((400, 403, 404, 501))
    @common.check_cells_enabled
    @validation.schema(cells.update_v20, '2.0', '2.0')
    @validation.schema(cells.update, '2.1')
    def update(self, req, id, body):
        """Update a child cell entry.  'id' is the cell name to update."""
        context = req.environ['nova.context']

        context.can(cells_policies.POLICY_ROOT % "update")

        cell = body['cell']
        cell.pop('id', None)

        try:
            # NOTE(Vek): There is a race condition here if multiple
            #            callers are trying to update the cell
            #            information simultaneously.  Since this
            #            operation is administrative in nature, and
            #            will be going away in the future, I don't see
            #            it as much of a problem...
            existing = self.cells_rpcapi.cell_get(context, id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        self._normalize_cell(cell, existing)
        try:
            cell = self.cells_rpcapi.cell_update(context, id, cell)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 204
    # as this operation complete the sync instance info and return
    # no response body.
    @wsgi.expected_errors((400, 501))
    @common.check_cells_enabled
    @validation.schema(cells.sync_instances)
    def sync_instances(self, req, body):
        """Tell all cells to sync instance info."""
        context = req.environ['nova.context']

        context.can(cells_policies.POLICY_ROOT % "sync_instances")

        project_id = body.pop('project_id', None)
        deleted = body.pop('deleted', False)
        updated_since = body.pop('updated_since', None)
        if isinstance(deleted, six.string_types):
            deleted = strutils.bool_from_string(deleted, strict=True)
        self.cells_rpcapi.sync_instances(context, project_id=project_id,
                updated_since=updated_since, deleted=deleted)
