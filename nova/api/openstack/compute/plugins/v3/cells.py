# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011-2012 OpenStack Foundation
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

"""The cells extension."""

from oslo.config import cfg
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.cells import rpc_driver
from nova.cells import rpcapi as cells_rpcapi
from nova.compute import api as compute
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('name', 'nova.cells.opts', group='cells')
CONF.import_opt('capabilities', 'nova.cells.opts', group='cells')

ALIAS = "os-cells"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


def make_cell(elem):
    elem.set('name')
    elem.set('username')
    elem.set('type')
    elem.set('rpc_host')
    elem.set('rpc_port')

    caps = xmlutil.SubTemplateElement(elem, 'capabilities',
            selector='capabilities')
    cap = xmlutil.SubTemplateElement(caps, xmlutil.Selector(0),
            selector=xmlutil.get_items)
    cap.text = 1
    make_capacity(elem)


def make_capacity(cell):

    def get_units_by_mb(capacity_info):
        return capacity_info['units_by_mb'].items()

    capacity = xmlutil.SubTemplateElement(cell, 'capacities',
                                          selector='capacities')

    ram_free = xmlutil.SubTemplateElement(capacity, 'ram_free',
                                          selector='ram_free')
    ram_free.set('total_mb', 'total_mb')
    unit_by_mb = xmlutil.SubTemplateElement(ram_free, 'unit_by_mb',
                                            selector=get_units_by_mb)
    unit_by_mb.set('mb', 0)
    unit_by_mb.set('unit', 1)

    disk_free = xmlutil.SubTemplateElement(capacity, 'disk_free',
                                           selector='disk_free')
    disk_free.set('total_mb', 'total_mb')
    unit_by_mb = xmlutil.SubTemplateElement(disk_free, 'unit_by_mb',
                                            selector=get_units_by_mb)
    unit_by_mb.set('mb', 0)
    unit_by_mb.set('unit', 1)

cell_nsmap = {None: wsgi.XMLNS_V10}


class CellTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('cell', selector='cell')
        make_cell(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=cell_nsmap)


class CellsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('cells')
        elem = xmlutil.SubTemplateElement(root, 'cell', selector='cells')
        make_cell(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=cell_nsmap)


class CellDeserializer(wsgi.XMLDeserializer):
    """Deserializer to handle xml-formatted cell create requests."""

    def _extract_capabilities(self, cap_node):
        caps = {}
        for cap in cap_node.childNodes:
            cap_name = cap.tagName
            caps[cap_name] = self.extract_text(cap)
        return caps

    def _extract_cell(self, node):
        cell = {}
        cell_node = self.find_first_child_named(node, 'cell')

        extract_fns = {
            'capabilities': self._extract_capabilities,
            'rpc_port': lambda child: int(self.extract_text(child)),
        }

        for child in cell_node.childNodes:
            name = child.tagName
            extract_fn = extract_fns.get(name, self.extract_text)
            cell[name] = extract_fn(child)
        return cell

    def default(self, string):
        """Deserialize an xml-formatted cell create request."""
        node = xmlutil.safe_minidom_parse_string(string)

        return {'body': {'cell': self._extract_cell(node)}}


def _filter_keys(item, keys):
    """
    Filters all model attributes except for keys
    item is a dict

    """
    return dict((k, v) for k, v in item.iteritems() if k in keys)


def _fixup_cell_info(cell_info, keys):
    """
    If the transport_url is present in the cell, derive username,
    rpc_host, and rpc_port from it.
    """

    if 'transport_url' not in cell_info:
        return

    # Disassemble the transport URL
    transport_url = cell_info.pop('transport_url')
    try:
        transport = rpc_driver.parse_transport_url(transport_url)
    except ValueError:
        # Just go with None's
        for key in keys:
            cell_info.setdefault(key, None)
        return cell_info

    transport_field_map = {'rpc_host': 'hostname', 'rpc_port': 'port'}
    for key in keys:
        if key in cell_info:
            continue

        transport_field = transport_field_map.get(key, key)
        cell_info[key] = transport[transport_field]


def _scrub_cell(cell, detail=False):
    keys = ['name', 'username', 'rpc_host', 'rpc_port']
    if detail:
        keys.append('capabilities')

    cell_info = _filter_keys(cell, keys + ['transport_url'])
    _fixup_cell_info(cell_info, keys)
    cell_info['type'] = 'parent' if cell['is_parent'] else 'child'
    return cell_info


class CellsController(object):
    """Controller for Cell resources."""

    def __init__(self):
        self.compute_api = compute.API()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _get_cells(self, ctxt, req, detail=False):
        """Return all cells."""
        # Ask the CellsManager for the most recent data
        items = self.cells_rpcapi.get_cell_info_for_neighbors(ctxt)
        items = common.limited(items, req)
        items = [_scrub_cell(item, detail=detail) for item in items]
        return dict(cells=items)

    @extensions.expected_errors(())
    @wsgi.serializers(xml=CellsTemplate)
    def index(self, req):
        """Return all cells in brief."""
        ctxt = req.environ['nova.context']
        authorize(ctxt)
        return self._get_cells(ctxt, req)

    @extensions.expected_errors(())
    @wsgi.serializers(xml=CellsTemplate)
    def detail(self, req):
        """Return all cells in detail."""
        ctxt = req.environ['nova.context']
        authorize(ctxt)
        return self._get_cells(ctxt, req, detail=True)

    @extensions.expected_errors(())
    @wsgi.serializers(xml=CellTemplate)
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

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=CellTemplate)
    def capacities(self, req, id=None):
        """Return capacities for a given cell or all cells."""
        # TODO(kaushikc): return capacities as a part of cell info and
        # cells detail calls in v3, along with capabilities
        context = req.environ['nova.context']
        authorize(context)
        try:
            capacities = self.cells_rpcapi.get_capacities(context,
                                                          cell_name=id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return dict(cell={"capacities": capacities})

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=CellTemplate)
    def show(self, req, id):
        """Return data about the given cell name.  'id' is a cell name."""
        context = req.environ['nova.context']
        authorize(context)
        try:
            cell = self.cells_rpcapi.cell_get(context, id)
        except exception.CellNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @extensions.expected_errors((403, 404))
    @wsgi.response(204)
    def delete(self, req, id):
        """Delete a child or parent cell entry.  'id' is a cell name."""
        context = req.environ['nova.context']
        authorize(context)
        try:
            num_deleted = self.cells_rpcapi.cell_delete(context, id)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        if num_deleted == 0:
            raise exc.HTTPNotFound(
                explanation=_("Cell %s doesn't exist.") % id)

    def _validate_cell_name(self, cell_name):
        """Validate cell name is not empty and doesn't contain '!' or '.'."""
        if not cell_name:
            msg = _("Cell name cannot be empty")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)
        if '!' in cell_name or '.' in cell_name:
            msg = _("Cell name cannot contain '!' or '.'")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    def _validate_cell_type(self, cell_type):
        """Validate cell_type is 'parent' or 'child'."""
        if cell_type not in ['parent', 'child']:
            msg = _("Cell type must be 'parent' or 'child'")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    def _normalize_cell(self, cell, existing=None):
        """
        Normalize input cell data.  Normalizations include:

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
        transport = {}
        if existing and 'transport_url' in existing:
            transport = rpc_driver.parse_transport_url(
                existing['transport_url'])

        # Copy over the input fields
        transport_field_map = {
            'username': 'username',
            'password': 'password',
            'hostname': 'rpc_host',
            'port': 'rpc_port',
            'virtual_host': 'rpc_virtual_host',
        }
        for key, input_field in transport_field_map.items():
            # Set the default value of the field; using setdefault()
            # lets us avoid overriding the existing transport URL
            transport.setdefault(key, None)

            # Only override the value if we're given an override
            if input_field in cell:
                transport[key] = cell.pop(input_field)

        # Now set the transport URL
        cell['transport_url'] = rpc_driver.unparse_transport_url(transport)

    @extensions.expected_errors((400, 403))
    @wsgi.serializers(xml=CellTemplate)
    @wsgi.deserializers(xml=CellDeserializer)
    @wsgi.response(201)
    def create(self, req, body):
        """Create a child cell entry."""
        context = req.environ['nova.context']
        authorize(context)
        if 'cell' not in body:
            msg = _("No cell information in request")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)
        cell = body['cell']
        if 'name' not in cell:
            msg = _("No cell name in request")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)
        self._validate_cell_name(cell['name'])
        self._normalize_cell(cell)
        try:
            cell = self.cells_rpcapi.cell_create(context, cell)
        except exception.CellsUpdateUnsupported as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(cell=_scrub_cell(cell))

    @extensions.expected_errors((400, 403, 404))
    @wsgi.serializers(xml=CellTemplate)
    @wsgi.deserializers(xml=CellDeserializer)
    def update(self, req, id, body):
        """Update a child cell entry.  'id' is the cell name to update."""
        context = req.environ['nova.context']
        authorize(context)
        if 'cell' not in body:
            msg = _("No cell information in request")
            LOG.error(msg)
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

    @extensions.expected_errors(400)
    @wsgi.response(204)
    def sync_instances(self, req, body):
        """Tell all cells to sync instance info."""
        context = req.environ['nova.context']
        authorize(context)
        project_id = body.pop('project_id', None)
        deleted = body.pop('deleted', False)
        updated_since = body.pop('updated_since', None)
        if body:
            msg = _("Only 'updated_since', 'project_id' and 'deleted' are "
                    "understood.")
            raise exc.HTTPBadRequest(explanation=msg)
        if updated_since:
            try:
                timeutils.parse_isotime(updated_since)
            except ValueError:
                msg = _('Invalid changes-since value')
                raise exc.HTTPBadRequest(explanation=msg)
        self.cells_rpcapi.sync_instances(context, project_id=project_id,
                updated_since=updated_since, deleted=deleted)


class Cells(extensions.V3APIExtensionBase):
    """Enables cells-related functionality such as adding neighbor cells,
    listing neighbor cells, and getting the capabilities of the local cell.
    """

    name = "Cells"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/cells/api/v3"
    version = 1

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

        res = extensions.ResourceExtension(ALIAS, CellsController(),
                                           collection_actions=coll_actions,
                                           member_actions=memb_actions)
        return [res]

    def get_controller_extensions(self):
        return []
