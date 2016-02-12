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
from oslo_utils import timeutils
import six
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.cells import rpcapi as cells_rpcapi
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import rpc


CONF = nova.conf.CONF

authorize = extensions.extension_authorizer('compute', 'cells')


def _filter_keys(item, keys):
    """Filters all model attributes except for keys
    item is a dict

    """
    return {k: v for k, v in six.iteritems(item) if k in keys}


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


class Controller(object):
    """Controller for Cell resources."""

    def __init__(self, ext_mgr):
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self.ext_mgr = ext_mgr

    def _get_cells(self, ctxt, req, detail=False):
        """Return all cells."""
        # Ask the CellsManager for the most recent data
        items = self.cells_rpcapi.get_cell_info_for_neighbors(ctxt)
        items = common.limited(items, req)
        items = [_scrub_cell(item, detail=detail) for item in items]
        return dict(cells=items)

    @common.check_cells_enabled
    def index(self, req):
        """Return all cells in brief."""
        ctxt = req.environ['nova.context']
        authorize(ctxt)
        return self._get_cells(ctxt, req)

    @common.check_cells_enabled
    def detail(self, req):
        """Return all cells in detail."""
        ctxt = req.environ['nova.context']
        authorize(ctxt)
        return self._get_cells(ctxt, req, detail=True)

    @common.check_cells_enabled
    def info(self, req):
        """Return name and capabilities for this cell."""
        context = req.environ['nova.context']
        authorize(context)
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

    @common.check_cells_enabled
    def capacities(self, req, id=None):
        """Return capacities for a given cell or all cells."""
        # TODO(kaushikc): return capacities as a part of cell info and
        # cells detail calls in v2.1, along with capabilities
        if not self.ext_mgr.is_loaded('os-cell-capacities'):
            raise exc.HTTPNotFound()

        context = req.environ['nova.context']
        authorize(context)
        try:
            capacities = self.cells_rpcapi.get_capacities(context,
                                                          cell_name=id)
        except exception.CellNotFound:
            msg = (_("Cell %(id)s not found.") % {'id': id})
            raise exc.HTTPNotFound(explanation=msg)

        return dict(cell={"capacities": capacities})

    @common.check_cells_enabled
    def show(self, req, id):
        """Return data about the given cell name.  'id' is a cell name."""
        context = req.environ['nova.context']
        authorize(context)
        try:
            cell = self.cells_rpcapi.cell_get(context, id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @common.check_cells_enabled
    def delete(self, req, id):
        """Delete a child or parent cell entry.  'id' is a cell name."""
        context = req.environ['nova.context']

        authorize(context)
        authorize(context, action="delete")
        # NOTE(eliqiao): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)

        try:
            num_deleted = self.cells_rpcapi.cell_delete(context, id)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        if num_deleted == 0:
            raise exc.HTTPNotFound()
        return {}

    def _validate_cell_name(self, cell_name):
        """Validate cell name is not empty and doesn't contain '!',
         '.' or '@'.
        """
        if not cell_name:
            msg = _("Cell name cannot be empty")
            raise exc.HTTPBadRequest(explanation=msg)
        if '!' in cell_name or '.' in cell_name or '@' in cell_name:
            msg = _("Cell name cannot contain '!', '.' or '@'")
            raise exc.HTTPBadRequest(explanation=msg)

    def _validate_cell_type(self, cell_type):
        """Validate cell_type is 'parent' or 'child'."""
        if cell_type not in ['parent', 'child']:
            msg = _("Cell type must be 'parent' or 'child'")
            raise exc.HTTPBadRequest(explanation=msg)

    def _normalize_cell(self, cell, existing=None):
        """Normalize input cell data.  Normalizations include:

        * Converting cell['type'] to is_parent boolean.
        * Merging existing transport URL with transport information.
        """

        # Start with the cell type conversion
        if 'type' in cell:
            self._validate_cell_type(cell['type'])
            cell['is_parent'] = cell['type'] == 'parent'
            del cell['type']
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
        if cell.get('rpc_port') is not None:
            try:
                cell['rpc_port'] = int(cell['rpc_port'])
            except ValueError:
                raise exc.HTTPBadRequest(
                    explanation=_('rpc_port must be integer'))
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

    @common.check_cells_enabled
    def create(self, req, body):
        """Create a child cell entry."""
        context = req.environ['nova.context']

        authorize(context)
        authorize(context, action="create")
        # NOTE(eliqiao): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)

        if 'cell' not in body:
            msg = _("No cell information in request")
            raise exc.HTTPBadRequest(explanation=msg)
        cell = body['cell']
        if 'name' not in cell:
            msg = _("No cell name in request")
            raise exc.HTTPBadRequest(explanation=msg)
        self._validate_cell_name(cell['name'])
        self._normalize_cell(cell)
        try:
            cell = self.cells_rpcapi.cell_create(context, cell)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @common.check_cells_enabled
    def update(self, req, id, body):
        """Update a child cell entry.  'id' is the cell name to update."""
        context = req.environ['nova.context']

        authorize(context)
        authorize(context, action="update")
        # NOTE(eliqiao): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)

        if 'cell' not in body:
            msg = _("No cell information in request")
            raise exc.HTTPBadRequest(explanation=msg)
        cell = body['cell']
        cell.pop('id', None)
        if 'name' in cell:
            self._validate_cell_name(cell['name'])
        try:
            # NOTE(Vek): There is a race condition here if multiple
            #            callers are trying to update the cell
            #            information simultaneously.  Since this
            #            operation is administrative in nature, and
            #            will be going away in the future, I don't see
            #            it as much of a problem...
            existing = self.cells_rpcapi.cell_get(context, id)
        except exception.CellNotFound:
            raise exc.HTTPNotFound()
        self._normalize_cell(cell, existing)
        try:
            cell = self.cells_rpcapi.cell_update(context, id, cell)
        except exception.CellNotFound:
            raise exc.HTTPNotFound()
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @common.check_cells_enabled
    def sync_instances(self, req, body):
        """Tell all cells to sync instance info."""
        context = req.environ['nova.context']

        authorize(context)
        authorize(context, action="sync_instances")

        project_id = body.pop('project_id', None)
        deleted = body.pop('deleted', False)
        updated_since = body.pop('updated_since', None)
        if body:
            msg = _("Only 'updated_since', 'project_id' and 'deleted' are "
                    "understood.")
            raise exc.HTTPBadRequest(explanation=msg)
        if isinstance(deleted, six.string_types):
            try:
                deleted = strutils.bool_from_string(deleted, strict=True)
            except ValueError as err:
                raise exc.HTTPBadRequest(explanation=six.text_type(err))
        if updated_since:
            try:
                timeutils.parse_isotime(updated_since)
            except ValueError:
                msg = _('Invalid changes-since value')
                raise exc.HTTPBadRequest(explanation=msg)
        self.cells_rpcapi.sync_instances(context, project_id=project_id,
                updated_since=updated_since, deleted=deleted)


class Cells(extensions.ExtensionDescriptor):
    """Enables cells-related functionality such as adding neighbor cells,
    listing neighbor cells, and getting the capabilities of the local cell.
    """

    name = "Cells"
    alias = "os-cells"
    namespace = "http://docs.openstack.org/compute/ext/cells/api/v1.1"
    updated = "2013-05-14T00:00:00Z"

    def get_resources(self):
        coll_actions = {
                'detail': 'GET',
                'info': 'GET',
                'sync_instances': 'POST',
                'capacities': 'GET',
                }
        memb_actions = {
                'capacities': 'GET',
                }

        res = extensions.ResourceExtension('os-cells',
                Controller(self.ext_mgr), collection_actions=coll_actions,
                member_actions=memb_actions)
        return [res]
