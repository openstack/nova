# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Implementation of SQLAlchemy backend."""

import uuid

from sqlalchemy.sql.expression import asc
from sqlalchemy.sql.expression import literal_column

import nova.context
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common.gettextutils import _
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova.virt.baremetal.db.sqlalchemy import models
from nova.virt.baremetal.db.sqlalchemy import session as db_session


def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or db_session.get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(
                _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and nova.context.is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query


def _save(ref, session=None):
    if not session:
        session = db_session.get_session()
    # We must not call ref.save() with session=None, otherwise NovaBase
    # uses nova-db's session, which cannot access bm-db.
    ref.save(session=session)


def _build_node_order_by(query):
    query = query.order_by(asc(models.BareMetalNode.memory_mb))
    query = query.order_by(asc(models.BareMetalNode.cpus))
    query = query.order_by(asc(models.BareMetalNode.local_gb))
    return query


@sqlalchemy_api.require_admin_context
def bm_node_get_all(context, service_host=None):
    query = model_query(context, models.BareMetalNode, read_deleted="no")
    if service_host:
        query = query.filter_by(service_host=service_host)
    return query.all()


@sqlalchemy_api.require_admin_context
def bm_node_get_associated(context, service_host=None):
    query = model_query(context, models.BareMetalNode, read_deleted="no").\
                filter(models.BareMetalNode.instance_uuid != None)
    if service_host:
        query = query.filter_by(service_host=service_host)
    return query.all()


@sqlalchemy_api.require_admin_context
def bm_node_get_unassociated(context, service_host=None):
    query = model_query(context, models.BareMetalNode, read_deleted="no").\
                filter(models.BareMetalNode.instance_uuid == None)
    if service_host:
        query = query.filter_by(service_host=service_host)
    return query.all()


@sqlalchemy_api.require_admin_context
def bm_node_find_free(context, service_host=None,
                      cpus=None, memory_mb=None, local_gb=None):
    query = model_query(context, models.BareMetalNode, read_deleted="no")
    query = query.filter(models.BareMetalNode.instance_uuid == None)
    if service_host:
        query = query.filter_by(service_host=service_host)
    if cpus is not None:
        query = query.filter(models.BareMetalNode.cpus >= cpus)
    if memory_mb is not None:
        query = query.filter(models.BareMetalNode.memory_mb >= memory_mb)
    if local_gb is not None:
        query = query.filter(models.BareMetalNode.local_gb >= local_gb)
    query = _build_node_order_by(query)
    return query.first()


@sqlalchemy_api.require_admin_context
def bm_node_get(context, bm_node_id):
    # bm_node_id may be passed as a string. Convert to INT to improve DB perf.
    bm_node_id = int(bm_node_id)
    result = model_query(context, models.BareMetalNode, read_deleted="no").\
                     filter_by(id=bm_node_id).\
                     first()

    if not result:
        raise exception.NodeNotFound(node_id=bm_node_id)

    return result


@sqlalchemy_api.require_admin_context
def bm_node_get_by_instance_uuid(context, instance_uuid):
    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InstanceNotFound(instance_id=instance_uuid)

    result = model_query(context, models.BareMetalNode, read_deleted="no").\
                     filter_by(instance_uuid=instance_uuid).\
                     first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_uuid)

    return result


@sqlalchemy_api.require_admin_context
def bm_node_get_by_node_uuid(context, bm_node_uuid):
    result = model_query(context, models.BareMetalNode, read_deleted="no").\
                     filter_by(uuid=bm_node_uuid).\
                     first()

    if not result:
        raise exception.NodeNotFoundByUUID(node_uuid=bm_node_uuid)

    return result


@sqlalchemy_api.require_admin_context
def bm_node_create(context, values):
    if not values.get('uuid'):
        values['uuid'] = str(uuid.uuid4())
    bm_node_ref = models.BareMetalNode()
    bm_node_ref.update(values)
    _save(bm_node_ref)
    return bm_node_ref


@sqlalchemy_api.require_admin_context
def bm_node_update(context, bm_node_id, values):
    rows = model_query(context, models.BareMetalNode, read_deleted="no").\
            filter_by(id=bm_node_id).\
            update(values)

    if not rows:
        raise exception.NodeNotFound(node_id=bm_node_id)


@sqlalchemy_api.require_admin_context
def bm_node_associate_and_update(context, node_uuid, values):
    """Associate an instance to a node safely

    Associate an instance to a node only if that node is not yet assocated.
    Allow the caller to set any other fields they require in the same
    operation. For example, this is used to set the node's task_state to
    BUILDING at the beginning of driver.spawn().

    """
    if 'instance_uuid' not in values:
        raise exception.NovaException(_(
            "instance_uuid must be supplied to bm_node_associate_and_update"))

    session = db_session.get_session()
    with session.begin():
        query = model_query(context, models.BareMetalNode,
                                session=session, read_deleted="no").\
                        filter_by(uuid=node_uuid)

        count = query.filter_by(instance_uuid=None).\
                        update(values, synchronize_session=False)
        if count != 1:
            raise exception.NovaException(_(
                "Failed to associate instance %(i_uuid)s to baremetal node "
                "%(n_uuid)s.") % {'i_uuid': values['instance_uuid'],
                                  'n_uuid': node_uuid})
        ref = query.first()
    return ref


@sqlalchemy_api.require_admin_context
def bm_node_destroy(context, bm_node_id):
    # First, delete all interfaces belonging to the node.
    # Delete physically since these have unique columns.
    session = db_session.get_session()
    with session.begin():
        model_query(context, models.BareMetalInterface, read_deleted="no").\
            filter_by(bm_node_id=bm_node_id).\
            delete()
        rows = model_query(context, models.BareMetalNode, read_deleted="no").\
            filter_by(id=bm_node_id).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})

        if not rows:
            raise exception.NodeNotFound(node_id=bm_node_id)


@sqlalchemy_api.require_admin_context
def bm_interface_get(context, if_id):
    result = model_query(context, models.BareMetalInterface,
                         read_deleted="no").\
                     filter_by(id=if_id).\
                     first()

    if not result:
        raise exception.NovaException(_("Baremetal interface %s "
                        "not found") % if_id)

    return result


@sqlalchemy_api.require_admin_context
def bm_interface_get_all(context):
    query = model_query(context, models.BareMetalInterface,
                        read_deleted="no")
    return query.all()


@sqlalchemy_api.require_admin_context
def bm_interface_destroy(context, if_id):
    # Delete physically since it has unique columns
    model_query(context, models.BareMetalInterface, read_deleted="no").\
            filter_by(id=if_id).\
            delete()


@sqlalchemy_api.require_admin_context
def bm_interface_create(context, bm_node_id, address, datapath_id, port_no):
    ref = models.BareMetalInterface()
    ref.bm_node_id = bm_node_id
    ref.address = address
    ref.datapath_id = datapath_id
    ref.port_no = port_no
    _save(ref)
    return ref.id


@sqlalchemy_api.require_admin_context
def bm_interface_set_vif_uuid(context, if_id, vif_uuid):
    session = db_session.get_session()
    with session.begin():
        bm_interface = model_query(context, models.BareMetalInterface,
                                read_deleted="no", session=session).\
                         filter_by(id=if_id).\
                         with_lockmode('update').\
                         first()
        if not bm_interface:
            raise exception.NovaException(_("Baremetal interface %s "
                        "not found") % if_id)

        bm_interface.vif_uuid = vif_uuid
        try:
            session.add(bm_interface)
            session.flush()
        except db_exc.DBError as e:
            # TODO(deva): clean up when db layer raises DuplicateKeyError
            if str(e).find('IntegrityError') != -1:
                raise exception.NovaException(_("Baremetal interface %s "
                        "already in use") % vif_uuid)
            raise


@sqlalchemy_api.require_admin_context
def bm_interface_get_by_vif_uuid(context, vif_uuid):
    result = model_query(context, models.BareMetalInterface,
                         read_deleted="no").\
                filter_by(vif_uuid=vif_uuid).\
                first()

    if not result:
        raise exception.NovaException(_("Baremetal virtual interface %s "
                        "not found") % vif_uuid)

    return result


@sqlalchemy_api.require_admin_context
def bm_interface_get_all_by_bm_node_id(context, bm_node_id):
    result = model_query(context, models.BareMetalInterface,
                         read_deleted="no").\
                 filter_by(bm_node_id=bm_node_id).\
                 all()

    if not result:
        raise exception.NodeNotFound(node_id=bm_node_id)

    return result
