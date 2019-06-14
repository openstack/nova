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

from oslo_db import exception as db_exc
from sqlalchemy.orm import joinedload

from nova import context
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.i18n import _
from nova.objects import base
from nova.objects import cell_mapping
from nova.objects import fields


def _cell_id_in_updates(updates):
    cell_mapping_obj = updates.pop("cell_mapping", None)
    if cell_mapping_obj:
        updates["cell_id"] = cell_mapping_obj.id


def _apply_updates(context, db_mapping, updates):
    db_mapping.update(updates)
    db_mapping.save(context.session)
    # NOTE: This is done because a later access will trigger a lazy load
    # outside of the db session so it will fail. We don't lazy load
    # cell_mapping on the object later because we never need a HostMapping
    # without the CellMapping.
    db_mapping.cell_mapping
    return db_mapping


@base.NovaObjectRegistry.register
class HostMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'host': fields.StringField(),
        'cell_mapping': fields.ObjectField('CellMapping'),
        }

    def _get_cell_mapping(self):
        with db_api.api_context_manager.reader.using(self._context) as session:
            cell_map = (session.query(api_models.CellMapping)
                        .join(api_models.HostMapping)
                        .filter(api_models.HostMapping.host == self.host)
                        .first())
            if cell_map is not None:
                return cell_mapping.CellMapping._from_db_object(
                    self._context, cell_mapping.CellMapping(), cell_map)

    def _load_cell_mapping(self):
        self.cell_mapping = self._get_cell_mapping()

    def obj_load_attr(self, attrname):
        if attrname == 'cell_mapping':
            self._load_cell_mapping()

    @staticmethod
    def _from_db_object(context, host_mapping, db_host_mapping):
        for key in host_mapping.fields:
            db_value = db_host_mapping.get(key)
            if key == "cell_mapping":
                # NOTE(dheeraj): If cell_mapping is stashed in db object
                # we load it here. Otherwise, lazy loading will happen
                # when .cell_mapping is accessed later
                if not db_value:
                    continue
                db_value = cell_mapping.CellMapping._from_db_object(
                    host_mapping._context, cell_mapping.CellMapping(),
                    db_value)
            setattr(host_mapping, key, db_value)
        host_mapping.obj_reset_changes()
        host_mapping._context = context
        return host_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_host_from_db(context, host):
        db_mapping = (context.session.query(api_models.HostMapping)
                      .options(joinedload('cell_mapping'))
                      .filter(api_models.HostMapping.host == host)).first()
        if not db_mapping:
            raise exception.HostMappingNotFound(name=host)
        return db_mapping

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_mapping = cls._get_by_host_from_db(context, host)
        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_mapping = api_models.HostMapping()
        return _apply_updates(context, db_mapping, updates)

    @base.remotable
    def create(self):
        changes = self.obj_get_changes()
        # cell_mapping must be mapped to cell_id for create
        _cell_id_in_updates(changes)
        db_mapping = self._create_in_db(self._context, changes)
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, obj, updates):
        db_mapping = context.session.query(api_models.HostMapping).filter_by(
            id=obj.id).first()
        if not db_mapping:
            raise exception.HostMappingNotFound(name=obj.host)
        return _apply_updates(context, db_mapping, updates)

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        # cell_mapping must be mapped to cell_id for updates
        _cell_id_in_updates(changes)
        db_mapping = self._save_in_db(self._context, self, changes)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, host):
        result = context.session.query(api_models.HostMapping).filter_by(
                host=host).delete()
        if not result:
            raise exception.HostMappingNotFound(name=host)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.host)


@base.NovaObjectRegistry.register
class HostMappingList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add get_all method
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('HostMapping'),
        }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db(context, cell_id=None):
        query = (context.session.query(api_models.HostMapping)
                 .options(joinedload('cell_mapping')))
        if cell_id:
            query = query.filter(api_models.HostMapping.cell_id == cell_id)
        return query.all()

    @base.remotable_classmethod
    def get_by_cell_id(cls, context, cell_id):
        db_mappings = cls._get_from_db(context, cell_id)
        return base.obj_make_list(context, cls(), HostMapping, db_mappings)

    @base.remotable_classmethod
    def get_all(cls, context):
        db_mappings = cls._get_from_db(context)
        return base.obj_make_list(context, cls(), HostMapping, db_mappings)


def _create_host_mapping(host_mapping):
    try:
        host_mapping.create()
    except db_exc.DBDuplicateEntry:
        raise exception.HostMappingExists(name=host_mapping.host)


def _check_and_create_node_host_mappings(ctxt, cm, compute_nodes, status_fn):
    host_mappings = []
    for compute in compute_nodes:
        status_fn(_("Checking host mapping for compute host "
                    "'%(host)s': %(uuid)s") %
                  {'host': compute.host, 'uuid': compute.uuid})
        try:
            HostMapping.get_by_host(ctxt, compute.host)
        except exception.HostMappingNotFound:
            status_fn(_("Creating host mapping for compute host "
                        "'%(host)s': %(uuid)s") %
                      {'host': compute.host, 'uuid': compute.uuid})
            host_mapping = HostMapping(
                ctxt, host=compute.host,
                cell_mapping=cm)
            _create_host_mapping(host_mapping)
            host_mappings.append(host_mapping)
            compute.mapped = 1
            compute.save()
    return host_mappings


def _check_and_create_service_host_mappings(ctxt, cm, services, status_fn):
    host_mappings = []
    for service in services:
        try:
            HostMapping.get_by_host(ctxt, service.host)
        except exception.HostMappingNotFound:
            status_fn(_('Creating host mapping for service %(srv)s') %
                        {'srv': service.host})
            host_mapping = HostMapping(
                ctxt, host=service.host,
                cell_mapping=cm)
            _create_host_mapping(host_mapping)
            host_mappings.append(host_mapping)
    return host_mappings


def _check_and_create_host_mappings(ctxt, cm, status_fn, by_service):
    from nova import objects

    if by_service:
        services = objects.ServiceList.get_by_binary(
            ctxt, 'nova-compute', include_disabled=True)
        added_hm = _check_and_create_service_host_mappings(ctxt, cm,
                                                           services,
                                                           status_fn)
    else:
        compute_nodes = objects.ComputeNodeList.get_all_by_not_mapped(
            ctxt, 1)
        added_hm = _check_and_create_node_host_mappings(ctxt, cm,
                                                        compute_nodes,
                                                        status_fn)
    return added_hm


def discover_hosts(ctxt, cell_uuid=None, status_fn=None, by_service=False):
    # TODO(alaski): If this is not run on a host configured to use the API
    # database most of the lookups below will fail and may not provide a
    # great error message. Add a check which will raise a useful error
    # message about running this from an API host.

    from nova import objects

    if not status_fn:
        status_fn = lambda x: None

    if cell_uuid:
        cell_mappings = [objects.CellMapping.get_by_uuid(ctxt, cell_uuid)]
    else:
        cell_mappings = objects.CellMappingList.get_all(ctxt)
        status_fn(_('Found %s cell mappings.') % len(cell_mappings))

    host_mappings = []
    for cm in cell_mappings:
        if cm.is_cell0():
            status_fn(_('Skipping cell0 since it does not contain hosts.'))
            continue
        if 'name' in cm and cm.name:
            status_fn(_("Getting computes from cell '%(name)s': "
                        "%(uuid)s") % {'name': cm.name,
                                       'uuid': cm.uuid})
        else:
            status_fn(_("Getting computes from cell: %(uuid)s") %
                      {'uuid': cm.uuid})
        with context.target_cell(ctxt, cm) as cctxt:
            added_hm = _check_and_create_host_mappings(cctxt, cm, status_fn,
                                                       by_service)
            status_fn(_('Found %(num)s unmapped computes in cell: %(uuid)s') %
                      {'num': len(added_hm),
                       'uuid': cm.uuid})

            host_mappings.extend(added_hm)

    return host_mappings
