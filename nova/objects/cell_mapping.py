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

from oslo_log import log as logging
from oslo_utils import versionutils
import six.moves.urllib.parse as urlparse
from sqlalchemy.sql.expression import asc
from sqlalchemy.sql import false
from sqlalchemy.sql import true

import nova.conf
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.objects import base
from nova.objects import fields

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def _parse_netloc(netloc):
    """Parse a user:pass@host:port and return a dict suitable for formatting
    a cell mapping template.
    """
    these = {
        'username': None,
        'password': None,
        'hostname': None,
        'port': None,
    }

    if '@' in netloc:
        userpass, hostport = netloc.split('@', 1)
    else:
        hostport = netloc
        userpass = ''

    if hostport.startswith('['):
        host_end = hostport.find(']')
        if host_end < 0:
            raise ValueError('Invalid IPv6 URL')
        these['hostname'] = hostport[1:host_end]
        these['port'] = hostport[host_end + 1:]
    elif ':' in hostport:
        these['hostname'], these['port'] = hostport.split(':', 1)
    else:
        these['hostname'] = hostport

    if ':' in userpass:
        these['username'], these['password'] = userpass.split(':', 1)
    else:
        these['username'] = userpass

    return these


@base.NovaObjectRegistry.register
class CellMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added disabled field
    VERSION = '1.1'

    CELL0_UUID = '00000000-0000-0000-0000-000000000000'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'transport_url': fields.StringField(),
        'database_connection': fields.StringField(),
        'disabled': fields.BooleanField(default=False),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(CellMapping, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            if 'disabled' in primitive:
                del primitive['disabled']

    @property
    def identity(self):
        if 'name' in self and self.name:
            return '%s(%s)' % (self.uuid, self.name)
        else:
            return self.uuid

    @staticmethod
    def _format_url(url, default):
        default_url = urlparse.urlparse(default)

        subs = {
            'username': default_url.username,
            'password': default_url.password,
            'hostname': default_url.hostname,
            'port': default_url.port,
            'scheme': default_url.scheme,
            'query': default_url.query,
            'fragment': default_url.fragment,
            'path': default_url.path.lstrip('/'),
        }

        # NOTE(danms): oslo.messaging has an extended format for the URL
        # which we need to support:
        #   scheme://user:pass@host:port[,user1:pass@host1:port, ...]/path
        # Encode these values, if they exist, as indexed keys like
        # username1, password1, hostname1, port1.
        if ',' in default_url.netloc:
            netlocs = default_url.netloc.split(',')
            index = 0
            for netloc in netlocs:
                index += 1
                these = _parse_netloc(netloc)
                for key in these:
                    subs['%s%i' % (key, index)] = these[key]

        return url.format(**subs)

    @staticmethod
    def format_db_url(url):
        if CONF.database.connection is None:
            if '{' in url:
                LOG.error('Cell mapping database_connection is a template, '
                          'but [database]/connection is not set')
            return url
        try:
            return CellMapping._format_url(url, CONF.database.connection)
        except Exception:
            LOG.exception('Failed to parse [database]/connection to '
                          'format cell mapping')
            return url

    @staticmethod
    def format_mq_url(url):
        if CONF.transport_url is None:
            if '{' in url:
                LOG.error('Cell mapping transport_url is a template, but '
                          '[DEFAULT]/transport_url is not set')
            return url
        try:
            return CellMapping._format_url(url, CONF.transport_url)
        except Exception:
            LOG.exception('Failed to parse [DEFAULT]/transport_url to '
                          'format cell mapping')
            return url

    @staticmethod
    def _from_db_object(context, cell_mapping, db_cell_mapping):
        for key in cell_mapping.fields:
            val = db_cell_mapping[key]
            if key == 'database_connection':
                val = cell_mapping.format_db_url(val)
            elif key == 'transport_url':
                val = cell_mapping.format_mq_url(val)
            setattr(cell_mapping, key, val)
        cell_mapping.obj_reset_changes()
        cell_mapping._context = context
        return cell_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_uuid_from_db(context, uuid):

        db_mapping = context.session.query(api_models.CellMapping).filter_by(
                uuid=uuid).first()
        if not db_mapping:
            raise exception.CellMappingNotFound(uuid=uuid)

        return db_mapping

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        db_mapping = cls._get_by_uuid_from_db(context, uuid)

        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):

        db_mapping = api_models.CellMapping()
        db_mapping.update(updates)
        db_mapping.save(context.session)
        return db_mapping

    @base.remotable
    def create(self):
        db_mapping = self._create_in_db(self._context, self.obj_get_changes())
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, uuid, updates):

        db_mapping = context.session.query(
                api_models.CellMapping).filter_by(uuid=uuid).first()
        if not db_mapping:
            raise exception.CellMappingNotFound(uuid=uuid)

        db_mapping.update(updates)
        context.session.add(db_mapping)
        return db_mapping

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        db_mapping = self._save_in_db(self._context, self.uuid, changes)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, uuid):

        result = context.session.query(api_models.CellMapping).filter_by(
                uuid=uuid).delete()
        if not result:
            raise exception.CellMappingNotFound(uuid=uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.uuid)

    def is_cell0(self):
        return self.obj_attr_is_set('uuid') and self.uuid == self.CELL0_UUID


@base.NovaObjectRegistry.register
class CellMappingList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add get_by_disabled()
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('CellMapping'),
    }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_from_db(context):
        return context.session.query(api_models.CellMapping).order_by(
            asc(api_models.CellMapping.id)).all()

    @base.remotable_classmethod
    def get_all(cls, context):
        db_mappings = cls._get_all_from_db(context)
        return base.obj_make_list(context, cls(), CellMapping, db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_disabled_from_db(context, disabled):
        if disabled:
            return context.session.query(api_models.CellMapping).filter_by(
                disabled=true()).order_by(asc(api_models.CellMapping.id)).all()
        else:
            return context.session.query(api_models.CellMapping).filter_by(
                disabled=false()).order_by(asc(
                    api_models.CellMapping.id)).all()

    @base.remotable_classmethod
    def get_by_disabled(cls, context, disabled):
        db_mappings = cls._get_by_disabled_from_db(context, disabled)
        return base.obj_make_list(context, cls(), CellMapping, db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_project_id_from_db(context, project_id):
        # SELECT DISTINCT cell_id FROM instance_mappings \
        #   WHERE project_id = $project_id;
        cell_ids = context.session.query(
            api_models.InstanceMapping.cell_id).filter_by(
            project_id=project_id).distinct().subquery()
        # SELECT cell_mappings WHERE cell_id IN ($cell_ids);
        return context.session.query(api_models.CellMapping).filter(
            api_models.CellMapping.id.in_(cell_ids)).all()

    @classmethod
    def get_by_project_id(cls, context, project_id):
        """Return a list of CellMapping objects which correspond to cells in
        which project_id has InstanceMappings.
        """
        db_mappings = cls._get_by_project_id_from_db(context, project_id)
        return base.obj_make_list(context, cls(), CellMapping, db_mappings)
