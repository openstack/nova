# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import uuid

from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import joinedload_all
from sqlalchemy.sql.expression import asc
from sqlalchemy.sql.expression import desc
from sqlalchemy.sql import func

from nova import block_device
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common.db.sqlalchemy import session as db_session
from nova.openstack.common.db.sqlalchemy import utils as sqlalchemyutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils

db_opts = [
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
               default='',
               help='When set, compute API will consider duplicate hostnames '
                    'invalid within the specified scope, regardless of case. '
                    'Should be empty, "project" or "global".'),
]

CONF = cfg.CONF
CONF.register_opts(db_opts)
CONF.import_opt('compute_topic', 'nova.compute.rpcapi')
CONF.import_opt('sql_connection',
                'nova.openstack.common.db.sqlalchemy.session')

LOG = logging.getLogger(__name__)

get_session = db_session.get_session


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if is_user_context(context):
        if not context.project_id:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if is_user_context(context):
        if not context.user_id:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def authorize_quota_class_context(context, class_name):
    """Ensures a request has permission to access the given quota class."""
    if is_user_context(context):
        if not context.quota_class:
            raise exception.NotAuthorized()
        elif context.quota_class != class_name:
            raise exception.NotAuthorized()


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        context = args[0]
        if not context.is_admin:
            raise exception.AdminRequired()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        context = args[0]
        if not context.is_admin and not is_user_context(context):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def require_instance_exists_using_uuid(f):
    """Decorator to require the specified instance to exist.

    Requires the wrapped function to use context and instance_uuid as
    their first two arguments.
    """
    @functools.wraps(f)
    def wrapper(context, instance_uuid, *args, **kwargs):
        db.instance_get_by_uuid(context, instance_uuid)
        return f(context, instance_uuid, *args, **kwargs)

    return wrapper


def require_aggregate_exists(f):
    """Decorator to require the specified aggregate to exist.

    Requires the wrapped function to use context and aggregate_id as
    their first two arguments.
    """

    @functools.wraps(f)
    def wrapper(context, aggregate_id, *args, **kwargs):
        db.aggregate_get(context, aggregate_id)
        return f(context, aggregate_id, *args, **kwargs)
    return wrapper


def model_query(context, model, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id. If set to 'allow_none',
            restriction includes project_id = None.
    :param base_model: Where model_query is passed a "model" parameter which is
            not a subclass of NovaBase, we should pass an extra base_model
            parameter that is a subclass of NovaBase and corresponds to the
            model parameter.
    """
    session = kwargs.get('session') or get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only', False)

    def issubclassof_nova_base(obj):
        return isinstance(obj, type) and issubclass(obj, models.NovaBase)

    base_model = model
    if not issubclassof_nova_base(base_model):
        base_model = kwargs.get('base_model', None)
        if not issubclassof_nova_base(base_model):
            raise Exception(_("model or base_model parameter should be "
                              "subclass of NovaBase"))

    query = session.query(model, *args)

    default_deleted_value = base_model.__mapper__.c.deleted.default.arg
    if read_deleted == 'no':
        query = query.filter(base_model.deleted == default_deleted_value)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter(base_model.deleted != default_deleted_value)
    else:
        raise Exception(_("Unrecognized read_deleted value '%s'")
                            % read_deleted)

    if is_user_context(context) and project_only:
        if project_only == 'allow_none':
            query = query.\
                filter(or_(base_model.project_id == context.project_id,
                           base_model.project_id == None))
        else:
            query = query.filter_by(project_id=context.project_id)

    return query


def exact_filter(query, model, filters, legal_keys):
    """Applies exact match filtering to a query.

    Returns the updated query.  Modifies filters argument to remove
    filters consumed.

    :param query: query to apply filters to
    :param model: model object the query applies to, for IN-style
                  filtering
    :param filters: dictionary of filters; values that are lists,
                    tuples, sets, or frozensets cause an 'IN' test to
                    be performed, while exact matching ('==' operator)
                    is used for other values
    :param legal_keys: list of keys to apply exact filtering to
    """

    filter_dict = {}

    # Walk through all the keys
    for key in legal_keys:
        # Skip ones we're not filtering on
        if key not in filters:
            continue

        # OK, filtering on this key; what value do we search for?
        value = filters.pop(key)

        if key == 'metadata':
            column_attr = getattr(model, key)
            if isinstance(value, list):
                for item in value:
                    for k, v in item.iteritems():
                        query = query.filter(column_attr.any(key=k))
                        query = query.filter(column_attr.any(value=v))

            else:
                for k, v in value.iteritems():
                    query = query.filter(column_attr.any(key=k))
                    query = query.filter(column_attr.any(value=v))
        elif isinstance(value, (list, tuple, set, frozenset)):
            # Looking for values in a list; apply to query directly
            column_attr = getattr(model, key)
            query = query.filter(column_attr.in_(value))
        else:
            # OK, simple exact match; save for later
            filter_dict[key] = value

    # Apply simple exact matches
    if filter_dict:
        query = query.filter_by(**filter_dict)

    return query


def convert_datetimes(values, *datetime_keys):
    for key in values:
        if key in datetime_keys and isinstance(values[key], basestring):
            values[key] = timeutils.parse_strtime(values[key])
    return values

###################


def constraint(**conditions):
    return Constraint(conditions)


def equal_any(*values):
    return EqualityCondition(values)


def not_equal(*values):
    return InequalityCondition(values)


class Constraint(object):

    def __init__(self, conditions):
        self.conditions = conditions

    def apply(self, model, query):
        for key, condition in self.conditions.iteritems():
            for clause in condition.clauses(getattr(model, key)):
                query = query.filter(clause)
        return query


class EqualityCondition(object):

    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        return or_([field == value for value in self.values])


class InequalityCondition(object):

    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        return [field != value for value in self.values]


###################


@require_admin_context
def service_destroy(context, service_id):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.soft_delete(session=session)

        if (service_ref.topic == CONF.compute_topic and
            service_ref.compute_node):
            for c in service_ref.compute_node:
                c.soft_delete(session=session)


@require_admin_context
def service_get(context, service_id, session=None):
    result = model_query(context, models.Service, session=session).\
                     options(joinedload('compute_node')).\
                     filter_by(id=service_id).\
                     first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@require_admin_context
def service_get_all(context, disabled=None):
    query = model_query(context, models.Service)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(topic=topic).\
                all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(host=host).\
                filter_by(topic=topic).\
                first()


@require_admin_context
def service_get_all_by_host(context, host):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(host=host).\
                all()


@require_admin_context
def service_get_by_compute_host(context, host):
    result = model_query(context, models.Service, read_deleted="no").\
                options(joinedload('compute_node')).\
                filter_by(host=host).\
                filter_by(topic=CONF.compute_topic).\
                first()

    if not result:
        raise exception.ComputeHostNotFound(host=host)

    return result


@require_admin_context
def service_get_by_args(context, host, binary):
    result = model_query(context, models.Service).\
                     filter_by(host=host).\
                     filter_by(binary=binary).\
                     first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not CONF.enable_new_services:
        service_ref.disabled = True
    service_ref.save()
    return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.update(values)
        service_ref.save(session=session)
    return service_ref


###################

def compute_node_get(context, compute_id):
    return _compute_node_get(context, compute_id)


def _compute_node_get(context, compute_id, session=None):
    result = model_query(context, models.ComputeNode, session=session).\
            filter_by(id=compute_id).\
            options(joinedload('service')).\
            options(joinedload('stats')).\
            first()

    if not result:
        raise exception.ComputeHostNotFound(host=compute_id)

    return result


@require_admin_context
def compute_node_get_all(context):
    return model_query(context, models.ComputeNode).\
            options(joinedload('service')).\
            options(joinedload('stats')).\
            all()


@require_admin_context
def compute_node_search_by_hypervisor(context, hypervisor_match):
    field = models.ComputeNode.hypervisor_hostname
    return model_query(context, models.ComputeNode).\
            options(joinedload('service')).\
            filter(field.like('%%%s%%' % hypervisor_match)).\
            all()


def _prep_stats_dict(values):
    """Make list of ComputeNodeStats."""
    stats = []
    d = values.get('stats', {})
    for k, v in d.iteritems():
        stat = models.ComputeNodeStat()
        stat['key'] = k
        stat['value'] = v
        stats.append(stat)
    values['stats'] = stats


@require_admin_context
def compute_node_create(context, values):
    """Creates a new ComputeNode and populates the capacity fields
    with the most recent data."""
    _prep_stats_dict(values)
    convert_datetimes(values, 'created_at', 'deleted_at', 'updated_at')

    compute_node_ref = models.ComputeNode()
    compute_node_ref.update(values)
    compute_node_ref.save()
    return compute_node_ref


def _update_stats(context, new_stats, compute_id, session, prune_stats=False):

    existing = model_query(context, models.ComputeNodeStat, session=session,
            read_deleted="no").filter_by(compute_node_id=compute_id).all()
    statmap = {}
    for stat in existing:
        key = stat['key']
        statmap[key] = stat

    stats = []
    for k, v in new_stats.iteritems():
        old_stat = statmap.pop(k, None)
        if old_stat:
            # update existing value:
            old_stat.update({'value': v})
            stats.append(old_stat)
        else:
            # add new stat:
            stat = models.ComputeNodeStat()
            stat['compute_node_id'] = compute_id
            stat['key'] = k
            stat['value'] = v
            stats.append(stat)

    if prune_stats:
        # prune un-touched old stats:
        for stat in statmap.values():
            session.add(stat)
            stat.soft_delete(session=session)

    # add new and updated stats
    for stat in stats:
        session.add(stat)


@require_admin_context
def compute_node_update(context, compute_id, values, prune_stats=False):
    """Updates the ComputeNode record with the most recent data."""
    stats = values.pop('stats', {})

    session = get_session()
    with session.begin():
        _update_stats(context, stats, compute_id, session, prune_stats)
        compute_ref = _compute_node_get(context, compute_id, session=session)
        convert_datetimes(values, 'created_at', 'deleted_at', 'updated_at')
        compute_ref.update(values)
    return compute_ref


def compute_node_get_by_host(context, host):
    """Get all capacity entries for the given host."""
    result = model_query(context, models.ComputeNode, read_deleted="no").\
            join('service').\
            filter(models.Service.host == host).\
            first()
    return result


def compute_node_statistics(context):
    """Compute statistics over all compute nodes."""
    result = model_query(context,
                         func.count(models.ComputeNode.id),
                         func.sum(models.ComputeNode.vcpus),
                         func.sum(models.ComputeNode.memory_mb),
                         func.sum(models.ComputeNode.local_gb),
                         func.sum(models.ComputeNode.vcpus_used),
                         func.sum(models.ComputeNode.memory_mb_used),
                         func.sum(models.ComputeNode.local_gb_used),
                         func.sum(models.ComputeNode.free_ram_mb),
                         func.sum(models.ComputeNode.free_disk_gb),
                         func.sum(models.ComputeNode.current_workload),
                         func.sum(models.ComputeNode.running_vms),
                         func.sum(models.ComputeNode.disk_available_least),
                         base_model=models.ComputeNode,
                         read_deleted="no").first()

    # Build a dict of the info--making no assumptions about result
    fields = ('count', 'vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
              'memory_mb_used', 'local_gb_used', 'free_ram_mb', 'free_disk_gb',
              'current_workload', 'running_vms', 'disk_available_least')
    return dict((field, int(result[idx] or 0))
                for idx, field in enumerate(fields))


###################


@require_admin_context
def certificate_get(context, certificate_id):
    result = model_query(context, models.Certificate).\
                     filter_by(id=certificate_id).\
                     first()

    if not result:
        raise exception.CertificateNotFound(certificate_id=certificate_id)

    return result


@require_admin_context
def certificate_create(context, values):
    certificate_ref = models.Certificate()
    for (key, value) in values.iteritems():
        certificate_ref[key] = value
    certificate_ref.save()
    return certificate_ref


@require_admin_context
def certificate_get_all_by_project(context, project_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()


@require_admin_context
def certificate_get_all_by_user(context, user_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   all()


@require_admin_context
def certificate_get_all_by_user_and_project(context, user_id, project_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   all()


###################


@require_context
def floating_ip_get(context, id):
    result = model_query(context, models.FloatingIp, project_only=True).\
                 filter_by(id=id).\
                 options(joinedload_all('fixed_ip.instance')).\
                 first()

    if not result:
        raise exception.FloatingIpNotFound(id=id)

    return result


@require_context
def floating_ip_get_pools(context):
    pools = []
    for result in model_query(context, models.FloatingIp.pool,
                              base_model=models.FloatingIp).distinct():
        pools.append({'name': result[0]})
    return pools


@require_context
def floating_ip_allocate_address(context, project_id, pool):
    authorize_project_context(context, project_id)
    session = get_session()
    with session.begin():
        floating_ip_ref = model_query(context, models.FloatingIp,
                                      session=session, read_deleted="no").\
                                  filter_by(fixed_ip_id=None).\
                                  filter_by(project_id=None).\
                                  filter_by(pool=pool).\
                                  with_lockmode('update').\
                                  first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not floating_ip_ref:
            raise exception.NoMoreFloatingIps()
        floating_ip_ref['project_id'] = project_id
        session.add(floating_ip_ref)
    return floating_ip_ref['address']


@require_context
def floating_ip_bulk_create(context, ips):
    existing_ips = {}
    for floating in _floating_ip_get_all(context).all():
        existing_ips[floating['address']] = floating

    session = get_session()
    with session.begin():
        for ip in ips:
            addr = ip['address']
            if (addr in existing_ips and
                ip.get('id') != existing_ips[addr]['id']):
                raise exception.FloatingIpExists(**dict(existing_ips[addr]))

            model = models.FloatingIp()
            model.update(ip)
            session.add(model)


def _ip_range_splitter(ips, block_size=256):
    """Yields blocks of IPs no more than block_size elements long."""
    out = []
    count = 0
    for ip in ips:
        out.append(ip['address'])
        count += 1

        if count > block_size - 1:
            yield out
            out = []
            count = 0

    if out:
        yield out


@require_context
def floating_ip_bulk_destroy(context, ips):
    session = get_session()
    with session.begin():
        for ip_block in _ip_range_splitter(ips):
            model_query(context, models.FloatingIp).\
                filter(models.FloatingIp.address.in_(ip_block)).\
                soft_delete(synchronize_session='fetch')


@require_context
def floating_ip_create(context, values, session=None):
    if not session:
        session = get_session()

    floating_ip_ref = models.FloatingIp()
    floating_ip_ref.update(values)

    # check uniqueness for not deleted addresses
    if not floating_ip_ref.deleted:
        try:
            floating_ip = _floating_ip_get_by_address(context,
                                                      floating_ip_ref.address,
                                                      session)
        except exception.FloatingIpNotFoundForAddress:
            pass
        else:
            if floating_ip.id != floating_ip_ref.id:
                raise exception.FloatingIpExists(**dict(floating_ip_ref))

    floating_ip_ref.save(session=session)
    return floating_ip_ref['address']


@require_context
def floating_ip_count_by_project(context, project_id, session=None):
    authorize_project_context(context, project_id)
    # TODO(tr3buchet): why leave auto_assigned floating IPs out?
    return model_query(context, models.FloatingIp, read_deleted="no",
                       session=session).\
                   filter_by(project_id=project_id).\
                   filter_by(auto_assigned=False).\
                   count()


@require_context
def floating_ip_fixed_ip_associate(context, floating_address,
                                   fixed_address, host):
    session = get_session()
    with session.begin():
        floating_ip_ref = _floating_ip_get_by_address(context,
                                                      floating_address,
                                                      session=session)
        fixed_ip_ref = model_query(context, models.FixedIp, session=session).\
                         filter_by(address=fixed_address).\
                         options(joinedload('network')).\
                         first()
        if floating_ip_ref.fixed_ip_id == fixed_ip_ref["id"]:
            return None
        floating_ip_ref.fixed_ip_id = fixed_ip_ref["id"]
        floating_ip_ref.host = host
        floating_ip_ref.save(session=session)
        return fixed_ip_ref


@require_context
def floating_ip_deallocate(context, address):
    model_query(context, models.FloatingIp).\
            filter_by(address=address).\
            update({'project_id': None,
                    'host': None,
                    'auto_assigned': False})


@require_context
def floating_ip_destroy(context, address):
    model_query(context, models.FloatingIp).\
            filter_by(address=address).\
            delete()


@require_context
def floating_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = model_query(context,
                                      models.FloatingIp,
                                      session=session).\
                            filter_by(address=address).\
                            first()
        if not floating_ip_ref:
            raise exception.FloatingIpNotFoundForAddress(address=address)

        fixed_ip_ref = model_query(context, models.FixedIp, session=session).\
                            filter_by(id=floating_ip_ref['fixed_ip_id']).\
                            options(joinedload('network')).\
                            first()
        floating_ip_ref.fixed_ip_id = None
        floating_ip_ref.host = None
        floating_ip_ref.save(session=session)
    return fixed_ip_ref


@require_context
def floating_ip_set_auto_assigned(context, address):
    model_query(context, models.FloatingIp).\
            filter_by(address=address).\
            update({'auto_assigned': True})


def _floating_ip_get_all(context, session=None):
    return model_query(context, models.FloatingIp, read_deleted="no",
                       session=session)


@require_admin_context
def floating_ip_get_all(context):
    floating_ip_refs = _floating_ip_get_all(context).all()
    if not floating_ip_refs:
        raise exception.NoFloatingIpsDefined()
    return floating_ip_refs


@require_admin_context
def floating_ip_get_all_by_host(context, host):
    floating_ip_refs = _floating_ip_get_all(context).\
                            filter_by(host=host).\
                            all()
    if not floating_ip_refs:
        raise exception.FloatingIpNotFoundForHost(host=host)
    return floating_ip_refs


@require_context
def floating_ip_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    # TODO(tr3buchet): why do we not want auto_assigned floating IPs here?
    return _floating_ip_get_all(context).\
                         filter_by(project_id=project_id).\
                         filter_by(auto_assigned=False).\
                         options(joinedload_all('fixed_ip.instance')).\
                         all()


@require_context
def floating_ip_get_by_address(context, address):
    return _floating_ip_get_by_address(context, address)


@require_context
def _floating_ip_get_by_address(context, address, session=None):

    # if address string is empty explicitly set it to None
    if not address:
        address = None

    result = model_query(context, models.FloatingIp, session=session).\
                filter_by(address=address).\
                options(joinedload_all('fixed_ip.instance')).\
                first()

    if not result:
        raise exception.FloatingIpNotFoundForAddress(address=address)

    # If the floating IP has a project ID set, check to make sure
    # the non-admin user has access.
    if result.project_id and is_user_context(context):
        authorize_project_context(context, result.project_id)

    return result


@require_context
def floating_ip_get_by_fixed_address(context, fixed_address):
    return model_query(context, models.FloatingIp).\
                       outerjoin(models.FixedIp,
                                 models.FixedIp.id ==
                                 models.FloatingIp.fixed_ip_id).\
                       filter(models.FixedIp.address == fixed_address).\
                       all()


@require_context
def floating_ip_get_by_fixed_ip_id(context, fixed_ip_id, session=None):
    if not session:
        session = get_session()

    return model_query(context, models.FloatingIp, session=session).\
                   filter_by(fixed_ip_id=fixed_ip_id).\
                   all()


@require_context
def floating_ip_update(context, address, values):
    session = get_session()
    with session.begin():
        floating_ip_ref = _floating_ip_get_by_address(context,
                                                      address,
                                                      session)
        for (key, value) in values.iteritems():
            floating_ip_ref[key] = value
        floating_ip_ref.save(session=session)


@require_context
def _dnsdomain_get(context, session, fqdomain):
    return model_query(context, models.DNSDomain,
                       session=session, read_deleted="no").\
               filter_by(domain=fqdomain).\
               with_lockmode('update').\
               first()


@require_context
def dnsdomain_get(context, fqdomain):
    session = get_session()
    with session.begin():
        return _dnsdomain_get(context, session, fqdomain)


@require_admin_context
def _dnsdomain_get_or_create(context, session, fqdomain):
    domain_ref = _dnsdomain_get(context, session, fqdomain)
    if not domain_ref:
        dns_ref = models.DNSDomain()
        dns_ref.update({'domain': fqdomain,
                        'availability_zone': None,
                        'project_id': None})
        return dns_ref

    return domain_ref


@require_admin_context
def dnsdomain_register_for_zone(context, fqdomain, zone):
    session = get_session()
    with session.begin():
        domain_ref = _dnsdomain_get_or_create(context, session, fqdomain)
        domain_ref.scope = 'private'
        domain_ref.availability_zone = zone
        domain_ref.save(session=session)


@require_admin_context
def dnsdomain_register_for_project(context, fqdomain, project):
    session = get_session()
    with session.begin():
        domain_ref = _dnsdomain_get_or_create(context, session, fqdomain)
        domain_ref.scope = 'public'
        domain_ref.project_id = project
        domain_ref.save(session=session)


@require_admin_context
def dnsdomain_unregister(context, fqdomain):
    model_query(context, models.DNSDomain).\
                 filter_by(domain=fqdomain).\
                 delete()


@require_context
def dnsdomain_list(context):
    query = model_query(context, models.DNSDomain, read_deleted="no")
    return [row.domain for row in query.all()]


###################


@require_admin_context
def fixed_ip_associate(context, address, instance_uuid, network_id=None,
                       reserved=False):
    """Keyword arguments:
    reserved -- should be a boolean value(True or False), exact value will be
    used to filter on the fixed ip address
    """
    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = model_query(context, models.FixedIp, session=session,
                                   read_deleted="no").\
                               filter(network_or_none).\
                               filter_by(reserved=reserved).\
                               filter_by(address=address).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if fixed_ip_ref is None:
            raise exception.FixedIpNotFoundForNetwork(address=address,
                                            network_uuid=network_id)
        if fixed_ip_ref.instance_uuid:
            raise exception.FixedIpAlreadyInUse(address=address,
                                                instance_uuid=instance_uuid)

        if not fixed_ip_ref.network_id:
            fixed_ip_ref.network_id = network_id
        fixed_ip_ref.instance_uuid = instance_uuid
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_admin_context
def fixed_ip_associate_pool(context, network_id, instance_uuid=None,
                            host=None):
    if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = model_query(context, models.FixedIp, session=session,
                                   read_deleted="no").\
                               filter(network_or_none).\
                               filter_by(reserved=False).\
                               filter_by(instance_uuid=None).\
                               filter_by(host=None).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise exception.NoMoreFixedIps()

        if fixed_ip_ref['network_id'] is None:
            fixed_ip_ref['network'] = network_id

        if instance_uuid:
            fixed_ip_ref['instance_uuid'] = instance_uuid

        if host:
            fixed_ip_ref['host'] = host
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_context
def fixed_ip_create(context, values):
    fixed_ip_ref = models.FixedIp()
    fixed_ip_ref.update(values)
    fixed_ip_ref.save()
    return fixed_ip_ref['address']


@require_context
def fixed_ip_bulk_create(context, ips):
    session = get_session()
    with session.begin():
        for ip in ips:
            model = models.FixedIp()
            model.update(ip)
            session.add(model)


@require_context
def fixed_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               address,
                                               session=session)
        fixed_ip_ref['instance_uuid'] = None
        fixed_ip_ref.save(session=session)


@require_admin_context
def fixed_ip_disassociate_all_by_timeout(context, host, time):
    session = get_session()
    # NOTE(vish): only update fixed ips that "belong" to this
    #             host; i.e. the network host or the instance
    #             host matches. Two queries necessary because
    #             join with update doesn't work.
    with session.begin():
        host_filter = or_(and_(models.Instance.host == host,
                               models.Network.multi_host == True),
                          models.Network.host == host)
        result = model_query(context, models.FixedIp.id,
                             base_model=models.FixedIp, read_deleted="no",
                             session=session).\
                filter(models.FixedIp.allocated == False).\
                filter(models.FixedIp.updated_at < time).\
                join((models.Network,
                      models.Network.id == models.FixedIp.network_id)).\
                join((models.Instance,
                      models.Instance.uuid == models.FixedIp.instance_uuid)).\
                filter(host_filter).\
                all()
        fixed_ip_ids = [fip[0] for fip in result]
        if not fixed_ip_ids:
            return 0
        result = model_query(context, models.FixedIp, session=session).\
                             filter(models.FixedIp.id.in_(fixed_ip_ids)).\
                             update({'instance_uuid': None,
                                     'leased': False,
                                     'updated_at': timeutils.utcnow()},
                                    synchronize_session='fetch')
        return result


@require_context
def fixed_ip_get(context, id, get_network=False):
    query = model_query(context, models.FixedIp).filter_by(id=id)
    if get_network:
        query = query.options(joinedload('network'))
    result = query.first()
    if not result:
        raise exception.FixedIpNotFound(id=id)

    # FIXME(sirp): shouldn't we just use project_only here to restrict the
    # results?
    if is_user_context(context) and result['instance_uuid'] is not None:
        instance = instance_get_by_uuid(context.elevated(read_deleted='yes'),
                                        result['instance_uuid'])
        authorize_project_context(context, instance.project_id)

    return result


@require_admin_context
def fixed_ip_get_all(context, session=None):
    result = model_query(context, models.FixedIp, session=session,
                         read_deleted="yes").\
                     all()
    if not result:
        raise exception.NoFixedIpsDefined()

    return result


@require_context
def fixed_ip_get_by_address(context, address, session=None):
    result = model_query(context, models.FixedIp, session=session).\
                     filter_by(address=address).\
                     first()
    if not result:
        raise exception.FixedIpNotFoundForAddress(address=address)

    # NOTE(sirp): shouldn't we just use project_only here to restrict the
    # results?
    if is_user_context(context) and result['instance_uuid'] is not None:
        instance = _instance_get_by_uuid(context.elevated(read_deleted='yes'),
                                         result['instance_uuid'],
                                         session)
        authorize_project_context(context, instance.project_id)

    return result


@require_admin_context
def fixed_ip_get_by_address_detailed(context, address, session=None):
    """
    :returns: a tuple of (models.FixedIp, models.Network, models.Instance)
    """
    if not session:
        session = get_session()

    result = session.query(models.FixedIp, models.Network, models.Instance).\
        filter_by(address=address).\
        outerjoin((models.Network,
                   models.Network.id ==
                   models.FixedIp.network_id)).\
        outerjoin((models.Instance,
                   models.Instance.uuid ==
                   models.FixedIp.instance_uuid)).\
        first()

    if not result:
        raise exception.FixedIpNotFoundForAddress(address=address)

    return result


@require_context
def fixed_ip_get_by_floating_address(context, floating_address):
    return model_query(context, models.FixedIp).\
                       outerjoin(models.FloatingIp,
                                 models.FloatingIp.fixed_ip_id ==
                                 models.FixedIp.id).\
                       filter(models.FloatingIp.address == floating_address).\
                       first()
    # NOTE(tr3buchet) please don't invent an exception here, empty list is fine


@require_context
def fixed_ip_get_by_instance(context, instance_uuid):
    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(instance_uuid=instance_uuid).\
                 all()

    if not result:
        raise exception.FixedIpNotFoundForInstance(instance_uuid=instance_uuid)

    return result


@require_context
def fixed_ip_get_by_network_host(context, network_id, host):
    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(network_id=network_id).\
                 filter_by(host=host).\
                 first()

    if not result:
        raise exception.FixedIpNotFoundForNetworkHost(network_id=network_id,
                                                      host=host)
    return result


@require_context
def fixed_ips_by_virtual_interface(context, vif_id):
    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(virtual_interface_id=vif_id).\
                 all()

    return result


@require_context
def fixed_ip_update(context, address, values):
    session = get_session()
    with session.begin():
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               address,
                                               session=session)
        fixed_ip_ref.update(values)
        fixed_ip_ref.save(session=session)


###################


@require_context
def virtual_interface_create(context, values):
    """Create a new virtual interface record in the database.

    :param values: = dict containing column values
    """
    try:
        vif_ref = models.VirtualInterface()
        vif_ref.update(values)
        vif_ref.save()
    except db_session.DBError:
        raise exception.VirtualInterfaceCreateException()

    return vif_ref


@require_context
def _virtual_interface_query(context, session=None):
    return model_query(context, models.VirtualInterface, session=session,
                       read_deleted="yes")


@require_context
def virtual_interface_get(context, vif_id):
    """Gets a virtual interface from the table.

    :param vif_id: = id of the virtual interface
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(id=vif_id).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_address(context, address):
    """Gets a virtual interface from the table.

    :param address: = the address of the interface you're looking to get
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(address=address).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_uuid(context, vif_uuid):
    """Gets a virtual interface from the table.

    :param vif_uuid: the uuid of the interface you're looking to get
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(uuid=vif_uuid).\
                      first()
    return vif_ref


@require_context
@require_instance_exists_using_uuid
def virtual_interface_get_by_instance(context, instance_uuid):
    """Gets all virtual interfaces for instance.

    :param instance_uuid: = uuid of the instance to retrieve vifs for
    """
    vif_refs = _virtual_interface_query(context).\
                       filter_by(instance_uuid=instance_uuid).\
                       all()
    return vif_refs


@require_context
def virtual_interface_get_by_instance_and_network(context, instance_uuid,
                                                  network_id):
    """Gets virtual interface for instance that's associated with network."""
    vif_ref = _virtual_interface_query(context).\
                      filter_by(instance_uuid=instance_uuid).\
                      filter_by(network_id=network_id).\
                      first()
    return vif_ref


@require_context
def virtual_interface_delete(context, vif_id):
    """Delete virtual interface record from the database.

    :param vif_id: = id of vif to delete
    """
    _virtual_interface_query(context).\
                      filter_by(id=vif_id).\
                      delete()


@require_context
def virtual_interface_delete_by_instance(context, instance_uuid):
    """Delete virtual interface records that are associated
    with the instance given by instance_id.

    :param instance_uuid: = uuid of instance
    """
    _virtual_interface_query(context).\
           filter_by(instance_uuid=instance_uuid).\
           delete()


@require_context
def virtual_interface_get_all(context):
    """Get all vifs."""
    vif_refs = _virtual_interface_query(context).all()
    return vif_refs


###################


def _metadata_refs(metadata_dict, meta_class):
    metadata_refs = []
    if metadata_dict:
        for k, v in metadata_dict.iteritems():
            metadata_ref = meta_class()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    return metadata_refs


def _validate_unique_server_name(context, session, name):
    if not CONF.osapi_compute_unique_server_name_scope:
        return

    search_opts = {'deleted': False}
    if CONF.osapi_compute_unique_server_name_scope == 'project':
        search_opts['project_id'] = context.project_id
        instance_list = instance_get_all_by_filters(context, search_opts,
                                                    'created_at', 'desc',
                                                    session=session)
    elif CONF.osapi_compute_unique_server_name_scope == 'global':
        instance_list = instance_get_all_by_filters(context.elevated(),
                                                    search_opts,
                                                    'created_at', 'desc',
                                                    session=session)
    else:
        msg = _('Unknown osapi_compute_unique_server_name_scope value: %s'
                ' Flag must be empty, "global" or'
                ' "project"') % CONF.osapi_compute_unique_server_name_scope
        LOG.warn(msg)
        return

    lowername = name.lower()
    for instance in instance_list:
        if instance['hostname'].lower() == lowername:
            raise exception.InstanceExists(name=instance['hostname'])


@require_context
def instance_create(context, values):
    """Create a new Instance record in the database.

    context - request context object
    values - dict containing column values.
    """
    values = values.copy()
    values['metadata'] = _metadata_refs(
            values.get('metadata'), models.InstanceMetadata)

    values['system_metadata'] = _metadata_refs(
            values.get('system_metadata'), models.InstanceSystemMetadata)

    instance_ref = models.Instance()
    if not values.get('uuid'):
        values['uuid'] = str(uuid.uuid4())
    instance_ref['info_cache'] = models.InstanceInfoCache()
    info_cache = values.pop('info_cache', None)
    if info_cache is not None:
        instance_ref['info_cache'].update(info_cache)
    security_groups = values.pop('security_groups', [])
    instance_ref.update(values)

    def _get_sec_group_models(session, security_groups):
        models = []
        _existed, default_group = security_group_ensure_default(context,
            session=session)
        if 'default' in security_groups:
            models.append(default_group)
            # Generate a new list, so we don't modify the original
            security_groups = [x for x in security_groups if x != 'default']
        if security_groups:
            models.extend(_security_group_get_by_names(context,
                    session, context.project_id, security_groups))
        return models

    session = get_session()
    with session.begin():
        if 'hostname' in values:
            _validate_unique_server_name(context, session, values['hostname'])
        instance_ref.security_groups = _get_sec_group_models(session,
                security_groups)
        instance_ref.save(session=session)
        # NOTE(comstud): This forces instance_type to be loaded so it
        # exists in the ref when we return.  Fixes lazy loading issues.
        instance_ref.instance_type

    # create the instance uuid to ec2_id mapping entry for instance
    db.ec2_instance_create(context, instance_ref['uuid'])

    return instance_ref


@require_admin_context
def instance_data_get_for_project(context, project_id, session=None):
    result = model_query(context,
                         func.count(models.Instance.id),
                         func.sum(models.Instance.vcpus),
                         func.sum(models.Instance.memory_mb),
                         base_model=models.Instance,
                         session=session).\
                     filter_by(project_id=project_id).\
                     first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0, result[2] or 0)


@require_context
def instance_destroy(context, instance_uuid, constraint=None):
    session = get_session()
    with session.begin():
        if uuidutils.is_uuid_like(instance_uuid):
            instance_ref = _instance_get_by_uuid(context, instance_uuid,
                    session=session)
        else:
            raise exception.InvalidUUID(instance_uuid)

        query = session.query(models.Instance).\
                        filter_by(uuid=instance_uuid)
        if constraint is not None:
            query = constraint.apply(models.Instance, query)
        count = query.soft_delete()
        if count == 0:
            raise exception.ConstraintNotMet()
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_uuid=instance_uuid).\
                soft_delete()

        session.query(models.InstanceInfoCache).\
                 filter_by(instance_uuid=instance_uuid).\
                 soft_delete()
    return instance_ref


@require_context
def instance_get_by_uuid(context, uuid):
    return _instance_get_by_uuid(context, uuid)


@require_context
def _instance_get_by_uuid(context, uuid, session=None):
    result = _build_instance_get(context, session=session).\
                filter_by(uuid=uuid).\
                first()

    if not result:
        raise exception.InstanceNotFound(instance_id=uuid)

    return result


@require_context
def instance_get(context, instance_id):
    result = _build_instance_get(context).\
                filter_by(id=instance_id).\
                first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_id)

    return result


@require_context
def _build_instance_get(context, session=None):
    return model_query(context, models.Instance, session=session,
                        project_only=True).\
            options(joinedload_all('security_groups.rules')).\
            options(joinedload('info_cache')).\
            options(joinedload('metadata')).\
            options(joinedload('instance_type')).\
            options(joinedload('system_metadata'))


@require_context
def instance_get_all(context, columns_to_join=None):
    if columns_to_join is None:
        columns_to_join = ['info_cache', 'security_groups',
                           'metadata', 'instance_type']
    query = model_query(context, models.Instance)
    for column in columns_to_join:
        query = query.options(joinedload(column))
    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            query = query.filter_by(project_id=context.project_id)
        else:
            query = query.filter_by(user_id=context.user_id)
    return query.all()


@require_context
def instance_get_all_by_filters(context, filters, sort_key, sort_dir,
                                limit=None, marker=None, session=None):
    """Return instances that match all filters.  Deleted instances
    will be returned by default, unless there's a filter that says
    otherwise"""

    sort_fn = {'desc': desc, 'asc': asc}

    if not session:
        session = get_session()

    query_prefix = session.query(models.Instance).\
            options(joinedload('info_cache')).\
            options(joinedload('security_groups')).\
            options(joinedload('system_metadata')).\
            options(joinedload('metadata')).\
            options(joinedload('instance_type')).\
            order_by(sort_fn[sort_dir](getattr(models.Instance, sort_key)))

    # Make a copy of the filters dictionary to use going forward, as we'll
    # be modifying it and we shouldn't affect the caller's use of it.
    filters = filters.copy()

    if 'changes-since' in filters:
        changes_since = timeutils.normalize_time(filters['changes-since'])
        query_prefix = query_prefix.\
                            filter(models.Instance.updated_at > changes_since)

    if 'deleted' in filters:
        # Instances can be soft or hard deleted and the query needs to
        # include or exclude both
        if filters.pop('deleted'):
            deleted = or_(models.Instance.deleted == models.Instance.id,
                          models.Instance.vm_state == vm_states.SOFT_DELETED)
            query_prefix = query_prefix.filter(deleted)
        else:
            query_prefix = query_prefix.\
                    filter_by(deleted=0).\
                    filter(models.Instance.vm_state != vm_states.SOFT_DELETED)

    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            filters['project_id'] = context.project_id
        else:
            filters['user_id'] = context.user_id

    # Filters for exact matches that we can do along with the SQL query...
    # For other filters that don't match this, we will do regexp matching
    exact_match_filter_names = ['project_id', 'user_id', 'image_ref',
                                'vm_state', 'instance_type_id', 'uuid',
                                'metadata']

    # Filter the query
    query_prefix = exact_filter(query_prefix, models.Instance,
                                filters, exact_match_filter_names)

    query_prefix = regex_filter(query_prefix, models.Instance, filters)

    # paginate query
    if marker is not None:
        try:
            marker = _instance_get_by_uuid(context, marker, session=session)
        except exception.InstanceNotFound:
            raise exception.MarkerNotFound(marker)
    query_prefix = sqlalchemyutils.paginate_query(query_prefix,
                           models.Instance, limit,
                           [sort_key, 'created_at', 'id'],
                           marker=marker,
                           sort_dir=sort_dir)

    instances = query_prefix.all()
    return instances


def regex_filter(query, model, filters):
    """Applies regular expression filtering to a query.

    Returns the updated query.

    :param query: query to apply filters to
    :param model: model object the query applies to
    :param filters: dictionary of filters with regex values
    """

    regexp_op_map = {
        'postgresql': '~',
        'mysql': 'REGEXP',
        'oracle': 'REGEXP_LIKE',
        'sqlite': 'REGEXP'
    }
    db_string = CONF.sql_connection.split(':')[0].split('+')[0]
    db_regexp_op = regexp_op_map.get(db_string, 'LIKE')
    for filter_name in filters.iterkeys():
        try:
            column_attr = getattr(model, filter_name)
        except AttributeError:
            continue
        if 'property' == type(column_attr).__name__:
            continue
        query = query.filter(column_attr.op(db_regexp_op)(
                                    str(filters[filter_name])))
    return query


@require_context
def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None, host=None):
    """Return instances and joins that were active during window."""
    session = get_session()
    query = session.query(models.Instance)

    query = query.options(joinedload('info_cache')).\
                  options(joinedload('security_groups')).\
                  options(joinedload('metadata')).\
                  options(joinedload('instance_type')).\
                  options(joinedload('system_metadata')).\
                  filter(or_(models.Instance.terminated_at == None,
                             models.Instance.terminated_at > begin))
    if end:
        query = query.filter(models.Instance.launched_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if host:
        query = query.filter_by(host=host)

    return query.all()


@require_admin_context
def _instance_get_all_query(context, project_only=False):
    return model_query(context, models.Instance, project_only=project_only).\
                   options(joinedload('info_cache')).\
                   options(joinedload('security_groups')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   options(joinedload('system_metadata'))


@require_admin_context
def instance_get_all_by_host(context, host):
    return _instance_get_all_query(context).filter_by(host=host).all()


@require_admin_context
def instance_get_all_by_host_and_node(context, host, node):
    return _instance_get_all_query(context).filter_by(host=host).\
                                            filter_by(node=node).all()


@require_admin_context
def instance_get_all_by_host_and_not_type(context, host, type_id=None):
    return _instance_get_all_query(context).filter_by(host=host).\
                   filter(models.Instance.instance_type_id != type_id).all()


@require_context
def instance_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return _instance_get_all_query(context).\
                    filter_by(project_id=project_id).\
                    all()


@require_context
def instance_get_all_by_reservation(context, reservation_id):
    return _instance_get_all_query(context, project_only=True).\
                    filter_by(reservation_id=reservation_id).\
                    all()


# NOTE(jkoelker) This is only being left here for compat with floating
#                ips. Currently the network_api doesn't return floaters
#                in network_info. Once it starts return the model. This
#                function and its call in compute/manager.py on 1829 can
#                go away
@require_context
def instance_get_floating_address(context, instance_id):
    instance = instance_get(context, instance_id)
    fixed_ips = fixed_ip_get_by_instance(context, instance['uuid'])

    if not fixed_ips:
        return None

    # NOTE(tr3buchet): this only gets the first fixed_ip
    # won't find floating ips associated with other fixed_ips
    floating_ips = floating_ip_get_by_fixed_address(context,
                                                    fixed_ips[0]['address'])
    if not floating_ips:
        return None
    # NOTE(vish): this just returns the first floating ip
    return floating_ips[0]['address']


@require_context
def instance_floating_address_get_all(context, instance_uuid):
    fixed_ips = fixed_ip_get_by_instance(context, instance_uuid)

    floating_ips = []
    for fixed_ip in fixed_ips:
        _floating_ips = floating_ip_get_by_fixed_ip_id(context,
                                                    fixed_ip['id'])
        floating_ips += _floating_ips

    return floating_ips


@require_admin_context
def instance_get_all_hung_in_rebooting(context, reboot_window):
    reboot_window = (timeutils.utcnow() -
                     datetime.timedelta(seconds=reboot_window))

    return model_query(context, models.Instance).\
            filter(models.Instance.updated_at <= reboot_window).\
            filter_by(task_state=task_states.REBOOTING).all()


@require_context
def instance_update(context, instance_uuid, values):
    instance_ref = _instance_update(context, instance_uuid, values)[1]
    return instance_ref


@require_context
def instance_update_and_get_original(context, instance_uuid, values):
    """Set the given properties on an instance and update it. Return
    a shallow copy of the original instance reference, as well as the
    updated one.

    :param context: = request context object
    :param instance_uuid: = instance uuid
    :param values: = dict containing column values

    If "expected_task_state" exists in values, the update can only happen
    when the task state before update matches expected_task_state. Otherwise
    a UnexpectedTaskStateError is thrown.

    :returns: a tuple of the form (old_instance_ref, new_instance_ref)

    Raises NotFound if instance does not exist.
    """
    return _instance_update(context, instance_uuid, values,
                            copy_old_instance=True)


# NOTE(danms): This updates the instance's metadata list in-place and in
# the database to avoid stale data and refresh issues. It assumes the
# delete=True behavior of instance_metadata_update(...)
def _instance_metadata_update_in_place(context, instance, metadata_type, model,
                                       metadata, session):
    to_delete = []
    for keyvalue in instance[metadata_type]:
        key = keyvalue['key']
        if key in metadata:
            keyvalue['value'] = metadata.pop(key)
        elif key not in metadata:
            to_delete.append(keyvalue)

    for condemned in to_delete:
        condemned.soft_delete(session=session)

    for key, value in metadata.iteritems():
        newitem = model()
        newitem.update({'key': key, 'value': value,
                        'instance_uuid': instance['uuid']})
        session.add(newitem)
        instance[metadata_type].append(newitem)


def _instance_update(context, instance_uuid, values, copy_old_instance=False):
    session = get_session()

    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(instance_uuid)

    with session.begin():
        instance_ref = _instance_get_by_uuid(context, instance_uuid,
                                             session=session)
        # TODO(deva): remove extra_specs from here after it is included
        #             in system_metadata. Until then, the baremetal driver
        #             needs extra_specs added to instance[]
        inst_type_ref = _instance_type_get_query(context, session=session).\
                            filter_by(id=instance_ref['instance_type_id']).\
                            first()
        if inst_type_ref:
            instance_ref['extra_specs'] = \
                _dict_with_extra_specs(inst_type_ref).get('extra_specs', {})
        else:
            instance_ref['extra_specs'] = {}

        if "expected_task_state" in values:
            # it is not a db column so always pop out
            expected = values.pop("expected_task_state")
            if not isinstance(expected, (tuple, list, set)):
                expected = (expected,)
            actual_state = instance_ref["task_state"]
            if actual_state not in expected:
                raise exception.UnexpectedTaskStateError(actual=actual_state,
                                                         expected=expected)

        instance_hostname = instance_ref['hostname'] or ''
        if ("hostname" in values and
                values["hostname"].lower() != instance_hostname.lower()):
                _validate_unique_server_name(context,
                                             session,
                                             values['hostname'])

        if copy_old_instance:
            old_instance_ref = copy.copy(instance_ref)
        else:
            old_instance_ref = None

        metadata = values.get('metadata')
        if metadata is not None:
            _instance_metadata_update_in_place(context, instance_ref,
                                               'metadata',
                                               models.InstanceMetadata,
                                               values.pop('metadata'),
                                               session)

        system_metadata = values.get('system_metadata')
        if system_metadata is not None:
            _instance_metadata_update_in_place(context, instance_ref,
                                               'system_metadata',
                                               models.InstanceSystemMetadata,
                                               values.pop('system_metadata'),
                                               session)

        instance_ref.update(values)
        instance_ref.save(session=session)
        if 'instance_type_id' in values:
            # NOTE(comstud): It appears that sqlalchemy doesn't refresh
            # the instance_type model after you update the ID.  You end
            # up with an instance_type model that only has 'id' updated,
            # but the rest of the model has the data from the old
            # instance_type.
            session.refresh(instance_ref['instance_type'])

    return (old_instance_ref, instance_ref)


def instance_add_security_group(context, instance_uuid, security_group_id):
    """Associate the given security group with the given instance."""
    sec_group_ref = models.SecurityGroupInstanceAssociation()
    sec_group_ref.update({'instance_uuid': instance_uuid,
                          'security_group_id': security_group_id})
    sec_group_ref.save()


@require_context
def instance_remove_security_group(context, instance_uuid, security_group_id):
    """Disassociate the given security group from the given instance."""
    model_query(context, models.SecurityGroupInstanceAssociation).\
                filter_by(instance_uuid=instance_uuid).\
                filter_by(security_group_id=security_group_id).\
                soft_delete()


###################


@require_context
def instance_info_cache_get(context, instance_uuid):
    """Gets an instance info cache from the table.

    :param instance_uuid: = uuid of the info cache's instance
    :param session: = optional session object
    """
    return model_query(context, models.InstanceInfoCache).\
                         filter_by(instance_uuid=instance_uuid).\
                         first()


@require_context
def instance_info_cache_update(context, instance_uuid, values):
    """Update an instance info cache record in the table.

    :param instance_uuid: = uuid of info cache's instance
    :param values: = dict containing column values to update
    :param session: = optional session object
    """
    session = get_session()
    with session.begin():
        info_cache = model_query(context, models.InstanceInfoCache,
                                 session=session).\
                         filter_by(instance_uuid=instance_uuid).\
                         first()

        if info_cache and not info_cache['deleted']:
            # NOTE(tr3buchet): let's leave it alone if it's already deleted
            info_cache.update(values)
        else:
            # NOTE(tr3buchet): just in case someone blows away an instance's
            #                  cache entry
            info_cache = models.InstanceInfoCache()
            info_cache.update({'instance_uuid': instance_uuid})

    return info_cache


@require_context
def instance_info_cache_delete(context, instance_uuid):
    """Deletes an existing instance_info_cache record

    :param instance_uuid: = uuid of the instance tied to the cache record
    :param session: = optional session object
    """
    model_query(context, models.InstanceInfoCache).\
                         filter_by(instance_uuid=instance_uuid).\
                         soft_delete()


###################


@require_context
def key_pair_create(context, values):
    key_pair_ref = models.KeyPair()
    key_pair_ref.update(values)
    key_pair_ref.save()
    return key_pair_ref


@require_context
def key_pair_destroy(context, user_id, name):
    authorize_user_context(context, user_id)
    model_query(context, models.KeyPair).\
             filter_by(user_id=user_id).\
             filter_by(name=name).\
             delete()


@require_context
def key_pair_get(context, user_id, name):
    authorize_user_context(context, user_id)
    result = model_query(context, models.KeyPair).\
                     filter_by(user_id=user_id).\
                     filter_by(name=name).\
                     first()

    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)

    return result


@require_context
def key_pair_get_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    return model_query(context, models.KeyPair, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   all()


def key_pair_count_by_user(context, user_id):
    authorize_user_context(context, user_id)
    return model_query(context, models.KeyPair, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   count()


###################


@require_admin_context
def network_associate(context, project_id, network_id=None, force=False):
    """Associate a project with a network.

    called by project_get_networks under certain conditions
    and network manager add_network_to_project()

    only associate if the project doesn't already have a network
    or if force is True

    force solves race condition where a fresh project has multiple instance
    builds simultaneously picked up by multiple network hosts which attempt
    to associate the project with multiple networks
    force should only be used as a direct consequence of user request
    all automated requests should not use force
    """
    session = get_session()
    with session.begin():

        def network_query(project_filter, id=None):
            filter_kwargs = {'project_id': project_filter}
            if id is not None:
                filter_kwargs['id'] = id
            return model_query(context, models.Network, session=session,
                              read_deleted="no").\
                           filter_by(**filter_kwargs).\
                           with_lockmode('update').\
                           first()

        if not force:
            # find out if project has a network
            network_ref = network_query(project_id)

        if force or not network_ref:
            # in force mode or project doesn't have a network so associate
            # with a new network

            # get new network
            network_ref = network_query(None, network_id)
            if not network_ref:
                raise db.NoMoreNetworks()

            # associate with network
            # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
            #             then this has concurrency issues
            network_ref['project_id'] = project_id
            session.add(network_ref)
    return network_ref


@require_admin_context
def _network_ips_query(context, network_id):
    return model_query(context, models.FixedIp, read_deleted="no").\
                   filter_by(network_id=network_id)


@require_admin_context
def network_count_reserved_ips(context, network_id):
    return _network_ips_query(context, network_id).\
                    filter_by(reserved=True).\
                    count()


@require_admin_context
def network_create_safe(context, values):
    if values.get('vlan'):
        if model_query(context, models.Network, read_deleted="no")\
                      .filter_by(vlan=values['vlan'])\
                      .first():
            raise exception.DuplicateVlan(vlan=values['vlan'])

    network_ref = models.Network()
    network_ref['uuid'] = str(uuid.uuid4())
    network_ref.update(values)

    try:
        network_ref.save()
        return network_ref
    except IntegrityError:
        return None


@require_admin_context
def network_delete_safe(context, network_id):
    session = get_session()
    with session.begin():
        result = model_query(context, models.FixedIp, session=session,
                             read_deleted="no").\
                         filter_by(network_id=network_id).\
                         filter_by(allocated=True).\
                         count()
        if result != 0:
            raise exception.NetworkInUse(network_id=network_id)
        network_ref = network_get(context, network_id=network_id,
                                  session=session)

        model_query(context, models.FixedIp, session=session,
                    read_deleted="no").\
                filter_by(network_id=network_id).\
                soft_delete()

        session.delete(network_ref)


@require_admin_context
def network_disassociate(context, network_id, disassociate_host,
                         disassociate_project):
    net_update = {}
    if disassociate_project:
        net_update['project_id'] = None
    if disassociate_host:
        net_update['host'] = None
    network_update(context, network_id, net_update)


@require_context
def network_get(context, network_id, session=None, project_only='allow_none'):
    result = model_query(context, models.Network, session=session,
                         project_only=project_only).\
                    filter_by(id=network_id).\
                    first()

    if not result:
        raise exception.NetworkNotFound(network_id=network_id)

    return result


@require_context
def network_get_all(context):
    result = model_query(context, models.Network, read_deleted="no").all()

    if not result:
        raise exception.NoNetworksFound()

    return result


@require_context
def network_get_all_by_uuids(context, network_uuids,
                             project_only="allow_none"):
    result = model_query(context, models.Network, read_deleted="no",
                         project_only=project_only).\
                filter(models.Network.uuid.in_(network_uuids)).\
                all()

    if not result:
        raise exception.NoNetworksFound()

    #check if the result contains all the networks
    #we are looking for
    for network_uuid in network_uuids:
        found = False
        for network in result:
            if network['uuid'] == network_uuid:
                found = True
                break
        if not found:
            if project_only:
                raise exception.NetworkNotFoundForProject(
                      network_uuid=network_uuid, project_id=context.project_id)
            raise exception.NetworkNotFound(network_id=network_uuid)

    return result

# NOTE(vish): pylint complains because of the long method name, but
#             it fits with the names of the rest of the methods
# pylint: disable=C0103


@require_admin_context
def network_get_associated_fixed_ips(context, network_id, host=None):
    # FIXME(sirp): since this returns fixed_ips, this would be better named
    # fixed_ip_get_all_by_network.
    # NOTE(vish): The ugly joins here are to solve a performance issue and
    #             should be removed once we can add and remove leases
    #             without regenerating the whole list
    vif_and = and_(models.VirtualInterface.id ==
                   models.FixedIp.virtual_interface_id,
                   models.VirtualInterface.deleted == 0)
    inst_and = and_(models.Instance.uuid == models.FixedIp.instance_uuid,
                    models.Instance.deleted == 0)
    session = get_session()
    query = session.query(models.FixedIp.address,
                          models.FixedIp.instance_uuid,
                          models.FixedIp.network_id,
                          models.FixedIp.virtual_interface_id,
                          models.VirtualInterface.address,
                          models.Instance.hostname,
                          models.Instance.updated_at,
                          models.Instance.created_at,
                          models.FixedIp.allocated,
                          models.FixedIp.leased).\
                          filter(models.FixedIp.deleted == 0).\
                          filter(models.FixedIp.network_id == network_id).\
                          filter(models.FixedIp.allocated == True).\
                          join((models.VirtualInterface, vif_and)).\
                          join((models.Instance, inst_and)).\
                          filter(models.FixedIp.instance_uuid != None).\
                          filter(models.FixedIp.virtual_interface_id != None)
    if host:
        query = query.filter(models.Instance.host == host)
    result = query.all()
    data = []
    for datum in result:
        cleaned = {}
        cleaned['address'] = datum[0]
        cleaned['instance_uuid'] = datum[1]
        cleaned['network_id'] = datum[2]
        cleaned['vif_id'] = datum[3]
        cleaned['vif_address'] = datum[4]
        cleaned['instance_hostname'] = datum[5]
        cleaned['instance_updated'] = datum[6]
        cleaned['instance_created'] = datum[7]
        cleaned['allocated'] = datum[8]
        cleaned['leased'] = datum[9]
        data.append(cleaned)
    return data


def network_in_use_on_host(context, network_id, host):
    fixed_ips = network_get_associated_fixed_ips(context, network_id, host)
    return len(fixed_ips) > 0


@require_admin_context
def _network_get_query(context, session=None):
    return model_query(context, models.Network, session=session,
                       read_deleted="no")


@require_admin_context
def network_get_by_bridge(context, bridge):
    result = _network_get_query(context).filter_by(bridge=bridge).first()

    if not result:
        raise exception.NetworkNotFoundForBridge(bridge=bridge)

    return result


@require_admin_context
def network_get_by_uuid(context, uuid):
    result = _network_get_query(context).filter_by(uuid=uuid).first()

    if not result:
        raise exception.NetworkNotFoundForUUID(uuid=uuid)

    return result


@require_admin_context
def network_get_by_cidr(context, cidr):
    result = _network_get_query(context).\
                filter(or_(models.Network.cidr == cidr,
                           models.Network.cidr_v6 == cidr)).\
                first()

    if not result:
        raise exception.NetworkNotFoundForCidr(cidr=cidr)

    return result


@require_admin_context
def network_get_by_instance(context, instance_id):
    # note this uses fixed IP to get to instance
    # only works for networks the instance has an IP from
    result = _network_get_query(context).\
                 filter_by(instance_id=instance_id).\
                 first()

    if not result:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)

    return result


@require_admin_context
def network_get_all_by_instance(context, instance_id):
    result = _network_get_query(context).\
                 filter_by(instance_id=instance_id).\
                 all()

    if not result:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)

    return result


@require_admin_context
def network_get_all_by_host(context, host):
    session = get_session()
    fixed_host_filter = or_(models.FixedIp.host == host,
                            models.Instance.host == host)
    fixed_ip_query = model_query(context, models.FixedIp.network_id,
                                 base_model=models.FixedIp,
                                 session=session).\
                     outerjoin((models.VirtualInterface,
                           models.VirtualInterface.id ==
                           models.FixedIp.virtual_interface_id)).\
                     outerjoin((models.Instance,
                           models.Instance.uuid ==
                               models.VirtualInterface.instance_uuid)).\
                     filter(fixed_host_filter)
    # NOTE(vish): return networks that have host set
    #             or that have a fixed ip with host set
    #             or that have an instance with host set
    host_filter = or_(models.Network.host == host,
                      models.Network.id.in_(fixed_ip_query.subquery()))
    return _network_get_query(context, session=session).\
                       filter(host_filter).\
                       all()


@require_admin_context
def network_set_host(context, network_id, host_id):
    session = get_session()
    with session.begin():
        network_ref = _network_get_query(context, session=session).\
                              filter_by(id=network_id).\
                              with_lockmode('update').\
                              first()

        if not network_ref:
            raise exception.NetworkNotFound(network_id=network_id)

        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not network_ref['host']:
            network_ref['host'] = host_id
            session.add(network_ref)

    return network_ref['host']


@require_context
def network_update(context, network_id, values):
    session = get_session()
    with session.begin():
        network_ref = network_get(context, network_id, session=session)
        network_ref.update(values)
        network_ref.save(session=session)
        return network_ref


###################


@require_admin_context
def iscsi_target_count_by_host(context, host):
    return model_query(context, models.IscsiTarget).\
                   filter_by(host=host).\
                   count()


@require_admin_context
def iscsi_target_create_safe(context, values):
    iscsi_target_ref = models.IscsiTarget()

    for (key, value) in values.iteritems():
        iscsi_target_ref[key] = value
    try:
        iscsi_target_ref.save()
        return iscsi_target_ref
    except IntegrityError:
        return None


###################


@require_context
def quota_get(context, project_id, resource):
    result = model_query(context, models.Quota, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     first()

    if not result:
        raise exception.ProjectQuotaNotFound(project_id=project_id)

    return result


@require_context
def quota_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.Quota, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_create(context, project_id, resource, limit):
    quota_ref = models.Quota()
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    quota_ref.save()
    return quota_ref


@require_admin_context
def quota_update(context, project_id, resource, limit):
    result = model_query(context, models.Quota, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     update({'hard_limit': limit})

    if not result:
        raise exception.ProjectQuotaNotFound(project_id=project_id)


###################


@require_context
def quota_class_get(context, class_name, resource):
    result = model_query(context, models.QuotaClass, read_deleted="no").\
                     filter_by(class_name=class_name).\
                     filter_by(resource=resource).\
                     first()

    if not result:
        raise exception.QuotaClassNotFound(class_name=class_name)

    return result


@require_context
def quota_class_get_all_by_name(context, class_name):
    authorize_quota_class_context(context, class_name)

    rows = model_query(context, models.QuotaClass, read_deleted="no").\
                   filter_by(class_name=class_name).\
                   all()

    result = {'class_name': class_name}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_class_create(context, class_name, resource, limit):
    quota_class_ref = models.QuotaClass()
    quota_class_ref.class_name = class_name
    quota_class_ref.resource = resource
    quota_class_ref.hard_limit = limit
    quota_class_ref.save()
    return quota_class_ref


@require_admin_context
def quota_class_update(context, class_name, resource, limit):
    result = model_query(context, models.QuotaClass, read_deleted="no").\
                     filter_by(class_name=class_name).\
                     filter_by(resource=resource).\
                     update({'hard_limit': limit})

    if not result:
        raise exception.QuotaClassNotFound(class_name=class_name)


###################


@require_context
def quota_usage_get(context, project_id, resource):
    result = model_query(context, models.QuotaUsage, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     first()

    if not result:
        raise exception.QuotaUsageNotFound(project_id=project_id)

    return result


@require_context
def quota_usage_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.QuotaUsage, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = dict(in_use=row.in_use, reserved=row.reserved)

    return result


@require_admin_context
def _quota_usage_create(context, project_id, resource, in_use, reserved,
                       until_refresh, session=None):
    quota_usage_ref = models.QuotaUsage()
    quota_usage_ref.project_id = project_id
    quota_usage_ref.resource = resource
    quota_usage_ref.in_use = in_use
    quota_usage_ref.reserved = reserved
    quota_usage_ref.until_refresh = until_refresh

    quota_usage_ref.save(session=session)

    return quota_usage_ref


@require_admin_context
def quota_usage_update(context, project_id, resource, **kwargs):
    updates = {}
    if 'in_use' in kwargs:
        updates['in_use'] = kwargs['in_use']
    if 'reserved' in kwargs:
        updates['reserved'] = kwargs['reserved']
    if 'until_refresh' in kwargs:
        updates['until_refresh'] = kwargs['until_refresh']

    result = model_query(context, models.QuotaUsage, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     update(updates)

    if not result:
        raise exception.QuotaUsageNotFound(project_id=project_id)


###################


@require_context
def reservation_get(context, uuid):
    result = model_query(context, models.Reservation, read_deleted="no").\
                     filter_by(uuid=uuid).\
                     first()

    if not result:
        raise exception.ReservationNotFound(uuid=uuid)

    return result


@require_admin_context
def reservation_create(context, uuid, usage, project_id, resource, delta,
                       expire, session=None):
    reservation_ref = models.Reservation()
    reservation_ref.uuid = uuid
    reservation_ref.usage_id = usage['id']
    reservation_ref.project_id = project_id
    reservation_ref.resource = resource
    reservation_ref.delta = delta
    reservation_ref.expire = expire
    reservation_ref.save(session=session)
    return reservation_ref


@require_admin_context
def reservation_destroy(context, uuid):
    result = model_query(context, models.Reservation, read_deleted="no").\
                     filter_by(uuid=uuid).\
                     delete()

    if not result:
        raise exception.ReservationNotFound(uuid=uuid)


###################


# NOTE(johannes): The quota code uses SQL locking to ensure races don't
# cause under or over counting of resources. To avoid deadlocks, this
# code always acquires the lock on quota_usages before acquiring the lock
# on reservations.

def _get_quota_usages(context, session, project_id):
    # Broken out for testability
    rows = model_query(context, models.QuotaUsage,
                       read_deleted="no",
                       session=session).\
                   filter_by(project_id=project_id).\
                   with_lockmode('update').\
                   all()
    return dict((row.resource, row) for row in rows)


@require_context
def quota_reserve(context, resources, quotas, deltas, expire,
                  until_refresh, max_age, project_id=None):
    elevated = context.elevated()
    session = get_session()
    with session.begin():

        if project_id is None:
            project_id = context.project_id

        # Get the current usages
        usages = _get_quota_usages(context, session, project_id)

        # Handle usage refresh
        work = set(deltas.keys())
        while work:
            resource = work.pop()

            # Do we need to refresh the usage?
            refresh = False
            if resource not in usages:
                usages[resource] = _quota_usage_create(elevated,
                                                      project_id,
                                                      resource,
                                                      0, 0,
                                                      until_refresh or None,
                                                      session=session)
                refresh = True
            elif usages[resource].in_use < 0:
                # Negative in_use count indicates a desync, so try to
                # heal from that...
                refresh = True
            elif usages[resource].until_refresh is not None:
                usages[resource].until_refresh -= 1
                if usages[resource].until_refresh <= 0:
                    refresh = True
            elif max_age and (usages[resource].updated_at -
                              timeutils.utcnow()).seconds >= max_age:
                refresh = True

            # OK, refresh the usage
            if refresh:
                # Grab the sync routine
                sync = resources[resource].sync

                updates = sync(elevated, project_id, session)
                for res, in_use in updates.items():
                    # Make sure we have a destination for the usage!
                    if res not in usages:
                        usages[res] = _quota_usage_create(elevated,
                                                         project_id,
                                                         res,
                                                         0, 0,
                                                         until_refresh or None,
                                                         session=session)

                    # Update the usage
                    usages[res].in_use = in_use
                    usages[res].until_refresh = until_refresh or None

                    # Because more than one resource may be refreshed
                    # by the call to the sync routine, and we don't
                    # want to double-sync, we make sure all refreshed
                    # resources are dropped from the work set.
                    work.discard(res)

                    # NOTE(Vek): We make the assumption that the sync
                    #            routine actually refreshes the
                    #            resources that it is the sync routine
                    #            for.  We don't check, because this is
                    #            a best-effort mechanism.

        # Check for deltas that would go negative
        unders = [resource for resource, delta in deltas.items()
                  if delta < 0 and
                  delta + usages[resource].in_use < 0]

        # Now, let's check the quotas
        # NOTE(Vek): We're only concerned about positive increments.
        #            If a project has gone over quota, we want them to
        #            be able to reduce their usage without any
        #            problems.
        overs = [resource for resource, delta in deltas.items()
                 if quotas[resource] >= 0 and delta >= 0 and
                 quotas[resource] < delta + usages[resource].total]

        # NOTE(Vek): The quota check needs to be in the transaction,
        #            but the transaction doesn't fail just because
        #            we're over quota, so the OverQuota raise is
        #            outside the transaction.  If we did the raise
        #            here, our usage updates would be discarded, but
        #            they're not invalidated by being over-quota.

        # Create the reservations
        if not overs:
            reservations = []
            for resource, delta in deltas.items():
                reservation = reservation_create(elevated,
                                                 str(uuid.uuid4()),
                                                 usages[resource],
                                                 project_id,
                                                 resource, delta, expire,
                                                 session=session)
                reservations.append(reservation.uuid)

                # Also update the reserved quantity
                # NOTE(Vek): Again, we are only concerned here about
                #            positive increments.  Here, though, we're
                #            worried about the following scenario:
                #
                #            1) User initiates resize down.
                #            2) User allocates a new instance.
                #            3) Resize down fails or is reverted.
                #            4) User is now over quota.
                #
                #            To prevent this, we only update the
                #            reserved value if the delta is positive.
                if delta > 0:
                    usages[resource].reserved += delta

        # Apply updates to the usages table
        for usage_ref in usages.values():
            usage_ref.save(session=session)

    if unders:
        LOG.warning(_("Change will make usage less than 0 for the following "
                      "resources: %(unders)s") % locals())
    if overs:
        usages = dict((k, dict(in_use=v['in_use'], reserved=v['reserved']))
                      for k, v in usages.items())
        raise exception.OverQuota(overs=sorted(overs), quotas=quotas,
                                  usages=usages)

    return reservations


def _quota_reservations_query(session, context, reservations):
    """Return the relevant reservations."""

    # Get the listed reservations
    return model_query(context, models.Reservation,
                       read_deleted="no",
                       session=session).\
                   filter(models.Reservation.uuid.in_(reservations)).\
                   with_lockmode('update')


@require_context
def reservation_commit(context, reservations, project_id=None):
    session = get_session()
    with session.begin():
        usages = _get_quota_usages(context, session, project_id)
        reservation_query = _quota_reservations_query(session, context,
                                                      reservations)
        for reservation in reservation_query.all():
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta
            usage.in_use += reservation.delta
        reservation_query.soft_delete(synchronize_session=False)


@require_context
def reservation_rollback(context, reservations, project_id=None):
    session = get_session()
    with session.begin():
        usages = _get_quota_usages(context, session, project_id)
        reservation_query = _quota_reservations_query(session, context,
                                                      reservations)
        for reservation in reservation_query.all():
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta
        reservation_query.soft_delete(synchronize_session=False)


@require_admin_context
def quota_destroy_all_by_project(context, project_id):
    session = get_session()
    with session.begin():
        model_query(context, models.Quota, session=session,
                    read_deleted="no").\
                filter_by(project_id=project_id).\
                soft_delete(synchronize_session=False)

        model_query(context, models.QuotaUsage,
                    session=session, read_deleted="no").\
                filter_by(project_id=project_id).\
                soft_delete(synchronize_session=False)

        model_query(context, models.Reservation,
                    session=session, read_deleted="no").\
                filter_by(project_id=project_id).\
                soft_delete(synchronize_session=False)


@require_admin_context
def reservation_expire(context):
    session = get_session()
    with session.begin():
        current_time = timeutils.utcnow()
        reservation_query = model_query(context, models.Reservation,
                                        session=session, read_deleted="no").\
                            filter(models.Reservation.expire < current_time)

        for reservation in reservation_query.join(models.QuotaUsage).all():
            if reservation.delta >= 0:
                reservation.usage.reserved -= reservation.delta
                reservation.usage.save(session=session)

        reservation_query.soft_delete(synchronize_session=False)


###################


@require_context
def _ec2_volume_get_query(context, session=None):
    return model_query(context, models.VolumeIdMapping,
                       session=session, read_deleted='yes')


@require_context
def _ec2_snapshot_get_query(context, session=None):
    return model_query(context, models.SnapshotIdMapping,
                       session=session, read_deleted='yes')


@require_admin_context
def volume_get_iscsi_target_num(context, volume_id):
    result = model_query(context, models.IscsiTarget, read_deleted="yes").\
                     filter_by(volume_id=volume_id).\
                     first()

    if not result:
        raise exception.ISCSITargetNotFoundForVolume(volume_id=volume_id)

    return result.target_num


@require_context
def ec2_volume_create(context, volume_uuid, id=None):
    """Create ec2 compatable volume by provided uuid."""
    ec2_volume_ref = models.VolumeIdMapping()
    ec2_volume_ref.update({'uuid': volume_uuid})
    if id is not None:
        ec2_volume_ref.update({'id': id})

    ec2_volume_ref.save()

    return ec2_volume_ref


@require_context
def get_ec2_volume_id_by_uuid(context, volume_id, session=None):
    result = _ec2_volume_get_query(context, session=session).\
                    filter_by(uuid=volume_id).\
                    first()

    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result['id']


@require_context
def get_volume_uuid_by_ec2_id(context, ec2_id, session=None):
    result = _ec2_volume_get_query(context, session=session).\
                    filter_by(id=ec2_id).\
                    first()

    if not result:
        raise exception.VolumeNotFound(volume_id=ec2_id)

    return result['uuid']


@require_context
def ec2_snapshot_create(context, snapshot_uuid, id=None):
    """Create ec2 compatable snapshot by provided uuid."""
    ec2_snapshot_ref = models.SnapshotIdMapping()
    ec2_snapshot_ref.update({'uuid': snapshot_uuid})
    if id is not None:
        ec2_snapshot_ref.update({'id': id})

    ec2_snapshot_ref.save()

    return ec2_snapshot_ref


@require_context
def get_ec2_snapshot_id_by_uuid(context, snapshot_id, session=None):
    result = _ec2_snapshot_get_query(context, session=session).\
                    filter_by(uuid=snapshot_id).\
                    first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result['id']


@require_context
def get_snapshot_uuid_by_ec2_id(context, ec2_id, session=None):
    result = _ec2_snapshot_get_query(context, session=session).\
                    filter_by(id=ec2_id).\
                    first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=ec2_id)

    return result['uuid']


###################


def _block_device_mapping_get_query(context, session=None):
    return model_query(context, models.BlockDeviceMapping, session=session)


@require_context
def block_device_mapping_create(context, values):
    bdm_ref = models.BlockDeviceMapping()
    bdm_ref.update(values)

    session = get_session()
    with session.begin():
        bdm_ref.save(session=session)


@require_context
def block_device_mapping_update(context, bdm_id, values):
    session = get_session()
    with session.begin():
        _block_device_mapping_get_query(context, session=session).\
                filter_by(id=bdm_id).\
                update(values)


@require_context
def block_device_mapping_update_or_create(context, values):
    session = get_session()
    with session.begin():
        result = _block_device_mapping_get_query(context, session=session).\
                 filter_by(instance_uuid=values['instance_uuid']).\
                 filter_by(device_name=values['device_name']).\
                 first()
        if not result:
            bdm_ref = models.BlockDeviceMapping()
            bdm_ref.update(values)
            bdm_ref.save(session=session)
        else:
            result.update(values)

        # NOTE(yamahata): same virtual device name can be specified multiple
        #                 times. So delete the existing ones.
        virtual_name = values['virtual_name']
        if (virtual_name is not None and
            block_device.is_swap_or_ephemeral(virtual_name)):
            session.query(models.BlockDeviceMapping).\
                filter_by(instance_uuid=values['instance_uuid']).\
                filter_by(virtual_name=virtual_name).\
                filter(models.BlockDeviceMapping.device_name !=
                       values['device_name']).\
                soft_delete()


@require_context
def block_device_mapping_get_all_by_instance(context, instance_uuid):
    return _block_device_mapping_get_query(context).\
                 filter_by(instance_uuid=instance_uuid).\
                 all()


@require_context
def block_device_mapping_destroy(context, bdm_id):
    session = get_session()
    with session.begin():
        session.query(models.BlockDeviceMapping).\
                filter_by(id=bdm_id).\
                soft_delete()


@require_context
def block_device_mapping_destroy_by_instance_and_volume(context, instance_uuid,
                                                        volume_id):
    session = get_session()
    with session.begin():
        _block_device_mapping_get_query(context, session=session).\
            filter_by(instance_uuid=instance_uuid).\
            filter_by(volume_id=volume_id).\
            soft_delete()


@require_context
def block_device_mapping_destroy_by_instance_and_device(context, instance_uuid,
                                                        device_name):
    session = get_session()
    with session.begin():
        _block_device_mapping_get_query(context, session=session).\
            filter_by(instance_uuid=instance_uuid).\
            filter_by(device_name=device_name).\
            soft_delete()


###################

def _security_group_get_query(context, session=None, read_deleted=None,
                              project_only=False, join_rules=True):
    query = model_query(context, models.SecurityGroup, session=session,
            read_deleted=read_deleted, project_only=project_only)
    if join_rules:
        query = query.options(joinedload_all('rules.grantee_group'))
    return query


def _security_group_get_by_names(context, session, project_id, group_names):
    """
    Get security group models for a project by a list of names.
    Raise SecurityGroupNotFoundForProject for a name not found.
    """
    query = _security_group_get_query(context, session=session,
            read_deleted="no", join_rules=False).\
            filter_by(project_id=project_id).\
            filter(models.SecurityGroup.name.in_(group_names))
    sg_models = query.all()
    if len(sg_models) == len(group_names):
        return sg_models
    # Find the first one missing and raise
    group_names_from_models = [x.name for x in sg_models]
    for group_name in group_names:
        if group_name not in group_names_from_models:
            raise exception.SecurityGroupNotFoundForProject(
                    project_id=project_id, security_group_id=group_name)
    # Not Reached


@require_context
def security_group_get_all(context):
    return _security_group_get_query(context).all()


@require_context
def security_group_get(context, security_group_id, session=None):
    result = _security_group_get_query(context, session=session,
                                       project_only=True).\
                    filter_by(id=security_group_id).\
                    options(joinedload_all('instances')).\
                    first()

    if not result:
        raise exception.SecurityGroupNotFound(
                security_group_id=security_group_id)

    return result


@require_context
def security_group_get_by_name(context, project_id, group_name,
        columns_to_join=None, session=None):
    if session is None:
        session = get_session()

    query = _security_group_get_query(context, session=session,
            read_deleted="no", join_rules=False).\
            filter_by(project_id=project_id).\
            filter_by(name=group_name)

    if columns_to_join is None:
        columns_to_join = ['instances', 'rules.grantee_group']

    for column in columns_to_join:
        query = query.options(joinedload_all(column))

    result = query.first()
    if not result:
        raise exception.SecurityGroupNotFoundForProject(
                project_id=project_id, security_group_id=group_name)

    return result


@require_context
def security_group_get_by_project(context, project_id):
    return _security_group_get_query(context, read_deleted="no").\
                        filter_by(project_id=project_id).\
                        all()


@require_context
def security_group_get_by_instance(context, instance_id):
    return _security_group_get_query(context, read_deleted="no").\
                   join(models.SecurityGroup.instances).\
                   filter_by(id=instance_id).\
                   all()


@require_context
def security_group_exists(context, project_id, group_name):
    try:
        group = security_group_get_by_name(context, project_id, group_name)
        return group is not None
    except exception.NotFound:
        return False


@require_context
def security_group_in_use(context, group_id):
    session = get_session()
    with session.begin():
        # Are there any instances that haven't been deleted
        # that include this group?
        inst_assoc = model_query(context,
                                 models.SecurityGroupInstanceAssociation,
                                 read_deleted="no", session=session).\
                        filter_by(security_group_id=group_id).\
                        all()
        for ia in inst_assoc:
            num_instances = model_query(context, models.Instance,
                                        session=session, read_deleted="no").\
                        filter_by(uuid=ia.instance_uuid).\
                        count()
            if num_instances:
                return True

    return False


@require_context
def security_group_create(context, values, session=None):
    security_group_ref = models.SecurityGroup()
    # FIXME(devcamcar): Unless I do this, rules fails with lazy load exception
    # once save() is called.  This will get cleaned up in next orm pass.
    security_group_ref.rules
    security_group_ref.update(values)
    if session is None:
        session = get_session()
    security_group_ref.save(session=session)
    return security_group_ref


def security_group_ensure_default(context, session=None):
    """Ensure default security group exists for a project_id.

    Returns a tuple with the first element being a bool indicating
    if the default security group previously existed. Second
    element is the dict used to create the default security group.
    """
    try:
        default_group = security_group_get_by_name(context,
                context.project_id, 'default',
                columns_to_join=[], session=session)
        return (True, default_group)
    except exception.NotFound:
        values = {'name': 'default',
                  'description': 'default',
                  'user_id': context.user_id,
                  'project_id': context.project_id}
        default_group = security_group_create(context, values,
                session=session)
        return (False, default_group)


@require_context
def security_group_destroy(context, security_group_id):
    session = get_session()
    with session.begin():
        session.query(models.SecurityGroup).\
                filter_by(id=security_group_id).\
                soft_delete()
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(security_group_id=security_group_id).\
                soft_delete()
        session.query(models.SecurityGroupIngressRule).\
                filter_by(group_id=security_group_id).\
                soft_delete()
        session.query(models.SecurityGroupIngressRule).\
                filter_by(parent_group_id=security_group_id).\
                soft_delete()


@require_context
def security_group_count_by_project(context, project_id, session=None):
    authorize_project_context(context, project_id)
    return model_query(context, models.SecurityGroup, read_deleted="no",
                       session=session).\
                   filter_by(project_id=project_id).\
                   count()

###################


def _security_group_rule_get_query(context, session=None):
    return model_query(context, models.SecurityGroupIngressRule,
                       session=session)


@require_context
def security_group_rule_get(context, security_group_rule_id, session=None):
    result = _security_group_rule_get_query(context, session=session).\
                         filter_by(id=security_group_rule_id).\
                         first()

    if not result:
        raise exception.SecurityGroupNotFoundForRule(
                                               rule_id=security_group_rule_id)

    return result


@require_context
def security_group_rule_get_by_security_group(context, security_group_id,
                                              session=None):
    return _security_group_rule_get_query(context, session=session).\
            filter_by(parent_group_id=security_group_id).\
            options(joinedload_all('grantee_group.instances.instance_type')).\
            all()


@require_context
def security_group_rule_get_by_security_group_grantee(context,
                                                      security_group_id,
                                                      session=None):

    return _security_group_rule_get_query(context, session=session).\
                         filter_by(group_id=security_group_id).\
                         all()


@require_context
def security_group_rule_create(context, values):
    security_group_rule_ref = models.SecurityGroupIngressRule()
    security_group_rule_ref.update(values)
    security_group_rule_ref.save()
    return security_group_rule_ref


@require_context
def security_group_rule_destroy(context, security_group_rule_id):
    session = get_session()
    with session.begin():
        count = _security_group_rule_get_query(context, session=session).\
                        filter_by(id=security_group_rule_id).\
                        soft_delete()
        if count == 0:
            raise exception.SecurityGroupNotFoundForRule(
                                               rule_id=security_group_rule_id)


@require_context
def security_group_rule_count_by_group(context, security_group_id):
    return model_query(context, models.SecurityGroupIngressRule,
                   read_deleted="no").\
                   filter_by(parent_group_id=security_group_id).\
                   count()

#
###################


@require_admin_context
def provider_fw_rule_create(context, rule):
    fw_rule_ref = models.ProviderFirewallRule()
    fw_rule_ref.update(rule)
    fw_rule_ref.save()
    return fw_rule_ref


@require_admin_context
def provider_fw_rule_get_all(context):
    return model_query(context, models.ProviderFirewallRule).all()


@require_admin_context
def provider_fw_rule_destroy(context, rule_id):
    session = get_session()
    with session.begin():
        session.query(models.ProviderFirewallRule).\
                filter_by(id=rule_id).\
                soft_delete()


###################


@require_context
def project_get_networks(context, project_id, associate=True):
    # NOTE(tr3buchet): as before this function will associate
    # a project with a network if it doesn't have one and
    # associate is true
    result = model_query(context, models.Network, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     all()

    if not result:
        if not associate:
            return []

        return [network_associate(context, project_id)]

    return result


###################


@require_admin_context
def migration_create(context, values):
    migration = models.Migration()
    migration.update(values)
    migration.save()
    return migration


@require_admin_context
def migration_update(context, id, values):
    session = get_session()
    with session.begin():
        migration = migration_get(context, id, session=session)
        migration.update(values)
        migration.save(session=session)
        return migration


@require_admin_context
def migration_get(context, id, session=None):
    result = model_query(context, models.Migration, session=session,
                         read_deleted="yes").\
                     filter_by(id=id).\
                     first()

    if not result:
        raise exception.MigrationNotFound(migration_id=id)

    return result


@require_admin_context
def migration_get_by_instance_and_status(context, instance_uuid, status):
    result = model_query(context, models.Migration, read_deleted="yes").\
                     filter_by(instance_uuid=instance_uuid).\
                     filter_by(status=status).\
                     first()

    if not result:
        raise exception.MigrationNotFoundByStatus(instance_id=instance_uuid,
                                                  status=status)

    return result


@require_admin_context
def migration_get_unconfirmed_by_dest_compute(context, confirm_window,
        dest_compute, session=None):
    confirm_window = (timeutils.utcnow() -
                      datetime.timedelta(seconds=confirm_window))

    return model_query(context, models.Migration, session=session,
                       read_deleted="yes").\
            filter(models.Migration.updated_at <= confirm_window).\
            filter_by(status="finished").\
            filter_by(dest_compute=dest_compute).\
            all()


@require_admin_context
def migration_get_in_progress_by_host_and_node(context, host, node,
                                               session=None):

    return model_query(context, models.Migration, session=session).\
            filter(or_(and_(models.Migration.source_compute == host,
                            models.Migration.source_node == node),
                       and_(models.Migration.dest_compute == host,
                            models.Migration.dest_node == node))).\
            filter(~models.Migration.status.in_(['confirmed', 'reverted'])).\
            options(joinedload('instance')).\
            all()


##################


def console_pool_create(context, values):
    pool = models.ConsolePool()
    pool.update(values)
    pool.save()
    return pool


def console_pool_get_by_host_type(context, compute_host, host,
                                  console_type):

    result = model_query(context, models.ConsolePool, read_deleted="no").\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   filter_by(compute_host=compute_host).\
                   options(joinedload('consoles')).\
                   first()

    if not result:
        raise exception.ConsolePoolNotFoundForHostType(
                host=host, console_type=console_type,
                compute_host=compute_host)

    return result


def console_pool_get_all_by_host_type(context, host, console_type):
    return model_query(context, models.ConsolePool, read_deleted="no").\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   options(joinedload('consoles')).\
                   all()


def console_create(context, values):
    console = models.Console()
    console.update(values)
    console.save()
    return console


def console_delete(context, console_id):
    session = get_session()
    with session.begin():
        # NOTE(mdragon): consoles are meant to be transient.
        session.query(models.Console).\
                filter_by(id=console_id).\
                delete()


def console_get_by_pool_instance(context, pool_id, instance_uuid):
    result = model_query(context, models.Console, read_deleted="yes").\
                   filter_by(pool_id=pool_id).\
                   filter_by(instance_uuid=instance_uuid).\
                   options(joinedload('pool')).\
                   first()

    if not result:
        raise exception.ConsoleNotFoundInPoolForInstance(
                pool_id=pool_id, instance_uuid=instance_uuid)

    return result


def console_get_all_by_instance(context, instance_uuid):
    return model_query(context, models.Console, read_deleted="yes").\
                   filter_by(instance_uuid=instance_uuid).\
                   all()


def console_get(context, console_id, instance_uuid=None):
    query = model_query(context, models.Console, read_deleted="yes").\
                    filter_by(id=console_id).\
                    options(joinedload('pool'))

    if instance_uuid is not None:
        query = query.filter_by(instance_uuid=instance_uuid)

    result = query.first()

    if not result:
        if instance_uuid:
            raise exception.ConsoleNotFoundForInstance(
                    console_id=console_id, instance_uuid=instance_uuid)
        else:
            raise exception.ConsoleNotFound(console_id=console_id)

    return result


##################


@require_admin_context
def instance_type_create(context, values):
    """Create a new instance type. In order to pass in extra specs,
    the values dict should contain a 'extra_specs' key/value pair:

    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}

    """
    session = get_session()
    with session.begin():
        try:
            instance_type_get_by_name(context, values['name'], session)
            raise exception.InstanceTypeExists(name=values['name'])
        except exception.InstanceTypeNotFoundByName:
            pass
        try:
            instance_type_get_by_flavor_id(context, values['flavorid'],
                                           session)
            raise exception.InstanceTypeIdExists(flavor_id=values['flavorid'])
        except exception.FlavorNotFound:
            pass
        try:
            specs = values.get('extra_specs')
            specs_refs = []
            if specs:
                for k, v in specs.iteritems():
                    specs_ref = models.InstanceTypeExtraSpecs()
                    specs_ref['key'] = k
                    specs_ref['value'] = v
                    specs_refs.append(specs_ref)
            values['extra_specs'] = specs_refs
            instance_type_ref = models.InstanceTypes()
            instance_type_ref.update(values)
            instance_type_ref.save(session=session)
        except Exception, e:
            raise db_session.DBError(e)
        return _dict_with_extra_specs(instance_type_ref)


def _dict_with_extra_specs(inst_type_query):
    """Takes an instance or instance type query returned
    by sqlalchemy and returns it as a dictionary, converting the
    extra_specs entry from a list of dicts:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]

    to a single dict:

    'extra_specs' : {'k1': 'v1'}

    """
    inst_type_dict = dict(inst_type_query)
    extra_specs = dict([(x['key'], x['value'])
                        for x in inst_type_query['extra_specs']])
    inst_type_dict['extra_specs'] = extra_specs
    return inst_type_dict


def _instance_type_get_query(context, session=None, read_deleted=None):
    return model_query(context, models.InstanceTypes, session=session,
                       read_deleted=read_deleted).\
                     options(joinedload('extra_specs'))


@require_context
def instance_type_get_all(context, inactive=False, filters=None):
    """
    Returns all instance types.
    """
    filters = filters or {}

    # FIXME(sirp): now that we have the `disabled` field for instance-types, we
    # should probably remove the use of `deleted` to mark inactive. `deleted`
    # should mean truly deleted, e.g. we can safely purge the record out of the
    # database.
    read_deleted = "yes" if inactive else "no"

    query = _instance_type_get_query(context, read_deleted=read_deleted)

    if 'min_memory_mb' in filters:
        query = query.filter(
                models.InstanceTypes.memory_mb >= filters['min_memory_mb'])

    if 'min_root_gb' in filters:
        query = query.filter(
                models.InstanceTypes.root_gb >= filters['min_root_gb'])

    if 'disabled' in filters:
        query = query.filter(
                models.InstanceTypes.disabled == filters['disabled'])

    if 'is_public' in filters and filters['is_public'] is not None:
        the_filter = [models.InstanceTypes.is_public == filters['is_public']]
        if filters['is_public'] and context.project_id is not None:
            the_filter.extend([
                models.InstanceTypes.projects.any(
                    project_id=context.project_id, deleted=0)
            ])
        if len(the_filter) > 1:
            query = query.filter(or_(*the_filter))
        else:
            query = query.filter(the_filter[0])
        del filters['is_public']

    inst_types = query.order_by("name").all()

    return [_dict_with_extra_specs(i) for i in inst_types]


@require_context
def instance_type_get(context, id, session=None):
    """Returns a dict describing specific instance_type."""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(id=id).\
                    first()

    if not result:
        raise exception.InstanceTypeNotFound(instance_type_id=id)

    return _dict_with_extra_specs(result)


@require_context
def instance_type_get_by_name(context, name, session=None):
    """Returns a dict describing specific instance_type."""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(name=name).\
                    first()

    if not result:
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)

    return _dict_with_extra_specs(result)


@require_context
def instance_type_get_by_flavor_id(context, flavor_id, session=None):
    """Returns a dict describing specific flavor_id."""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(flavorid=flavor_id).\
                    first()

    if not result:
        raise exception.FlavorNotFound(flavor_id=flavor_id)

    return _dict_with_extra_specs(result)


@require_admin_context
def instance_type_destroy(context, name):
    """Marks specific instance_type as deleted."""
    session = get_session()
    with session.begin():
        instance_type_ref = instance_type_get_by_name(context, name,
                                                      session=session)
        instance_type_id = instance_type_ref['id']
        session.query(models.InstanceTypes).\
                filter_by(id=instance_type_id).\
                soft_delete()
        session.query(models.InstanceTypeExtraSpecs).\
                filter_by(instance_type_id=instance_type_id).\
                soft_delete()


@require_context
def _instance_type_access_query(context, session=None):
    return model_query(context, models.InstanceTypeProjects, session=session,
                       read_deleted="no")


@require_admin_context
def instance_type_access_get_by_flavor_id(context, flavor_id):
    """Get flavor access list by flavor id."""
    instance_type_ref = _instance_type_get_query(context).\
                    filter_by(flavorid=flavor_id).\
                    first()

    return [r for r in instance_type_ref.projects]


@require_admin_context
def instance_type_access_add(context, flavor_id, project_id):
    """Add given tenant to the flavor access list."""
    # NOTE(boris-42): There is a race condition in this method and it will be
    #                 rewritten after bp/db-unique-keys implementation.
    session = get_session()
    with session.begin():
        instance_type_ref = instance_type_get_by_flavor_id(context, flavor_id,
                                                           session=session)
        instance_type_id = instance_type_ref['id']
        access_ref = _instance_type_access_query(context, session=session).\
                        filter_by(instance_type_id=instance_type_id).\
                        filter_by(project_id=project_id).\
                        first()
        if access_ref:
            raise exception.FlavorAccessExists(flavor_id=flavor_id,
                                               project_id=project_id)

        access_ref = models.InstanceTypeProjects()
        access_ref.update({"instance_type_id": instance_type_id,
                           "project_id": project_id})
        access_ref.save(session=session)
        return access_ref


@require_admin_context
def instance_type_access_remove(context, flavor_id, project_id):
    """Remove given tenant from the flavor access list."""
    session = get_session()
    with session.begin():
        instance_type_ref = instance_type_get_by_flavor_id(context, flavor_id,
                                                           session=session)
        instance_type_id = instance_type_ref['id']
        count = _instance_type_access_query(context, session=session).\
                        filter_by(instance_type_id=instance_type_id).\
                        filter_by(project_id=project_id).\
                        soft_delete()
        if count == 0:
            raise exception.FlavorAccessNotFound(flavor_id=flavor_id,
                                                 project_id=project_id)


####################


@require_admin_context
def cell_create(context, values):
    cell = models.Cell()
    cell.update(values)
    cell.save()
    return cell


def _cell_get_by_name_query(context, cell_name, session=None):
    return model_query(context, models.Cell,
                       session=session).filter_by(name=cell_name)


@require_admin_context
def cell_update(context, cell_name, values):
    session = get_session()
    with session.begin():
        cell = _cell_get_by_name_query(context, cell_name, session=session)
        cell.update(values)
    return cell


@require_admin_context
def cell_delete(context, cell_name):
    return _cell_get_by_name_query(context, cell_name).soft_delete()


@require_admin_context
def cell_get(context, cell_name):
    result = _cell_get_by_name_query(context, cell_name).first()
    if not result:
        raise exception.CellNotFound(cell_name=cell_name)
    return result


@require_admin_context
def cell_get_all(context):
    return model_query(context, models.Cell, read_deleted="no").all()


########################
# User-provided metadata

def _instance_metadata_get_query(context, instance_uuid, session=None):
    return model_query(context, models.InstanceMetadata, session=session,
                       read_deleted="no").\
                    filter_by(instance_uuid=instance_uuid)


@require_context
def instance_metadata_get(context, instance_uuid, session=None):
    rows = _instance_metadata_get_query(context, instance_uuid,
                                        session=session).all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
def instance_metadata_delete(context, instance_uuid, key):
    _instance_metadata_get_query(context, instance_uuid).\
        filter_by(key=key).\
        soft_delete()


@require_context
def instance_metadata_get_item(context, instance_uuid, key, session=None):
    result = _instance_metadata_get_query(
                            context, instance_uuid, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.InstanceMetadataNotFound(metadata_key=key,
                                                 instance_uuid=instance_uuid)

    return result


@require_context
def instance_metadata_update(context, instance_uuid, metadata, delete,
                             session=None):
    all_keys = metadata.keys()
    synchronize_session = "fetch"
    if session is None:
        session = get_session()
        synchronize_session = False
    with session.begin(subtransactions=True):
        if delete:
            _instance_metadata_get_query(context, instance_uuid,
                                         session=session).\
                filter(~models.InstanceMetadata.key.in_(all_keys)).\
                soft_delete(synchronize_session=synchronize_session)

        already_existing_keys = []
        meta_refs = _instance_metadata_get_query(context, instance_uuid,
                                                 session=session).\
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
            session.add(meta_ref)

        return metadata


#######################
# System-owned metadata


def _instance_system_metadata_get_query(context, instance_uuid, session=None):
    return model_query(context, models.InstanceSystemMetadata,
                       session=session).\
                    filter_by(instance_uuid=instance_uuid)


@require_context
def instance_system_metadata_get(context, instance_uuid, session=None):
    rows = _instance_system_metadata_get_query(context, instance_uuid,
                                               session=session).all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


def _instance_system_metadata_get_item(context, instance_uuid, key,
                                       session=None):
    result = _instance_system_metadata_get_query(
                            context, instance_uuid, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.InstanceSystemMetadataNotFound(
                metadata_key=key, instance_uuid=instance_uuid)

    return result


@require_context
def instance_system_metadata_update(context, instance_uuid, metadata, delete,
                                    session=None):
    all_keys = metadata.keys()
    synchronize_session = "fetch"
    if session is None:
        session = get_session()
        synchronize_session = False
    with session.begin(subtransactions=True):
        if delete:
            _instance_system_metadata_get_query(context, instance_uuid,
                                                session=session).\
                filter(~models.InstanceSystemMetadata.key.in_(all_keys)).\
                soft_delete(synchronize_session=synchronize_session)

        already_existing_keys = []
        meta_refs = _instance_system_metadata_get_query(context, instance_uuid,
                                                        session=session).\
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
            session.add(meta_ref)

        return metadata


####################


@require_admin_context
def agent_build_create(context, values):
    agent_build_ref = models.AgentBuild()
    agent_build_ref.update(values)
    agent_build_ref.save()
    return agent_build_ref


@require_admin_context
def agent_build_get_by_triple(context, hypervisor, os, architecture,
                              session=None):
    return model_query(context, models.AgentBuild, session=session,
                       read_deleted="no").\
                   filter_by(hypervisor=hypervisor).\
                   filter_by(os=os).\
                   filter_by(architecture=architecture).\
                   first()


@require_admin_context
def agent_build_get_all(context, hypervisor=None):
    if hypervisor:
        return model_query(context, models.AgentBuild, read_deleted="no").\
                   filter_by(hypervisor=hypervisor).\
                   all()
    else:
        return model_query(context, models.AgentBuild, read_deleted="no").\
                   all()


@require_admin_context
def agent_build_destroy(context, agent_build_id):
    session = get_session()
    with session.begin():
        count = model_query(context, models.AgentBuild,
                    session=session, read_deleted="yes").\
                filter_by(id=agent_build_id).\
                soft_delete()
        if count == 0:
            raise exception.AgentBuildNotFound(id=agent_build_id)


@require_admin_context
def agent_build_update(context, agent_build_id, values):
    session = get_session()
    with session.begin():
        agent_build_ref = model_query(context, models.AgentBuild,
                                      session=session, read_deleted="yes").\
                   filter_by(id=agent_build_id).\
                   first()
        if not agent_build_ref:
            raise exception.AgentBuildNotFound(id=agent_build_id)
        agent_build_ref.update(values)
        agent_build_ref.save(session=session)


####################

@require_context
def bw_usage_get(context, uuid, start_period, mac):
    return model_query(context, models.BandwidthUsage, read_deleted="yes").\
                      filter_by(start_period=start_period).\
                      filter_by(uuid=uuid).\
                      filter_by(mac=mac).\
                      first()


@require_context
def bw_usage_get_by_uuids(context, uuids, start_period):
    return model_query(context, models.BandwidthUsage, read_deleted="yes").\
                   filter(models.BandwidthUsage.uuid.in_(uuids)).\
                   filter_by(start_period=start_period).\
                   all()


@require_context
def bw_usage_update(context, uuid, mac, start_period, bw_in, bw_out,
                    last_ctr_in, last_ctr_out, last_refreshed=None,
                    session=None):
    if not session:
        session = get_session()

    if last_refreshed is None:
        last_refreshed = timeutils.utcnow()

    # NOTE(comstud): More often than not, we'll be updating records vs
    # creating records.  Optimize accordingly, trying to update existing
    # records.  Fall back to creation when no rows are updated.
    with session.begin():
        values = {'last_refreshed': last_refreshed,
                  'last_ctr_in': last_ctr_in,
                  'last_ctr_out': last_ctr_out,
                  'bw_in': bw_in,
                  'bw_out': bw_out}
        rows = model_query(context, models.BandwidthUsage,
                              session=session, read_deleted="yes").\
                      filter_by(start_period=start_period).\
                      filter_by(uuid=uuid).\
                      filter_by(mac=mac).\
                      update(values, synchronize_session=False)
        if rows:
            return

        bwusage = models.BandwidthUsage()
        bwusage.start_period = start_period
        bwusage.uuid = uuid
        bwusage.mac = mac
        bwusage.last_refreshed = last_refreshed
        bwusage.bw_in = bw_in
        bwusage.bw_out = bw_out
        bwusage.last_ctr_in = last_ctr_in
        bwusage.last_ctr_out = last_ctr_out
        bwusage.save(session=session)


####################


def _instance_type_extra_specs_get_query(context, flavor_id,
                                         session=None):
    # Two queries necessary because join with update doesn't work.
    t = model_query(context, models.InstanceTypes.id,
                    base_model=models.InstanceTypes, session=session,
                    read_deleted="no").\
              filter(models.InstanceTypes.flavorid == flavor_id).\
              subquery()
    return model_query(context, models.InstanceTypeExtraSpecs,
                       session=session, read_deleted="no").\
                       filter(models.InstanceTypeExtraSpecs.
                              instance_type_id.in_(t))


@require_context
def instance_type_extra_specs_get(context, flavor_id):
    rows = _instance_type_extra_specs_get_query(
                            context, flavor_id).\
                    all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
def instance_type_extra_specs_delete(context, flavor_id, key):
    # Don't need synchronize the session since we will not use the query result
    _instance_type_extra_specs_get_query(
                            context, flavor_id).\
        filter(models.InstanceTypeExtraSpecs.key == key).\
        soft_delete(synchronize_session=False)


@require_context
def instance_type_extra_specs_get_item(context, flavor_id, key,
                                       session=None):
    result = _instance_type_extra_specs_get_query(
                            context, flavor_id, session=session).\
                    filter(models.InstanceTypeExtraSpecs.key == key).\
                    first()
    if not result:
        raise exception.InstanceTypeExtraSpecsNotFound(
                extra_specs_key=key, instance_type_id=flavor_id)

    return result


@require_context
def instance_type_extra_specs_update_or_create(context, flavor_id, specs):
    # NOTE(boris-42): There is a race condition in this method. We should add
    #                 UniqueConstraint on (instance_type_id, key, deleted) to
    #                 avoid duplicated instance_type_extra_specs. This will be
    #                 possible after bp/db-unique-keys implementation.
    session = get_session()
    with session.begin():
        instance_type_id = model_query(context, models.InstanceTypes.id,
                                       base_model=models.InstanceTypes,
                                       session=session, read_deleted="no").\
            filter(models.InstanceTypes.flavorid == flavor_id).\
            first()
        if not instance_type_id:
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        instance_type_id = instance_type_id.id

        spec_refs = model_query(context, models.InstanceTypeExtraSpecs,
                                session=session, read_deleted="no").\
            filter_by(instance_type_id=instance_type_id).\
            filter(models.InstanceTypeExtraSpecs.key.in_(specs.keys())).\
            all()

        existing_keys = set()
        for spec_ref in spec_refs:
            key = spec_ref["key"]
            existing_keys.add(key)
            spec_ref.update({"value": specs[key]})

        for key, value in specs.iteritems():
            if key in existing_keys:
                continue
            spec_ref = models.InstanceTypeExtraSpecs()
            spec_ref.update({"key": key, "value": value,
                             "instance_type_id": instance_type_id})
            session.add(spec_ref)

    return specs


####################


@require_context
def vol_get_usage_by_time(context, begin):
    """Return volumes usage that have been updated after a specified time."""
    return model_query(context, models.VolumeUsage, read_deleted="yes").\
                   filter(or_(models.VolumeUsage.tot_last_refreshed == None,
                              models.VolumeUsage.tot_last_refreshed > begin,
                              models.VolumeUsage.curr_last_refreshed == None,
                              models.VolumeUsage.curr_last_refreshed > begin,
                              )).\
                              all()


@require_context
def vol_usage_update(context, id, rd_req, rd_bytes, wr_req, wr_bytes,
                     instance_id, last_refreshed=None, update_totals=False,
                     session=None):
    if not session:
        session = get_session()

    if last_refreshed is None:
        last_refreshed = timeutils.utcnow()

    with session.begin():
        values = {}
        # NOTE(dricco): We will be mostly updating current usage records vs
        # updating total or creating records. Optimize accordingly.
        if not update_totals:
            values = {'curr_last_refreshed': last_refreshed,
                      'curr_reads': rd_req,
                      'curr_read_bytes': rd_bytes,
                      'curr_writes': wr_req,
                      'curr_write_bytes': wr_bytes,
                      'instance_id': instance_id}
        else:
            values = {'tot_last_refreshed': last_refreshed,
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
                      'instance_id': instance_id}

        rows = model_query(context, models.VolumeUsage,
                           session=session, read_deleted="yes").\
                           filter_by(volume_id=id).\
                           update(values, synchronize_session=False)

        if rows:
            return

        vol_usage = models.VolumeUsage()
        vol_usage.tot_last_refreshed = timeutils.utcnow()
        vol_usage.curr_last_refreshed = timeutils.utcnow()
        vol_usage.volume_id = id

        if not update_totals:
            vol_usage.curr_reads = rd_req
            vol_usage.curr_read_bytes = rd_bytes
            vol_usage.curr_writes = wr_req
            vol_usage.curr_write_bytes = wr_bytes
        else:
            vol_usage.tot_reads = rd_req
            vol_usage.tot_read_bytes = rd_bytes
            vol_usage.tot_writes = wr_req
            vol_usage.tot_write_bytes = wr_bytes

        vol_usage.save(session=session)

    return


####################


def s3_image_get(context, image_id):
    """Find local s3 image represented by the provided id."""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(id=image_id).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_id)

    return result


def s3_image_get_by_uuid(context, image_uuid):
    """Find local s3 image represented by the provided uuid."""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(uuid=image_uuid).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_uuid)

    return result


def s3_image_create(context, image_uuid):
    """Create local s3 image represented by provided uuid."""
    try:
        s3_image_ref = models.S3Image()
        s3_image_ref.update({'uuid': image_uuid})
        s3_image_ref.save()
    except Exception, e:
        raise db_session.DBError(e)

    return s3_image_ref


####################


def _aggregate_get_query(context, model_class, id_field=None, id=None,
                         session=None, read_deleted=None):
    columns_to_join = {models.Aggregate: ['_hosts', '_metadata']}

    query = model_query(context, model_class, session=session,
                        read_deleted=read_deleted)

    for c in columns_to_join.get(model_class, []):
        query = query.options(joinedload(c))

    if id and id_field:
        query = query.filter(id_field == id)

    return query


@require_admin_context
def aggregate_create(context, values, metadata=None):
    session = get_session()
    query = _aggregate_get_query(context,
                                 models.Aggregate,
                                 models.Aggregate.name,
                                 values['name'],
                                 session=session,
                                 read_deleted='no')
    aggregate = query.options(joinedload('_metadata')).first()
    if not aggregate:
        aggregate = models.Aggregate()
        aggregate.update(values)
        aggregate.save(session=session)
        # We don't want these to be lazy loaded later.  We know there is
        # nothing here since we just created this aggregate.
        aggregate._hosts = []
        aggregate._metadata = []
    else:
        raise exception.AggregateNameExists(aggregate_name=values['name'])
    if metadata:
        aggregate_metadata_add(context, aggregate.id, metadata)
    return aggregate_get(context, aggregate.id)


@require_admin_context
def aggregate_get(context, aggregate_id):
    query = _aggregate_get_query(context,
                                 models.Aggregate,
                                 models.Aggregate.id,
                                 aggregate_id)
    aggregate = query.options(joinedload('_metadata')).first()

    if not aggregate:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)

    return aggregate


@require_admin_context
def aggregate_get_by_host(context, host, key=None):
    query = _aggregate_get_query(context, models.Aggregate,
            models.AggregateHost.host, host)

    if key:
        query = query.join("_metadata").filter(
        models.AggregateMetadata.key == key)
    return query.all()


@require_admin_context
def aggregate_metadata_get_by_host(context, host, key=None):
    query = model_query(context, models.Aggregate).join(
            "_hosts").filter(models.AggregateHost.host == host).join(
            "_metadata")

    if key:
        query = query.filter(models.AggregateMetadata.key == key)
    rows = query.all()
    metadata = collections.defaultdict(set)
    for agg in rows:
        for kv in agg._metadata:
            metadata[kv['key']].add(kv['value'])
    return dict(metadata)


@require_admin_context
def aggregate_host_get_by_metadata_key(context, key):
    query = model_query(context, models.Aggregate).join(
            "_metadata").filter(models.AggregateMetadata.key == key)
    rows = query.all()
    metadata = collections.defaultdict(set)
    for agg in rows:
        for agghost in agg._hosts:
            metadata[agghost.host].add(agg._metadata[0]['value'])
    return dict(metadata)


@require_admin_context
def aggregate_update(context, aggregate_id, values):
    session = get_session()
    aggregate = (_aggregate_get_query(context,
                                     models.Aggregate,
                                     models.Aggregate.id,
                                     aggregate_id,
                                     session=session).
                                     options(joinedload('_metadata')).first())

    if aggregate:
        if "availability_zone" in values:
            az = values.pop('availability_zone')
            if 'metadata' not in values:
                values['metadata'] = {'availability_zone': az}
            else:
                values['metadata']['availability_zone'] = az
        metadata = values.get('metadata')
        if metadata is not None:
            aggregate_metadata_add(context,
                                   aggregate_id,
                                   values.pop('metadata'),
                                   set_delete=True)
        with session.begin():
            aggregate.update(values)
            aggregate.save(session=session)
        values['metadata'] = metadata
        return aggregate_get(context, aggregate.id)
    else:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)


@require_admin_context
def aggregate_delete(context, aggregate_id):
    session = get_session()
    with session.begin():
        count = _aggregate_get_query(context,
                                     models.Aggregate,
                                     models.Aggregate.id,
                                     aggregate_id,
                                     session=session).\
                    soft_delete()
        if count == 0:
            raise exception.AggregateNotFound(aggregate_id=aggregate_id)

        #Delete Metadata
        model_query(context,
                    models.AggregateMetadata, session=session).\
                    filter_by(aggregate_id=aggregate_id).\
                    soft_delete()


@require_admin_context
def aggregate_get_all(context):
    return _aggregate_get_query(context, models.Aggregate).all()


@require_admin_context
def aggregate_metadata_get_query(context, aggregate_id, session=None,
                                 read_deleted="yes"):
    return model_query(context,
                       models.AggregateMetadata,
                       read_deleted=read_deleted,
                       session=session).\
                filter_by(aggregate_id=aggregate_id)


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_get(context, aggregate_id):
    rows = model_query(context,
                       models.AggregateMetadata).\
                       filter_by(aggregate_id=aggregate_id).all()

    return dict([(r['key'], r['value']) for r in rows])


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_delete(context, aggregate_id, key):
    count = _aggregate_get_query(context,
                                 models.AggregateMetadata,
                                 models.AggregateMetadata.aggregate_id,
                                 aggregate_id).\
                                 filter_by(key=key).\
                                 soft_delete()
    if count == 0:
        raise exception.AggregateMetadataNotFound(aggregate_id=aggregate_id,
                                                  metadata_key=key)


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_get_item(context, aggregate_id, key, session=None):
    result = _aggregate_get_query(context,
                                  models.AggregateMetadata,
                                  models.AggregateMetadata.aggregate_id,
                                  aggregate_id, session=session,
                                  read_deleted='yes').\
                                  filter_by(key=key).first()

    if not result:
        raise exception.AggregateMetadataNotFound(metadata_key=key,
                                                 aggregate_id=aggregate_id)

    return result


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_add(context, aggregate_id, metadata, set_delete=False):
    # NOTE(boris-42): There is a race condition in this method. We should add
    #                 UniqueConstraint on (start_period, uuid, mac, deleted) to
    #                 avoid duplicated aggregate_metadata. This will be
    #                 possible after bp/db-unique-keys implementation.
    session = get_session()
    all_keys = metadata.keys()
    with session.begin():
        query = aggregate_metadata_get_query(context, aggregate_id,
                                             read_deleted='no',
                                             session=session)
        if set_delete:
            query.filter(~models.AggregateMetadata.key.in_(all_keys)).\
                soft_delete(synchronize_session=False)

        query = query.filter(models.AggregateMetadata.key.in_(all_keys))
        already_existing_keys = set()
        for meta_ref in query.all():
            key = meta_ref.key
            meta_ref.update({"value": metadata[key]})
            already_existing_keys.add(key)

        for key, value in metadata.iteritems():
            if key in already_existing_keys:
                continue
            meta_ref = models.AggregateMetadata()
            meta_ref.update({"key": key,
                             "value": value,
                             "aggregate_id": aggregate_id})
            session.add(meta_ref)

        return metadata


@require_admin_context
@require_aggregate_exists
def aggregate_host_get_all(context, aggregate_id):
    rows = model_query(context,
                       models.AggregateHost).\
                       filter_by(aggregate_id=aggregate_id).all()

    return [r.host for r in rows]


@require_admin_context
@require_aggregate_exists
def aggregate_host_delete(context, aggregate_id, host):
    count = _aggregate_get_query(context,
                                 models.AggregateHost,
                                 models.AggregateHost.aggregate_id,
                                 aggregate_id).\
            filter_by(host=host).\
            soft_delete()
    if count == 0:
        raise exception.AggregateHostNotFound(aggregate_id=aggregate_id,
                                              host=host)


@require_admin_context
@require_aggregate_exists
def aggregate_host_add(context, aggregate_id, host):
    # NOTE(boris-42): There is a race condition in this method and it will be
    #                 rewritten after bp/db-unique-keys implementation.
    session = get_session()
    with session.begin():
        host_ref = _aggregate_get_query(context,
                                        models.AggregateHost,
                                        models.AggregateHost.aggregate_id,
                                        aggregate_id,
                                        session=session,
                                        read_deleted='no').\
                            filter_by(host=host).\
                            first()
        if host_ref:
            raise exception.AggregateHostExists(host=host,
                                            aggregate_id=aggregate_id)
        host_ref = models.AggregateHost()
        host_ref.update({"host": host, "aggregate_id": aggregate_id})
        host_ref.save(session=session)
    return host_ref


################


def instance_fault_create(context, values):
    """Create a new InstanceFault."""
    fault_ref = models.InstanceFault()
    fault_ref.update(values)
    fault_ref.save()
    return dict(fault_ref.iteritems())


def instance_fault_get_by_instance_uuids(context, instance_uuids):
    """Get all instance faults for the provided instance_uuids."""
    rows = model_query(context, models.InstanceFault, read_deleted='no').\
                       filter(models.InstanceFault.instance_uuid.in_(
                           instance_uuids)).\
                       order_by(desc("created_at"), desc("id")).\
                       all()

    output = {}
    for instance_uuid in instance_uuids:
        output[instance_uuid] = []

    for row in rows:
        data = dict(row.iteritems())
        output[row['instance_uuid']].append(data)

    return output


##################


def action_start(context, values):
    convert_datetimes(values, 'start_time')
    action_ref = models.InstanceAction()
    action_ref.update(values)
    action_ref.save()
    return action_ref


def action_finish(context, values):
    convert_datetimes(values, 'start_time', 'finish_time')
    session = get_session()
    with session.begin():
        action_ref = model_query(context, models.InstanceAction,
                                 session=session).\
                           filter_by(instance_uuid=values['instance_uuid']).\
                           filter_by(request_id=values['request_id']).\
                           first()

        if not action_ref:
            raise exception.InstanceActionNotFound(
                                        request_id=values['request_id'],
                                        instance_uuid=values['instance_uuid'])

        action_ref.update(values)
    return action_ref


def actions_get(context, instance_uuid):
    """Get all instance actions for the provided uuid."""
    actions = model_query(context, models.InstanceAction).\
                          filter_by(instance_uuid=instance_uuid).\
                          order_by(desc("created_at")).\
                          all()
    return actions


def action_get_by_request_id(context, instance_uuid, request_id):
    """Get the action by request_id and given instance."""
    action = _action_get_by_request_id(context, instance_uuid, request_id)
    return action


def _action_get_by_request_id(context, instance_uuid, request_id,
                                                                session=None):
    result = model_query(context, models.InstanceAction, session=session).\
                         filter_by(instance_uuid=instance_uuid).\
                         filter_by(request_id=request_id).\
                         first()
    return result


def action_event_start(context, values):
    """Start an event on an instance action."""
    convert_datetimes(values, 'start_time')
    session = get_session()
    with session.begin():
        action = _action_get_by_request_id(context, values['instance_uuid'],
                                           values['request_id'], session)

        if not action:
            raise exception.InstanceActionNotFound(
                                        request_id=values['request_id'],
                                        instance_uuid=values['instance_uuid'])

        values['action_id'] = action['id']

        event_ref = models.InstanceActionEvent()
        event_ref.update(values)
        event_ref.save(session=session)
    return event_ref


def action_event_finish(context, values):
    """Finish an event on an instance action."""
    convert_datetimes(values, 'start_time', 'finish_time')
    session = get_session()
    with session.begin():
        action = _action_get_by_request_id(context, values['instance_uuid'],
                                           values['request_id'], session)

        if not action:
            raise exception.InstanceActionNotFound(
                                        request_id=values['request_id'],
                                        instance_uuid=values['instance_uuid'])

        event_ref = model_query(context, models.InstanceActionEvent,
                                session=session).\
                            filter_by(action_id=action['id']).\
                            filter_by(event=values['event']).\
                            first()

        if not event_ref:
            raise exception.InstanceActionEventNotFound(action_id=action['id'],
                                                        event=values['event'])
        event_ref.update(values)
    return event_ref


def action_events_get(context, action_id):
    events = model_query(context, models.InstanceActionEvent).\
                         filter_by(action_id=action_id).\
                         order_by(desc("created_at")).\
                         all()

    return events


def action_event_get_by_id(context, action_id, event_id):
    event = model_query(context, models.InstanceActionEvent).\
                        filter_by(action_id=action_id).\
                        filter_by(id=event_id).\
                        first()

    return event


##################


@require_context
def ec2_instance_create(context, instance_uuid, id=None):
    """Create ec2 compatable instance by provided uuid."""
    ec2_instance_ref = models.InstanceIdMapping()
    ec2_instance_ref.update({'uuid': instance_uuid})
    if id is not None:
        ec2_instance_ref.update({'id': id})

    ec2_instance_ref.save()

    return ec2_instance_ref


@require_context
def get_ec2_instance_id_by_uuid(context, instance_id, session=None):
    result = _ec2_instance_get_query(context,
                                     session=session).\
                    filter_by(uuid=instance_id).\
                    first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_id)

    return result['id']


@require_context
def get_instance_uuid_by_ec2_id(context, ec2_id, session=None):
    result = _ec2_instance_get_query(context,
                                     session=session).\
                    filter_by(id=ec2_id).\
                    first()

    if not result:
        raise exception.InstanceNotFound(instance_id=ec2_id)

    return result['uuid']


@require_context
def _ec2_instance_get_query(context, session=None):
    return model_query(context,
                       models.InstanceIdMapping,
                       session=session,
                       read_deleted='yes')


@require_admin_context
def _task_log_get_query(context, task_name, period_beginning,
                        period_ending, host=None, state=None, session=None):
    query = model_query(context, models.TaskLog, session=session).\
                     filter_by(task_name=task_name).\
                     filter_by(period_beginning=period_beginning).\
                     filter_by(period_ending=period_ending)
    if host is not None:
        query = query.filter_by(host=host)
    if state is not None:
        query = query.filter_by(state=state)
    return query


@require_admin_context
def task_log_get(context, task_name, period_beginning, period_ending, host,
                 state=None):
    return _task_log_get_query(context, task_name, period_beginning,
                               period_ending, host, state).first()


@require_admin_context
def task_log_get_all(context, task_name, period_beginning, period_ending,
                     host=None, state=None):
    return _task_log_get_query(context, task_name, period_beginning,
                               period_ending, host, state).all()


@require_admin_context
def task_log_begin_task(context, task_name, period_beginning, period_ending,
                        host, task_items=None, message=None):
    # NOTE(boris-42): This method has a race condition and will be rewritten
    #                 after bp/db-unique-keys implementation.
    session = get_session()
    with session.begin():
        task_ref = _task_log_get_query(context, task_name, period_beginning,
                                       period_ending, host, session=session).\
                        first()
        if task_ref:
            #It's already run(ning)!
            raise exception.TaskAlreadyRunning(task_name=task_name, host=host)
        task = models.TaskLog()
        task.task_name = task_name
        task.period_beginning = period_beginning
        task.period_ending = period_ending
        task.host = host
        task.state = "RUNNING"
        if message:
            task.message = message
        if task_items:
            task.task_items = task_items
        task.save(session=session)


@require_admin_context
def task_log_end_task(context, task_name, period_beginning, period_ending,
                      host, errors, message=None):
    values = dict(state="DONE", errors=errors)
    if message:
        values["message"] = message

    session = get_session()
    with session.begin():
        rows = _task_log_get_query(context, task_name, period_beginning,
                                       period_ending, host, session=session).\
                        update(values)
        if rows == 0:
            #It's not running!
            raise exception.TaskNotRunning(task_name=task_name, host=host)
