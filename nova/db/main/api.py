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

import collections
import copy
import datetime
import functools
import inspect
import traceback

from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import update_match
from oslo_db.sqlalchemy import utils as sqlalchemyutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import sqlalchemy as sa
from sqlalchemy import exc as sqla_exc
from sqlalchemy import orm
from sqlalchemy import schema
from sqlalchemy import sql
from sqlalchemy.sql import expression
from sqlalchemy.sql import func

from nova import block_device
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
import nova.context
from nova.db.main import models
from nova.db import utils as db_utils
from nova.db.utils import require_context
from nova import exception
from nova.i18n import _
from nova import safe_utils

profiler_sqlalchemy = importutils.try_import('osprofiler.sqlalchemy')

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

DISABLE_DB_ACCESS = False

context_manager = enginefacade.transaction_context()


def _get_db_conf(conf_group, connection=None):
    kw = dict(conf_group.items())
    if connection is not None:
        kw['connection'] = connection
    return kw


def _context_manager_from_context(context):
    if context:
        try:
            return context.db_connection
        except AttributeError:
            pass


def _joinedload_all(column):
    elements = column.split('.')
    joined = orm.joinedload(elements.pop(0))
    for element in elements:
        joined = joined.joinedload(element)

    return joined


def configure(conf):
    context_manager.configure(**_get_db_conf(conf.database))

    if (
        profiler_sqlalchemy and
        CONF.profiler.enabled and
        CONF.profiler.trace_sqlalchemy
    ):
        context_manager.append_on_engine_create(
            lambda eng: profiler_sqlalchemy.add_tracing(sa, eng, "db"))


def create_context_manager(connection=None):
    """Create a database context manager object for a cell database connection.

    :param connection: The database connection string
    """
    ctxt_mgr = enginefacade.transaction_context()
    ctxt_mgr.configure(**_get_db_conf(CONF.database, connection=connection))
    return ctxt_mgr


def get_context_manager(context):
    """Get a database context manager object.

    :param context: The request context that can contain a context manager
    """
    return _context_manager_from_context(context) or context_manager


def get_engine(use_slave=False, context=None):
    """Get a database engine object.

    :param use_slave: Whether to use the slave connection
    :param context: The request context that can contain a context manager
    """
    ctxt_mgr = get_context_manager(context)
    if use_slave:
        return ctxt_mgr.reader.get_engine()
    return ctxt_mgr.writer.get_engine()


_SHADOW_TABLE_PREFIX = 'shadow_'
_DEFAULT_QUOTA_NAME = 'default'
PER_PROJECT_QUOTAS = ['fixed_ips', 'floating_ips', 'networks']


def select_db_reader_mode(f):
    """Decorator to select synchronous or asynchronous reader mode.

    The kwarg argument 'use_slave' defines reader mode. Asynchronous reader
    will be used if 'use_slave' is True and synchronous reader otherwise.
    If 'use_slave' is not specified default value 'False' will be used.

    Wrapped function must have a context in the arguments.
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        wrapped_func = safe_utils.get_wrapped_function(f)
        keyed_args = inspect.getcallargs(wrapped_func, *args, **kwargs)

        context = keyed_args['context']
        use_slave = keyed_args.get('use_slave', False)

        if use_slave:
            reader_mode = get_context_manager(context).async_
        else:
            reader_mode = get_context_manager(context).reader

        with reader_mode.using(context):
            return f(*args, **kwargs)
    wrapper.__signature__ = inspect.signature(f)
    return wrapper


def _check_db_access():
    # disable all database access if required
    if DISABLE_DB_ACCESS:
        service_name = 'nova-compute'
        stacktrace = ''.join(traceback.format_stack())
        LOG.error(
            'No DB access allowed in %(service_name)s: %(stacktrace)s',
            {'service_name': service_name, 'stacktrace': stacktrace})
        raise exception.DBNotAllowed(binary=service_name)


def pick_context_manager_writer(f):
    """Decorator to use a writer db context manager.

    The db context manager will be picked from the RequestContext.

    Wrapped function must have a RequestContext in the arguments.
    """
    @functools.wraps(f)
    def wrapper(context, *args, **kwargs):
        _check_db_access()
        ctxt_mgr = get_context_manager(context)
        with ctxt_mgr.writer.using(context):
            return f(context, *args, **kwargs)
    wrapper.__signature__ = inspect.signature(f)
    return wrapper


def pick_context_manager_reader(f):
    """Decorator to use a reader db context manager.

    The db context manager will be picked from the RequestContext.

    Wrapped function must have a RequestContext in the arguments.
    """
    @functools.wraps(f)
    def wrapper(context, *args, **kwargs):
        _check_db_access()
        ctxt_mgr = get_context_manager(context)
        with ctxt_mgr.reader.using(context):
            return f(context, *args, **kwargs)
    wrapper.__signature__ = inspect.signature(f)
    return wrapper


def pick_context_manager_reader_allow_async(f):
    """Decorator to use a reader.allow_async db context manager.

    The db context manager will be picked from the RequestContext.

    Wrapped function must have a RequestContext in the arguments.
    """
    @functools.wraps(f)
    def wrapper(context, *args, **kwargs):
        _check_db_access()
        ctxt_mgr = get_context_manager(context)
        with ctxt_mgr.reader.allow_async.using(context):
            return f(context, *args, **kwargs)
    wrapper.__signature__ = inspect.signature(f)
    return wrapper


def model_query(
    context, model, args=None, read_deleted=None, project_only=False,
):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: The request context that can contain a context manager
    :param model: Model to query. Must be a subclass of ModelBase.
    :param args: Arguments to query. If None - model is used.
    :param read_deleted: If not None, overrides context's read_deleted field.
         Permitted values are 'no', which does not return deleted values;
         'only', which only returns deleted values; and 'yes', which does not
         filter deleted values.
    :param project_only: If set and context is user-type, then restrict
         query to match the context's project_id. If set to 'allow_none',
         restriction includes project_id = None.
    """

    if read_deleted is None:
        read_deleted = context.read_deleted

    query_kwargs = {}
    if 'no' == read_deleted:
        query_kwargs['deleted'] = False
    elif 'only' == read_deleted:
        query_kwargs['deleted'] = True
    elif 'yes' == read_deleted:
        pass
    else:
        raise ValueError(_("Unrecognized read_deleted value '%s'")
                           % read_deleted)

    query = sqlalchemyutils.model_query(
        model, context.session, args, **query_kwargs)

    # We can't use oslo.db model_query's project_id here, as it doesn't allow
    # us to return both our projects and unowned projects.
    if nova.context.is_user_context(context) and project_only:
        if project_only == 'allow_none':
            query = query.filter(sql.or_(
                model.project_id == context.project_id,
                model.project_id == sql.null()
            ))
        else:
            query = query.filter_by(project_id=context.project_id)

    return query


def convert_objects_related_datetimes(values, *datetime_keys):
    if not datetime_keys:
        datetime_keys = ('created_at', 'deleted_at', 'updated_at')

    for key in datetime_keys:
        if key in values and values[key]:
            if isinstance(values[key], str):
                try:
                    values[key] = timeutils.parse_strtime(values[key])
                except ValueError:
                    # Try alternate parsing since parse_strtime will fail
                    # with say converting '2015-05-28T19:59:38+00:00'
                    values[key] = timeutils.parse_isotime(values[key])
            # NOTE(danms): Strip UTC timezones from datetimes, since they're
            # stored that way in the database
            values[key] = values[key].replace(tzinfo=None)
    return values


###################


def constraint(**conditions):
    """Return a constraint object suitable for use with some updates."""
    return Constraint(conditions)


def equal_any(*values):
    """Return an equality condition object suitable for use in a constraint.

    Equal_any conditions require that a model object's attribute equal any
    one of the given values.
    """
    return EqualityCondition(values)


def not_equal(*values):
    """Return an inequality condition object suitable for use in a constraint.

    Not_equal conditions require that a model object's attribute differs from
    all of the given values.
    """
    return InequalityCondition(values)


class Constraint(object):

    def __init__(self, conditions):
        self.conditions = conditions

    def apply(self, model, query):
        for key, condition in self.conditions.items():
            for clause in condition.clauses(getattr(model, key)):
                query = query.filter(clause)
        return query


class EqualityCondition(object):

    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        # method signature requires us to return an iterable even if for OR
        # operator this will actually be a single clause
        return [sql.or_(*[field == value for value in self.values])]


class InequalityCondition(object):

    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        return [field != value for value in self.values]


###################


@pick_context_manager_writer
def service_destroy(context, service_id):
    """Destroy the service or raise if it does not exist."""
    service = service_get(context, service_id)

    model_query(context, models.Service).\
                filter_by(id=service_id).\
                soft_delete(synchronize_session=False)

    if service.binary == 'nova-compute':
        # TODO(sbauza): Remove the service_id filter in a later release
        # once we are sure that all compute nodes report the host field
        model_query(context, models.ComputeNode).\
            filter(sql.or_(
                models.ComputeNode.service_id == service_id,
                models.ComputeNode.host == service['host'])).\
            soft_delete(synchronize_session=False)


@pick_context_manager_reader
def service_get(context, service_id):
    """Get a service or raise if it does not exist."""
    query = model_query(context, models.Service).filter_by(id=service_id)

    result = query.first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@pick_context_manager_reader
def service_get_by_uuid(context, service_uuid):
    """Get a service by it's uuid or raise ServiceNotFound if it does not
    exist.
    """
    query = model_query(context, models.Service).filter_by(uuid=service_uuid)

    result = query.first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_uuid)

    return result


@pick_context_manager_reader_allow_async
def service_get_minimum_version(context, binaries):
    """Get the minimum service version in the database."""
    min_versions = context.session.query(
        models.Service.binary,
        func.min(models.Service.version)).\
                         filter(models.Service.binary.in_(binaries)).\
                         filter(models.Service.deleted == 0).\
                         filter(models.Service.forced_down == sql.false()).\
                         group_by(models.Service.binary)
    return dict(min_versions)


@pick_context_manager_reader
def service_get_all(context, disabled=None):
    """Get all services."""
    query = model_query(context, models.Service)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@pick_context_manager_reader
def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(topic=topic).\
                all()


@pick_context_manager_reader
def service_get_by_host_and_topic(context, host, topic):
    """Get a service by hostname and topic it listens to."""
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(host=host).\
                filter_by(topic=topic).\
                first()


@pick_context_manager_reader
def service_get_all_by_binary(context, binary, include_disabled=False):
    """Get services for a given binary.

    Includes disabled services if 'include_disabled' parameter is True
    """
    query = model_query(context, models.Service).filter_by(binary=binary)
    if not include_disabled:
        query = query.filter_by(disabled=False)
    return query.all()


@pick_context_manager_reader
def service_get_all_computes_by_hv_type(context, hv_type,
                                        include_disabled=False):
    """Get all compute services for a given hypervisor type.

    Includes disabled services if 'include_disabled' parameter is True.
    """
    query = model_query(context, models.Service, read_deleted="no").\
                    filter_by(binary='nova-compute')
    if not include_disabled:
        query = query.filter_by(disabled=False)
    query = query.join(models.ComputeNode,
                       models.Service.host == models.ComputeNode.host).\
                  filter(models.ComputeNode.hypervisor_type == hv_type).\
                  distinct()
    return query.all()


@pick_context_manager_reader
def service_get_by_host_and_binary(context, host, binary):
    """Get a service by hostname and binary."""
    result = model_query(context, models.Service, read_deleted="no").\
                    filter_by(host=host).\
                    filter_by(binary=binary).\
                    first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@pick_context_manager_reader
def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(host=host).\
                all()


@pick_context_manager_reader_allow_async
def service_get_by_compute_host(context, host):
    """Get the service entry for a given compute host.

    Returns the service entry joined with the compute_node entry.
    """
    result = model_query(context, models.Service, read_deleted="no").\
                filter_by(host=host).\
                filter_by(binary='nova-compute').\
                first()

    if not result:
        raise exception.ComputeHostNotFound(host=host)

    return result


@pick_context_manager_writer
def service_create(context, values):
    """Create a service from the values dictionary."""
    service_ref = models.Service()
    service_ref.update(values)
    # We only auto-disable nova-compute services since those are the only
    # ones that can be enabled using the os-services REST API and they are
    # the only ones where being disabled means anything. It does
    # not make sense to be able to disable non-compute services like
    # nova-scheduler or nova-osapi_compute since that does nothing.
    if not CONF.enable_new_services and values.get('binary') == 'nova-compute':
        msg = _("New compute service disabled due to config option.")
        service_ref.disabled = True
        service_ref.disabled_reason = msg
    try:
        service_ref.save(context.session)
    except db_exc.DBDuplicateEntry as e:
        if 'binary' in e.columns:
            raise exception.ServiceBinaryExists(host=values.get('host'),
                        binary=values.get('binary'))
        raise exception.ServiceTopicExists(host=values.get('host'),
                        topic=values.get('topic'))
    return service_ref


@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def service_update(context, service_id, values):
    """Set the given properties on a service and update it.

    :raises: NotFound if service does not exist.
    """
    service_ref = service_get(context, service_id)
    # Only servicegroup.drivers.db.DbDriver._report_state() updates
    # 'report_count', so if that value changes then store the timestamp
    # as the last time we got a state report.
    if 'report_count' in values:
        if values['report_count'] > service_ref.report_count:
            service_ref.last_seen_up = timeutils.utcnow()
    service_ref.update(values)

    return service_ref


###################


def _compute_node_select(context, filters=None, limit=None, marker=None):
    if filters is None:
        filters = {}

    cn_tbl = sa.alias(models.ComputeNode.__table__, name='cn')
    select = sa.select([cn_tbl])

    if context.read_deleted == "no":
        select = select.where(cn_tbl.c.deleted == 0)
    if "compute_id" in filters:
        select = select.where(cn_tbl.c.id == filters["compute_id"])
    if "service_id" in filters:
        select = select.where(cn_tbl.c.service_id == filters["service_id"])
    if "host" in filters:
        select = select.where(cn_tbl.c.host == filters["host"])
    if "hypervisor_hostname" in filters:
        hyp_hostname = filters["hypervisor_hostname"]
        select = select.where(cn_tbl.c.hypervisor_hostname == hyp_hostname)
    if "mapped" in filters:
        select = select.where(cn_tbl.c.mapped < filters['mapped'])
    if marker is not None:
        try:
            compute_node_get(context, marker)
        except exception.ComputeHostNotFound:
            raise exception.MarkerNotFound(marker=marker)
        select = select.where(cn_tbl.c.id > marker)
    if limit is not None:
        select = select.limit(limit)
    # Explicitly order by id, so we're not dependent on the native sort
    # order of the underlying DB.
    select = select.order_by(expression.asc("id"))
    return select


def _compute_node_fetchall(context, filters=None, limit=None, marker=None):
    select = _compute_node_select(context, filters, limit=limit, marker=marker)
    engine = get_engine(context=context)
    conn = engine.connect()

    results = conn.execute(select).fetchall()

    # Callers expect dict-like objects, not SQLAlchemy RowProxy objects...
    results = [dict(r) for r in results]
    conn.close()
    return results


@pick_context_manager_reader
def compute_node_get(context, compute_id):
    """Get a compute node by its id.

    :param context: The security context
    :param compute_id: ID of the compute node

    :returns: Dictionary-like object containing properties of the compute node
    :raises: ComputeHostNotFound if compute node with the given ID doesn't
        exist.
    """
    results = _compute_node_fetchall(context, {"compute_id": compute_id})
    if not results:
        raise exception.ComputeHostNotFound(host=compute_id)
    return results[0]


# TODO(edleafe): remove once the compute node resource provider migration is
# complete, and this distinction is no longer necessary.
@pick_context_manager_reader
def compute_node_get_model(context, compute_id):
    """Get a compute node sqlalchemy model object by its id.

    :param context: The security context
    :param compute_id: ID of the compute node

    :returns: Sqlalchemy model object containing properties of the compute node
    :raises: ComputeHostNotFound if compute node with the given ID doesn't
        exist.
    """
    result = model_query(context, models.ComputeNode).\
            filter_by(id=compute_id).\
            first()
    if not result:
        raise exception.ComputeHostNotFound(host=compute_id)
    return result


@pick_context_manager_reader
def compute_nodes_get_by_service_id(context, service_id):
    """Get a list of compute nodes by their associated service id.

    :param context: The security context
    :param service_id: ID of the associated service

    :returns: List of dictionary-like objects, each containing properties of
        the compute node, including its corresponding service and statistics
    :raises: ServiceNotFound if service with the given ID doesn't exist.
    """
    results = _compute_node_fetchall(context, {"service_id": service_id})
    if not results:
        raise exception.ServiceNotFound(service_id=service_id)
    return results


@pick_context_manager_reader
def compute_node_get_by_host_and_nodename(context, host, nodename):
    """Get a compute node by its associated host and nodename.

    :param context: The security context (admin)
    :param host: Name of the host
    :param nodename: Name of the node

    :returns: Dictionary-like object containing properties of the compute node,
        including its statistics
    :raises: ComputeHostNotFound if host with the given name doesn't exist.
    """
    results = _compute_node_fetchall(context,
            {"host": host, "hypervisor_hostname": nodename})
    if not results:
        raise exception.ComputeHostNotFound(host=host)
    return results[0]


@pick_context_manager_reader
def compute_node_get_by_nodename(context, hypervisor_hostname):
    """Get a compute node by hypervisor_hostname.

    :param context: The security context (admin)
    :param hypervisor_hostname: Name of the node

    :returns: Dictionary-like object containing properties of the compute node,
        including its statistics
    :raises: ComputeHostNotFound if hypervisor_hostname with the given name
        doesn't exist.
    """
    results = _compute_node_fetchall(context,
            {"hypervisor_hostname": hypervisor_hostname})
    if not results:
        raise exception.ComputeHostNotFound(host=hypervisor_hostname)
    return results[0]


@pick_context_manager_reader
def compute_node_get_all(context):
    """Get all compute nodes.

    :param context: The security context

    :returns: List of dictionaries each containing compute node properties
    """
    return _compute_node_fetchall(context)


@pick_context_manager_reader_allow_async
def compute_node_get_all_by_host(context, host):
    """Get all compute nodes by host name.

    :param context: The security context (admin)
    :param host: Name of the host

    :returns: List of dictionaries each containing compute node properties
    """
    results = _compute_node_fetchall(context, {"host": host})
    if not results:
        raise exception.ComputeHostNotFound(host=host)
    return results


@pick_context_manager_reader
def compute_node_get_all_mapped_less_than(context, mapped_less_than):
    """Get all compute nodes with specific mapped values.

    :param context: The security context
    :param mapped_less_than: Get compute nodes with mapped less than this value

    :returns: List of dictionaries each containing compute node properties
    """
    return _compute_node_fetchall(context,
                                  {'mapped': mapped_less_than})


@pick_context_manager_reader
def compute_node_get_all_by_pagination(context, limit=None, marker=None):
    """Get all compute nodes by pagination.

    :param context: The security context
    :param limit: Maximum number of items to return
    :param marker: The last item of the previous page, the next results after
        this value will be returned

    :returns: List of dictionaries each containing compute node properties
    """
    return _compute_node_fetchall(context, limit=limit, marker=marker)


@pick_context_manager_reader
def compute_node_search_by_hypervisor(context, hypervisor_match):
    """Get all compute nodes by hypervisor hostname.

    :param context: The security context
    :param hypervisor_match: The hypervisor hostname

    :returns: List of dictionary-like objects each containing compute node
        properties
    """
    field = models.ComputeNode.hypervisor_hostname
    return model_query(context, models.ComputeNode).\
            filter(field.like('%%%s%%' % hypervisor_match)).\
            all()


@pick_context_manager_writer
def _compute_node_create(context, values):
    """Create a compute node from the values dictionary.

    :param context: The security context
    :param values: Dictionary containing compute node properties

    :returns: Dictionary-like object containing the properties of the created
        node, including its corresponding service and statistics
    """
    convert_objects_related_datetimes(values)

    compute_node_ref = models.ComputeNode()
    compute_node_ref.update(values)
    compute_node_ref.save(context.session)
    return compute_node_ref


# NOTE(mgoddard): We avoid decorating this with @pick_context_manager_writer,
# so that we get a separate transaction in the exception handler. This avoids
# an error message about inactive DB sessions during a transaction rollback.
# See https://bugs.launchpad.net/nova/+bug/1853159.
def compute_node_create(context, values):
    """Creates a new ComputeNode and populates the capacity fields
    with the most recent data. Will restore a soft deleted compute node if a
    UUID has been explicitly requested.
    """
    try:
        compute_node_ref = _compute_node_create(context, values)
    except db_exc.DBDuplicateEntry:
        with excutils.save_and_reraise_exception(logger=LOG) as err_ctx:
            # Check to see if we have a (soft) deleted ComputeNode with the
            # same UUID and if so just update it and mark as no longer (soft)
            # deleted. See bug 1839560 for details.
            if 'uuid' in values:
                # Get a fresh context for a new DB session and allow it to
                # get a deleted record.
                ctxt = nova.context.get_admin_context(read_deleted='yes')
                compute_node_ref = _compute_node_get_and_update_deleted(
                    ctxt, values)
                # If we didn't get anything back we failed to find the node
                # by uuid and update it so re-raise the DBDuplicateEntry.
                if compute_node_ref:
                    err_ctx.reraise = False

    return compute_node_ref


@pick_context_manager_writer
def _compute_node_get_and_update_deleted(context, values):
    """Find a compute node by uuid, update and un-delete it.

    This is a special case from the ``compute_node_create`` method which
    needs to be separate to get a new Session.

    This method will update the ComputeNode, if found, to have deleted=0 and
    deleted_at=None values.

    :param context: request auth context which should be able to read deleted
        records
    :param values: values used to update the ComputeNode record - must include
        uuid
    :return: updated ComputeNode sqlalchemy model object if successfully found
        and updated, None otherwise
    """
    cn = model_query(
        context, models.ComputeNode).filter_by(uuid=values['uuid']).first()
    if cn:
        # Update with the provided values but un-soft-delete.
        update_values = copy.deepcopy(values)
        update_values['deleted'] = 0
        update_values['deleted_at'] = None
        return compute_node_update(context, cn.id, update_values)


@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def compute_node_update(context, compute_id, values):
    """Set the given properties on a compute node and update it.

    :param context: The security context
    :param compute_id: ID of the compute node
    :param values: Dictionary containing compute node properties to be updated

    :returns: Dictionary-like object containing the properties of the updated
        compute node, including its corresponding service and statistics
    :raises: ComputeHostNotFound if compute node with the given ID doesn't
        exist.
    """
    compute_ref = compute_node_get_model(context, compute_id)
    # Always update this, even if there's going to be no other
    # changes in data.  This ensures that we invalidate the
    # scheduler cache of compute node data in case of races.
    values['updated_at'] = timeutils.utcnow()
    convert_objects_related_datetimes(values)
    compute_ref.update(values)

    return compute_ref


@pick_context_manager_writer
def compute_node_delete(context, compute_id, constraint=None):
    """Delete a compute node from the database.

    :param context: The security context
    :param compute_id: ID of the compute node
    :param constraint: a constraint object

    :raises: ComputeHostNotFound if compute node with the given ID doesn't
        exist.
    :raises: ConstraintNotMet if a constraint was specified and it was not met.
    """
    query = model_query(context, models.ComputeNode).filter_by(id=compute_id)

    if constraint is not None:
        query = constraint.apply(models.ComputeNode, query)

    result = query.soft_delete(synchronize_session=False)

    if not result:
        # The soft_delete could fail for one of two reasons:
        # 1) The compute node no longer exists
        # 2) The constraint, if specified, was not met
        # Try to read the compute node and let it raise ComputeHostNotFound if
        # 1) happened.
        compute_node_get(context, compute_id)
        # Else, raise ConstraintNotMet if 2) happened.
        raise exception.ConstraintNotMet()


@pick_context_manager_reader
def compute_node_statistics(context):
    """Get aggregate statistics over all compute nodes.

    :param context: The security context

    :returns: Dictionary containing compute node characteristics summed up
        over all the compute nodes, e.g. 'vcpus', 'free_ram_mb' etc.
    """
    engine = get_engine(context=context)
    services_tbl = models.Service.__table__

    inner_sel = sa.alias(_compute_node_select(context), name='inner_sel')

    # TODO(sbauza): Remove the service_id filter in a later release
    # once we are sure that all compute nodes report the host field
    j = sa.join(
        inner_sel, services_tbl,
        sql.and_(
            sql.or_(
                inner_sel.c.host == services_tbl.c.host,
                inner_sel.c.service_id == services_tbl.c.id
            ),
            services_tbl.c.disabled == sql.false(),
            services_tbl.c.binary == 'nova-compute',
            services_tbl.c.deleted == 0
        )
    )

    # NOTE(jaypipes): This COALESCE() stuff is temporary while the data
    # migration to the new resource providers inventories and allocations
    # tables is completed.
    agg_cols = [
        func.count().label('count'),
        sql.func.sum(
            inner_sel.c.vcpus
        ).label('vcpus'),
        sql.func.sum(
            inner_sel.c.memory_mb
        ).label('memory_mb'),
        sql.func.sum(
            inner_sel.c.local_gb
        ).label('local_gb'),
        sql.func.sum(
            inner_sel.c.vcpus_used
        ).label('vcpus_used'),
        sql.func.sum(
            inner_sel.c.memory_mb_used
        ).label('memory_mb_used'),
        sql.func.sum(
            inner_sel.c.local_gb_used
        ).label('local_gb_used'),
        sql.func.sum(
            inner_sel.c.free_ram_mb
        ).label('free_ram_mb'),
        sql.func.sum(
            inner_sel.c.free_disk_gb
        ).label('free_disk_gb'),
        sql.func.sum(
            inner_sel.c.current_workload
        ).label('current_workload'),
        sql.func.sum(
            inner_sel.c.running_vms
        ).label('running_vms'),
        sql.func.sum(
            inner_sel.c.disk_available_least
        ).label('disk_available_least'),
    ]
    select = sql.select(agg_cols).select_from(j)
    conn = engine.connect()

    results = conn.execute(select).fetchone()

    # Build a dict of the info--making no assumptions about result
    fields = ('count', 'vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
              'memory_mb_used', 'local_gb_used', 'free_ram_mb', 'free_disk_gb',
              'current_workload', 'running_vms', 'disk_available_least')
    results = {field: int(results[idx] or 0)
               for idx, field in enumerate(fields)}
    conn.close()
    return results


###################


@pick_context_manager_writer
def certificate_create(context, values):
    """Create a certificate from the values dictionary."""
    certificate_ref = models.Certificate()
    for (key, value) in values.items():
        certificate_ref[key] = value
    certificate_ref.save(context.session)
    return certificate_ref


@pick_context_manager_reader
def certificate_get_all_by_project(context, project_id):
    """Get all certificates for a project."""
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()


@pick_context_manager_reader
def certificate_get_all_by_user(context, user_id):
    """Get all certificates for a user."""
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   all()


@pick_context_manager_reader
def certificate_get_all_by_user_and_project(context, user_id, project_id):
    """Get all certificates for a user and project."""
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   all()


###################


@require_context
@pick_context_manager_writer
def virtual_interface_create(context, values):
    """Create a new virtual interface record.

    :param values: Dict containing column values.
    """
    try:
        vif_ref = models.VirtualInterface()
        vif_ref.update(values)
        vif_ref.save(context.session)
    except db_exc.DBError:
        LOG.exception("VIF creation failed with a database error.")
        raise exception.VirtualInterfaceCreateException()

    return vif_ref


def _virtual_interface_query(context):
    return model_query(context, models.VirtualInterface, read_deleted="no")


@require_context
@pick_context_manager_writer
def virtual_interface_update(context, address, values):
    """Create a virtual interface record in the database."""
    vif_ref = virtual_interface_get_by_address(context, address)
    vif_ref.update(values)
    vif_ref.save(context.session)
    return vif_ref


@require_context
@pick_context_manager_reader
def virtual_interface_get(context, vif_id):
    """Get a virtual interface by ID.

    :param vif_id: ID of the virtual interface.
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(id=vif_id).\
                      first()
    return vif_ref


@require_context
@pick_context_manager_reader
def virtual_interface_get_by_address(context, address):
    """Get a virtual interface by address.

    :param address: The address of the interface you're looking to get.
    """
    try:
        vif_ref = _virtual_interface_query(context).\
                          filter_by(address=address).\
                          first()
    except db_exc.DBError:
        msg = _("Invalid virtual interface address %s in request") % address
        LOG.warning(msg)
        raise exception.InvalidIpAddressError(msg)
    return vif_ref


@require_context
@pick_context_manager_reader
def virtual_interface_get_by_uuid(context, vif_uuid):
    """Get a virtual interface by UUID.

    :param vif_uuid: The uuid of the interface you're looking to get
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(uuid=vif_uuid).\
                      first()
    return vif_ref


@require_context
@pick_context_manager_reader_allow_async
def virtual_interface_get_by_instance(context, instance_uuid):
    """Gets all virtual interfaces for instance.

    :param instance_uuid: UUID of the instance to filter on.
    """
    vif_refs = _virtual_interface_query(context).\
        filter_by(instance_uuid=instance_uuid).\
        order_by(expression.asc("created_at"), expression.asc("id")).\
        all()
    return vif_refs


@require_context
@pick_context_manager_reader
def virtual_interface_get_by_instance_and_network(context, instance_uuid,
                                                  network_id):
    """Get all virtual interface for instance that's associated with
    network.
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(instance_uuid=instance_uuid).\
                      filter_by(network_id=network_id).\
                      first()
    return vif_ref


@require_context
@pick_context_manager_writer
def virtual_interface_delete_by_instance(context, instance_uuid):
    """Delete virtual interface records associated with instance.

    :param instance_uuid: UUID of the instance to filter on.
    """
    _virtual_interface_query(context).\
           filter_by(instance_uuid=instance_uuid).\
           soft_delete()


@require_context
@pick_context_manager_writer
def virtual_interface_delete(context, id):
    """Delete a virtual interface records.

    :param id: ID of the interface.
    """
    _virtual_interface_query(context).\
        filter_by(id=id).\
        soft_delete()


@require_context
@pick_context_manager_reader
def virtual_interface_get_all(context):
    """Get all virtual interface records."""
    vif_refs = _virtual_interface_query(context).all()
    return vif_refs


###################


def _metadata_refs(metadata_dict, meta_class):
    metadata_refs = []
    if metadata_dict:
        for k, v in metadata_dict.items():
            metadata_ref = meta_class()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    return metadata_refs


def _validate_unique_server_name(context, name):
    if not CONF.osapi_compute_unique_server_name_scope:
        return

    lowername = name.lower()
    base_query = model_query(context, models.Instance, read_deleted='no').\
            filter(func.lower(models.Instance.hostname) == lowername)

    if CONF.osapi_compute_unique_server_name_scope == 'project':
        instance_with_same_name = base_query.\
                        filter_by(project_id=context.project_id).\
                        count()

    elif CONF.osapi_compute_unique_server_name_scope == 'global':
        instance_with_same_name = base_query.count()

    else:
        return

    if instance_with_same_name > 0:
        raise exception.InstanceExists(name=lowername)


def _handle_objects_related_type_conversions(values):
    """Make sure that certain things in values (which may have come from
    an objects.instance.Instance object) are in suitable form for the
    database.
    """
    # NOTE(danms): Make sure IP addresses are passed as strings to
    # the database engine
    for key in ('access_ip_v4', 'access_ip_v6'):
        if key in values and values[key] is not None:
            values[key] = str(values[key])

    datetime_keys = ('created_at', 'deleted_at', 'updated_at',
                     'launched_at', 'terminated_at')
    convert_objects_related_datetimes(values, *datetime_keys)


def _check_instance_exists_in_project(context, instance_uuid):
    if not model_query(context, models.Instance, read_deleted="no",
                       project_only=True).filter_by(
                       uuid=instance_uuid).first():
        raise exception.InstanceNotFound(instance_id=instance_uuid)


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def instance_create(context, values):
    """Create an instance from the values dictionary.

    :param context: Request context object
    :param values: Dict containing column values.
    """

    default_group = security_group_ensure_default(context)

    values = values.copy()
    values['metadata'] = _metadata_refs(
            values.get('metadata'), models.InstanceMetadata)

    values['system_metadata'] = _metadata_refs(
            values.get('system_metadata'), models.InstanceSystemMetadata)
    _handle_objects_related_type_conversions(values)

    instance_ref = models.Instance()
    if not values.get('uuid'):
        values['uuid'] = uuidutils.generate_uuid()
    instance_ref['info_cache'] = models.InstanceInfoCache()
    info_cache = values.pop('info_cache', None)
    if info_cache is not None:
        instance_ref['info_cache'].update(info_cache)
    security_groups = values.pop('security_groups', [])
    instance_ref['extra'] = models.InstanceExtra()
    instance_ref['extra'].update(
        {'numa_topology': None,
         'pci_requests': None,
         'vcpu_model': None,
         'trusted_certs': None,
         'resources': None,
         })
    instance_ref['extra'].update(values.pop('extra', {}))
    instance_ref.update(values)

    # Gather the security groups for the instance
    sg_models = []
    if 'default' in security_groups:
        sg_models.append(default_group)
        # Generate a new list, so we don't modify the original
        security_groups = [x for x in security_groups if x != 'default']
    if security_groups:
        sg_models.extend(_security_group_get_by_names(
            context, security_groups))

    if 'hostname' in values:
        _validate_unique_server_name(context, values['hostname'])
    instance_ref.security_groups = sg_models
    context.session.add(instance_ref)

    # create the instance uuid to ec2_id mapping entry for instance
    ec2_instance_create(context, instance_ref['uuid'])

    # Parity with the return value of instance_get_all_by_filters_sort()
    # Obviously a newly-created instance record can't already have a fault
    # record because of the FK constraint, so this is fine.
    instance_ref.fault = None

    return instance_ref


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def instance_destroy(
    context, instance_uuid, constraint=None, hard_delete=False,
):
    """Destroy the instance or raise if it does not exist.

    :param context: request context object
    :param instance_uuid: uuid of the instance to delete
    :param constraint: a constraint object
    :param hard_delete: when set to True, removes all records related to the
        instance
    """
    if uuidutils.is_uuid_like(instance_uuid):
        instance_ref = _instance_get_by_uuid(context, instance_uuid)
    else:
        raise exception.InvalidUUID(uuid=instance_uuid)

    query = model_query(context, models.Instance).\
                    filter_by(uuid=instance_uuid)
    if constraint is not None:
        query = constraint.apply(models.Instance, query)
    # Either in hard or soft delete, we soft delete the instance first
    # to make sure that the constraints were met.
    count = query.soft_delete()
    if count == 0:
        # The failure to soft delete could be due to one of two things:
        # 1) A racing request has deleted the instance out from under us
        # 2) A constraint was not met
        # Try to read the instance back once more and let it raise
        # InstanceNotFound if 1) happened. This will give the caller an error
        # that more accurately reflects the reason for the failure.
        _instance_get_by_uuid(context, instance_uuid)
        # Else, raise ConstraintNotMet if 2) happened.
        raise exception.ConstraintNotMet()

    models_to_delete = [
        models.SecurityGroupInstanceAssociation, models.InstanceInfoCache,
        models.InstanceMetadata, models.InstanceFault, models.InstanceExtra,
        models.InstanceSystemMetadata, models.BlockDeviceMapping,
        models.Migration, models.VirtualInterface
    ]

    # For most referenced models we filter by the instance_uuid column, but for
    # these models we filter by the uuid column.
    filtered_by_uuid = [models.InstanceIdMapping]

    for model in models_to_delete + filtered_by_uuid:
        key = 'instance_uuid' if model not in filtered_by_uuid else 'uuid'
        filter_ = {key: instance_uuid}
        if hard_delete:
            # We need to read any soft-deleted related records to make sure
            # and clean those up as well otherwise we can fail with ForeignKey
            # constraint errors when hard deleting the instance.
            model_query(context, model, read_deleted='yes').filter_by(
                **filter_).delete()
        else:
            model_query(context, model).filter_by(**filter_).soft_delete()

    # NOTE(snikitin): We can't use model_query here, because there is no
    # column 'deleted' in 'tags' or 'console_auth_tokens' tables.
    context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid).delete()
    context.session.query(models.ConsoleAuthToken).filter_by(
        instance_uuid=instance_uuid).delete()
    # NOTE(cfriesen): We intentionally do not soft-delete entries in the
    # instance_actions or instance_actions_events tables because they
    # can be used by operators to find out what actions were performed on a
    # deleted instance.  Both of these tables are special-cased in
    # _archive_deleted_rows_for_table().
    if hard_delete:
        # NOTE(ttsiousts): In case of hard delete, we need to remove the
        # instance actions too since instance_uuid is a foreign key and
        # for this we need to delete the corresponding InstanceActionEvents
        actions = context.session.query(models.InstanceAction).filter_by(
            instance_uuid=instance_uuid).all()
        for action in actions:
            context.session.query(models.InstanceActionEvent).filter_by(
                action_id=action.id).delete()
        context.session.query(models.InstanceAction).filter_by(
            instance_uuid=instance_uuid).delete()
        # NOTE(ttsiouts): The instance is the last thing to be deleted in
        # order to respect all constraints
        context.session.query(models.Instance).filter_by(
            uuid=instance_uuid).delete()

    return instance_ref


@require_context
@pick_context_manager_reader_allow_async
def instance_get_by_uuid(context, uuid, columns_to_join=None):
    """Get an instance or raise if it does not exist."""
    return _instance_get_by_uuid(context, uuid,
                                 columns_to_join=columns_to_join)


def _instance_get_by_uuid(context, uuid, columns_to_join=None):
    result = _build_instance_get(context, columns_to_join=columns_to_join).\
                filter_by(uuid=uuid).\
                first()

    if not result:
        raise exception.InstanceNotFound(instance_id=uuid)

    return result


@require_context
@pick_context_manager_reader
def instance_get(context, instance_id, columns_to_join=None):
    """Get an instance or raise if it does not exist."""
    try:
        result = _build_instance_get(context, columns_to_join=columns_to_join
                                     ).filter_by(id=instance_id).first()

        if not result:
            raise exception.InstanceNotFound(instance_id=instance_id)

        return result
    except db_exc.DBError:
        # NOTE(sdague): catch all in case the db engine chokes on the
        # id because it's too long of an int to store.
        LOG.warning("Invalid instance id %s in request", instance_id)
        raise exception.InvalidID(id=instance_id)


def _build_instance_get(context, columns_to_join=None):
    query = model_query(context, models.Instance, project_only=True).\
            options(_joinedload_all('security_groups.rules')).\
            options(orm.joinedload('info_cache'))
    if columns_to_join is None:
        columns_to_join = ['metadata', 'system_metadata']
    for column in columns_to_join:
        if column in ['info_cache', 'security_groups']:
            # Already always joined above
            continue
        if 'extra.' in column:
            query = query.options(orm.undefer(column))
        elif column in ['metadata', 'system_metadata']:
            # NOTE(melwitt): We use subqueryload() instead of joinedload() for
            # metadata and system_metadata because of the one-to-many
            # relationship of the data. Directly joining these columns can
            # result in a large number of additional rows being queried if an
            # instance has a large number of (system_)metadata items, resulting
            # in a large data transfer. Instead, the subqueryload() will
            # perform additional queries to obtain metadata and system_metadata
            # for the instance.
            query = query.options(orm.subqueryload(column))
        else:
            query = query.options(orm.joinedload(column))
    # NOTE(alaski) Stop lazy loading of columns not needed.
    for col in ['metadata', 'system_metadata']:
        if col not in columns_to_join:
            query = query.options(orm.noload(col))
    # NOTE(melwitt): We need to use order_by(<unique column>) so that the
    # additional queries emitted by subqueryload() include the same ordering as
    # used by the parent query.
    # https://docs.sqlalchemy.org/en/13/orm/loading_relationships.html#the-importance-of-ordering
    return query.order_by(models.Instance.id)


def _instances_fill_metadata(context, instances, manual_joins=None):
    """Selectively fill instances with manually-joined metadata. Note that
    instance will be converted to a dict.

    :param context: security context
    :param instances: list of instances to fill
    :param manual_joins: list of tables to manually join (can be any
                         combination of 'metadata' and 'system_metadata' or
                         None to take the default of both)
    """
    uuids = [inst['uuid'] for inst in instances]

    if manual_joins is None:
        manual_joins = ['metadata', 'system_metadata']

    meta = collections.defaultdict(list)
    if 'metadata' in manual_joins:
        for row in _instance_metadata_get_multi(context, uuids):
            meta[row['instance_uuid']].append(row)

    sys_meta = collections.defaultdict(list)
    if 'system_metadata' in manual_joins:
        for row in _instance_system_metadata_get_multi(context, uuids):
            sys_meta[row['instance_uuid']].append(row)

    pcidevs = collections.defaultdict(list)
    if 'pci_devices' in manual_joins:
        for row in _instance_pcidevs_get_multi(context, uuids):
            pcidevs[row['instance_uuid']].append(row)

    if 'fault' in manual_joins:
        faults = instance_fault_get_by_instance_uuids(context, uuids,
                                                      latest=True)
    else:
        faults = {}

    filled_instances = []
    for inst in instances:
        inst = dict(inst)
        inst['system_metadata'] = sys_meta[inst['uuid']]
        inst['metadata'] = meta[inst['uuid']]
        if 'pci_devices' in manual_joins:
            inst['pci_devices'] = pcidevs[inst['uuid']]
        inst_faults = faults.get(inst['uuid'])
        inst['fault'] = inst_faults and inst_faults[0] or None
        filled_instances.append(inst)

    return filled_instances


def _manual_join_columns(columns_to_join):
    """Separate manually joined columns from columns_to_join

    If columns_to_join contains 'metadata', 'system_metadata', 'fault', or
    'pci_devices' those columns are removed from columns_to_join and added
    to a manual_joins list to be used with the _instances_fill_metadata method.

    The columns_to_join formal parameter is copied and not modified, the return
    tuple has the modified columns_to_join list to be used with joinedload in
    a model query.

    :param:columns_to_join: List of columns to join in a model query.
    :return: tuple of (manual_joins, columns_to_join)
    """
    manual_joins = []
    columns_to_join_new = copy.copy(columns_to_join)
    for column in ('metadata', 'system_metadata', 'pci_devices', 'fault'):
        if column in columns_to_join_new:
            columns_to_join_new.remove(column)
            manual_joins.append(column)
    return manual_joins, columns_to_join_new


@require_context
@pick_context_manager_reader
def instance_get_all(context, columns_to_join=None):
    """Get all instances."""
    if columns_to_join is None:
        columns_to_join_new = ['info_cache', 'security_groups']
        manual_joins = ['metadata', 'system_metadata']
    else:
        manual_joins, columns_to_join_new = (
            _manual_join_columns(columns_to_join))
    query = model_query(context, models.Instance)
    for column in columns_to_join_new:
        query = query.options(orm.joinedload(column))
    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            query = query.filter_by(project_id=context.project_id)
        else:
            query = query.filter_by(user_id=context.user_id)
    instances = query.all()
    return _instances_fill_metadata(context, instances, manual_joins)


@require_context
@pick_context_manager_reader_allow_async
def instance_get_all_by_filters(
    context, filters, sort_key='created_at', sort_dir='desc', limit=None,
    marker=None, columns_to_join=None,
):
    """Get all instances matching all filters sorted by the primary key.

    See instance_get_all_by_filters_sort for more information.
    """
    # Invoke the API with the multiple sort keys and directions using the
    # single sort key/direction
    return instance_get_all_by_filters_sort(context, filters, limit=limit,
                                            marker=marker,
                                            columns_to_join=columns_to_join,
                                            sort_keys=[sort_key],
                                            sort_dirs=[sort_dir])


def _get_query_nova_resource_by_changes_time(query, filters, model_object):
    """Filter resources by changes-since or changes-before.

    Special keys are used to tweek the query further::

    |   'changes-since' - only return resources updated after
    |   'changes-before' - only return resources updated before

    Return query results.

    :param query: query to apply filters to.
    :param filters: dictionary of filters with regex values.
    :param model_object: object of the operation target.
    """
    for change_filter in ['changes-since', 'changes-before']:
        if filters and filters.get(change_filter):
            changes_filter_time = timeutils.normalize_time(
                filters.get(change_filter))
            updated_at = getattr(model_object, 'updated_at')
            if change_filter == 'changes-since':
                query = query.filter(updated_at >= changes_filter_time)
            else:
                query = query.filter(updated_at <= changes_filter_time)
    return query


@require_context
@pick_context_manager_reader_allow_async
def instance_get_all_by_filters_sort(context, filters, limit=None, marker=None,
                                     columns_to_join=None, sort_keys=None,
                                     sort_dirs=None):
    """Get all instances that match all filters sorted by the given keys.

    Deleted instances will be returned by default, unless there's a filter that
    says otherwise.

    Depending on the name of a filter, matching for that filter is
    performed using either exact matching or as regular expression
    matching. Exact matching is applied for the following filters::

    |   ['project_id', 'user_id', 'image_ref',
    |    'vm_state', 'instance_type_id', 'uuid',
    |    'metadata', 'host', 'system_metadata', 'locked', 'hidden']

    Hidden instances will *not* be returned by default, unless there's a
    filter that says otherwise.

    A third type of filter (also using exact matching), filters
    based on instance metadata tags when supplied under a special
    key named 'filter'::

    |   filters = {
    |       'filter': [
    |           {'name': 'tag-key', 'value': '<metakey>'},
    |           {'name': 'tag-value', 'value': '<metaval>'},
    |           {'name': 'tag:<metakey>', 'value': '<metaval>'}
    |       ]
    |   }

    Special keys are used to tweek the query further::

    |   'changes-since' - only return instances updated after
    |   'changes-before' - only return instances updated before
    |   'deleted' - only return (or exclude) deleted instances
    |   'soft_deleted' - modify behavior of 'deleted' to either
    |                    include or exclude instances whose
    |                    vm_state is SOFT_DELETED.

    A fourth type of filter (also using exact matching), filters
    based on instance tags (not metadata tags). There are two types
    of these tags:

    `tags` -- One or more strings that will be used to filter results
            in an AND expression: T1 AND T2

    `tags-any` -- One or more strings that will be used to filter results in
            an OR expression: T1 OR T2

    `not-tags` -- One or more strings that will be used to filter results in
            an NOT AND expression: NOT (T1 AND T2)

    `not-tags-any` -- One or more strings that will be used to filter results
            in an NOT OR expression: NOT (T1 OR T2)

    Tags should be represented as list::

    |    filters = {
    |        'tags': [some-tag, some-another-tag],
    |        'tags-any: [some-any-tag, some-another-any-tag],
    |        'not-tags: [some-not-tag, some-another-not-tag],
    |        'not-tags-any: [some-not-any-tag, some-another-not-any-tag]
    |    }
    """
    # NOTE(mriedem): If the limit is 0 there is no point in even going
    # to the database since nothing is going to be returned anyway.
    if limit == 0:
        return []

    sort_keys, sort_dirs = db_utils.process_sort_params(
        sort_keys, sort_dirs, default_dir='desc')

    if columns_to_join is None:
        columns_to_join_new = ['info_cache', 'security_groups']
        manual_joins = ['metadata', 'system_metadata']
    else:
        manual_joins, columns_to_join_new = (
            _manual_join_columns(columns_to_join))

    query_prefix = context.session.query(models.Instance)
    for column in columns_to_join_new:
        if 'extra.' in column:
            query_prefix = query_prefix.options(orm.undefer(column))
        else:
            query_prefix = query_prefix.options(orm.joinedload(column))

    # Note: order_by is done in the sqlalchemy.utils.py paginate_query(),
    # no need to do it here as well

    # Make a copy of the filters dictionary to use going forward, as we'll
    # be modifying it and we shouldn't affect the caller's use of it.
    filters = copy.deepcopy(filters)

    model_object = models.Instance
    query_prefix = _get_query_nova_resource_by_changes_time(query_prefix,
                                                            filters,
                                                            model_object)

    if 'deleted' in filters:
        # Instances can be soft or hard deleted and the query needs to
        # include or exclude both
        deleted = filters.pop('deleted')
        if deleted:
            if filters.pop('soft_deleted', True):
                delete = sql.or_(
                    models.Instance.deleted == models.Instance.id,
                    models.Instance.vm_state == vm_states.SOFT_DELETED
                    )
                query_prefix = query_prefix.\
                    filter(delete)
            else:
                query_prefix = query_prefix.\
                    filter(models.Instance.deleted == models.Instance.id)
        else:
            query_prefix = query_prefix.\
                    filter_by(deleted=0)
            if not filters.pop('soft_deleted', False):
                # It would be better to have vm_state not be nullable
                # but until then we test it explicitly as a workaround.
                not_soft_deleted = sql.or_(
                    models.Instance.vm_state != vm_states.SOFT_DELETED,
                    models.Instance.vm_state == sql.null()
                )
                query_prefix = query_prefix.filter(not_soft_deleted)

    if 'cleaned' in filters:
        cleaned = 1 if filters.pop('cleaned') else 0
        query_prefix = query_prefix.filter(models.Instance.cleaned == cleaned)

    if 'tags' in filters:
        tags = filters.pop('tags')
        # We build a JOIN ladder expression for each tag, JOIN'ing
        # the first tag to the instances table, and each subsequent
        # tag to the last JOIN'd tags table
        first_tag = tags.pop(0)
        query_prefix = query_prefix.join(models.Instance.tags)
        query_prefix = query_prefix.filter(models.Tag.tag == first_tag)

        for tag in tags:
            tag_alias = orm.aliased(models.Tag)
            query_prefix = query_prefix.join(tag_alias,
                                             models.Instance.tags)
            query_prefix = query_prefix.filter(tag_alias.tag == tag)

    if 'tags-any' in filters:
        tags = filters.pop('tags-any')
        tag_alias = orm.aliased(models.Tag)
        query_prefix = query_prefix.join(tag_alias, models.Instance.tags)
        query_prefix = query_prefix.filter(tag_alias.tag.in_(tags))

    if 'not-tags' in filters:
        tags = filters.pop('not-tags')
        first_tag = tags.pop(0)
        subq = query_prefix.session.query(models.Tag.resource_id)
        subq = subq.join(models.Instance.tags)
        subq = subq.filter(models.Tag.tag == first_tag)

        for tag in tags:
            tag_alias = orm.aliased(models.Tag)
            subq = subq.join(tag_alias, models.Instance.tags)
            subq = subq.filter(tag_alias.tag == tag)

        query_prefix = query_prefix.filter(~models.Instance.uuid.in_(subq))

    if 'not-tags-any' in filters:
        tags = filters.pop('not-tags-any')
        query_prefix = query_prefix.filter(~models.Instance.tags.any(
            models.Tag.tag.in_(tags)))

    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            filters['project_id'] = context.project_id
        else:
            filters['user_id'] = context.user_id

    if filters.pop('hidden', False):
        query_prefix = query_prefix.filter(
            models.Instance.hidden == sql.true())
    else:
        # If the query should not include hidden instances, then
        # filter instances with hidden=False or hidden=NULL because
        # older records may have no value set.
        query_prefix = query_prefix.filter(sql.or_(
            models.Instance.hidden == sql.false(),
            models.Instance.hidden == sql.null()))

    # Filters for exact matches that we can do along with the SQL query...
    # For other filters that don't match this, we will do regexp matching
    exact_match_filter_names = ['project_id', 'user_id', 'image_ref',
                                'vm_state', 'instance_type_id', 'uuid',
                                'metadata', 'host', 'task_state',
                                'system_metadata', 'locked', 'hidden']

    # Filter the query
    query_prefix = _exact_instance_filter(query_prefix,
                                filters, exact_match_filter_names)
    if query_prefix is None:
        return []
    query_prefix = _regex_instance_filter(query_prefix, filters)

    # paginate query
    if marker is not None:
        try:
            marker = _instance_get_by_uuid(
                    context.elevated(read_deleted='yes'), marker)
        except exception.InstanceNotFound:
            raise exception.MarkerNotFound(marker=marker)
    try:
        query_prefix = sqlalchemyutils.paginate_query(query_prefix,
                               models.Instance, limit,
                               sort_keys,
                               marker=marker,
                               sort_dirs=sort_dirs)
    except db_exc.InvalidSortKey:
        raise exception.InvalidSortKey()

    return _instances_fill_metadata(context, query_prefix.all(), manual_joins)


@require_context
@pick_context_manager_reader_allow_async
def instance_get_by_sort_filters(context, sort_keys, sort_dirs, values):
    """Get the UUID of the first instance in a sort order.

    Attempt to get a single instance based on a combination of sort
    keys, directions and filter values. This is used to try to find a
    marker instance when we don't have a marker uuid.

    :returns: The UUID of the instance that matched, if any.
    """

    model = models.Instance
    return _model_get_uuid_by_sort_filters(context, model, sort_keys,
                                           sort_dirs, values)


def _model_get_uuid_by_sort_filters(context, model, sort_keys, sort_dirs,
                                    values):
    query = context.session.query(model.uuid)

    # NOTE(danms): Below is a re-implementation of our
    # oslo_db.sqlalchemy.utils.paginate_query() utility. We can't use that
    # directly because it does not return the marker and we need it to.
    # The below is basically the same algorithm, stripped down to just what
    # we need, and augmented with the filter criteria required for us to
    # get back the instance that would correspond to our query.

    # This is our position in sort_keys,sort_dirs,values for the loop below
    key_index = 0

    # We build a list of criteria to apply to the query, which looks
    # approximately like this (assuming all ascending):
    #
    #  OR(row.key1 > val1,
    #     AND(row.key1 == val1, row.key2 > val2),
    #     AND(row.key1 == val1, row.key2 == val2, row.key3 >= val3),
    #  )
    #
    # The final key is compared with the "or equal" variant so that
    # a complete match instance is still returned.
    criteria = []

    for skey, sdir, val in zip(sort_keys, sort_dirs, values):
        # Apply ordering to our query for the key, direction we're processing
        if sdir == 'desc':
            query = query.order_by(expression.desc(getattr(model, skey)))
        else:
            query = query.order_by(expression.asc(getattr(model, skey)))

        # Build a list of equivalence requirements on keys we've already
        # processed through the loop. In other words, if we're adding
        # key2 > val2, make sure that key1 == val1
        crit_attrs = []
        for equal_attr in range(0, key_index):
            crit_attrs.append(
                (getattr(model, sort_keys[equal_attr]) == values[equal_attr]))

        model_attr = getattr(model, skey)
        if isinstance(model_attr.type, sa.Boolean):
            model_attr = expression.cast(model_attr, sa.Integer)
            val = int(val)

        if skey == sort_keys[-1]:
            # If we are the last key, then we should use or-equal to
            # allow a complete match to be returned
            if sdir == 'asc':
                crit = (model_attr >= val)
            else:
                crit = (model_attr <= val)
        else:
            # If we're not the last key, then strict greater or less than
            # so we order strictly.
            if sdir == 'asc':
                crit = (model_attr > val)
            else:
                crit = (model_attr < val)

        # AND together all the above
        crit_attrs.append(crit)
        criteria.append(sql.and_(*crit_attrs))
        key_index += 1

    # OR together all the ANDs
    query = query.filter(sql.or_(*criteria))

    # We can't raise InstanceNotFound because we don't have a uuid to
    # be looking for, so just return nothing if no match.
    result = query.limit(1).first()
    if result:
        # We're querying for a single column, which means we get back a
        # tuple of one thing. Strip that out and just return the uuid
        # for our caller.
        return result[0]
    else:
        return result


def _db_connection_type(db_connection):
    """Returns a lowercase symbol for the db type.

    This is useful when we need to change what we are doing per DB
    (like handling regexes). In a CellsV2 world it probably needs to
    do something better than use the database configuration string.
    """

    db_string = db_connection.split(':')[0].split('+')[0]
    return db_string.lower()


def _safe_regex_mysql(raw_string):
    """Make regex safe to mysql.

    Certain items like '|' are interpreted raw by mysql REGEX. If you
    search for a single | then you trigger an error because it's
    expecting content on either side.

    For consistency sake we escape all '|'. This does mean we wouldn't
    support something like foo|bar to match completely different
    things, however, one can argue putting such complicated regex into
    name search probably means you are doing this wrong.
    """
    return raw_string.replace('|', '\\|')


def _get_regexp_ops(connection):
    """Return safety filter and db opts for regex."""
    regexp_op_map = {
        'postgresql': '~',
        'mysql': 'REGEXP',
        'sqlite': 'REGEXP'
    }
    regex_safe_filters = {
        'mysql': _safe_regex_mysql
    }
    db_type = _db_connection_type(connection)

    return (regex_safe_filters.get(db_type, lambda x: x),
            regexp_op_map.get(db_type, 'LIKE'))


def _regex_instance_filter(query, filters):

    """Applies regular expression filtering to an Instance query.

    Returns the updated query.

    :param query: query to apply filters to
    :param filters: dictionary of filters with regex values
    """

    model = models.Instance
    safe_regex_filter, db_regexp_op = _get_regexp_ops(CONF.database.connection)
    for filter_name in filters:
        try:
            column_attr = getattr(model, filter_name)
        except AttributeError:
            continue
        if 'property' == type(column_attr).__name__:
            continue
        filter_val = filters[filter_name]
        # Sometimes the REGEX filter value is not a string
        if not isinstance(filter_val, str):
            filter_val = str(filter_val)
        if db_regexp_op == 'LIKE':
            query = query.filter(column_attr.op(db_regexp_op)(
                                 u'%' + filter_val + u'%'))
        else:
            filter_val = safe_regex_filter(filter_val)
            query = query.filter(column_attr.op(db_regexp_op)(
                                 filter_val))
    return query


def _exact_instance_filter(query, filters, legal_keys):
    """Applies exact match filtering to an Instance query.

    Returns the updated query.  Modifies filters argument to remove
    filters consumed.

    :param query: query to apply filters to
    :param filters: dictionary of filters; values that are lists,
                    tuples, sets, or frozensets cause an 'IN' test to
                    be performed, while exact matching ('==' operator)
                    is used for other values
    :param legal_keys: list of keys to apply exact filtering to
    """

    filter_dict = {}
    model = models.Instance

    # Walk through all the keys
    for key in legal_keys:
        # Skip ones we're not filtering on
        if key not in filters:
            continue

        # OK, filtering on this key; what value do we search for?
        value = filters.pop(key)

        if key in ('metadata', 'system_metadata'):
            column_attr = getattr(model, key)
            if isinstance(value, list):
                for item in value:
                    for k, v in item.items():
                        query = query.filter(column_attr.any(key=k))
                        query = query.filter(column_attr.any(value=v))

            else:
                for k, v in value.items():
                    query = query.filter(column_attr.any(key=k))
                    query = query.filter(column_attr.any(value=v))
        elif isinstance(value, (list, tuple, set, frozenset)):
            if not value:
                return None  # empty IN-predicate; short circuit
            # Looking for values in a list; apply to query directly
            column_attr = getattr(model, key)
            query = query.filter(column_attr.in_(value))
        else:
            # OK, simple exact match; save for later
            filter_dict[key] = value

    # Apply simple exact matches
    if filter_dict:
        query = query.filter(*[getattr(models.Instance, k) == v
                               for k, v in filter_dict.items()])
    return query


@require_context
@pick_context_manager_reader_allow_async
def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None, host=None,
                                         columns_to_join=None, limit=None,
                                         marker=None):
    """Get instances and joins active during a certain time window.

    Specifying a project_id will filter for a certain project.
    Specifying a host will filter for instances on a given compute host.
    """
    query = context.session.query(models.Instance)

    if columns_to_join is None:
        columns_to_join_new = ['info_cache', 'security_groups']
        manual_joins = ['metadata', 'system_metadata']
    else:
        manual_joins, columns_to_join_new = (
            _manual_join_columns(columns_to_join))

    for column in columns_to_join_new:
        if 'extra.' in column:
            query = query.options(orm.undefer(column))
        else:
            query = query.options(orm.joinedload(column))

    query = query.filter(sql.or_(
        models.Instance.terminated_at == sql.null(),
        models.Instance.terminated_at > begin))
    if end:
        query = query.filter(models.Instance.launched_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if host:
        query = query.filter_by(host=host)

    if marker is not None:
        try:
            marker = _instance_get_by_uuid(
                context.elevated(read_deleted='yes'), marker)
        except exception.InstanceNotFound:
            raise exception.MarkerNotFound(marker=marker)

    query = sqlalchemyutils.paginate_query(
        query, models.Instance, limit, ['project_id', 'uuid'], marker=marker)

    return _instances_fill_metadata(context, query.all(), manual_joins)


def _instance_get_all_query(context, project_only=False, joins=None):
    if joins is None:
        joins = ['info_cache', 'security_groups']

    query = model_query(context,
                        models.Instance,
                        project_only=project_only)
    for column in joins:
        if 'extra.' in column:
            query = query.options(orm.undefer(column))
        else:
            query = query.options(orm.joinedload(column))
    return query


@pick_context_manager_reader_allow_async
def instance_get_all_by_host(context, host, columns_to_join=None):
    """Get all instances belonging to a host."""
    query = _instance_get_all_query(context, joins=columns_to_join)
    return _instances_fill_metadata(context,
                                    query.filter_by(host=host).all(),
                                    manual_joins=columns_to_join)


def _instance_get_all_uuids_by_hosts(context, hosts):
    itbl = models.Instance.__table__
    default_deleted_value = itbl.c.deleted.default.arg
    sel = sql.select([itbl.c.host, itbl.c.uuid])
    sel = sel.where(sql.and_(
            itbl.c.deleted == default_deleted_value,
            itbl.c.host.in_(sa.bindparam('hosts', expanding=True))))

    # group the instance UUIDs by hostname
    res = collections.defaultdict(list)
    for rec in context.session.execute(sel, {'hosts': hosts}).fetchall():
        res[rec[0]].append(rec[1])
    return res


@pick_context_manager_reader
def instance_get_all_uuids_by_hosts(context, hosts):
    """Get a dict, keyed by hostname, of a list of the instance UUIDs on the
    host for each supplied hostname, not Instance model objects.

    The dict is a defaultdict of list, thus inspecting the dict for a host not
    in the dict will return an empty list not a KeyError.
    """
    return _instance_get_all_uuids_by_hosts(context, hosts)


@pick_context_manager_reader
def instance_get_all_by_host_and_node(
    context, host, node, columns_to_join=None,
):
    """Get all instances belonging to a node."""
    if columns_to_join is None:
        manual_joins = []
    else:
        candidates = ['system_metadata', 'metadata']
        manual_joins = [x for x in columns_to_join if x in candidates]
        columns_to_join = list(set(columns_to_join) - set(candidates))
    return _instances_fill_metadata(context,
            _instance_get_all_query(
                context,
                joins=columns_to_join).filter_by(host=host).
                filter_by(node=node).all(), manual_joins=manual_joins)


@pick_context_manager_reader
def instance_get_all_by_host_and_not_type(context, host, type_id=None):
    """Get all instances belonging to a host with a different type_id."""
    return _instances_fill_metadata(context,
        _instance_get_all_query(context).filter_by(host=host).
                   filter(models.Instance.instance_type_id != type_id).all())


# NOTE(hanlind): This method can be removed as conductor RPC API moves to v2.0.
@pick_context_manager_reader
def instance_get_all_hung_in_rebooting(context, reboot_window):
    """Get all instances stuck in a rebooting state."""
    reboot_window = (timeutils.utcnow() -
                     datetime.timedelta(seconds=reboot_window))

    # NOTE(danms): this is only used in the _poll_rebooting_instances()
    # call in compute/manager, so we can avoid the metadata lookups
    # explicitly
    return _instances_fill_metadata(context,
        model_query(context, models.Instance).
            filter(models.Instance.updated_at <= reboot_window).
            filter_by(task_state=task_states.REBOOTING).all(),
        manual_joins=[])


def _retry_instance_update():
    """Wrap with oslo_db_api.wrap_db_retry, and also retry on
    UnknownInstanceUpdateConflict.
    """
    exception_checker = \
        lambda exc: isinstance(exc, (exception.UnknownInstanceUpdateConflict,))
    return oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True,
                                     exception_checker=exception_checker)


@require_context
@_retry_instance_update()
@pick_context_manager_writer
def instance_update(context, instance_uuid, values, expected=None):
    """Set the given properties on an instance and update it.

    :raises: NotFound if instance does not exist.
    """
    return _instance_update(context, instance_uuid, values, expected)


@require_context
@_retry_instance_update()
@pick_context_manager_writer
def instance_update_and_get_original(context, instance_uuid, values,
                                     columns_to_join=None, expected=None):
    """Set the given properties on an instance and update it.

    Return a shallow copy of the original instance reference, as well as the
    updated one.

    If "expected_task_state" exists in values, the update can only happen
    when the task state before update matches expected_task_state. Otherwise
    a UnexpectedTaskStateError is thrown.

    :param context: request context object
    :param instance_uuid: instance uuid
    :param values: dict containing column values
    :returns: a tuple of the form (old_instance_ref, new_instance_ref)
    :raises: NotFound if instance does not exist.
    """
    instance_ref = _instance_get_by_uuid(context, instance_uuid,
                                         columns_to_join=columns_to_join)
    return (copy.copy(instance_ref), _instance_update(
        context, instance_uuid, values, expected, original=instance_ref))


# NOTE(danms): This updates the instance's metadata list in-place and in
# the database to avoid stale data and refresh issues. It assumes the
# delete=True behavior of instance_metadata_update(...)
def _instance_metadata_update_in_place(context, instance, metadata_type, model,
                                       metadata):
    metadata = dict(metadata)
    to_delete = []
    for keyvalue in instance[metadata_type]:
        key = keyvalue['key']
        if key in metadata:
            keyvalue['value'] = metadata.pop(key)
        elif key not in metadata:
            to_delete.append(keyvalue)

    # NOTE: we have to hard_delete here otherwise we will get more than one
    # system_metadata record when we read deleted for an instance;
    # regular metadata doesn't have the same problem because we don't
    # allow reading deleted regular metadata anywhere.
    if metadata_type == 'system_metadata':
        for condemned in to_delete:
            context.session.delete(condemned)
            instance[metadata_type].remove(condemned)
    else:
        for condemned in to_delete:
            condemned.soft_delete(context.session)

    for key, value in metadata.items():
        newitem = model()
        newitem.update({'key': key, 'value': value,
                        'instance_uuid': instance['uuid']})
        context.session.add(newitem)
        instance[metadata_type].append(newitem)


def _instance_update(context, instance_uuid, values, expected, original=None):
    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    # NOTE(mdbooth): We pop values from this dict below, so we copy it here to
    # ensure there are no side effects for the caller or if we retry the
    # function due to a db conflict.
    updates = copy.copy(values)

    if expected is None:
        expected = {}
    else:
        # Coerce all single values to singleton lists
        expected = {k: [None] if v is None else sqlalchemyutils.to_list(v)
                       for (k, v) in expected.items()}

    # Extract 'expected_' values from values dict, as these aren't actually
    # updates
    for field in ('task_state', 'vm_state'):
        expected_field = 'expected_%s' % field
        if expected_field in updates:
            value = updates.pop(expected_field, None)
            # Coerce all single values to singleton lists
            if value is None:
                expected[field] = [None]
            else:
                expected[field] = sqlalchemyutils.to_list(value)

    # Values which need to be updated separately
    metadata = updates.pop('metadata', None)
    system_metadata = updates.pop('system_metadata', None)

    _handle_objects_related_type_conversions(updates)

    # Hostname is potentially unique, but this is enforced in code rather
    # than the DB. The query below races, but the number of users of
    # osapi_compute_unique_server_name_scope is small, and a robust fix
    # will be complex. This is intentionally left as is for the moment.
    if 'hostname' in updates:
        _validate_unique_server_name(context, updates['hostname'])

    compare = models.Instance(uuid=instance_uuid, **expected)
    try:
        instance_ref = model_query(context, models.Instance,
                                   project_only=True).\
                       update_on_match(compare, 'uuid', updates)
    except update_match.NoRowsMatched:
        # Update failed. Try to find why and raise a specific error.

        # We should get here only because our expected values were not current
        # when update_on_match executed. Having failed, we now have a hint that
        # the values are out of date and should check them.

        # This code is made more complex because we are using repeatable reads.
        # If we have previously read the original instance in the current
        # transaction, reading it again will return the same data, even though
        # the above update failed because it has changed: it is not possible to
        # determine what has changed in this transaction. In this case we raise
        # UnknownInstanceUpdateConflict, which will cause the operation to be
        # retried in a new transaction.

        # Because of the above, if we have previously read the instance in the
        # current transaction it will have been passed as 'original', and there
        # is no point refreshing it. If we have not previously read the
        # instance, we can fetch it here and we will get fresh data.
        if original is None:
            original = _instance_get_by_uuid(context, instance_uuid)

        conflicts_expected = {}
        conflicts_actual = {}
        for (field, expected_values) in expected.items():
            actual = original[field]
            if actual not in expected_values:
                conflicts_expected[field] = expected_values
                conflicts_actual[field] = actual

        # Exception properties
        exc_props = {
            'instance_uuid': instance_uuid,
            'expected': conflicts_expected,
            'actual': conflicts_actual
        }

        # There was a conflict, but something (probably the MySQL read view,
        # but possibly an exceptionally unlikely second race) is preventing us
        # from seeing what it is. When we go round again we'll get a fresh
        # transaction and a fresh read view.
        if len(conflicts_actual) == 0:
            raise exception.UnknownInstanceUpdateConflict(**exc_props)

        # Task state gets special handling for convenience. We raise the
        # specific error UnexpectedDeletingTaskStateError or
        # UnexpectedTaskStateError as appropriate
        if 'task_state' in conflicts_actual:
            conflict_task_state = conflicts_actual['task_state']
            if conflict_task_state == task_states.DELETING:
                exc = exception.UnexpectedDeletingTaskStateError
            else:
                exc = exception.UnexpectedTaskStateError

        # Everything else is an InstanceUpdateConflict
        else:
            exc = exception.InstanceUpdateConflict

        raise exc(**exc_props)

    if metadata is not None:
        _instance_metadata_update_in_place(context, instance_ref,
                                           'metadata',
                                           models.InstanceMetadata,
                                           metadata)

    if system_metadata is not None:
        _instance_metadata_update_in_place(context, instance_ref,
                                           'system_metadata',
                                           models.InstanceSystemMetadata,
                                           system_metadata)

    return instance_ref


@pick_context_manager_writer
def instance_add_security_group(context, instance_uuid, security_group_id):
    """Associate the given security group with the given instance."""
    sec_group_ref = models.SecurityGroupInstanceAssociation()
    sec_group_ref.update({'instance_uuid': instance_uuid,
                          'security_group_id': security_group_id})
    sec_group_ref.save(context.session)


@require_context
@pick_context_manager_writer
def instance_remove_security_group(context, instance_uuid, security_group_id):
    """Disassociate the given security group from the given instance."""
    model_query(context, models.SecurityGroupInstanceAssociation).\
                filter_by(instance_uuid=instance_uuid).\
                filter_by(security_group_id=security_group_id).\
                soft_delete()


###################


@require_context
@pick_context_manager_reader
def instance_info_cache_get(context, instance_uuid):
    """Gets an instance info cache from the table.

    :param instance_uuid: = uuid of the info cache's instance
    """
    return model_query(context, models.InstanceInfoCache).\
                         filter_by(instance_uuid=instance_uuid).\
                         first()


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def instance_info_cache_update(context, instance_uuid, values):
    """Update an instance info cache record in the table.

    :param instance_uuid: = uuid of info cache's instance
    :param values: = dict containing column values to update
    """
    convert_objects_related_datetimes(values)

    info_cache = model_query(context, models.InstanceInfoCache).\
                     filter_by(instance_uuid=instance_uuid).\
                     first()
    needs_create = False
    if info_cache and info_cache['deleted']:
        raise exception.InstanceInfoCacheNotFound(
                instance_uuid=instance_uuid)
    elif not info_cache:
        # NOTE(tr3buchet): just in case someone blows away an instance's
        #                  cache entry, re-create it.
        values['instance_uuid'] = instance_uuid
        info_cache = models.InstanceInfoCache(**values)
        needs_create = True

    try:
        with get_context_manager(context).writer.savepoint.using(context):
            if needs_create:
                info_cache.save(context.session)
            else:
                info_cache.update(values)
    except db_exc.DBDuplicateEntry:
        # NOTE(sirp): Possible race if two greenthreads attempt to
        # recreate the instance cache entry at the same time. First one
        # wins.
        pass

    return info_cache


@require_context
@pick_context_manager_writer
def instance_info_cache_delete(context, instance_uuid):
    """Deletes an existing instance_info_cache record

    :param instance_uuid: = uuid of the instance tied to the cache record
    """
    model_query(context, models.InstanceInfoCache).\
                         filter_by(instance_uuid=instance_uuid).\
                         soft_delete()


###################


def _instance_extra_create(context, values):
    inst_extra_ref = models.InstanceExtra()
    inst_extra_ref.update(values)
    inst_extra_ref.save(context.session)
    return inst_extra_ref


@pick_context_manager_writer
def instance_extra_update_by_uuid(context, instance_uuid, updates):
    """Update the instance extra record by instance uuid

    :param instance_uuid: UUID of the instance tied to the record
    :param updates: A dict of updates to apply
    """
    rows_updated = model_query(context, models.InstanceExtra).\
        filter_by(instance_uuid=instance_uuid).\
        update(updates)
    if not rows_updated:
        LOG.debug("Created instance_extra for %s", instance_uuid)
        create_values = copy.copy(updates)
        create_values["instance_uuid"] = instance_uuid
        _instance_extra_create(context, create_values)
        rows_updated = 1
    return rows_updated


@pick_context_manager_reader
def instance_extra_get_by_instance_uuid(
    context, instance_uuid, columns=None,
):
    """Get the instance extra record

    :param instance_uuid: UUID of the instance tied to the topology record
    :param columns: A list of the columns to load, or None for 'all of them'
    """
    query = model_query(context, models.InstanceExtra).\
        filter_by(instance_uuid=instance_uuid)
    if columns is None:
        columns = ['numa_topology', 'pci_requests', 'flavor', 'vcpu_model',
                   'trusted_certs', 'resources', 'migration_context']
    for column in columns:
        query = query.options(orm.undefer(column))
    instance_extra = query.first()
    return instance_extra


###################


@require_context
@pick_context_manager_writer
def key_pair_create(context, values):
    """Create a key_pair from the values dictionary."""
    try:
        key_pair_ref = models.KeyPair()
        key_pair_ref.update(values)
        key_pair_ref.save(context.session)
        return key_pair_ref
    except db_exc.DBDuplicateEntry:
        raise exception.KeyPairExists(key_name=values['name'])


@require_context
@pick_context_manager_writer
def key_pair_destroy(context, user_id, name):
    """Destroy the key_pair or raise if it does not exist."""
    result = model_query(context, models.KeyPair).\
                         filter_by(user_id=user_id).\
                         filter_by(name=name).\
                         soft_delete()
    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)


@require_context
@pick_context_manager_reader
def key_pair_get(context, user_id, name):
    """Get a key_pair or raise if it does not exist."""
    result = model_query(context, models.KeyPair).\
                     filter_by(user_id=user_id).\
                     filter_by(name=name).\
                     first()

    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)

    return result


@require_context
@pick_context_manager_reader
def key_pair_get_all_by_user(context, user_id, limit=None, marker=None):
    """Get all key_pairs by user."""
    marker_row = None
    if marker is not None:
        marker_row = model_query(context, models.KeyPair, read_deleted="no").\
            filter_by(name=marker).filter_by(user_id=user_id).first()
        if not marker_row:
            raise exception.MarkerNotFound(marker=marker)

    query = model_query(context, models.KeyPair, read_deleted="no").\
        filter_by(user_id=user_id)

    query = sqlalchemyutils.paginate_query(
        query, models.KeyPair, limit, ['name'], marker=marker_row)

    return query.all()


@require_context
@pick_context_manager_reader
def key_pair_count_by_user(context, user_id):
    """Count number of key pairs for the given user ID."""
    return model_query(context, models.KeyPair, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   count()


###################


@require_context
@pick_context_manager_reader
def quota_get(context, project_id, resource, user_id=None):
    """Retrieve a quota or raise if it does not exist."""
    model = models.ProjectUserQuota if user_id else models.Quota
    query = model_query(context, model).\
                    filter_by(project_id=project_id).\
                    filter_by(resource=resource)
    if user_id:
        query = query.filter_by(user_id=user_id)

    result = query.first()
    if not result:
        if user_id:
            raise exception.ProjectUserQuotaNotFound(project_id=project_id,
                                                     user_id=user_id)
        else:
            raise exception.ProjectQuotaNotFound(project_id=project_id)

    return result


@require_context
@pick_context_manager_reader
def quota_get_all_by_project_and_user(context, project_id, user_id):
    """Retrieve all quotas associated with a given project and user."""
    user_quotas = model_query(context, models.ProjectUserQuota,
                              (models.ProjectUserQuota.resource,
                               models.ProjectUserQuota.hard_limit)).\
                   filter_by(project_id=project_id).\
                   filter_by(user_id=user_id).\
                   all()

    result = {'project_id': project_id, 'user_id': user_id}
    for user_quota in user_quotas:
        result[user_quota.resource] = user_quota.hard_limit

    return result


@require_context
@pick_context_manager_reader
def quota_get_all_by_project(context, project_id):
    """Retrieve all quotas associated with a given project."""
    rows = model_query(context, models.Quota, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_context
@pick_context_manager_reader
def quota_get_all(context, project_id):
    """Retrieve all user quotas associated with a given project."""
    result = model_query(context, models.ProjectUserQuota).\
                   filter_by(project_id=project_id).\
                   all()

    return result


def quota_get_per_project_resources():
    """Retrieve the names of resources whose quotas are calculated on a
    per-project rather than a per-user basis.
    """
    return PER_PROJECT_QUOTAS


@pick_context_manager_writer
def quota_create(context, project_id, resource, limit, user_id=None):
    """Create a quota for the given project and resource."""
    per_user = user_id and resource not in PER_PROJECT_QUOTAS
    quota_ref = models.ProjectUserQuota() if per_user else models.Quota()
    if per_user:
        quota_ref.user_id = user_id
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    try:
        quota_ref.save(context.session)
    except db_exc.DBDuplicateEntry:
        raise exception.QuotaExists(project_id=project_id, resource=resource)
    return quota_ref


@pick_context_manager_writer
def quota_update(context, project_id, resource, limit, user_id=None):
    """Update a quota or raise if it does not exist."""
    per_user = user_id and resource not in PER_PROJECT_QUOTAS
    model = models.ProjectUserQuota if per_user else models.Quota
    query = model_query(context, model).\
                filter_by(project_id=project_id).\
                filter_by(resource=resource)
    if per_user:
        query = query.filter_by(user_id=user_id)

    result = query.update({'hard_limit': limit})
    if not result:
        if per_user:
            raise exception.ProjectUserQuotaNotFound(project_id=project_id,
                                                     user_id=user_id)
        else:
            raise exception.ProjectQuotaNotFound(project_id=project_id)


###################


@require_context
@pick_context_manager_reader
def quota_class_get(context, class_name, resource):
    """Retrieve a quota class or raise if it does not exist."""
    result = model_query(context, models.QuotaClass, read_deleted="no").\
                     filter_by(class_name=class_name).\
                     filter_by(resource=resource).\
                     first()

    if not result:
        raise exception.QuotaClassNotFound(class_name=class_name)

    return result


@pick_context_manager_reader
def quota_class_get_default(context):
    """Retrieve all default quotas."""
    rows = model_query(context, models.QuotaClass, read_deleted="no").\
                   filter_by(class_name=_DEFAULT_QUOTA_NAME).\
                   all()

    result = {'class_name': _DEFAULT_QUOTA_NAME}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_context
@pick_context_manager_reader
def quota_class_get_all_by_name(context, class_name):
    """Retrieve all quotas associated with a given quota class."""
    rows = model_query(context, models.QuotaClass, read_deleted="no").\
                   filter_by(class_name=class_name).\
                   all()

    result = {'class_name': class_name}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@pick_context_manager_writer
def quota_class_create(context, class_name, resource, limit):
    """Create a quota class for the given name and resource."""
    quota_class_ref = models.QuotaClass()
    quota_class_ref.class_name = class_name
    quota_class_ref.resource = resource
    quota_class_ref.hard_limit = limit
    quota_class_ref.save(context.session)
    return quota_class_ref


@pick_context_manager_writer
def quota_class_update(context, class_name, resource, limit):
    """Update a quota class or raise if it does not exist."""
    result = model_query(context, models.QuotaClass, read_deleted="no").\
                     filter_by(class_name=class_name).\
                     filter_by(resource=resource).\
                     update({'hard_limit': limit})

    if not result:
        raise exception.QuotaClassNotFound(class_name=class_name)


###################


@pick_context_manager_writer
def quota_destroy_all_by_project_and_user(context, project_id, user_id):
    """Destroy all quotas associated with a given project and user."""
    model_query(context, models.ProjectUserQuota, read_deleted="no").\
        filter_by(project_id=project_id).\
        filter_by(user_id=user_id).\
        soft_delete(synchronize_session=False)


@pick_context_manager_writer
def quota_destroy_all_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    model_query(context, models.Quota, read_deleted="no").\
        filter_by(project_id=project_id).\
        soft_delete(synchronize_session=False)

    model_query(context, models.ProjectUserQuota, read_deleted="no").\
        filter_by(project_id=project_id).\
        soft_delete(synchronize_session=False)


###################


def _block_device_mapping_get_query(context, columns_to_join=None):
    if columns_to_join is None:
        columns_to_join = []

    query = model_query(context, models.BlockDeviceMapping)

    for column in columns_to_join:
        query = query.options(orm.joinedload(column))

    return query


def _scrub_empty_str_values(dct, keys_to_scrub):
    """Remove any keys found in sequence keys_to_scrub from the dict
    if they have the value ''.
    """
    for key in keys_to_scrub:
        if key in dct and dct[key] == '':
            del dct[key]


def _from_legacy_values(values, legacy, allow_updates=False):
    if legacy:
        if allow_updates and block_device.is_safe_for_update(values):
            return values
        else:
            return block_device.BlockDeviceDict.from_legacy(values)
    else:
        return values


def _set_or_validate_uuid(values):
    uuid = values.get('uuid')

    # values doesn't contain uuid, or it's blank
    if not uuid:
        values['uuid'] = uuidutils.generate_uuid()

    # values contains a uuid
    else:
        if not uuidutils.is_uuid_like(uuid):
            raise exception.InvalidUUID(uuid=uuid)


@require_context
@pick_context_manager_writer
def block_device_mapping_create(context, values, legacy=True):
    """Create an entry of block device mapping."""
    _scrub_empty_str_values(values, ['volume_size'])
    values = _from_legacy_values(values, legacy)
    convert_objects_related_datetimes(values)

    _set_or_validate_uuid(values)

    bdm_ref = models.BlockDeviceMapping()
    bdm_ref.update(values)
    bdm_ref.save(context.session)
    return bdm_ref


@require_context
@pick_context_manager_writer
def block_device_mapping_update(context, bdm_id, values, legacy=True):
    """Update an entry of block device mapping."""
    _scrub_empty_str_values(values, ['volume_size'])
    values = _from_legacy_values(values, legacy, allow_updates=True)
    convert_objects_related_datetimes(values)

    query = _block_device_mapping_get_query(context).filter_by(id=bdm_id)
    query.update(values)
    return query.first()


@pick_context_manager_writer
def block_device_mapping_update_or_create(context, values, legacy=True):
    """Update an entry of block device mapping.

    If not existed, create a new entry
    """
    # TODO(mdbooth): Remove this method entirely. Callers should know whether
    # they require update or create, and call the appropriate method.

    _scrub_empty_str_values(values, ['volume_size'])
    values = _from_legacy_values(values, legacy, allow_updates=True)
    convert_objects_related_datetimes(values)

    result = None
    # NOTE(xqueralt,danms): Only update a BDM when device_name or
    # uuid was provided. Prefer the uuid, if available, but fall
    # back to device_name if no uuid is provided, which can happen
    # for BDMs created before we had a uuid. We allow empty device
    # names so they will be set later by the manager.
    if 'uuid' in values:
        query = _block_device_mapping_get_query(context)
        result = query.filter_by(instance_uuid=values['instance_uuid'],
                                 uuid=values['uuid']).one_or_none()

    if not result and values['device_name']:
        query = _block_device_mapping_get_query(context)
        result = query.filter_by(instance_uuid=values['instance_uuid'],
                                 device_name=values['device_name']).first()

    if result:
        result.update(values)
    else:
        # Either the device_name or uuid doesn't exist in the database yet, or
        # neither was provided. Both cases mean creating a new BDM.
        _set_or_validate_uuid(values)
        result = models.BlockDeviceMapping(**values)
        result.save(context.session)

    # NOTE(xqueralt): Prevent from having multiple swap devices for the
    # same instance. This will delete all the existing ones.
    if block_device.new_format_is_swap(values):
        query = _block_device_mapping_get_query(context)
        query = query.filter_by(instance_uuid=values['instance_uuid'],
                                source_type='blank', guest_format='swap')
        query = query.filter(models.BlockDeviceMapping.id != result.id)
        query.soft_delete()

    return result


@require_context
@pick_context_manager_reader_allow_async
def block_device_mapping_get_all_by_instance_uuids(context, instance_uuids):
    """Get all block device mapping belonging to a list of instances."""
    if not instance_uuids:
        return []
    return _block_device_mapping_get_query(context).filter(
        models.BlockDeviceMapping.instance_uuid.in_(instance_uuids)).all()


@require_context
@pick_context_manager_reader_allow_async
def block_device_mapping_get_all_by_instance(context, instance_uuid):
    """Get all block device mapping belonging to an instance."""
    return _block_device_mapping_get_query(context).\
                 filter_by(instance_uuid=instance_uuid).\
                 all()


@require_context
@pick_context_manager_reader
def block_device_mapping_get_all_by_volume_id(
    context, volume_id, columns_to_join=None,
):
    """Get block device mapping for a given volume."""
    return _block_device_mapping_get_query(context,
            columns_to_join=columns_to_join).\
                 filter_by(volume_id=volume_id).\
                 all()


@require_context
@pick_context_manager_reader
def block_device_mapping_get_by_instance_and_volume_id(
    context, volume_id, instance_uuid, columns_to_join=None,
):
    """Get block device mapping for a given volume ID and instance UUID."""
    return _block_device_mapping_get_query(context,
            columns_to_join=columns_to_join).\
                 filter_by(volume_id=volume_id).\
                 filter_by(instance_uuid=instance_uuid).\
                 first()


@require_context
@pick_context_manager_writer
def block_device_mapping_destroy(context, bdm_id):
    """Destroy the block device mapping."""
    _block_device_mapping_get_query(context).\
            filter_by(id=bdm_id).\
            soft_delete()


@require_context
@pick_context_manager_writer
def block_device_mapping_destroy_by_instance_and_volume(
    context, instance_uuid, volume_id,
):
    """Destroy the block device mapping."""
    _block_device_mapping_get_query(context).\
            filter_by(instance_uuid=instance_uuid).\
            filter_by(volume_id=volume_id).\
            soft_delete()


@require_context
@pick_context_manager_writer
def block_device_mapping_destroy_by_instance_and_device(
    context, instance_uuid, device_name,
):
    """Destroy the block device mapping."""
    _block_device_mapping_get_query(context).\
            filter_by(instance_uuid=instance_uuid).\
            filter_by(device_name=device_name).\
            soft_delete()


###################


@require_context
@pick_context_manager_writer
def security_group_create(context, values):
    """Create a new security group."""
    security_group_ref = models.SecurityGroup()
    # FIXME(devcamcar): Unless I do this, rules fails with lazy load exception
    # once save() is called.  This will get cleaned up in next orm pass.
    security_group_ref.rules = []
    security_group_ref.update(values)
    try:
        with get_context_manager(context).writer.savepoint.using(context):
            security_group_ref.save(context.session)
    except db_exc.DBDuplicateEntry:
        raise exception.SecurityGroupExists(
                project_id=values['project_id'],
                security_group_name=values['name'])
    return security_group_ref


def _security_group_get_query(context, read_deleted=None,
                              project_only=False, join_rules=True):
    query = model_query(context, models.SecurityGroup,
            read_deleted=read_deleted, project_only=project_only)
    if join_rules:
        query = query.options(_joinedload_all('rules.grantee_group'))
    return query


def _security_group_get_by_names(context, group_names):
    """Get security group models for a project by a list of names.
    Raise SecurityGroupNotFoundForProject for a name not found.
    """
    query = _security_group_get_query(context, read_deleted="no",
                                      join_rules=False).\
            filter_by(project_id=context.project_id).\
            filter(models.SecurityGroup.name.in_(group_names))
    sg_models = query.all()
    if len(sg_models) == len(group_names):
        return sg_models
    # Find the first one missing and raise
    group_names_from_models = [x.name for x in sg_models]
    for group_name in group_names:
        if group_name not in group_names_from_models:
            raise exception.SecurityGroupNotFoundForProject(
                project_id=context.project_id, security_group_id=group_name)
    # Not Reached


@require_context
@pick_context_manager_reader
def security_group_get_all(context):
    """Get all security groups."""
    return _security_group_get_query(context).all()


@require_context
@pick_context_manager_reader
def security_group_get(context, security_group_id, columns_to_join=None):
    """Get security group by its ID."""
    join_rules = columns_to_join and 'rules' in columns_to_join
    if join_rules:
        columns_to_join.remove('rules')
    query = _security_group_get_query(context, project_only=True,
                                      join_rules=join_rules).\
                    filter_by(id=security_group_id)

    if columns_to_join is None:
        columns_to_join = []
    for column in columns_to_join:
        if column.startswith('instances'):
            query = query.options(_joinedload_all(column))

    result = query.first()
    if not result:
        raise exception.SecurityGroupNotFound(
                security_group_id=security_group_id)

    return result


@require_context
@pick_context_manager_reader
def security_group_get_by_name(
    context, project_id, group_name, columns_to_join=None,
):
    """Returns a security group with the specified name from a project."""
    query = _security_group_get_query(context,
                                      read_deleted="no", join_rules=False).\
            filter_by(project_id=project_id).\
            filter_by(name=group_name)

    if columns_to_join is None:
        columns_to_join = ['instances', 'rules.grantee_group']

    for column in columns_to_join:
        query = query.options(_joinedload_all(column))

    result = query.first()
    if not result:
        raise exception.SecurityGroupNotFoundForProject(
                project_id=project_id, security_group_id=group_name)

    return result


@require_context
@pick_context_manager_reader
def security_group_get_by_project(context, project_id):
    """Get all security groups belonging to a project."""
    return _security_group_get_query(context, read_deleted="no").\
                        filter_by(project_id=project_id).\
                        all()


@require_context
@pick_context_manager_reader
def security_group_get_by_instance(context, instance_uuid):
    """Get security groups to which the instance is assigned."""
    return _security_group_get_query(context, read_deleted="no").\
                   join(models.SecurityGroup.instances).\
                   filter_by(uuid=instance_uuid).\
                   all()


@require_context
@pick_context_manager_reader
def security_group_in_use(context, group_id):
    """Indicates if a security group is currently in use."""
    # Are there any instances that haven't been deleted
    # that include this group?
    inst_assoc = model_query(context,
                             models.SecurityGroupInstanceAssociation,
                             read_deleted="no").\
                    filter_by(security_group_id=group_id).\
                    all()
    for ia in inst_assoc:
        num_instances = model_query(context, models.Instance,
                                    read_deleted="no").\
                    filter_by(uuid=ia.instance_uuid).\
                    count()
        if num_instances:
            return True

    return False


@require_context
@pick_context_manager_writer
def security_group_update(context, security_group_id, values,
                          columns_to_join=None):
    """Update a security group."""
    query = model_query(context, models.SecurityGroup).filter_by(
        id=security_group_id)
    if columns_to_join:
        for column in columns_to_join:
            query = query.options(_joinedload_all(column))
    security_group_ref = query.first()

    if not security_group_ref:
        raise exception.SecurityGroupNotFound(
                security_group_id=security_group_id)
    security_group_ref.update(values)
    name = security_group_ref['name']
    project_id = security_group_ref['project_id']
    try:
        security_group_ref.save(context.session)
    except db_exc.DBDuplicateEntry:
        raise exception.SecurityGroupExists(
                project_id=project_id,
                security_group_name=name)
    return security_group_ref


def security_group_ensure_default(context):
    """Ensure default security group exists for a project_id.

    Returns a tuple with the first element being a bool indicating
    if the default security group previously existed. Second
    element is the dict used to create the default security group.
    """

    try:
        # NOTE(rpodolyaka): create the default security group, if it doesn't
        # exist. This must be done in a separate transaction, so that
        # this one is not aborted in case a concurrent one succeeds first
        # and the unique constraint for security group names is violated
        # by a concurrent INSERT
        with get_context_manager(context).writer.independent.using(context):
            return _security_group_ensure_default(context)
    except exception.SecurityGroupExists:
        # NOTE(rpodolyaka): a concurrent transaction has succeeded first,
        # suppress the error and proceed
        return security_group_get_by_name(context, context.project_id,
                                          'default')


@pick_context_manager_writer
def _security_group_ensure_default(context):
    try:
        default_group = _security_group_get_by_names(context, ['default'])[0]
    except exception.NotFound:
        values = {'name': 'default',
                  'description': 'default',
                  'user_id': context.user_id,
                  'project_id': context.project_id}
        default_group = security_group_create(context, values)
    return default_group


@require_context
@pick_context_manager_writer
def security_group_destroy(context, security_group_id):
    """Deletes a security group."""
    model_query(context, models.SecurityGroup).\
            filter_by(id=security_group_id).\
            soft_delete()
    model_query(context, models.SecurityGroupInstanceAssociation).\
            filter_by(security_group_id=security_group_id).\
            soft_delete()
    model_query(context, models.SecurityGroupIngressRule).\
            filter_by(group_id=security_group_id).\
            soft_delete()
    model_query(context, models.SecurityGroupIngressRule).\
            filter_by(parent_group_id=security_group_id).\
            soft_delete()


###################


@pick_context_manager_writer
def migration_create(context, values):
    """Create a migration record."""
    migration = models.Migration()
    migration.update(values)
    migration.save(context.session)
    return migration


@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def migration_update(context, migration_id, values):
    """Update a migration instance."""
    migration = migration_get(context, migration_id)
    migration.update(values)

    return migration


@pick_context_manager_reader
def migration_get(context, migration_id):
    """Finds a migration by the ID."""
    result = model_query(context, models.Migration, read_deleted="yes").\
                     filter_by(id=migration_id).\
                     first()

    if not result:
        raise exception.MigrationNotFound(migration_id=migration_id)

    return result


@pick_context_manager_reader
def migration_get_by_uuid(context, migration_uuid):
    """Finds a migration by the migration UUID."""
    result = model_query(context, models.Migration, read_deleted="yes").\
                     filter_by(uuid=migration_uuid).\
                     first()

    if not result:
        raise exception.MigrationNotFound(migration_id=migration_uuid)

    return result


@pick_context_manager_reader
def migration_get_by_id_and_instance(context, migration_id, instance_uuid):
    """Finds a migration by the migration ID and the instance UUID."""
    result = model_query(context, models.Migration).\
                     filter_by(id=migration_id).\
                     filter_by(instance_uuid=instance_uuid).\
                     first()

    if not result:
        raise exception.MigrationNotFoundForInstance(
            migration_id=migration_id, instance_id=instance_uuid)

    return result


@pick_context_manager_reader
def migration_get_by_instance_and_status(context, instance_uuid, status):
    """Finds a migration by the instance UUID it's migrating."""
    result = model_query(context, models.Migration, read_deleted="yes").\
                     filter_by(instance_uuid=instance_uuid).\
                     filter_by(status=status).\
                     first()

    if not result:
        raise exception.MigrationNotFoundByStatus(instance_id=instance_uuid,
                                                  status=status)

    return result


@pick_context_manager_reader_allow_async
def migration_get_unconfirmed_by_dest_compute(
    context, confirm_window, dest_compute,
):
    """Finds all unconfirmed migrations within the confirmation window for
    a specific destination compute host.
    """
    confirm_window = (timeutils.utcnow() -
                      datetime.timedelta(seconds=confirm_window))

    return model_query(context, models.Migration, read_deleted="yes").\
             filter(models.Migration.updated_at <= confirm_window).\
             filter_by(status="finished").\
             filter_by(dest_compute=dest_compute).\
             all()


@pick_context_manager_reader
def migration_get_in_progress_by_host_and_node(context, host, node):
    """Finds all migrations for the given host + node  that are not yet
    confirmed or reverted.
    """
    # TODO(mriedem): Tracking what various code flows set for
    # migration status is nutty, since it happens all over the place
    # and several of the statuses are redundant (done and completed).
    # We need to define these in an enum somewhere and just update
    # that one central place that defines what "in progress" means.
    # NOTE(mriedem): The 'finished' status is not in this list because
    # 'finished' means a resize is finished on the destination host
    # and the instance is in VERIFY_RESIZE state, so the end state
    # for a resize is actually 'confirmed' or 'reverted'.
    return model_query(context, models.Migration).\
            filter(sql.or_(
                sql.and_(
                    models.Migration.source_compute == host,
                    models.Migration.source_node == node),
                sql.and_(
                    models.Migration.dest_compute == host,
                    models.Migration.dest_node == node))).\
            filter(~models.Migration.status.in_(['confirmed', 'reverted',
                                                 'error', 'failed',
                                                 'completed', 'cancelled',
                                                 'done'])).\
            options(_joinedload_all('instance.system_metadata')).\
            all()


@pick_context_manager_reader
def migration_get_in_progress_by_instance(context, instance_uuid,
                                          migration_type=None):
    """Finds all migrations of an instance in progress."""
    # TODO(Shaohe Feng) we should share the in-progress list.
    # TODO(Shaohe Feng) will also summarize all status to a new
    # MigrationStatus class.
    query = model_query(context, models.Migration).\
            filter_by(instance_uuid=instance_uuid).\
            filter(models.Migration.status.in_(['queued', 'preparing',
                                                'running',
                                                'post-migrating']))
    if migration_type:
        query = query.filter(models.Migration.migration_type == migration_type)

    return query.all()


def _migration_filter_item(query, filters, name):
    if name not in filters:
        return query

    column = getattr(models.Migration, name)

    item = filters[name]
    if isinstance(item, str) or item is None:
        return query.filter(column == item)

    try:
        return query.filter(column.in_(item))
    except TypeError:  # in_ expects an iterable, we fall back to comparison
        return query.filter(column == item)


@pick_context_manager_reader
def migration_get_all_by_filters(context, filters,
                                 sort_keys=None, sort_dirs=None,
                                 limit=None, marker=None):
    """Finds all migrations using the provided filters."""
    if limit == 0:
        return []

    query = model_query(context, models.Migration)

    model_object = models.Migration
    query = _get_query_nova_resource_by_changes_time(query,
                                                     filters,
                                                     model_object)

    if "node" in filters:
        node = filters['node']
        query = query.filter(sql.or_(
            models.Migration.source_node == node,
            models.Migration.dest_node == node))
    if "hidden" in filters:
        hidden = filters["hidden"]
        query = query.filter(models.Migration.hidden == hidden)
    if 'user_id' in filters:
        user_id = filters['user_id']
        query = query.filter(models.Migration.user_id == user_id)
    if 'project_id' in filters:
        project_id = filters['project_id']
        query = query.filter(models.Migration.project_id == project_id)

    # The uuid filter is here for the MigrationLister and multi-cell
    # paging support in the compute API.
    for item in ("uuid", "status", "migration_type", "instance_uuid"):
        query = _migration_filter_item(query, filters, item)

    if "host" in filters:
        host = filters["host"]
        query = query.filter(sql.or_(
            models.Migration.source_compute == host,
            models.Migration.dest_compute == host))
    else:
        query = _migration_filter_item(query, filters, "source_compute")

    if "hidden" in filters:
        hidden = filters["hidden"]
        query = query.filter(models.Migration.hidden == hidden)

    if marker:
        try:
            marker = migration_get_by_uuid(context, marker)
        except exception.MigrationNotFound:
            raise exception.MarkerNotFound(marker=marker)
    if limit or marker or sort_keys or sort_dirs:
        # Default sort by desc(['created_at', 'id'])
        sort_keys, sort_dirs = db_utils.process_sort_params(
            sort_keys, sort_dirs, default_dir='desc')
        return sqlalchemyutils.paginate_query(query,
                                              models.Migration,
                                              limit=limit,
                                              sort_keys=sort_keys,
                                              marker=marker,
                                              sort_dirs=sort_dirs).all()
    else:
        return query.all()


@require_context
@pick_context_manager_reader_allow_async
def migration_get_by_sort_filters(context, sort_keys, sort_dirs, values):
    """Get the uuid of the first migration in a sort order.

    Return the first migration (uuid) of the set where each column value
    is greater than or equal to the matching one in @values, for each key
    in @sort_keys. This is used to try to find a marker migration when we don't
    have a marker uuid.

    :returns: A UUID of the migration that matched.
    """
    model = models.Migration
    return _model_get_uuid_by_sort_filters(context, model, sort_keys,
                                           sort_dirs, values)


@pick_context_manager_writer
def migration_migrate_to_uuid(context, count):
    # Avoid circular import
    from nova import objects

    db_migrations = model_query(context, models.Migration).filter_by(
        uuid=None).limit(count).all()

    done = 0
    for db_migration in db_migrations:
        mig = objects.Migration(context)
        mig._from_db_object(context, mig, db_migration)
        done += 1

    # We don't have any situation where we can (detectably) not
    # migrate a thing, so report anything that matched as "completed".
    return done, done


@pick_context_manager_reader
def migration_get_in_progress_and_error_by_host_and_node(context, host, node):
    """Finds all in progress migrations and error migrations for the given
    host and node.
    """
    return model_query(context, models.Migration).\
            filter(sql.or_(
                sql.and_(
                    models.Migration.source_compute == host,
                    models.Migration.source_node == node),
                sql.and_(
                    models.Migration.dest_compute == host,
                    models.Migration.dest_node == node))).\
            filter(~models.Migration.status.in_(['confirmed', 'reverted',
                                                 'failed', 'completed',
                                                 'cancelled', 'done'])).\
            options(_joinedload_all('instance.system_metadata')).\
            all()


########################
# User-provided metadata

def _instance_metadata_get_multi(context, instance_uuids):
    if not instance_uuids:
        return []
    return model_query(context, models.InstanceMetadata).filter(
        models.InstanceMetadata.instance_uuid.in_(instance_uuids))


def _instance_metadata_get_query(context, instance_uuid):
    return model_query(context, models.InstanceMetadata, read_deleted="no").\
                    filter_by(instance_uuid=instance_uuid)


@require_context
@pick_context_manager_reader
def instance_metadata_get(context, instance_uuid):
    """Get all metadata for an instance."""
    rows = _instance_metadata_get_query(context, instance_uuid).all()
    return {row['key']: row['value'] for row in rows}


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def instance_metadata_delete(context, instance_uuid, key):
    """Delete the given metadata item."""
    _instance_metadata_get_query(context, instance_uuid).\
        filter_by(key=key).\
        soft_delete()


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def instance_metadata_update(context, instance_uuid, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    all_keys = metadata.keys()
    if delete:
        _instance_metadata_get_query(context, instance_uuid).\
            filter(~models.InstanceMetadata.key.in_(all_keys)).\
            soft_delete(synchronize_session=False)

    already_existing_keys = []
    meta_refs = _instance_metadata_get_query(context, instance_uuid).\
        filter(models.InstanceMetadata.key.in_(all_keys)).\
        all()

    for meta_ref in meta_refs:
        already_existing_keys.append(meta_ref.key)
        meta_ref.update({"value": metadata[meta_ref.key]})

    new_keys = set(all_keys) - set(already_existing_keys)
    for key in new_keys:
        meta_ref = models.InstanceMetadata()
        meta_ref.update({"key": key, "value": metadata[key],
                         "instance_uuid": instance_uuid})
        context.session.add(meta_ref)

    return metadata


#######################
# System-owned metadata


def _instance_system_metadata_get_multi(context, instance_uuids):
    if not instance_uuids:
        return []
    return model_query(context, models.InstanceSystemMetadata,
                       read_deleted='yes').filter(
        models.InstanceSystemMetadata.instance_uuid.in_(instance_uuids))


def _instance_system_metadata_get_query(context, instance_uuid):
    return model_query(context, models.InstanceSystemMetadata).\
                    filter_by(instance_uuid=instance_uuid)


@require_context
@pick_context_manager_reader
def instance_system_metadata_get(context, instance_uuid):
    """Get all system metadata for an instance."""
    rows = _instance_system_metadata_get_query(context, instance_uuid).all()
    return {row['key']: row['value'] for row in rows}


@require_context
@pick_context_manager_writer
def instance_system_metadata_update(context, instance_uuid, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    all_keys = metadata.keys()
    if delete:
        _instance_system_metadata_get_query(context, instance_uuid).\
            filter(~models.InstanceSystemMetadata.key.in_(all_keys)).\
            soft_delete(synchronize_session=False)

    already_existing_keys = []
    meta_refs = _instance_system_metadata_get_query(context, instance_uuid).\
        filter(models.InstanceSystemMetadata.key.in_(all_keys)).\
        all()

    for meta_ref in meta_refs:
        already_existing_keys.append(meta_ref.key)
        meta_ref.update({"value": metadata[meta_ref.key]})

    new_keys = set(all_keys) - set(already_existing_keys)
    for key in new_keys:
        meta_ref = models.InstanceSystemMetadata()
        meta_ref.update({"key": key, "value": metadata[key],
                         "instance_uuid": instance_uuid})
        context.session.add(meta_ref)

    return metadata


####################

@require_context
@pick_context_manager_reader_allow_async
def bw_usage_get(context, uuid, start_period, mac):
    """Return bw usage for instance and mac in a given audit period."""
    values = {'start_period': start_period}
    values = convert_objects_related_datetimes(values, 'start_period')
    return model_query(context, models.BandwidthUsage, read_deleted="yes").\
                           filter_by(start_period=values['start_period']).\
                           filter_by(uuid=uuid).\
                           filter_by(mac=mac).\
                           first()


@require_context
@pick_context_manager_reader_allow_async
def bw_usage_get_by_uuids(context, uuids, start_period):
    """Return bw usages for instance(s) in a given audit period."""
    values = {'start_period': start_period}
    values = convert_objects_related_datetimes(values, 'start_period')
    return (
        model_query(context, models.BandwidthUsage, read_deleted="yes").
        filter(models.BandwidthUsage.uuid.in_(uuids)).
        filter_by(start_period=values['start_period']).
        all()
    )


@require_context
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def bw_usage_update(
    context, uuid, mac, start_period, bw_in, bw_out, last_ctr_in, last_ctr_out,
    last_refreshed=None,
):
    """Update cached bandwidth usage for an instance's network based on mac
    address.  Creates new record if needed.
    """

    if last_refreshed is None:
        last_refreshed = timeutils.utcnow()

    # NOTE(comstud): More often than not, we'll be updating records vs
    # creating records.  Optimize accordingly, trying to update existing
    # records.  Fall back to creation when no rows are updated.
    ts_values = {'last_refreshed': last_refreshed,
                 'start_period': start_period}
    ts_keys = ('start_period', 'last_refreshed')
    ts_values = convert_objects_related_datetimes(ts_values, *ts_keys)
    values = {'last_refreshed': ts_values['last_refreshed'],
              'last_ctr_in': last_ctr_in,
              'last_ctr_out': last_ctr_out,
              'bw_in': bw_in,
              'bw_out': bw_out}
    # NOTE(pkholkin): order_by() is needed here to ensure that the
    # same record is updated every time. It can be removed after adding
    # unique constraint to this model.
    bw_usage = model_query(context, models.BandwidthUsage,
        read_deleted='yes').\
            filter_by(start_period=ts_values['start_period']).\
            filter_by(uuid=uuid).\
            filter_by(mac=mac).\
            order_by(expression.asc(models.BandwidthUsage.id)).first()

    if bw_usage:
        bw_usage.update(values)
        return bw_usage

    bwusage = models.BandwidthUsage()
    bwusage.start_period = ts_values['start_period']
    bwusage.uuid = uuid
    bwusage.mac = mac
    bwusage.last_refreshed = ts_values['last_refreshed']
    bwusage.bw_in = bw_in
    bwusage.bw_out = bw_out
    bwusage.last_ctr_in = last_ctr_in
    bwusage.last_ctr_out = last_ctr_out
    bwusage.save(context.session)

    return bwusage


####################


@require_context
@pick_context_manager_reader
def vol_get_usage_by_time(context, begin):
    """Return volumes usage that have been updated after a specified time."""
    return model_query(context, models.VolumeUsage, read_deleted="yes").\
        filter(sql.or_(
            models.VolumeUsage.tot_last_refreshed == sql.null(),
            models.VolumeUsage.tot_last_refreshed > begin,
            models.VolumeUsage.curr_last_refreshed == sql.null(),
            models.VolumeUsage.curr_last_refreshed > begin,
        )).all()


@require_context
@pick_context_manager_writer
def vol_usage_update(
    context, id, rd_req, rd_bytes, wr_req, wr_bytes,
    instance_id, project_id, user_id, availability_zone,
    update_totals=False,
):
    """Update cached volume usage for a volume

    Creates new record if needed.
    """

    refreshed = timeutils.utcnow()

    values = {}
    # NOTE(dricco): We will be mostly updating current usage records vs
    # updating total or creating records. Optimize accordingly.
    if not update_totals:
        values = {'curr_last_refreshed': refreshed,
                  'curr_reads': rd_req,
                  'curr_read_bytes': rd_bytes,
                  'curr_writes': wr_req,
                  'curr_write_bytes': wr_bytes,
                  'instance_uuid': instance_id,
                  'project_id': project_id,
                  'user_id': user_id,
                  'availability_zone': availability_zone}
    else:
        values = {'tot_last_refreshed': refreshed,
                  'tot_reads': models.VolumeUsage.tot_reads + rd_req,
                  'tot_read_bytes': models.VolumeUsage.tot_read_bytes +
                                    rd_bytes,
                  'tot_writes': models.VolumeUsage.tot_writes + wr_req,
                  'tot_write_bytes': models.VolumeUsage.tot_write_bytes +
                                     wr_bytes,
                  'curr_reads': 0,
                  'curr_read_bytes': 0,
                  'curr_writes': 0,
                  'curr_write_bytes': 0,
                  'instance_uuid': instance_id,
                  'project_id': project_id,
                  'user_id': user_id,
                  'availability_zone': availability_zone}

    current_usage = model_query(context, models.VolumeUsage,
                        read_deleted="yes").\
                        filter_by(volume_id=id).\
                        first()
    if current_usage:
        if (rd_req < current_usage['curr_reads'] or
            rd_bytes < current_usage['curr_read_bytes'] or
            wr_req < current_usage['curr_writes'] or
                wr_bytes < current_usage['curr_write_bytes']):
            LOG.info("Volume(%s) has lower stats then what is in "
                     "the database. Instance must have been rebooted "
                     "or crashed. Updating totals.", id)
            if not update_totals:
                values['tot_reads'] = (models.VolumeUsage.tot_reads +
                                       current_usage['curr_reads'])
                values['tot_read_bytes'] = (
                    models.VolumeUsage.tot_read_bytes +
                    current_usage['curr_read_bytes'])
                values['tot_writes'] = (models.VolumeUsage.tot_writes +
                                        current_usage['curr_writes'])
                values['tot_write_bytes'] = (
                    models.VolumeUsage.tot_write_bytes +
                    current_usage['curr_write_bytes'])
            else:
                values['tot_reads'] = (models.VolumeUsage.tot_reads +
                                       current_usage['curr_reads'] +
                                       rd_req)
                values['tot_read_bytes'] = (
                    models.VolumeUsage.tot_read_bytes +
                    current_usage['curr_read_bytes'] + rd_bytes)
                values['tot_writes'] = (models.VolumeUsage.tot_writes +
                                        current_usage['curr_writes'] +
                                        wr_req)
                values['tot_write_bytes'] = (
                    models.VolumeUsage.tot_write_bytes +
                    current_usage['curr_write_bytes'] + wr_bytes)

        current_usage.update(values)
        current_usage.save(context.session)
        context.session.refresh(current_usage)
        return current_usage

    vol_usage = models.VolumeUsage()
    vol_usage.volume_id = id
    vol_usage.instance_uuid = instance_id
    vol_usage.project_id = project_id
    vol_usage.user_id = user_id
    vol_usage.availability_zone = availability_zone

    if not update_totals:
        vol_usage.curr_last_refreshed = refreshed
        vol_usage.curr_reads = rd_req
        vol_usage.curr_read_bytes = rd_bytes
        vol_usage.curr_writes = wr_req
        vol_usage.curr_write_bytes = wr_bytes
    else:
        vol_usage.tot_last_refreshed = refreshed
        vol_usage.tot_reads = rd_req
        vol_usage.tot_read_bytes = rd_bytes
        vol_usage.tot_writes = wr_req
        vol_usage.tot_write_bytes = wr_bytes

    vol_usage.save(context.session)

    return vol_usage


####################


@pick_context_manager_reader
def s3_image_get(context, image_id):
    """Find local s3 image represented by the provided id."""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(id=image_id).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_id)

    return result


@pick_context_manager_reader
def s3_image_get_by_uuid(context, image_uuid):
    """Find local s3 image represented by the provided uuid."""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(uuid=image_uuid).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_uuid)

    return result


@pick_context_manager_writer
def s3_image_create(context, image_uuid):
    """Create local s3 image represented by provided uuid."""
    try:
        s3_image_ref = models.S3Image()
        s3_image_ref.update({'uuid': image_uuid})
        s3_image_ref.save(context.session)
    except Exception as e:
        raise db_exc.DBError(e)

    return s3_image_ref


####################


@pick_context_manager_writer
def instance_fault_create(context, values):
    """Create a new instance fault."""
    fault_ref = models.InstanceFault()
    fault_ref.update(values)
    fault_ref.save(context.session)
    return dict(fault_ref)


@pick_context_manager_reader
def instance_fault_get_by_instance_uuids(
    context, instance_uuids, latest=False,
):
    """Get all instance faults for the provided instance_uuids.

    :param instance_uuids: List of UUIDs of instances to grab faults for
    :param latest: Optional boolean indicating we should only return the latest
        fault for the instance
    """
    if not instance_uuids:
        return {}

    faults_tbl = models.InstanceFault.__table__
    # NOTE(rpodolyaka): filtering by instance_uuids is performed in both
    # code branches below for the sake of a better query plan. On change,
    # make sure to update the other one as well.
    query = model_query(context, models.InstanceFault,
                        [faults_tbl],
                        read_deleted='no')

    if latest:
        # NOTE(jaypipes): We join instance_faults to a derived table of the
        # latest faults per instance UUID. The SQL produced below looks like
        # this:
        #
        #  SELECT instance_faults.*
        #  FROM instance_faults
        #  JOIN (
        #    SELECT instance_uuid, MAX(id) AS max_id
        #    FROM instance_faults
        #    WHERE instance_uuid IN ( ... )
        #    AND deleted = 0
        #    GROUP BY instance_uuid
        #  ) AS latest_faults
        #    ON instance_faults.id = latest_faults.max_id;
        latest_faults = model_query(
            context, models.InstanceFault,
            [faults_tbl.c.instance_uuid,
             sql.func.max(faults_tbl.c.id).label('max_id')],
            read_deleted='no'
        ).filter(
            faults_tbl.c.instance_uuid.in_(instance_uuids)
        ).group_by(
            faults_tbl.c.instance_uuid
        ).subquery(name="latest_faults")

        query = query.join(latest_faults,
                           faults_tbl.c.id == latest_faults.c.max_id)
    else:
        query = query.filter(
            models.InstanceFault.instance_uuid.in_(instance_uuids)
        ).order_by(expression.desc("id"))

    output = {}
    for instance_uuid in instance_uuids:
        output[instance_uuid] = []

    for row in query:
        output[row.instance_uuid].append(row._asdict())

    return output


##################


@pick_context_manager_writer
def action_start(context, values):
    """Start an action for an instance."""
    convert_objects_related_datetimes(values, 'start_time', 'updated_at')
    action_ref = models.InstanceAction()
    action_ref.update(values)
    action_ref.save(context.session)
    return action_ref


@pick_context_manager_writer
def action_finish(context, values):
    """Finish an action for an instance."""
    convert_objects_related_datetimes(values, 'start_time', 'finish_time',
                                      'updated_at')
    query = model_query(context, models.InstanceAction).\
                        filter_by(instance_uuid=values['instance_uuid']).\
                        filter_by(request_id=values['request_id'])
    if query.update(values) != 1:
        raise exception.InstanceActionNotFound(
                                    request_id=values['request_id'],
                                    instance_uuid=values['instance_uuid'])
    return query.one()


@pick_context_manager_reader
def actions_get(context, instance_uuid, limit=None, marker=None,
                filters=None):
    """Get all instance actions for the provided instance and filters."""
    if limit == 0:
        return []

    sort_keys = ['created_at', 'id']
    sort_dirs = ['desc', 'desc']

    query_prefix = model_query(context, models.InstanceAction).\
        filter_by(instance_uuid=instance_uuid)

    model_object = models.InstanceAction
    query_prefix = _get_query_nova_resource_by_changes_time(query_prefix,
                                                            filters,
                                                            model_object)

    if marker is not None:
        marker = action_get_by_request_id(context, instance_uuid, marker)
        if not marker:
            raise exception.MarkerNotFound(marker=marker)
    actions = sqlalchemyutils.paginate_query(query_prefix,
                                             models.InstanceAction, limit,
                                             sort_keys, marker=marker,
                                             sort_dirs=sort_dirs).all()
    return actions


@pick_context_manager_reader
def action_get_by_request_id(context, instance_uuid, request_id):
    """Get the action by request_id and given instance."""
    action = _action_get_by_request_id(context, instance_uuid, request_id)
    return action


def _action_get_by_request_id(context, instance_uuid, request_id):
    result = model_query(context, models.InstanceAction).\
        filter_by(instance_uuid=instance_uuid).\
        filter_by(request_id=request_id).\
        order_by(expression.desc("created_at"), expression.desc("id")).\
        first()
    return result


def _action_get_last_created_by_instance_uuid(context, instance_uuid):
    result = model_query(context, models.InstanceAction).\
        filter_by(instance_uuid=instance_uuid).\
        order_by(expression.desc("created_at"), expression.desc("id")).\
        first()
    return result


@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def action_event_start(context, values):
    """Start an event on an instance action."""
    convert_objects_related_datetimes(values, 'start_time')
    action = _action_get_by_request_id(context, values['instance_uuid'],
                                       values['request_id'])
    # When nova-compute restarts, the context is generated again in
    # init_host workflow, the request_id was different with the request_id
    # recorded in InstanceAction, so we can't get the original record
    # according to request_id. Try to get the last created action so that
    # init_instance can continue to finish the recovery action, like:
    # powering_off, unpausing, and so on.
    update_action = True
    if not action and not context.project_id:
        action = _action_get_last_created_by_instance_uuid(
            context, values['instance_uuid'])
        # If we couldn't find an action by the request_id, we don't want to
        # update this action since it likely represents an inactive action.
        update_action = False

    if not action:
        raise exception.InstanceActionNotFound(
                                    request_id=values['request_id'],
                                    instance_uuid=values['instance_uuid'])

    values['action_id'] = action['id']

    event_ref = models.InstanceActionEvent()
    event_ref.update(values)
    context.session.add(event_ref)

    # Update action updated_at.
    if update_action:
        action.update({'updated_at': values['start_time']})
        action.save(context.session)

    return event_ref


# NOTE: We need the retry_on_deadlock decorator for cases like resize where
# a lot of events are happening at once between multiple hosts trying to
# update the same action record in a small time window.
@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@pick_context_manager_writer
def action_event_finish(context, values):
    """Finish an event on an instance action."""
    convert_objects_related_datetimes(values, 'start_time', 'finish_time')
    action = _action_get_by_request_id(context, values['instance_uuid'],
                                       values['request_id'])
    # When nova-compute restarts, the context is generated again in
    # init_host workflow, the request_id was different with the request_id
    # recorded in InstanceAction, so we can't get the original record
    # according to request_id. Try to get the last created action so that
    # init_instance can continue to finish the recovery action, like:
    # powering_off, unpausing, and so on.
    update_action = True
    if not action and not context.project_id:
        action = _action_get_last_created_by_instance_uuid(
            context, values['instance_uuid'])
        # If we couldn't find an action by the request_id, we don't want to
        # update this action since it likely represents an inactive action.
        update_action = False

    if not action:
        raise exception.InstanceActionNotFound(
                                    request_id=values['request_id'],
                                    instance_uuid=values['instance_uuid'])

    event_ref = model_query(context, models.InstanceActionEvent).\
                            filter_by(action_id=action['id']).\
                            filter_by(event=values['event']).\
                            first()

    if not event_ref:
        raise exception.InstanceActionEventNotFound(action_id=action['id'],
                                                    event=values['event'])
    event_ref.update(values)

    if values['result'].lower() == 'error':
        action.update({'message': 'Error'})

    # Update action updated_at.
    if update_action:
        action.update({'updated_at': values['finish_time']})
        action.save(context.session)

    return event_ref


@pick_context_manager_reader
def action_events_get(context, action_id):
    """Get the events by action id."""
    events = model_query(context, models.InstanceActionEvent).\
        filter_by(action_id=action_id).\
        order_by(expression.desc("created_at"), expression.desc("id")).\
        all()

    return events


@pick_context_manager_reader
def action_event_get_by_id(context, action_id, event_id):
    event = model_query(context, models.InstanceActionEvent).\
                        filter_by(action_id=action_id).\
                        filter_by(id=event_id).\
                        first()

    return event


##################


@require_context
@pick_context_manager_writer
def ec2_instance_create(context, instance_uuid, id=None):
    """Create the EC2 ID to instance UUID mapping on demand."""
    ec2_instance_ref = models.InstanceIdMapping()
    ec2_instance_ref.update({'uuid': instance_uuid})
    if id is not None:
        ec2_instance_ref.update({'id': id})

    ec2_instance_ref.save(context.session)

    return ec2_instance_ref


@require_context
@pick_context_manager_reader
def ec2_instance_get_by_uuid(context, instance_uuid):
    """Get UUID through EC2 ID from instance_id_mappings table."""
    result = _ec2_instance_get_query(context).\
                    filter_by(uuid=instance_uuid).\
                    first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_uuid)

    return result


@require_context
@pick_context_manager_reader
def ec2_instance_get_by_id(context, instance_id):
    result = _ec2_instance_get_query(context).\
                    filter_by(id=instance_id).\
                    first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_id)

    return result


@require_context
@pick_context_manager_reader
def get_instance_uuid_by_ec2_id(context, ec2_id):
    """Get UUID through EC2 ID from instance_id_mappings table."""
    result = ec2_instance_get_by_id(context, ec2_id)
    return result['uuid']


def _ec2_instance_get_query(context):
    return model_query(context, models.InstanceIdMapping, read_deleted='yes')


##################


def _task_log_get_query(context, task_name, period_beginning,
                        period_ending, host=None, state=None):
    values = {'period_beginning': period_beginning,
              'period_ending': period_ending}
    values = convert_objects_related_datetimes(values, *values.keys())

    query = model_query(context, models.TaskLog).\
                     filter_by(task_name=task_name).\
                     filter_by(period_beginning=values['period_beginning']).\
                     filter_by(period_ending=values['period_ending'])
    if host is not None:
        query = query.filter_by(host=host)
    if state is not None:
        query = query.filter_by(state=state)
    return query


@pick_context_manager_reader
def task_log_get(context, task_name, period_beginning, period_ending, host,
                 state=None):
    return _task_log_get_query(context, task_name, period_beginning,
                               period_ending, host, state).first()


@pick_context_manager_reader
def task_log_get_all(context, task_name, period_beginning, period_ending,
                     host=None, state=None):
    return _task_log_get_query(context, task_name, period_beginning,
                               period_ending, host, state).all()


@pick_context_manager_writer
def task_log_begin_task(
    context, task_name, period_beginning, period_ending, host, task_items=None,
    message=None,
):
    """Mark a task as started for a given host/time period."""
    values = {'period_beginning': period_beginning,
              'period_ending': period_ending}
    values = convert_objects_related_datetimes(values, *values.keys())

    task = models.TaskLog()
    task.task_name = task_name
    task.period_beginning = values['period_beginning']
    task.period_ending = values['period_ending']
    task.host = host
    task.state = "RUNNING"
    if message:
        task.message = message
    if task_items:
        task.task_items = task_items
    try:
        task.save(context.session)
    except db_exc.DBDuplicateEntry:
        raise exception.TaskAlreadyRunning(task_name=task_name, host=host)


@pick_context_manager_writer
def task_log_end_task(
    context, task_name, period_beginning, period_ending, host, errors,
    message=None,
):
    """Mark a task as complete for a given host/time period."""
    values = dict(state="DONE", errors=errors)
    if message:
        values["message"] = message

    rows = _task_log_get_query(context, task_name, period_beginning,
                               period_ending, host).update(values)
    if rows == 0:
        # It's not running!
        raise exception.TaskNotRunning(task_name=task_name, host=host)


##################


def _get_tables_with_fk_to_table(table):
    """Get a list of tables that refer to the given table by foreign key (FK).

    :param table: Table object (parent) for which to find references by FK

    :returns: A list of Table objects that refer to the specified table by FK
    """
    tables = []
    for t in models.BASE.metadata.tables.values():
        for fk in t.foreign_keys:
            if fk.references(table):
                tables.append(t)
    return tables


def _get_fk_stmts(metadata, conn, table, column, records):
    """Find records related to this table by foreign key (FK) and create and
    return insert/delete statements for them.

    Logic is: find the tables that reference the table passed to this method
    and walk the tree of references by FK. As child records are found, prepend
    them to deques to execute later in a single database transaction (to avoid
    orphaning related records if any one insert/delete fails or the archive
    process is otherwise interrupted).

    :param metadata: Metadata object to use to construct a shadow Table object
    :param conn: Connection object to use to select records related by FK
    :param table: Table object (parent) for which to find references by FK
    :param column: Column object (parent) to use to select records related by
        FK
    :param records: A list of records (column values) to use to select records
        related by FK

    :returns: tuple of (insert statements, delete statements) for records
        related by FK to insert into shadow tables and delete from main tables
    """
    inserts = collections.deque()
    deletes = collections.deque()
    fk_tables = _get_tables_with_fk_to_table(table)
    for fk_table in fk_tables:
        # Create the shadow table for the referencing table.
        fk_shadow_tablename = _SHADOW_TABLE_PREFIX + fk_table.name
        try:
            fk_shadow_table = schema.Table(
                fk_shadow_tablename, metadata, autoload=True)
        except sqla_exc.NoSuchTableError:
            # No corresponding shadow table; skip it.
            continue

        # TODO(stephenfin): Drop this when we drop the table
        if fk_table.name == "dns_domains":
            # We have one table (dns_domains) where the key is called
            # "domain" rather than "id"
            fk_column = fk_table.c.domain
        else:
            fk_column = fk_table.c.id

        for fk in fk_table.foreign_keys:
            # We need to find the records in the referring (child) table that
            # correspond to the records in our (parent) table so we can archive
            # them.

            # First, select the column in the parent referenced by the child
            # table that corresponds to the parent table records that were
            # passed in.
            # Example: table = 'instances' and fk_table = 'instance_extra'
            #          fk.parent = instance_extra.instance_uuid
            #          fk.column = instances.uuid
            #          SELECT instances.uuid FROM instances, instance_extra
            #              WHERE instance_extra.instance_uuid = instances.uuid
            #              AND instance.id IN (<ids>)
            #          We need the instance uuids for the <ids> in order to
            #          look up the matching instance_extra records.
            select = sql.select([fk.column]).where(
                sql.and_(fk.parent == fk.column, column.in_(records)))
            rows = conn.execute(select).fetchall()
            p_records = [r[0] for r in rows]
            # Then, select rows in the child table that correspond to the
            # parent table records that were passed in.
            # Example: table = 'instances' and fk_table = 'instance_extra'
            #          fk.parent = instance_extra.instance_uuid
            #          fk.column = instances.uuid
            #          SELECT instance_extra.id FROM instance_extra, instances
            #              WHERE instance_extra.instance_uuid = instances.uuid
            #              AND instances.uuid IN (<uuids>)
            #          We will get the instance_extra ids we need to archive
            #          them.
            fk_select = sql.select([fk_column]).where(
                sql.and_(fk.parent == fk.column, fk.column.in_(p_records)))
            fk_rows = conn.execute(fk_select).fetchall()
            fk_records = [r[0] for r in fk_rows]
            if fk_records:
                # If we found any records in the child table, create shadow
                # table insert statements for them and prepend them to the
                # deque.
                fk_columns = [c.name for c in fk_table.c]
                fk_insert = fk_shadow_table.insert(inline=True).\
                    from_select(fk_columns, sql.select([fk_table],
                        fk_column.in_(fk_records)))
                inserts.appendleft(fk_insert)
                # Create main table delete statements and prepend them to the
                # deque.
                fk_delete = fk_table.delete().where(fk_column.in_(fk_records))
                deletes.appendleft(fk_delete)
        # Repeat for any possible nested child tables.
        i, d = _get_fk_stmts(metadata, conn, fk_table, fk_column, fk_records)
        inserts.extendleft(i)
        deletes.extendleft(d)

    return inserts, deletes


def _archive_deleted_rows_for_table(metadata, tablename, max_rows, before,
                                    task_log):
    """Move up to max_rows rows from one tables to the corresponding
    shadow table.

    Will also follow FK constraints and archive all referring rows.
    Example: archving a record from the 'instances' table will also archive
    the 'instance_extra' record before archiving the 'instances' record.

    :returns: 3-item tuple:

        - number of rows archived
        - list of UUIDs of instances that were archived
        - number of extra rows archived (due to FK constraints)
          dict of {tablename: rows_archived}
    """
    conn = metadata.bind.connect()
    # NOTE(tdurakov): table metadata should be received
    # from models, not db tables. Default value specified by SoftDeleteMixin
    # is known only by models, not DB layer.
    # IMPORTANT: please do not change source of metadata information for table.
    table = models.BASE.metadata.tables[tablename]

    shadow_tablename = _SHADOW_TABLE_PREFIX + tablename
    rows_archived = 0
    deleted_instance_uuids = []
    try:
        shadow_table = schema.Table(shadow_tablename, metadata, autoload=True)
    except sqla_exc.NoSuchTableError:
        # No corresponding shadow table; skip it.
        return rows_archived, deleted_instance_uuids, {}

    # TODO(stephenfin): Drop this when we drop the table
    if tablename == "dns_domains":
        # We have one table (dns_domains) where the key is called
        # "domain" rather than "id"
        column = table.c.domain
    else:
        column = table.c.id

    deleted_column = table.c.deleted
    columns = [c.name for c in table.c]

    select = sql.select([column],
                        deleted_column != deleted_column.default.arg)

    if tablename == "task_log" and task_log:
        # task_log table records are never deleted by anything, so we won't
        # base our select statement on the 'deleted' column status.
        select = sql.select([column])

    if before:
        if tablename != "task_log":
            select = select.where(table.c.deleted_at < before)
        elif task_log:
            # task_log table records are never deleted by anything, so we won't
            # base our select statement on the 'deleted_at' column status.
            select = select.where(table.c.updated_at < before)

    select = select.order_by(column).limit(max_rows)
    rows = conn.execute(select).fetchall()
    records = [r[0] for r in rows]

    # We will archive deleted rows for this table and also generate insert and
    # delete statements for extra rows we may archive by following FK
    # relationships. Because we are iterating over the sorted_tables (list of
    # Table objects sorted in order of foreign key dependency), new inserts and
    # deletes ("leaves") will be added to the fronts of the deques created in
    # _get_fk_stmts. This way, we make sure we delete child table records
    # before we delete their parent table records.

    # Keep track of any extra tablenames to number of rows that we archive by
    # following FK relationships.
    # {tablename: extra_rows_archived}
    extras = collections.defaultdict(int)
    if records:
        insert = shadow_table.insert(inline=True).\
                from_select(columns, sql.select([table], column.in_(records)))
        delete = table.delete().where(column.in_(records))
        # Walk FK relationships and add insert/delete statements for rows that
        # refer to this table via FK constraints. fk_inserts and fk_deletes
        # will be prepended to by _get_fk_stmts if referring rows are found by
        # FK constraints.
        fk_inserts, fk_deletes = _get_fk_stmts(
            metadata, conn, table, column, records)

        # NOTE(tssurya): In order to facilitate the deletion of records from
        # instance_mappings, request_specs and instance_group_member tables in
        # the nova_api DB, the rows of deleted instances from the instances
        # table are stored prior to their deletion. Basically the uuids of the
        # archived instances are queried and returned.
        if tablename == "instances":
            query_select = sql.select([table.c.uuid], table.c.id.in_(records))
            rows = conn.execute(query_select).fetchall()
            deleted_instance_uuids = [r[0] for r in rows]

        try:
            # Group the insert and delete in a transaction.
            with conn.begin():
                for fk_insert in fk_inserts:
                    conn.execute(fk_insert)
                for fk_delete in fk_deletes:
                    result_fk_delete = conn.execute(fk_delete)
                    extras[fk_delete.table.name] += result_fk_delete.rowcount
                conn.execute(insert)
                result_delete = conn.execute(delete)
            rows_archived += result_delete.rowcount
        except db_exc.DBReferenceError as ex:
            # A foreign key constraint keeps us from deleting some of
            # these rows until we clean up a dependent table.  Just
            # skip this table for now; we'll come back to it later.
            LOG.warning("IntegrityError detected when archiving table "
                        "%(tablename)s: %(error)s",
                        {'tablename': tablename, 'error': str(ex)})

    return rows_archived, deleted_instance_uuids, extras


def archive_deleted_rows(context=None, max_rows=None, before=None,
                         task_log=False):
    """Move up to max_rows rows from production tables to the corresponding
    shadow tables.

    :param context: nova.context.RequestContext for database access
    :param max_rows: Maximum number of rows to archive (required)
    :param before: optional datetime which when specified filters the records
        to only archive those records deleted before the given date
    :param task_log: Optional for whether to archive task_log table records
    :returns: 3-item tuple:

        - dict that maps table name to number of rows archived from that table,
          for example::

            {
                'instances': 5,
                'block_device_mapping': 5,
                'pci_devices': 2,
            }
        - list of UUIDs of instances that were archived
        - total number of rows that were archived
    """
    table_to_rows_archived = collections.defaultdict(int)
    deleted_instance_uuids = []
    total_rows_archived = 0
    meta = sa.MetaData(get_engine(use_slave=True, context=context))
    meta.reflect()
    # Get the sorted list of tables in order of foreign key dependency.
    # Process the parent tables and find their dependent records in order to
    # archive the related records in a single database transactions. The goal
    # is to avoid a situation where, for example, an 'instances' table record
    # is missing its corresponding 'instance_extra' record due to running the
    # archive_deleted_rows command with max_rows.
    for table in meta.sorted_tables:
        tablename = table.name
        rows_archived = 0
        # skip the special sqlalchemy-migrate migrate_version table and any
        # shadow tables
        # TODO(stephenfin): Drop 'migrate_version' once we remove support for
        # the legacy sqlalchemy-migrate migrations
        if (
            tablename in ('migrate_version', 'alembic_version') or
            tablename.startswith(_SHADOW_TABLE_PREFIX)
        ):
            continue

        rows_archived, _deleted_instance_uuids, extras = (
            _archive_deleted_rows_for_table(
                meta, tablename,
                max_rows=max_rows - total_rows_archived,
                before=before,
                task_log=task_log))
        total_rows_archived += rows_archived
        if tablename == 'instances':
            deleted_instance_uuids = _deleted_instance_uuids
        # Only report results for tables that had updates.
        if rows_archived:
            table_to_rows_archived[tablename] = rows_archived
            for tablename, extra_rows_archived in extras.items():
                table_to_rows_archived[tablename] += extra_rows_archived
                total_rows_archived += extra_rows_archived
        if total_rows_archived >= max_rows:
            break
    return table_to_rows_archived, deleted_instance_uuids, total_rows_archived


def _purgeable_tables(metadata):
    return [t for t in metadata.sorted_tables
            if (t.name.startswith(_SHADOW_TABLE_PREFIX) and not
                t.name.endswith('migrate_version'))]


def purge_shadow_tables(context, before_date, status_fn=None):
    engine = get_engine(context=context)
    conn = engine.connect()
    metadata = sa.MetaData()
    metadata.bind = engine
    metadata.reflect()
    total_deleted = 0

    if status_fn is None:
        status_fn = lambda m: None

    # Some things never get formally deleted, and thus deleted_at
    # is never set. So, prefer specific timestamp columns here
    # for those special cases.
    overrides = {
        'shadow_instance_actions': 'created_at',
        'shadow_instance_actions_events': 'created_at',
        'shadow_task_log': 'updated_at',
    }

    for table in _purgeable_tables(metadata):
        if before_date is None:
            col = None
        elif table.name in overrides:
            col = getattr(table.c, overrides[table.name])
        elif hasattr(table.c, 'deleted_at'):
            col = table.c.deleted_at
        elif hasattr(table.c, 'updated_at'):
            col = table.c.updated_at
        elif hasattr(table.c, 'created_at'):
            col = table.c.created_at
        else:
            status_fn(_('Unable to purge table %(table)s because it '
                        'has no timestamp column') % {
                            'table': table.name})
            continue

        if col is not None:
            delete = table.delete().where(col < before_date)
        else:
            delete = table.delete()

        deleted = conn.execute(delete)
        if deleted.rowcount > 0:
            status_fn(_('Deleted %(rows)i rows from %(table)s based on '
                        'timestamp column %(col)s') % {
                            'rows': deleted.rowcount,
                            'table': table.name,
                            'col': col is None and '(n/a)' or col.name})
        total_deleted += deleted.rowcount

    return total_deleted


####################


@pick_context_manager_reader
def pci_device_get_by_addr(context, node_id, dev_addr):
    """Get PCI device by address."""
    pci_dev_ref = model_query(context, models.PciDevice).\
                        filter_by(compute_node_id=node_id).\
                        filter_by(address=dev_addr).\
                        first()
    if not pci_dev_ref:
        raise exception.PciDeviceNotFound(node_id=node_id, address=dev_addr)
    return pci_dev_ref


@pick_context_manager_reader
def pci_device_get_by_id(context, id):
    """Get PCI device by id."""
    pci_dev_ref = model_query(context, models.PciDevice).\
                        filter_by(id=id).\
                        first()
    if not pci_dev_ref:
        raise exception.PciDeviceNotFoundById(id=id)
    return pci_dev_ref


@pick_context_manager_reader
def pci_device_get_all_by_node(context, node_id):
    """Get all PCI devices for one host."""
    return model_query(context, models.PciDevice).\
                       filter_by(compute_node_id=node_id).\
                       all()


@pick_context_manager_reader
def pci_device_get_all_by_parent_addr(context, node_id, parent_addr):
    """Get all PCI devices by parent address."""
    return model_query(context, models.PciDevice).\
                       filter_by(compute_node_id=node_id).\
                       filter_by(parent_addr=parent_addr).\
                       all()


@require_context
@pick_context_manager_reader
def pci_device_get_all_by_instance_uuid(context, instance_uuid):
    """Get PCI devices allocated to instance."""
    return model_query(context, models.PciDevice).\
                       filter_by(status='allocated').\
                       filter_by(instance_uuid=instance_uuid).\
                       all()


@pick_context_manager_reader
def _instance_pcidevs_get_multi(context, instance_uuids):
    if not instance_uuids:
        return []
    return model_query(context, models.PciDevice).\
        filter_by(status='allocated').\
        filter(models.PciDevice.instance_uuid.in_(instance_uuids))


@pick_context_manager_writer
def pci_device_destroy(context, node_id, address):
    """Delete a PCI device record."""
    result = model_query(context, models.PciDevice).\
                         filter_by(compute_node_id=node_id).\
                         filter_by(address=address).\
                         soft_delete()
    if not result:
        raise exception.PciDeviceNotFound(node_id=node_id, address=address)


@pick_context_manager_writer
def pci_device_update(context, node_id, address, values):
    """Update a pci device."""
    query = model_query(context, models.PciDevice, read_deleted="no").\
                    filter_by(compute_node_id=node_id).\
                    filter_by(address=address)
    if query.update(values) == 0:
        device = models.PciDevice()
        device.update(values)
        context.session.add(device)
    return query.one()


####################


@pick_context_manager_writer
def instance_tag_add(context, instance_uuid, tag):
    """Add tag to the instance."""
    tag_ref = models.Tag()
    tag_ref.resource_id = instance_uuid
    tag_ref.tag = tag

    try:
        _check_instance_exists_in_project(context, instance_uuid)
        with get_context_manager(context).writer.savepoint.using(context):
            context.session.add(tag_ref)
    except db_exc.DBDuplicateEntry:
        # NOTE(snikitin): We should ignore tags duplicates
        pass

    return tag_ref


@pick_context_manager_writer
def instance_tag_set(context, instance_uuid, tags):
    """Replace all of the instance tags with specified list of tags."""
    _check_instance_exists_in_project(context, instance_uuid)

    existing = context.session.query(models.Tag.tag).filter_by(
        resource_id=instance_uuid).all()

    existing = set(row.tag for row in existing)
    tags = set(tags)
    to_delete = existing - tags
    to_add = tags - existing

    if to_delete:
        context.session.query(models.Tag).filter_by(
            resource_id=instance_uuid).filter(
            models.Tag.tag.in_(to_delete)).delete(
            synchronize_session=False)

    if to_add:
        data = [
            {'resource_id': instance_uuid, 'tag': tag} for tag in to_add]
        context.session.execute(models.Tag.__table__.insert(None), data)

    return context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid).all()


@pick_context_manager_reader
def instance_tag_get_by_instance_uuid(context, instance_uuid):
    """Get all tags for a given instance."""
    _check_instance_exists_in_project(context, instance_uuid)
    return context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid).all()


@pick_context_manager_writer
def instance_tag_delete(context, instance_uuid, tag):
    """Delete specified tag from the instance."""
    _check_instance_exists_in_project(context, instance_uuid)
    result = context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid, tag=tag).delete()

    if not result:
        raise exception.InstanceTagNotFound(instance_id=instance_uuid,
                                            tag=tag)


@pick_context_manager_writer
def instance_tag_delete_all(context, instance_uuid):
    """Delete all tags from the instance."""
    _check_instance_exists_in_project(context, instance_uuid)
    context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid).delete()


@pick_context_manager_reader
def instance_tag_exists(context, instance_uuid, tag):
    """Check if specified tag exist on the instance."""
    _check_instance_exists_in_project(context, instance_uuid)
    q = context.session.query(models.Tag).filter_by(
        resource_id=instance_uuid, tag=tag)
    return context.session.query(q.exists()).scalar()


####################


@pick_context_manager_writer
def console_auth_token_create(context, values):
    """Create a console authorization."""
    instance_uuid = values.get('instance_uuid')
    _check_instance_exists_in_project(context, instance_uuid)
    token_ref = models.ConsoleAuthToken()
    token_ref.update(values)
    context.session.add(token_ref)
    return token_ref


@pick_context_manager_reader
def console_auth_token_get_valid(context, token_hash, instance_uuid=None):
    """Get a valid console authorization by token_hash and instance_uuid.

    The console authorizations expire at the time specified by their
    'expires' column. An expired console auth token will not be returned
    to the caller - it is treated as if it does not exist.

    If instance_uuid is specified, the token is validated against both
    expiry and instance_uuid.

    If instance_uuid is not specified, the token is validated against
    expiry only.
    """
    if instance_uuid is not None:
        _check_instance_exists_in_project(context, instance_uuid)
    query = context.session.query(models.ConsoleAuthToken).\
        filter_by(token_hash=token_hash)
    if instance_uuid is not None:
        query = query.filter_by(instance_uuid=instance_uuid)
    return query.filter(
        models.ConsoleAuthToken.expires > timeutils.utcnow_ts()).first()


@pick_context_manager_writer
def console_auth_token_destroy_all_by_instance(context, instance_uuid):
    """Delete all console authorizations belonging to the instance."""
    context.session.query(models.ConsoleAuthToken).\
        filter_by(instance_uuid=instance_uuid).delete()


@pick_context_manager_writer
def console_auth_token_destroy_expired(context):
    """Delete expired console authorizations.

    The console authorizations expire at the time specified by their
    'expires' column. This function is used to garbage collect expired tokens.
    """
    context.session.query(models.ConsoleAuthToken).\
        filter(models.ConsoleAuthToken.expires <= timeutils.utcnow_ts()).\
        delete()


@pick_context_manager_writer
def console_auth_token_destroy_expired_by_host(context, host):
    """Delete expired console authorizations belonging to the host.

    The console authorizations expire at the time specified by their
    'expires' column. This function is used to garbage collect expired
    tokens associated with the given host.
    """
    context.session.query(models.ConsoleAuthToken).\
        filter_by(host=host).\
        filter(models.ConsoleAuthToken.expires <= timeutils.utcnow_ts()).\
        delete()
