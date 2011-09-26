# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
"""
Implementation of SQLAlchemy backend.
"""
import re
import warnings

from nova import block_device
from nova import db
from nova import exception
from nova import flags
from nova import ipv6
from nova import utils
from nova import log as logging
from nova.compute import vm_states
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import joinedload_all
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import desc
from sqlalchemy.sql.expression import literal_column

FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.db.sqlalchemy")


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        warnings.warn(_('Use of empty request context is deprecated'),
                      DeprecationWarning)
        raise Exception('die')
    return context.is_admin


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


def can_read_deleted(context):
    """Indicates if the context has access to deleted objects."""
    if not context:
        return False
    return context.read_deleted


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]):
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
        if not is_admin_context(args[0]) and not is_user_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def require_instance_exists(f):
    """Decorator to require the specified instance to exist.

    Requres the wrapped function to use context and instance_id as
    their first two arguments.
    """

    def wrapper(context, instance_id, *args, **kwargs):
        db.api.instance_get(context, instance_id)
        return f(context, instance_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_volume_exists(f):
    """Decorator to require the specified volume to exist.

    Requres the wrapped function to use context and volume_id as
    their first two arguments.
    """

    def wrapper(context, volume_id, *args, **kwargs):
        db.api.volume_get(context, volume_id)
        return f(context, volume_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


###################


@require_admin_context
def service_destroy(context, service_id):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.delete(session=session)

        if service_ref.topic == 'compute' and \
            len(service_ref.compute_node) != 0:
            for c in service_ref.compute_node:
                c.delete(session=session)


@require_admin_context
def service_get(context, service_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Service).\
                     options(joinedload('compute_node')).\
                     filter_by(id=service_id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()

    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@require_admin_context
def service_get_all(context, disabled=None):
    session = get_session()
    query = session.query(models.Service).\
                   filter_by(deleted=can_read_deleted(context))

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    session = get_session()
    return session.query(models.Service).\
                   filter_by(deleted=False).\
                   filter_by(disabled=False).\
                   filter_by(topic=topic).\
                   all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    session = get_session()
    return session.query(models.Service).\
                   filter_by(deleted=False).\
                   filter_by(disabled=False).\
                   filter_by(host=host).\
                   filter_by(topic=topic).\
                   first()


@require_admin_context
def service_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.Service).\
                   filter_by(deleted=False).\
                   filter_by(host=host).\
                   all()


@require_admin_context
def service_get_all_compute_by_host(context, host):
    topic = 'compute'
    session = get_session()
    result = session.query(models.Service).\
                  options(joinedload('compute_node')).\
                  filter_by(deleted=False).\
                  filter_by(host=host).\
                  filter_by(topic=topic).\
                  all()

    if not result:
        raise exception.ComputeHostNotFound(host=host)

    return result


@require_admin_context
def _service_get_all_topic_subquery(context, session, topic, subq, label):
    sort_value = getattr(subq.c, label)
    return session.query(models.Service, func.coalesce(sort_value, 0)).\
                   filter_by(topic=topic).\
                   filter_by(deleted=False).\
                   filter_by(disabled=False).\
                   outerjoin((subq, models.Service.host == subq.c.host)).\
                   order_by(sort_value).\
                   all()


@require_admin_context
def service_get_all_compute_sorted(context):
    session = get_session()
    with session.begin():
        # NOTE(vish): The intended query is below
        #             SELECT services.*, COALESCE(inst_cores.instance_cores,
        #                                         0)
        #             FROM services LEFT OUTER JOIN
        #             (SELECT host, SUM(instances.vcpus) AS instance_cores
        #              FROM instances GROUP BY host) AS inst_cores
        #             ON services.host = inst_cores.host
        topic = 'compute'
        label = 'instance_cores'
        subq = session.query(models.Instance.host,
                             func.sum(models.Instance.vcpus).label(label)).\
                       filter_by(deleted=False).\
                       group_by(models.Instance.host).\
                       subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_all_network_sorted(context):
    session = get_session()
    with session.begin():
        topic = 'network'
        label = 'network_count'
        subq = session.query(models.Network.host,
                             func.count(models.Network.id).label(label)).\
                       filter_by(deleted=False).\
                       group_by(models.Network.host).\
                       subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_all_volume_sorted(context):
    session = get_session()
    with session.begin():
        topic = 'volume'
        label = 'volume_gigabytes'
        subq = session.query(models.Volume.host,
                             func.sum(models.Volume.size).label(label)).\
                       filter_by(deleted=False).\
                       group_by(models.Volume.host).\
                       subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_by_args(context, host, binary):
    session = get_session()
    result = session.query(models.Service).\
                     filter_by(host=host).\
                     filter_by(binary=binary).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()
    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not FLAGS.enable_new_services:
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


###################


@require_admin_context
def compute_node_get(context, compute_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.ComputeNode).\
                     filter_by(id=compute_id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()

    if not result:
        raise exception.ComputeHostNotFound(host=compute_id)

    return result


@require_admin_context
def compute_node_create(context, values):
    compute_node_ref = models.ComputeNode()
    compute_node_ref.update(values)
    compute_node_ref.save()
    return compute_node_ref


@require_admin_context
def compute_node_update(context, compute_id, values):
    session = get_session()
    with session.begin():
        compute_ref = compute_node_get(context, compute_id, session=session)
        compute_ref.update(values)
        compute_ref.save(session=session)


###################


@require_admin_context
def certificate_get(context, certificate_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Certificate).\
                     filter_by(id=certificate_id).\
                     filter_by(deleted=can_read_deleted(context)).\
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
def certificate_destroy(context, certificate_id):
    session = get_session()
    with session.begin():
        certificate_ref = certificate_get(context,
                                          certificate_id,
                                          session=session)
        certificate_ref.delete(session=session)


@require_admin_context
def certificate_get_all_by_project(context, project_id):
    session = get_session()
    return session.query(models.Certificate).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def certificate_get_all_by_user(context, user_id):
    session = get_session()
    return session.query(models.Certificate).\
                   filter_by(user_id=user_id).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def certificate_get_all_by_user_and_project(_context, user_id, project_id):
    session = get_session()
    return session.query(models.Certificate).\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def certificate_update(context, certificate_id, values):
    session = get_session()
    with session.begin():
        certificate_ref = certificate_get(context,
                                          certificate_id,
                                          session=session)
        for (key, value) in values.iteritems():
            certificate_ref[key] = value
        certificate_ref.save(session=session)


###################


@require_context
def floating_ip_get(context, id):
    session = get_session()
    result = None
    if is_admin_context(context):
        result = session.query(models.FloatingIp).\
                         options(joinedload('fixed_ip')).\
                         options(joinedload_all('fixed_ip.instance')).\
                         filter_by(id=id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.FloatingIp).\
                         options(joinedload('fixed_ip')).\
                         options(joinedload_all('fixed_ip.instance')).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.FloatingIpNotFound(id=id)

    return result


@require_context
def floating_ip_allocate_address(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    with session.begin():
        floating_ip_ref = session.query(models.FloatingIp).\
                                  filter_by(fixed_ip_id=None).\
                                  filter_by(project_id=None).\
                                  filter_by(deleted=False).\
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
def floating_ip_create(context, values):
    floating_ip_ref = models.FloatingIp()
    floating_ip_ref.update(values)
    floating_ip_ref.save()
    return floating_ip_ref['address']


@require_context
def floating_ip_count_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    # TODO(tr3buchet): why leave auto_assigned floating IPs out?
    return session.query(models.FloatingIp).\
                   filter_by(project_id=project_id).\
                   filter_by(auto_assigned=False).\
                   filter_by(deleted=False).\
                   count()


@require_context
def floating_ip_fixed_ip_associate(context, floating_address,
                                   fixed_address, host):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     floating_address,
                                                     session=session)
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               fixed_address,
                                               session=session)
        floating_ip_ref.fixed_ip = fixed_ip_ref
        floating_ip_ref.host = host
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_deallocate(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref['project_id'] = None
        floating_ip_ref['host'] = None
        floating_ip_ref['auto_assigned'] = False
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_destroy(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref.delete(session=session)


@require_context
def floating_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        fixed_ip_ref = floating_ip_ref.fixed_ip
        if fixed_ip_ref:
            fixed_ip_address = fixed_ip_ref['address']
        else:
            fixed_ip_address = None
        floating_ip_ref.fixed_ip = None
        floating_ip_ref.host = None
        floating_ip_ref.save(session=session)
    return fixed_ip_address


@require_context
def floating_ip_set_auto_assigned(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref.auto_assigned = True
        floating_ip_ref.save(session=session)


@require_admin_context
def floating_ip_get_all(context):
    session = get_session()
    floating_ip_refs = session.query(models.FloatingIp).\
                               options(joinedload_all('fixed_ip.instance')).\
                               filter_by(deleted=False).\
                               all()
    if not floating_ip_refs:
        raise exception.NoFloatingIpsDefined()
    return floating_ip_refs


@require_admin_context
def floating_ip_get_all_by_host(context, host):
    session = get_session()
    floating_ip_refs = session.query(models.FloatingIp).\
                               options(joinedload_all('fixed_ip.instance')).\
                               filter_by(host=host).\
                               filter_by(deleted=False).\
                               all()
    if not floating_ip_refs:
        raise exception.FloatingIpNotFoundForHost(host=host)
    return floating_ip_refs


@require_context
def floating_ip_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    # TODO(tr3buchet): why do we not want auto_assigned floating IPs here?
    floating_ip_refs = session.query(models.FloatingIp).\
                               options(joinedload_all('fixed_ip.instance')).\
                               filter_by(project_id=project_id).\
                               filter_by(auto_assigned=False).\
                               filter_by(deleted=False).\
                               all()
    if not floating_ip_refs:
        raise exception.FloatingIpNotFoundForProject(project_id=project_id)
    return floating_ip_refs


@require_context
def floating_ip_get_by_address(context, address, session=None):
    if not session:
        session = get_session()

    result = session.query(models.FloatingIp).\
                options(joinedload_all('fixed_ip.network')).\
                filter_by(address=address).\
                filter_by(deleted=can_read_deleted(context)).\
                first()

    if not result:
        raise exception.FloatingIpNotFoundForAddress(address=address)

    # If the floating IP has a project ID set, check to make sure
    # the non-admin user has access.
    if result.project_id and is_user_context(context):
        authorize_project_context(context, result.project_id)

    return result


@require_context
def floating_ip_update(context, address, values):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context, address, session)
        for (key, value) in values.iteritems():
            floating_ip_ref[key] = value
        floating_ip_ref.save(session=session)


###################


@require_admin_context
def fixed_ip_associate(context, address, instance_id, network_id=None,
                       reserved=False):
    """Keyword arguments:
    reserved -- should be a boolean value(True or False), exact value will be
    used to filter on the fixed ip address
    """
    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = session.query(models.FixedIp).\
                               filter(network_or_none).\
                               filter_by(reserved=reserved).\
                               filter_by(deleted=False).\
                               filter_by(address=address).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if fixed_ip_ref is None:
            raise exception.FixedIpNotFoundForNetwork(address=address,
                                            network_id=network_id)
        if fixed_ip_ref.instance is not None:
            raise exception.FixedIpAlreadyInUse(address=address)

        if not fixed_ip_ref.network:
            fixed_ip_ref.network = network_get(context,
                                           network_id,
                                           session=session)
        fixed_ip_ref.instance = instance_get(context,
                                             instance_id,
                                             session=session)
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_admin_context
def fixed_ip_associate_pool(context, network_id, instance_id=None, host=None):
    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = session.query(models.FixedIp).\
                               filter(network_or_none).\
                               filter_by(reserved=False).\
                               filter_by(deleted=False).\
                               filter_by(instance=None).\
                               filter_by(host=None).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise exception.NoMoreFixedIps()
        if not fixed_ip_ref.network:
            fixed_ip_ref.network = network_get(context,
                                           network_id,
                                           session=session)
        if instance_id:
            fixed_ip_ref.instance = instance_get(context,
                                                 instance_id,
                                                 session=session)
        if host:
            fixed_ip_ref.host = host
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_context
def fixed_ip_create(_context, values):
    fixed_ip_ref = models.FixedIp()
    fixed_ip_ref.update(values)
    fixed_ip_ref.save()
    return fixed_ip_ref['address']


@require_context
def fixed_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               address,
                                               session=session)
        fixed_ip_ref.instance = None
        fixed_ip_ref.save(session=session)


@require_admin_context
def fixed_ip_disassociate_all_by_timeout(_context, host, time):
    session = get_session()
    inner_q = session.query(models.Network.id).\
                      filter_by(host=host).\
                      subquery()
    result = session.query(models.FixedIp).\
                     filter(models.FixedIp.network_id.in_(inner_q)).\
                     filter(models.FixedIp.updated_at < time).\
                     filter(models.FixedIp.instance_id != None).\
                     filter_by(allocated=False).\
                     update({'instance_id': None,
                             'leased': False,
                             'updated_at': utils.utcnow()},
                             synchronize_session='fetch')
    return result


@require_admin_context
def fixed_ip_get_all(context, session=None):
    if not session:
        session = get_session()
    result = session.query(models.FixedIp).\
                     options(joinedload('floating_ips')).\
                     all()
    if not result:
        raise exception.NoFixedIpsDefined()

    return result


@require_admin_context
def fixed_ip_get_all_by_instance_host(context, host=None):
    session = get_session()

    result = session.query(models.FixedIp).\
                     options(joinedload('floating_ips')).\
                     join(models.FixedIp.instance).\
                     filter_by(state=1).\
                     filter_by(host=host).\
                     all()

    if not result:
        raise exception.FixedIpNotFoundForHost(host=host)

    return result


@require_context
def fixed_ip_get_by_address(context, address, session=None):
    if not session:
        session = get_session()
    result = session.query(models.FixedIp).\
                     filter_by(address=address).\
                     filter_by(deleted=can_read_deleted(context)).\
                     options(joinedload('floating_ips')).\
                     options(joinedload('network')).\
                     options(joinedload('instance')).\
                     first()
    if not result:
        raise exception.FixedIpNotFoundForAddress(address=address)

    if is_user_context(context):
        authorize_project_context(context, result.instance.project_id)

    return result


@require_context
def fixed_ip_get_by_instance(context, instance_id):
    session = get_session()
    rv = session.query(models.FixedIp).\
                 options(joinedload('floating_ips')).\
                 filter_by(instance_id=instance_id).\
                 filter_by(deleted=False).\
                 all()
    if not rv:
        raise exception.FixedIpNotFoundForInstance(instance_id=instance_id)
    return rv


@require_context
def fixed_ip_get_by_network_host(context, network_id, host):
    session = get_session()
    rv = session.query(models.FixedIp).\
                 filter_by(network_id=network_id).\
                 filter_by(host=host).\
                 filter_by(deleted=False).\
                 first()
    if not rv:
        raise exception.FixedIpNotFoundForNetworkHost(network_id=network_id,
                                                      host=host)
    return rv


@require_context
def fixed_ip_get_by_virtual_interface(context, vif_id):
    session = get_session()
    rv = session.query(models.FixedIp).\
                 options(joinedload('floating_ips')).\
                 filter_by(virtual_interface_id=vif_id).\
                 filter_by(deleted=False).\
                 all()
    if not rv:
        raise exception.FixedIpNotFoundForVirtualInterface(vif_id=vif_id)
    return rv


@require_admin_context
def fixed_ip_get_network(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    return fixed_ip_ref.network


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
    """Create a new virtual interface record in teh database.

    :param values: = dict containing column values
    """
    try:
        vif_ref = models.VirtualInterface()
        vif_ref.update(values)
        vif_ref.save()
    except IntegrityError:
        raise exception.VirtualInterfaceCreateException()

    return vif_ref


@require_context
def virtual_interface_update(context, vif_id, values):
    """Update a virtual interface record in the database.

    :param vif_id: = id of virtual interface to update
    :param values: = values to update
    """
    session = get_session()
    with session.begin():
        vif_ref = virtual_interface_get(context, vif_id, session=session)
        vif_ref.update(values)
        vif_ref.save(session=session)
        return vif_ref


@require_context
def virtual_interface_get(context, vif_id, session=None):
    """Gets a virtual interface from the table.

    :param vif_id: = id of the virtual interface
    """
    if not session:
        session = get_session()

    vif_ref = session.query(models.VirtualInterface).\
                      filter_by(id=vif_id).\
                      options(joinedload('network')).\
                      options(joinedload('instance')).\
                      options(joinedload('fixed_ips')).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_address(context, address):
    """Gets a virtual interface from the table.

    :param address: = the address of the interface you're looking to get
    """
    session = get_session()
    vif_ref = session.query(models.VirtualInterface).\
                      filter_by(address=address).\
                      options(joinedload('network')).\
                      options(joinedload('instance')).\
                      options(joinedload('fixed_ips')).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_uuid(context, vif_uuid):
    """Gets a virtual interface from the table.

    :param vif_uuid: the uuid of the interface you're looking to get
    """
    session = get_session()
    vif_ref = session.query(models.VirtualInterface).\
                      filter_by(uuid=vif_uuid).\
                      options(joinedload('network')).\
                      options(joinedload('instance')).\
                      options(joinedload('fixed_ips')).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_fixed_ip(context, fixed_ip_id):
    """Gets the virtual interface fixed_ip is associated with.

    :param fixed_ip_id: = id of the fixed_ip
    """
    session = get_session()
    vif_ref = session.query(models.VirtualInterface).\
                      filter_by(fixed_ip_id=fixed_ip_id).\
                      options(joinedload('network')).\
                      options(joinedload('instance')).\
                      options(joinedload('fixed_ips')).\
                      first()
    return vif_ref


@require_context
@require_instance_exists
def virtual_interface_get_by_instance(context, instance_id):
    """Gets all virtual interfaces for instance.

    :param instance_id: = id of the instance to retreive vifs for
    """
    session = get_session()
    vif_refs = session.query(models.VirtualInterface).\
                       filter_by(instance_id=instance_id).\
                       options(joinedload('network')).\
                       options(joinedload('instance')).\
                       options(joinedload('fixed_ips')).\
                       all()
    return vif_refs


@require_context
def virtual_interface_get_by_instance_and_network(context, instance_id,
                                                           network_id):
    """Gets virtual interface for instance that's associated with network."""
    session = get_session()
    vif_ref = session.query(models.VirtualInterface).\
                      filter_by(instance_id=instance_id).\
                      filter_by(network_id=network_id).\
                      options(joinedload('network')).\
                      options(joinedload('instance')).\
                      options(joinedload('fixed_ips')).\
                      first()
    return vif_ref


@require_admin_context
def virtual_interface_get_by_network(context, network_id):
    """Gets all virtual_interface on network.

    :param network_id: = network to retreive vifs for
    """
    session = get_session()
    vif_refs = session.query(models.VirtualInterface).\
                       filter_by(network_id=network_id).\
                       options(joinedload('network')).\
                       options(joinedload('instance')).\
                       options(joinedload('fixed_ips')).\
                       all()
    return vif_refs


@require_context
def virtual_interface_delete(context, vif_id):
    """Delete virtual interface record from teh database.

    :param vif_id: = id of vif to delete
    """
    session = get_session()
    vif_ref = virtual_interface_get(context, vif_id, session)
    with session.begin():
        session.delete(vif_ref)


@require_context
def virtual_interface_delete_by_instance(context, instance_id):
    """Delete virtual interface records that are associated
    with the instance given by instance_id.

    :param instance_id: = id of instance
    """
    vif_refs = virtual_interface_get_by_instance(context, instance_id)
    for vif_ref in vif_refs:
        virtual_interface_delete(context, vif_ref['id'])


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


@require_context
def instance_create(context, values):
    """Create a new Instance record in the database.

    context - request context object
    values - dict containing column values.
    """
    values['metadata'] = _metadata_refs(values.get('metadata'),
                                        models.InstanceMetadata)
    instance_ref = models.Instance()
    instance_ref['uuid'] = str(utils.gen_uuid())

    instance_ref.update(values)

    session = get_session()
    with session.begin():
        instance_ref.save(session=session)
    return instance_ref


@require_admin_context
def instance_data_get_for_project(context, project_id):
    session = get_session()
    result = session.query(func.count(models.Instance.id),
                           func.sum(models.Instance.vcpus),
                           func.sum(models.Instance.memory_mb)).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=False).\
                     first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0, result[2] or 0)


@require_context
def instance_destroy(context, instance_id):
    session = get_session()
    with session.begin():
        session.query(models.Instance).\
                filter_by(id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.InstanceMetadata).\
                filter_by(instance_id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def instance_stop(context, instance_id):
    session = get_session()
    with session.begin():
        session.query(models.Instance).\
                filter_by(id=instance_id).\
                update({'host': None,
                        'vm_state': vm_states.STOPPED,
                        'task_state': None,
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_id).\
                update({'updated_at': literal_column('updated_at')})
        session.query(models.InstanceMetadata).\
                filter_by(instance_id=instance_id).\
                update({'updated_at': literal_column('updated_at')})


@require_context
def instance_get_by_uuid(context, uuid, session=None):
    partial = _build_instance_get(context, session=session)
    result = partial.filter_by(uuid=uuid)
    result = result.first()
    if not result:
        # FIXME(sirp): it would be nice if InstanceNotFound would accept a
        # uuid parameter as well
        raise exception.InstanceNotFound(instance_id=uuid)
    return result


@require_context
def instance_get(context, instance_id, session=None):
    partial = _build_instance_get(context, session=session)
    result = partial.filter_by(id=instance_id)
    result = result.first()
    if not result:
        raise exception.InstanceNotFound(instance_id=instance_id)
    return result


@require_context
def _build_instance_get(context, session=None):
    if not session:
        session = get_session()

    partial = session.query(models.Instance).\
                     options(joinedload_all('fixed_ips.floating_ips')).\
                     options(joinedload_all('fixed_ips.network')).\
                     options(joinedload('virtual_interfaces')).\
                     options(joinedload_all('security_groups.rules')).\
                     options(joinedload('volumes')).\
                     options(joinedload('metadata')).\
                     options(joinedload('instance_type'))

    if is_admin_context(context):
        partial = partial.filter_by(deleted=can_read_deleted(context))
    elif is_user_context(context):
        partial = partial.filter_by(project_id=context.project_id).\
                        filter_by(deleted=False)
    return partial


@require_admin_context
def instance_get_all(context):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload_all('virtual_interfaces.network')).\
                   options(joinedload_all(
                           'virtual_interfaces.fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces.instance')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def instance_get_all_by_filters(context, filters):
    """Return instances that match all filters.  Deleted instances
    will be returned by default, unless there's a filter that says
    otherwise"""

    def _regexp_filter_by_ipv6(instance, filter_re):
        for interface in instance['virtual_interfaces']:
            fixed_ipv6 = interface.get('fixed_ipv6')
            if fixed_ipv6 and filter_re.match(fixed_ipv6):
                return True
        return False

    def _regexp_filter_by_ip(instance, filter_re):
        for interface in instance['virtual_interfaces']:
            for fixed_ip in interface['fixed_ips']:
                if not fixed_ip or not fixed_ip['address']:
                    continue
                if filter_re.match(fixed_ip['address']):
                    return True
                for floating_ip in fixed_ip.get('floating_ips', []):
                    if not floating_ip or not floating_ip['address']:
                        continue
                    if filter_re.match(floating_ip['address']):
                        return True
        return False

    def _regexp_filter_by_metadata(instance, meta):
        inst_metadata = [{node['key']: node['value']} \
                         for node in instance['metadata']]
        if isinstance(meta, list):
            for node in meta:
                if node not in inst_metadata:
                    return False
        elif isinstance(meta, dict):
            for k, v in meta.iteritems():
                if {k: v} not in inst_metadata:
                    return False
        return True

    def _regexp_filter_by_column(instance, filter_name, filter_re):
        try:
            v = getattr(instance, filter_name)
        except AttributeError:
            return True
        if v and filter_re.match(str(v)):
            return True
        return False

    def _exact_match_filter(query, column, value):
        """Do exact match against a column.  value to match can be a list
        so you can match any value in the list.
        """
        if isinstance(value, list):
            column_attr = getattr(models.Instance, column)
            return query.filter(column_attr.in_(value))
        else:
            filter_dict = {}
            filter_dict[column] = value
            return query.filter_by(**filter_dict)

    session = get_session()
    query_prefix = session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload_all('virtual_interfaces.network')).\
                   options(joinedload_all(
                           'virtual_interfaces.fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces.instance')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   order_by(desc(models.Instance.created_at))

    # Make a copy of the filters dictionary to use going forward, as we'll
    # be modifying it and we shouldn't affect the caller's use of it.
    filters = filters.copy()

    if 'changes-since' in filters:
        changes_since = filters['changes-since']
        query_prefix = query_prefix.\
                            filter(models.Instance.updated_at > changes_since)

    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            filters['project_id'] = context.project_id
        else:
            filters['user_id'] = context.user_id

    # Filters for exact matches that we can do along with the SQL query...
    # For other filters that don't match this, we will do regexp matching
    exact_match_filter_names = ['project_id', 'user_id', 'image_ref',
            'vm_state', 'instance_type_id', 'deleted']

    query_filters = [key for key in filters.iterkeys()
            if key in exact_match_filter_names]

    for filter_name in query_filters:
        # Do the matching and remove the filter from the dictionary
        # so we don't try it again below..
        query_prefix = _exact_match_filter(query_prefix, filter_name,
                filters.pop(filter_name))

    instances = query_prefix.all()

    if not instances:
        return []

    # Now filter on everything else for regexp matching..
    # For filters not in the list, we'll attempt to use the filter_name
    # as a column name in Instance..
    regexp_filter_funcs = {'ip6': _regexp_filter_by_ipv6,
            'ip': _regexp_filter_by_ip}

    for filter_name in filters.iterkeys():
        filter_func = regexp_filter_funcs.get(filter_name, None)
        filter_re = re.compile(str(filters[filter_name]))
        if filter_func:
            filter_l = lambda instance: filter_func(instance, filter_re)
        elif filter_name == 'metadata':
            filter_l = lambda instance: _regexp_filter_by_metadata(instance,
                    filters[filter_name])
        else:
            filter_l = lambda instance: _regexp_filter_by_column(instance,
                    filter_name, filter_re)
        instances = filter(filter_l, instances)

    return instances


@require_context
def instance_get_active_by_window(context, begin, end=None, project_id=None):
    """Return instances that were continuously active over window."""
    session = get_session()
    query = session.query(models.Instance).\
                    filter(models.Instance.launched_at < begin)
    if end:
        query = query.filter(or_(models.Instance.terminated_at == None,
                                 models.Instance.terminated_at > end))
    else:
        query = query.filter(models.Instance.terminated_at == None)
    if project_id:
        query = query.filter_by(project_id=project_id)
    return query.all()


@require_admin_context
def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None):
    """Return instances and joins that were continuously active over window."""
    session = get_session()
    query = session.query(models.Instance).\
                    options(joinedload_all('fixed_ips.floating_ips')).\
                    options(joinedload('security_groups')).\
                    options(joinedload_all('fixed_ips.network')).\
                    options(joinedload('instance_type')).\
                    filter(models.Instance.launched_at < begin)
    if end:
        query = query.filter(or_(models.Instance.terminated_at == None,
                                 models.Instance.terminated_at > end))
    else:
        query = query.filter(models.Instance.terminated_at == None)
    if project_id:
        query = query.filter_by(project_id=project_id)
    return query.all()


@require_admin_context
def instance_get_all_by_user(context, user_id):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   filter_by(user_id=user_id).\
                   all()


@require_admin_context
def instance_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   filter_by(host=host).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def instance_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def instance_get_all_by_reservation(context, reservation_id):
    session = get_session()
    query = session.query(models.Instance).\
                    filter_by(reservation_id=reservation_id).\
                    options(joinedload_all('fixed_ips.floating_ips')).\
                    options(joinedload('virtual_interfaces')).\
                    options(joinedload('security_groups')).\
                    options(joinedload_all('fixed_ips.network')).\
                    options(joinedload('metadata')).\
                    options(joinedload('instance_type'))

    if is_admin_context(context):
        return query.\
                filter_by(deleted=can_read_deleted(context)).\
                all()
    elif is_user_context(context):
        return query.\
                filter_by(project_id=context.project_id).\
                filter_by(deleted=False).\
                all()


@require_context
def instance_get_by_fixed_ip(context, address):
    """Return instance ref by exact match of FixedIP"""
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    return fixed_ip_ref.instance


@require_context
def instance_get_by_fixed_ipv6(context, address):
    """Return instance ref by exact match of IPv6"""
    session = get_session()

    # convert IPv6 address to mac
    mac = ipv6.to_mac(address)

    # get virtual interface
    vif_ref = virtual_interface_get_by_address(context, mac)

    # look up instance based on instance_id from vif row
    result = session.query(models.Instance).\
                     filter_by(id=vif_ref['instance_id'])
    return result


@require_admin_context
def instance_get_project_vpn(context, project_id):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('virtual_interfaces')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(image_ref=str(FLAGS.vpn_image_id)).\
                   filter_by(deleted=can_read_deleted(context)).\
                   first()


@require_context
def instance_get_fixed_addresses(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        try:
            fixed_ips = fixed_ip_get_by_instance(context, instance_id)
        except exception.NotFound:
            return []
        return [fixed_ip.address for fixed_ip in fixed_ips]


@require_context
def instance_get_fixed_addresses_v6(context, instance_id):
    session = get_session()
    with session.begin():
        # get instance
        instance_ref = instance_get(context, instance_id, session=session)
        # assume instance has 1 mac for each network associated with it
        # get networks associated with instance
        network_refs = network_get_all_by_instance(context, instance_id)
        # compile a list of cidr_v6 prefixes sorted by network id
        prefixes = [ref.cidr_v6 for ref in
                sorted(network_refs, key=lambda ref: ref.id)]
        # get vifs associated with instance
        vif_refs = virtual_interface_get_by_instance(context, instance_ref.id)
        # compile list of the mac_addresses for vifs sorted by network id
        macs = [vif_ref['address'] for vif_ref in
                sorted(vif_refs, key=lambda vif_ref: vif_ref['network_id'])]
        # get project id from instance
        project_id = instance_ref.project_id
        # combine prefixes, macs, and project_id into (prefix,mac,p_id) tuples
        prefix_mac_tuples = zip(prefixes, macs, [project_id for m in macs])
        # return list containing ipv6 address for each tuple
        return [ipv6.to_global(*t) for t in prefix_mac_tuples]


@require_context
def instance_get_floating_address(context, instance_id):
    fixed_ip_refs = fixed_ip_get_by_instance(context, instance_id)
    if not fixed_ip_refs:
        return None
    # NOTE(tr3buchet): this only gets the first fixed_ip
    # won't find floating ips associated with other fixed_ips
    if not fixed_ip_refs[0].floating_ips:
        return None
    # NOTE(vish): this just returns the first floating ip
    return fixed_ip_refs[0].floating_ips[0]['address']


@require_context
def instance_update(context, instance_id, values):
    session = get_session()
    metadata = values.get('metadata')
    if metadata is not None:
        instance_metadata_update(context,
                                 instance_id,
                                 values.pop('metadata'),
                                 delete=True)
    with session.begin():
        if utils.is_uuid_like(instance_id):
            instance_ref = instance_get_by_uuid(context, instance_id,
                                                session=session)
        else:
            instance_ref = instance_get(context, instance_id, session=session)
        instance_ref.update(values)
        instance_ref.save(session=session)
        return instance_ref


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance"""
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        security_group_ref = security_group_get(context,
                                                security_group_id,
                                                session=session)
        instance_ref.security_groups += [security_group_ref]
        instance_ref.save(session=session)


@require_context
def instance_remove_security_group(context, instance_id, security_group_id):
    """Disassociate the given security group from the given instance"""
    session = get_session()

    session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_id).\
                filter_by(security_group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def instance_action_create(context, values):
    """Create an instance action from the values dictionary."""
    action_ref = models.InstanceActions()
    action_ref.update(values)

    session = get_session()
    with session.begin():
        action_ref.save(session=session)
    return action_ref


@require_admin_context
def instance_get_actions(context, instance_id):
    """Return the actions associated to the given instance id"""
    session = get_session()

    if utils.is_uuid_like(instance_id):
        instance = instance_get_by_uuid(context, instance_id, session)
        instance_id = instance.id

    return session.query(models.InstanceActions).\
        filter_by(instance_id=instance_id).\
       all()


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
    session = get_session()
    with session.begin():
        key_pair_ref = key_pair_get(context, user_id, name, session=session)
        key_pair_ref.delete(session=session)


@require_context
def key_pair_destroy_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    session = get_session()
    with session.begin():
        session.query(models.KeyPair).\
                filter_by(user_id=user_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def key_pair_get(context, user_id, name, session=None):
    authorize_user_context(context, user_id)

    if not session:
        session = get_session()

    result = session.query(models.KeyPair).\
                     filter_by(user_id=user_id).\
                     filter_by(name=name).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()
    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)
    return result


@require_context
def key_pair_get_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    session = get_session()
    return session.query(models.KeyPair).\
                   filter_by(user_id=user_id).\
                   filter_by(deleted=False).\
                   all()


###################


@require_admin_context
def network_associate(context, project_id, force=False):
    """Associate a project with a network.

    called by project_get_networks under certain conditions
    and network manager add_network_to_project()

    only associate if the project doesn't already have a network
    or if force is True

    force solves race condition where a fresh project has multiple instance
    builds simultaneosly picked up by multiple network hosts which attempt
    to associate the project with multiple networks
    force should only be used as a direct consequence of user request
    all automated requests should not use force
    """
    session = get_session()
    with session.begin():

        def network_query(project_filter):
            return session.query(models.Network).\
                           filter_by(deleted=False).\
                           filter_by(project_id=project_filter).\
                           with_lockmode('update').\
                           first()

        if not force:
            # find out if project has a network
            network_ref = network_query(project_id)

        if force or not network_ref:
            # in force mode or project doesn't have a network so assocaite
            # with a new network

            # get new network
            network_ref = network_query(None)
            if not network_ref:
                raise db.NoMoreNetworks()

            # associate with network
            # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
            #             then this has concurrency issues
            network_ref['project_id'] = project_id
            session.add(network_ref)
    return network_ref


@require_admin_context
def network_count(context):
    session = get_session()
    return session.query(models.Network).\
                   filter_by(deleted=can_read_deleted(context)).\
                   count()


@require_admin_context
def network_count_allocated_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp).\
                   filter_by(network_id=network_id).\
                   filter_by(allocated=True).\
                   filter_by(deleted=False).\
                   count()


@require_admin_context
def network_count_available_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp).\
                   filter_by(network_id=network_id).\
                   filter_by(allocated=False).\
                   filter_by(reserved=False).\
                   filter_by(deleted=False).\
                   count()


@require_admin_context
def network_count_reserved_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp).\
                   filter_by(network_id=network_id).\
                   filter_by(reserved=True).\
                   filter_by(deleted=False).\
                   count()


@require_admin_context
def network_create_safe(context, values):
    network_ref = models.Network()
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
        network_ref = network_get(context, network_id=network_id, \
                                  session=session)
        session.delete(network_ref)


@require_admin_context
def network_disassociate(context, network_id):
    network_update(context, network_id, {'project_id': None,
                                         'host': None})


@require_admin_context
def network_disassociate_all(context):
    session = get_session()
    session.query(models.Network).\
            update({'project_id': None,
                    'updated_at': literal_column('updated_at')})


@require_context
def network_get(context, network_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Network).\
                         filter_by(id=network_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.Network).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=network_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.NetworkNotFound(network_id=network_id)

    return result


@require_admin_context
def network_get_all(context):
    session = get_session()
    result = session.query(models.Network).\
                 filter_by(deleted=False).all()
    if not result:
        raise exception.NoNetworksFound()
    return result


@require_admin_context
def network_get_all_by_uuids(context, network_uuids, project_id=None):
    session = get_session()
    project_or_none = or_(models.Network.project_id == project_id,
                              models.Network.project_id == None)
    result = session.query(models.Network).\
                 filter(models.Network.uuid.in_(network_uuids)).\
                 filter(project_or_none).\
                 filter_by(deleted=False).all()
    if not result:
        raise exception.NoNetworksFound()

    #check if host is set to all of the networks
    # returned in the result
    for network in result:
            if network['host'] is None:
                raise exception.NetworkHostNotSet(network_id=network['id'])

    #check if the result contains all the networks
    #we are looking for
    for network_uuid in network_uuids:
        found = False
        for network in result:
            if network['uuid'] == network_uuid:
                found = True
                break
        if not found:
            if project_id:
                raise exception.NetworkNotFoundForProject(network_uuid=uuid,
                                              project_id=context.project_id)
            raise exception.NetworkNotFound(network_id=network_uuid)

    return result

# NOTE(vish): pylint complains because of the long method name, but
#             it fits with the names of the rest of the methods
# pylint: disable=C0103


@require_admin_context
def network_get_associated_fixed_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp).\
                   options(joinedload_all('instance')).\
                   filter_by(network_id=network_id).\
                   filter(models.FixedIp.instance_id != None).\
                   filter(models.FixedIp.virtual_interface_id != None).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def network_get_by_bridge(context, bridge):
    session = get_session()
    result = session.query(models.Network).\
                 filter_by(bridge=bridge).\
                 filter_by(deleted=False).\
                 first()

    if not result:
        raise exception.NetworkNotFoundForBridge(bridge=bridge)
    return result


@require_admin_context
def network_get_by_uuid(context, uuid):
    session = get_session()
    result = session.query(models.Network).\
                 filter_by(uuid=uuid).\
                 filter_by(deleted=False).\
                 first()

    if not result:
        raise exception.NetworkNotFoundForUUID(uuid=uuid)
    return result


@require_admin_context
def network_get_by_cidr(context, cidr):
    session = get_session()
    result = session.query(models.Network).\
                filter(or_(models.Network.cidr == cidr,
                           models.Network.cidr_v6 == cidr)).\
                filter_by(deleted=False).\
                first()

    if not result:
        raise exception.NetworkNotFoundForCidr(cidr=cidr)
    return result


@require_admin_context
def network_get_by_instance(_context, instance_id):
    # note this uses fixed IP to get to instance
    # only works for networks the instance has an IP from
    session = get_session()
    rv = session.query(models.Network).\
                 filter_by(deleted=False).\
                 join(models.Network.fixed_ips).\
                 filter_by(instance_id=instance_id).\
                 filter_by(deleted=False).\
                 first()
    if not rv:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)
    return rv


@require_admin_context
def network_get_all_by_instance(_context, instance_id):
    session = get_session()
    rv = session.query(models.Network).\
                 filter_by(deleted=False).\
                 join(models.Network.fixed_ips).\
                 filter_by(instance_id=instance_id).\
                 filter_by(deleted=False).\
                 all()
    if not rv:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)
    return rv


@require_admin_context
def network_get_all_by_host(context, host):
    session = get_session()
    with session.begin():
        # NOTE(vish): return networks that have host set
        #             or that have a fixed ip with host set
        host_filter = or_(models.Network.host == host,
                          models.FixedIp.host == host)

        return session.query(models.Network).\
                       filter_by(deleted=False).\
                       join(models.Network.fixed_ips).\
                       filter(host_filter).\
                       filter_by(deleted=False).\
                       all()


@require_admin_context
def network_set_host(context, network_id, host_id):
    session = get_session()
    with session.begin():
        network_ref = session.query(models.Network).\
                              filter_by(id=network_id).\
                              filter_by(deleted=False).\
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


def queue_get_for(_context, topic, physical_node_id):
    # FIXME(ja): this should be servername?
    return "%s.%s" % (topic, physical_node_id)


###################


@require_admin_context
def export_device_count(context):
    session = get_session()
    return session.query(models.ExportDevice).\
                   filter_by(deleted=can_read_deleted(context)).\
                   count()


@require_admin_context
def export_device_create_safe(context, values):
    export_device_ref = models.ExportDevice()
    export_device_ref.update(values)
    try:
        export_device_ref.save()
        return export_device_ref
    except IntegrityError:
        return None


###################


@require_admin_context
def iscsi_target_count_by_host(context, host):
    session = get_session()
    return session.query(models.IscsiTarget).\
                   filter_by(deleted=can_read_deleted(context)).\
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


@require_admin_context
def auth_token_destroy(context, token_id):
    session = get_session()
    with session.begin():
        token_ref = auth_token_get(context, token_id, session=session)
        token_ref.delete(session=session)


@require_admin_context
def auth_token_get(context, token_hash, session=None):
    if session is None:
        session = get_session()
    tk = session.query(models.AuthToken).\
                  filter_by(token_hash=token_hash).\
                  filter_by(deleted=can_read_deleted(context)).\
                  first()
    if not tk:
        raise exception.AuthTokenNotFound(token=token_hash)
    return tk


@require_admin_context
def auth_token_update(context, token_hash, values):
    session = get_session()
    with session.begin():
        token_ref = auth_token_get(context, token_hash, session=session)
        token_ref.update(values)
        token_ref.save(session=session)


@require_admin_context
def auth_token_create(_context, token):
    tk = models.AuthToken()
    tk.update(token)
    tk.save()
    return tk


###################


@require_context
def quota_get(context, project_id, resource, session=None):
    if not session:
        session = get_session()
    result = session.query(models.Quota).\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     filter_by(deleted=False).\
                     first()
    if not result:
        raise exception.ProjectQuotaNotFound(project_id=project_id)
    return result


@require_context
def quota_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    result = {'project_id': project_id}
    rows = session.query(models.Quota).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   all()
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
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, resource, session=session)
        quota_ref.hard_limit = limit
        quota_ref.save(session=session)


@require_admin_context
def quota_destroy(context, project_id, resource):
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, resource, session=session)
        quota_ref.delete(session=session)


@require_admin_context
def quota_destroy_all_by_project(context, project_id):
    session = get_session()
    with session.begin():
        quotas = session.query(models.Quota).\
                         filter_by(project_id=project_id).\
                         filter_by(deleted=False).\
                         all()
        for quota_ref in quotas:
            quota_ref.delete(session=session)


###################


@require_admin_context
def volume_allocate_shelf_and_blade(context, volume_id):
    session = get_session()
    with session.begin():
        export_device = session.query(models.ExportDevice).\
                                filter_by(volume=None).\
                                filter_by(deleted=False).\
                                with_lockmode('update').\
                                first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not export_device:
            raise db.NoMoreBlades()
        export_device.volume_id = volume_id
        session.add(export_device)
    return (export_device.shelf_id, export_device.blade_id)


@require_admin_context
def volume_allocate_iscsi_target(context, volume_id, host):
    session = get_session()
    with session.begin():
        iscsi_target_ref = session.query(models.IscsiTarget).\
                                filter_by(volume=None).\
                                filter_by(host=host).\
                                filter_by(deleted=False).\
                                with_lockmode('update').\
                                first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not iscsi_target_ref:
            raise db.NoMoreTargets()
        iscsi_target_ref.volume_id = volume_id
        session.add(iscsi_target_ref)
    return iscsi_target_ref.target_num


@require_admin_context
def volume_attached(context, volume_id, instance_id, mountpoint):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'in-use'
        volume_ref['mountpoint'] = mountpoint
        volume_ref['attach_status'] = 'attached'
        volume_ref.instance = instance_get(context, instance_id,
                                           session=session)
        volume_ref.save(session=session)


@require_context
def volume_create(context, values):
    values['volume_metadata'] = _metadata_refs(values.get('metadata'),
                                               models.VolumeMetadata)
    volume_ref = models.Volume()
    volume_ref.update(values)

    session = get_session()
    with session.begin():
        volume_ref.save(session=session)
    return volume_ref


@require_admin_context
def volume_data_get_for_project(context, project_id):
    session = get_session()
    result = session.query(func.count(models.Volume.id),
                           func.sum(models.Volume.size)).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=False).\
                     first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_admin_context
def volume_destroy(context, volume_id):
    session = get_session()
    with session.begin():
        session.query(models.Volume).\
                filter_by(id=volume_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.ExportDevice).\
                filter_by(volume_id=volume_id).\
                update({'volume_id': None})
        session.query(models.IscsiTarget).\
                filter_by(volume_id=volume_id).\
                update({'volume_id': None})
        session.query(models.VolumeMetadata).\
                filter_by(volume_id=volume_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_admin_context
def volume_detached(context, volume_id):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'available'
        volume_ref['mountpoint'] = None
        volume_ref['attach_status'] = 'detached'
        volume_ref.instance = None
        volume_ref.save(session=session)


@require_context
def volume_get(context, volume_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Volume).\
                         options(joinedload('instance')).\
                         options(joinedload('volume_metadata')).\
                         options(joinedload('volume_type')).\
                         filter_by(id=volume_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.Volume).\
                         options(joinedload('instance')).\
                         options(joinedload('volume_metadata')).\
                         options(joinedload('volume_type')).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=volume_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result


@require_admin_context
def volume_get_all(context):
    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
                   options(joinedload('volume_metadata')).\
                   options(joinedload('volume_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def volume_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
                   options(joinedload('volume_metadata')).\
                   options(joinedload('volume_type')).\
                   filter_by(host=host).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def volume_get_all_by_instance(context, instance_id):
    session = get_session()
    result = session.query(models.Volume).\
                     options(joinedload('volume_metadata')).\
                     options(joinedload('volume_type')).\
                     filter_by(instance_id=instance_id).\
                     filter_by(deleted=False).\
                     all()
    if not result:
        raise exception.VolumeNotFoundForInstance(instance_id=instance_id)
    return result


@require_context
def volume_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
                   options(joinedload('volume_metadata')).\
                   options(joinedload('volume_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def volume_get_instance(context, volume_id):
    session = get_session()
    result = session.query(models.Volume).\
                     filter_by(id=volume_id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     options(joinedload('instance')).\
                     options(joinedload('volume_metadata')).\
                     options(joinedload('volume_type')).\
                     first()
    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result.instance


@require_admin_context
def volume_get_shelf_and_blade(context, volume_id):
    session = get_session()
    result = session.query(models.ExportDevice).\
                     filter_by(volume_id=volume_id).\
                     first()
    if not result:
        raise exception.ExportDeviceNotFoundForVolume(volume_id=volume_id)

    return (result.shelf_id, result.blade_id)


@require_admin_context
def volume_get_iscsi_target_num(context, volume_id):
    session = get_session()
    result = session.query(models.IscsiTarget).\
                     filter_by(volume_id=volume_id).\
                     first()
    if not result:
        raise exception.ISCSITargetNotFoundForVolume(volume_id=volume_id)

    return result.target_num


@require_context
def volume_update(context, volume_id, values):
    session = get_session()
    metadata = values.get('metadata')
    if metadata is not None:
        volume_metadata_update(context,
                                volume_id,
                                values.pop('metadata'),
                                delete=True)
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref.update(values)
        volume_ref.save(session=session)


####################


@require_context
@require_volume_exists
def volume_metadata_get(context, volume_id):
    session = get_session()

    meta_results = session.query(models.VolumeMetadata).\
                    filter_by(volume_id=volume_id).\
                    filter_by(deleted=False).\
                    all()

    meta_dict = {}
    for i in meta_results:
        meta_dict[i['key']] = i['value']
    return meta_dict


@require_context
@require_volume_exists
def volume_metadata_delete(context, volume_id, key):
    session = get_session()
    session.query(models.VolumeMetadata).\
        filter_by(volume_id=volume_id).\
        filter_by(key=key).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_volume_exists
def volume_metadata_delete_all(context, volume_id):
    session = get_session()
    session.query(models.VolumeMetadata).\
        filter_by(volume_id=volume_id).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_volume_exists
def volume_metadata_get_item(context, volume_id, key, session=None):
    if not session:
        session = get_session()

    meta_result = session.query(models.VolumeMetadata).\
                    filter_by(volume_id=volume_id).\
                    filter_by(key=key).\
                    filter_by(deleted=False).\
                    first()

    if not meta_result:
        raise exception.VolumeMetadataNotFound(metadata_key=key,
                                               volume_id=volume_id)
    return meta_result


@require_context
@require_volume_exists
def volume_metadata_update(context, volume_id, metadata, delete):
    session = get_session()

    # Set existing metadata to deleted if delete argument is True
    if delete:
        original_metadata = volume_metadata_get(context, volume_id)
        for meta_key, meta_value in original_metadata.iteritems():
            if meta_key not in metadata:
                meta_ref = volume_metadata_get_item(context, volume_id,
                                                    meta_key, session)
                meta_ref.update({'deleted': True})
                meta_ref.save(session=session)

    meta_ref = None

    # Now update all existing items with new values, or create new meta objects
    for meta_key, meta_value in metadata.iteritems():

        # update the value whether it exists or not
        item = {"value": meta_value}

        try:
            meta_ref = volume_metadata_get_item(context, volume_id,
                                                  meta_key, session)
        except exception.VolumeMetadataNotFound, e:
            meta_ref = models.VolumeMetadata()
            item.update({"key": meta_key, "volume_id": volume_id})

        meta_ref.update(item)
        meta_ref.save(session=session)

    return metadata


###################


@require_context
def snapshot_create(context, values):
    snapshot_ref = models.Snapshot()
    snapshot_ref.update(values)

    session = get_session()
    with session.begin():
        snapshot_ref.save(session=session)
    return snapshot_ref


@require_admin_context
def snapshot_destroy(context, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.Snapshot).\
                filter_by(id=snapshot_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def snapshot_get(context, snapshot_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Snapshot).\
                         filter_by(id=snapshot_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.Snapshot).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=snapshot_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result


@require_admin_context
def snapshot_get_all(context):
    session = get_session()
    return session.query(models.Snapshot).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def snapshot_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Snapshot).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def snapshot_update(context, snapshot_id, values):
    session = get_session()
    with session.begin():
        snapshot_ref = snapshot_get(context, snapshot_id, session=session)
        snapshot_ref.update(values)
        snapshot_ref.save(session=session)


###################


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
        session.query(models.BlockDeviceMapping).\
                filter_by(id=bdm_id).\
                filter_by(deleted=False).\
                update(values)


@require_context
def block_device_mapping_update_or_create(context, values):
    session = get_session()
    with session.begin():
        result = session.query(models.BlockDeviceMapping).\
                 filter_by(instance_id=values['instance_id']).\
                 filter_by(device_name=values['device_name']).\
                 filter_by(deleted=False).\
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
            filter_by(instance_id=values['instance_id']).\
            filter_by(virtual_name=virtual_name).\
            filter(models.BlockDeviceMapping.device_name !=
                   values['device_name']).\
            update({'deleted': True,
                    'deleted_at': utils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_context
def block_device_mapping_get_all_by_instance(context, instance_id):
    session = get_session()
    result = session.query(models.BlockDeviceMapping).\
             filter_by(instance_id=instance_id).\
             filter_by(deleted=False).\
             all()
    if not result:
        return []
    return result


@require_context
def block_device_mapping_destroy(context, bdm_id):
    session = get_session()
    with session.begin():
        session.query(models.BlockDeviceMapping).\
                filter_by(id=bdm_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def block_device_mapping_destroy_by_instance_and_volume(context, instance_id,
                                                        volume_id):
    session = get_session()
    with session.begin():
        session.query(models.BlockDeviceMapping).\
        filter_by(instance_id=instance_id).\
        filter_by(volume_id=volume_id).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


###################


@require_context
def security_group_get_all(context):
    session = get_session()
    return session.query(models.SecurityGroup).\
                   filter_by(deleted=can_read_deleted(context)).\
                   options(joinedload_all('rules')).\
                   all()


@require_context
def security_group_get(context, security_group_id, session=None):
    if not session:
        session = get_session()
    if is_admin_context(context):
        result = session.query(models.SecurityGroup).\
                         filter_by(deleted=can_read_deleted(context),).\
                         filter_by(id=security_group_id).\
                         options(joinedload_all('rules')).\
                         options(joinedload_all('instances')).\
                         first()
    else:
        result = session.query(models.SecurityGroup).\
                         filter_by(deleted=False).\
                         filter_by(id=security_group_id).\
                         filter_by(project_id=context.project_id).\
                         options(joinedload_all('rules')).\
                         options(joinedload_all('instances')).\
                         first()
    if not result:
        raise exception.SecurityGroupNotFound(
                security_group_id=security_group_id)
    return result


@require_context
def security_group_get_by_name(context, project_id, group_name):
    session = get_session()
    result = session.query(models.SecurityGroup).\
                        filter_by(project_id=project_id).\
                        filter_by(name=group_name).\
                        filter_by(deleted=False).\
                        options(joinedload_all('rules')).\
                        options(joinedload_all('instances')).\
                        first()
    if not result:
        raise exception.SecurityGroupNotFoundForProject(project_id=project_id,
                                                 security_group_id=group_name)
    return result


@require_context
def security_group_get_by_project(context, project_id):
    session = get_session()
    return session.query(models.SecurityGroup).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   options(joinedload_all('rules')).\
                   all()


@require_context
def security_group_get_by_instance(context, instance_id):
    session = get_session()
    return session.query(models.SecurityGroup).\
                   filter_by(deleted=False).\
                   options(joinedload_all('rules')).\
                   join(models.SecurityGroup.instances).\
                   filter_by(id=instance_id).\
                   filter_by(deleted=False).\
                   all()


@require_context
def security_group_exists(context, project_id, group_name):
    try:
        group = security_group_get_by_name(context, project_id, group_name)
        return group is not None
    except exception.NotFound:
        return False


@require_context
def security_group_create(context, values):
    security_group_ref = models.SecurityGroup()
    # FIXME(devcamcar): Unless I do this, rules fails with lazy load exception
    # once save() is called.  This will get cleaned up in next orm pass.
    security_group_ref.rules
    security_group_ref.update(values)
    security_group_ref.save()
    return security_group_ref


@require_context
def security_group_destroy(context, security_group_id):
    session = get_session()
    with session.begin():
        session.query(models.SecurityGroup).\
                filter_by(id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(security_group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupIngressRule).\
                filter_by(group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def security_group_destroy_all(context, session=None):
    if not session:
        session = get_session()
    with session.begin():
        session.query(models.SecurityGroup).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupIngressRule).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


###################


@require_context
def security_group_rule_get(context, security_group_rule_id, session=None):
    if not session:
        session = get_session()
    if is_admin_context(context):
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=can_read_deleted(context)).\
                         filter_by(id=security_group_rule_id).\
                         first()
    else:
        # TODO(vish): Join to group and check for project_id
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=False).\
                         filter_by(id=security_group_rule_id).\
                         first()
    if not result:
        raise exception.SecurityGroupNotFoundForRule(
                                               rule_id=security_group_rule_id)
    return result


@require_context
def security_group_rule_get_by_security_group(context, security_group_id,
                                              session=None):
    if not session:
        session = get_session()
    if is_admin_context(context):
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=can_read_deleted(context)).\
                         filter_by(parent_group_id=security_group_id).\
                         options(joinedload_all('grantee_group.instances')).\
                         all()
    else:
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=False).\
                         filter_by(parent_group_id=security_group_id).\
                         options(joinedload_all('grantee_group.instances')).\
                         all()
    return result


@require_context
def security_group_rule_get_by_security_group_grantee(context,
                                                      security_group_id,
                                                      session=None):
    if not session:
        session = get_session()
    if is_admin_context(context):
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=can_read_deleted(context)).\
                         filter_by(group_id=security_group_id).\
                         all()
    else:
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=False).\
                         filter_by(group_id=security_group_id).\
                         all()
    return result


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
        security_group_rule = security_group_rule_get(context,
                                                      security_group_rule_id,
                                                      session=session)
        security_group_rule.delete(session=session)


###################


@require_admin_context
def provider_fw_rule_create(context, rule):
    fw_rule_ref = models.ProviderFirewallRule()
    fw_rule_ref.update(rule)
    fw_rule_ref.save()
    return fw_rule_ref


@require_admin_context
def provider_fw_rule_get_all(context):
    session = get_session()
    return session.query(models.ProviderFirewallRule).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def provider_fw_rule_get_all_by_cidr(context, cidr):
    session = get_session()
    return session.query(models.ProviderFirewallRule).\
                   filter_by(deleted=can_read_deleted(context)).\
                   filter_by(cidr=cidr).\
                   all()


@require_admin_context
def provider_fw_rule_destroy(context, rule_id):
    session = get_session()
    with session.begin():
        session.query(models.ProviderFirewallRule).\
                filter_by(id=rule_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


###################


@require_admin_context
def user_get(context, id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.User).\
                     filter_by(id=id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()

    if not result:
        raise exception.UserNotFound(user_id=id)

    return result


@require_admin_context
def user_get_by_access_key(context, access_key, session=None):
    if not session:
        session = get_session()

    result = session.query(models.User).\
                   filter_by(access_key=access_key).\
                   filter_by(deleted=can_read_deleted(context)).\
                   first()

    if not result:
        raise exception.AccessKeyNotFound(access_key=access_key)

    return result


@require_admin_context
def user_create(_context, values):
    user_ref = models.User()
    user_ref.update(values)
    user_ref.save()
    return user_ref


@require_admin_context
def user_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectAssociation).\
                filter_by(user_id=id).\
                delete()
        session.query(models.UserRoleAssociation).\
                filter_by(user_id=id).\
                delete()
        session.query(models.UserProjectRoleAssociation).\
                filter_by(user_id=id).\
                delete()
        user_ref = user_get(context, id, session=session)
        session.delete(user_ref)


def user_get_all(context):
    session = get_session()
    return session.query(models.User).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


def user_get_roles(context, user_id):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        return [role.role for role in user_ref['roles']]


def user_get_roles_for_project(context, user_id, project_id):
    session = get_session()
    with session.begin():
        res = session.query(models.UserProjectRoleAssociation).\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   all()
        return [association.role for association in res]


def user_remove_project_role(context, user_id, project_id, role):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectRoleAssociation).\
                filter_by(user_id=user_id).\
                filter_by(project_id=project_id).\
                filter_by(role=role).\
                delete()


def user_remove_role(context, user_id, role):
    session = get_session()
    with session.begin():
        res = session.query(models.UserRoleAssociation).\
                    filter_by(user_id=user_id).\
                    filter_by(role=role).\
                    all()
        for role in res:
            session.delete(role)


def user_add_role(context, user_id, role):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        models.UserRoleAssociation(user=user_ref, role=role).\
               save(session=session)


def user_add_project_role(context, user_id, project_id, role):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        project_ref = project_get(context, project_id, session=session)
        models.UserProjectRoleAssociation(user_id=user_ref['id'],
                                          project_id=project_ref['id'],
                                          role=role).save(session=session)


def user_update(context, user_id, values):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        user_ref.update(values)
        user_ref.save(session=session)


###################


def project_create(_context, values):
    project_ref = models.Project()
    project_ref.update(values)
    project_ref.save()
    return project_ref


def project_add_member(context, project_id, user_id):
    session = get_session()
    with session.begin():
        project_ref = project_get(context, project_id, session=session)
        user_ref = user_get(context, user_id, session=session)

        project_ref.members += [user_ref]
        project_ref.save(session=session)


def project_get(context, id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Project).\
                     filter_by(deleted=False).\
                     filter_by(id=id).\
                     options(joinedload_all('members')).\
                     first()

    if not result:
        raise exception.ProjectNotFound(project_id=id)

    return result


def project_get_all(context):
    session = get_session()
    return session.query(models.Project).\
                   filter_by(deleted=can_read_deleted(context)).\
                   options(joinedload_all('members')).\
                   all()


def project_get_by_user(context, user_id):
    session = get_session()
    user = session.query(models.User).\
                   filter_by(deleted=can_read_deleted(context)).\
                   filter_by(id=user_id).\
                   options(joinedload_all('projects')).\
                   first()
    if not user:
        raise exception.UserNotFound(user_id=user_id)
    return user.projects


def project_remove_member(context, project_id, user_id):
    session = get_session()
    project = project_get(context, project_id, session=session)
    user = user_get(context, user_id, session=session)

    if user in project.members:
        project.members.remove(user)
        project.save(session=session)


def project_update(context, project_id, values):
    session = get_session()
    with session.begin():
        project_ref = project_get(context, project_id, session=session)
        project_ref.update(values)
        project_ref.save(session=session)


def project_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectAssociation).\
                filter_by(project_id=id).\
                delete()
        session.query(models.UserProjectRoleAssociation).\
                filter_by(project_id=id).\
                delete()
        project_ref = project_get(context, id, session=session)
        session.delete(project_ref)


@require_context
def project_get_networks(context, project_id, associate=True):
    # NOTE(tr3buchet): as before this function will associate
    # a project with a network if it doesn't have one and
    # associate is true
    session = get_session()
    result = session.query(models.Network).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=False).all()

    if not result:
        if not associate:
            return []
        return [network_associate(context, project_id)]
    return result


@require_context
def project_get_networks_v6(context, project_id):
    return project_get_networks(context, project_id)


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
    if not session:
        session = get_session()
    result = session.query(models.Migration).\
                     filter_by(id=id).first()
    if not result:
        raise exception.MigrationNotFound(migration_id=id)
    return result


@require_admin_context
def migration_get_by_instance_and_status(context, instance_uuid, status):
    session = get_session()
    result = session.query(models.Migration).\
                     filter_by(instance_uuid=instance_uuid).\
                     filter_by(status=status).first()
    if not result:
        raise exception.MigrationNotFoundByStatus(instance_id=instance_uuid,
                                                  status=status)
    return result


##################


def console_pool_create(context, values):
    pool = models.ConsolePool()
    pool.update(values)
    pool.save()
    return pool


def console_pool_get(context, pool_id):
    session = get_session()
    result = session.query(models.ConsolePool).\
                     filter_by(deleted=False).\
                     filter_by(id=pool_id).\
                     first()
    if not result:
        raise exception.ConsolePoolNotFound(pool_id=pool_id)

    return result


def console_pool_get_by_host_type(context, compute_host, host,
                                  console_type):
    session = get_session()
    result = session.query(models.ConsolePool).\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   filter_by(compute_host=compute_host).\
                   filter_by(deleted=False).\
                   options(joinedload('consoles')).\
                   first()
    if not result:
        raise exception.ConsolePoolNotFoundForHostType(host=host,
                                                  console_type=console_type,
                                                  compute_host=compute_host)
    return result


def console_pool_get_all_by_host_type(context, host, console_type):
    session = get_session()
    return session.query(models.ConsolePool).\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   filter_by(deleted=False).\
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
        # consoles are meant to be transient. (mdragon)
        session.query(models.Console).\
                filter_by(id=console_id).\
                delete()


def console_get_by_pool_instance(context, pool_id, instance_id):
    session = get_session()
    result = session.query(models.Console).\
                   filter_by(pool_id=pool_id).\
                   filter_by(instance_id=instance_id).\
                   options(joinedload('pool')).\
                   first()
    if not result:
        raise exception.ConsoleNotFoundInPoolForInstance(pool_id=pool_id,
                                                 instance_id=instance_id)
    return result


def console_get_all_by_instance(context, instance_id):
    session = get_session()
    results = session.query(models.Console).\
                   filter_by(instance_id=instance_id).\
                   options(joinedload('pool')).\
                   all()
    return results


def console_get(context, console_id, instance_id=None):
    session = get_session()
    query = session.query(models.Console).\
                    filter_by(id=console_id)
    if instance_id:
        query = query.filter_by(instance_id=instance_id)
    result = query.options(joinedload('pool')).first()
    if not result:
        if instance_id:
            raise exception.ConsoleNotFoundForInstance(console_id=console_id,
                                                       instance_id=instance_id)
        else:
            raise exception.ConsoleNotFound(console_id=console_id)
    return result


    ##################


@require_admin_context
def instance_type_create(_context, values):
    """Create a new instance type. In order to pass in extra specs,
    the values dict should contain a 'extra_specs' key/value pair:

    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}

    """
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
        instance_type_ref.save()
    except Exception, e:
        raise exception.DBError(e)
    return instance_type_ref


def _dict_with_extra_specs(inst_type_query):
    """Takes an instance OR volume type query returned by sqlalchemy
    and returns it as a dictionary, converting the extra_specs
    entry from a list of dicts:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]

    to a single dict:

    'extra_specs' : {'k1': 'v1'}

    """
    inst_type_dict = dict(inst_type_query)
    extra_specs = dict([(x['key'], x['value']) for x in \
                        inst_type_query['extra_specs']])
    inst_type_dict['extra_specs'] = extra_specs
    return inst_type_dict


@require_context
def instance_type_get_all(context, inactive=False):
    """
    Returns a dict describing all instance_types with name as key.
    """
    session = get_session()
    if inactive:
        inst_types = session.query(models.InstanceTypes).\
                        options(joinedload('extra_specs')).\
                        order_by("name").\
                        all()
    else:
        inst_types = session.query(models.InstanceTypes).\
                        options(joinedload('extra_specs')).\
                        filter_by(deleted=False).\
                        order_by("name").\
                        all()
    inst_dict = {}
    if inst_types:
        for i in inst_types:
            inst_dict[i['name']] = _dict_with_extra_specs(i)
    return inst_dict


@require_context
def instance_type_get(context, id):
    """Returns a dict describing specific instance_type"""
    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                    options(joinedload('extra_specs')).\
                    filter_by(id=id).\
                    first()

    if not inst_type:
        raise exception.InstanceTypeNotFound(instance_type=id)
    else:
        return _dict_with_extra_specs(inst_type)


@require_context
def instance_type_get_by_name(context, name):
    """Returns a dict describing specific instance_type"""
    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                    options(joinedload('extra_specs')).\
                    filter_by(name=name).\
                    first()
    if not inst_type:
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)
    else:
        return _dict_with_extra_specs(inst_type)


@require_context
def instance_type_get_by_flavor_id(context, id):
    """Returns a dict describing specific flavor_id"""
    try:
        flavor_id = int(id)
    except ValueError:
        raise exception.FlavorNotFound(flavor_id=id)

    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                                    options(joinedload('extra_specs')).\
                                    filter_by(flavorid=flavor_id).\
                                    first()
    if not inst_type:
        raise exception.FlavorNotFound(flavor_id=flavor_id)
    else:
        return _dict_with_extra_specs(inst_type)


@require_admin_context
def instance_type_destroy(context, name):
    """ Marks specific instance_type as deleted"""
    session = get_session()
    instance_type_ref = session.query(models.InstanceTypes).\
                                      filter_by(name=name)
    records = instance_type_ref.update(dict(deleted=True))
    if records == 0:
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)
    else:
        return instance_type_ref


@require_admin_context
def instance_type_purge(context, name):
    """ Removes specific instance_type from DB
        Usually instance_type_destroy should be used
    """
    session = get_session()
    instance_type_ref = session.query(models.InstanceTypes).\
                                      filter_by(name=name)
    records = instance_type_ref.delete()
    if records == 0:
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)
    else:
        return instance_type_ref


####################


@require_admin_context
def zone_create(context, values):
    zone = models.Zone()
    zone.update(values)
    zone.save()
    return zone


@require_admin_context
def zone_update(context, zone_id, values):
    session = get_session()
    zone = session.query(models.Zone).filter_by(id=zone_id).first()
    if not zone:
        raise exception.ZoneNotFound(zone_id=zone_id)
    zone.update(values)
    zone.save(session=session)
    return zone


@require_admin_context
def zone_delete(context, zone_id):
    session = get_session()
    with session.begin():
        session.query(models.Zone).\
                filter_by(id=zone_id).\
                delete()


@require_admin_context
def zone_get(context, zone_id):
    session = get_session()
    result = session.query(models.Zone).filter_by(id=zone_id).first()
    if not result:
        raise exception.ZoneNotFound(zone_id=zone_id)
    return result


@require_admin_context
def zone_get_all(context):
    session = get_session()
    return session.query(models.Zone).all()


####################


@require_context
@require_instance_exists
def instance_metadata_get(context, instance_id):
    session = get_session()

    meta_results = session.query(models.InstanceMetadata).\
                    filter_by(instance_id=instance_id).\
                    filter_by(deleted=False).\
                    all()

    meta_dict = {}
    for i in meta_results:
        meta_dict[i['key']] = i['value']
    return meta_dict


@require_context
@require_instance_exists
def instance_metadata_delete(context, instance_id, key):
    session = get_session()
    session.query(models.InstanceMetadata).\
        filter_by(instance_id=instance_id).\
        filter_by(key=key).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_instance_exists
def instance_metadata_delete_all(context, instance_id):
    session = get_session()
    session.query(models.InstanceMetadata).\
        filter_by(instance_id=instance_id).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_instance_exists
def instance_metadata_get_item(context, instance_id, key, session=None):
    if not session:
        session = get_session()

    meta_result = session.query(models.InstanceMetadata).\
                    filter_by(instance_id=instance_id).\
                    filter_by(key=key).\
                    filter_by(deleted=False).\
                    first()

    if not meta_result:
        raise exception.InstanceMetadataNotFound(metadata_key=key,
                                                 instance_id=instance_id)
    return meta_result


@require_context
@require_instance_exists
def instance_metadata_update(context, instance_id, metadata, delete):
    session = get_session()

    # Set existing metadata to deleted if delete argument is True
    if delete:
        original_metadata = instance_metadata_get(context, instance_id)
        for meta_key, meta_value in original_metadata.iteritems():
            if meta_key not in metadata:
                meta_ref = instance_metadata_get_item(context, instance_id,
                                                      meta_key, session)
                meta_ref.update({'deleted': True})
                meta_ref.save(session=session)

    meta_ref = None

    # Now update all existing items with new values, or create new meta objects
    for meta_key, meta_value in metadata.iteritems():

        # update the value whether it exists or not
        item = {"value": meta_value}

        try:
            meta_ref = instance_metadata_get_item(context, instance_id,
                                                  meta_key, session)
        except exception.InstanceMetadataNotFound, e:
            meta_ref = models.InstanceMetadata()
            item.update({"key": meta_key, "instance_id": instance_id})

        meta_ref.update(item)
        meta_ref.save(session=session)

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
    if not session:
        session = get_session()
    return session.query(models.AgentBuild).\
                   filter_by(hypervisor=hypervisor).\
                   filter_by(os=os).\
                   filter_by(architecture=architecture).\
                   filter_by(deleted=False).\
                   first()


@require_admin_context
def agent_build_get_all(context):
    session = get_session()
    return session.query(models.AgentBuild).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def agent_build_destroy(context, agent_build_id):
    session = get_session()
    with session.begin():
        session.query(models.AgentBuild).\
                filter_by(id=agent_build_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_admin_context
def agent_build_update(context, agent_build_id, values):
    session = get_session()
    with session.begin():
        agent_build_ref = session.query(models.AgentBuild).\
                   filter_by(id=agent_build_id). \
                   first()
        agent_build_ref.update(values)
        agent_build_ref.save(session=session)


####################


@require_context
def instance_type_extra_specs_get(context, instance_type_id):
    session = get_session()

    spec_results = session.query(models.InstanceTypeExtraSpecs).\
                    filter_by(instance_type_id=instance_type_id).\
                    filter_by(deleted=False).\
                    all()

    spec_dict = {}
    for i in spec_results:
        spec_dict[i['key']] = i['value']
    return spec_dict


@require_context
def instance_type_extra_specs_delete(context, instance_type_id, key):
    session = get_session()
    session.query(models.InstanceTypeExtraSpecs).\
        filter_by(instance_type_id=instance_type_id).\
        filter_by(key=key).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def instance_type_extra_specs_get_item(context, instance_type_id, key,
                                       session=None):

    if not session:
        session = get_session()

    spec_result = session.query(models.InstanceTypeExtraSpecs).\
                    filter_by(instance_type_id=instance_type_id).\
                    filter_by(key=key).\
                    filter_by(deleted=False).\
                    first()

    if not spec_result:
        raise exception.\
           InstanceTypeExtraSpecsNotFound(extra_specs_key=key,
                                        instance_type_id=instance_type_id)
    return spec_result


@require_context
def instance_type_extra_specs_update_or_create(context, instance_type_id,
                                               specs):
    session = get_session()
    spec_ref = None
    for key, value in specs.iteritems():
        try:
            spec_ref = instance_type_extra_specs_get_item(
                context, instance_type_id, key, session)
        except exception.InstanceTypeExtraSpecsNotFound, e:
            spec_ref = models.InstanceTypeExtraSpecs()
        spec_ref.update({"key": key, "value": value,
                         "instance_type_id": instance_type_id,
                         "deleted": 0})
        spec_ref.save(session=session)
    return specs


##################


@require_admin_context
def volume_type_create(_context, values):
    """Create a new instance type. In order to pass in extra specs,
    the values dict should contain a 'extra_specs' key/value pair:

    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}

    """
    try:
        specs = values.get('extra_specs')

        values['extra_specs'] = _metadata_refs(values.get('extra_specs'),
                                                models.VolumeTypeExtraSpecs)
        volume_type_ref = models.VolumeTypes()
        volume_type_ref.update(values)
        volume_type_ref.save()
    except Exception, e:
        raise exception.DBError(e)
    return volume_type_ref


@require_context
def volume_type_get_all(context, inactive=False, filters={}):
    """
    Returns a dict describing all volume_types with name as key.
    """
    session = get_session()
    if inactive:
        vol_types = session.query(models.VolumeTypes).\
                        options(joinedload('extra_specs')).\
                        order_by("name").\
                        all()
    else:
        vol_types = session.query(models.VolumeTypes).\
                        options(joinedload('extra_specs')).\
                        filter_by(deleted=False).\
                        order_by("name").\
                        all()
    vol_dict = {}
    if vol_types:
        for i in vol_types:
            vol_dict[i['name']] = _dict_with_extra_specs(i)
    return vol_dict


@require_context
def volume_type_get(context, id):
    """Returns a dict describing specific volume_type"""
    session = get_session()
    vol_type = session.query(models.VolumeTypes).\
                    options(joinedload('extra_specs')).\
                    filter_by(id=id).\
                    first()

    if not vol_type:
        raise exception.VolumeTypeNotFound(volume_type=id)
    else:
        return _dict_with_extra_specs(vol_type)


@require_context
def volume_type_get_by_name(context, name):
    """Returns a dict describing specific volume_type"""
    session = get_session()
    vol_type = session.query(models.VolumeTypes).\
                    options(joinedload('extra_specs')).\
                    filter_by(name=name).\
                    first()
    if not vol_type:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    else:
        return _dict_with_extra_specs(vol_type)


@require_admin_context
def volume_type_destroy(context, name):
    """ Marks specific volume_type as deleted"""
    session = get_session()
    volume_type_ref = session.query(models.VolumeTypes).\
                                      filter_by(name=name)
    records = volume_type_ref.update(dict(deleted=True))
    if records == 0:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    else:
        return volume_type_ref


@require_admin_context
def volume_type_purge(context, name):
    """ Removes specific volume_type from DB
        Usually volume_type_destroy should be used
    """
    session = get_session()
    volume_type_ref = session.query(models.VolumeTypes).\
                                      filter_by(name=name)
    records = volume_type_ref.delete()
    if records == 0:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    else:
        return volume_type_ref


####################


@require_context
def volume_type_extra_specs_get(context, volume_type_id):
    session = get_session()

    spec_results = session.query(models.VolumeTypeExtraSpecs).\
                    filter_by(volume_type_id=volume_type_id).\
                    filter_by(deleted=False).\
                    all()

    spec_dict = {}
    for i in spec_results:
        spec_dict[i['key']] = i['value']
    return spec_dict


@require_context
def volume_type_extra_specs_delete(context, volume_type_id, key):
    session = get_session()
    session.query(models.VolumeTypeExtraSpecs).\
        filter_by(volume_type_id=volume_type_id).\
        filter_by(key=key).\
        filter_by(deleted=False).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def volume_type_extra_specs_get_item(context, volume_type_id, key,
                                       session=None):

    if not session:
        session = get_session()

    spec_result = session.query(models.VolumeTypeExtraSpecs).\
                    filter_by(volume_type_id=volume_type_id).\
                    filter_by(key=key).\
                    filter_by(deleted=False).\
                    first()

    if not spec_result:
        raise exception.\
           VolumeTypeExtraSpecsNotFound(extra_specs_key=key,
                                        volume_type_id=volume_type_id)
    return spec_result


@require_context
def volume_type_extra_specs_update_or_create(context, volume_type_id,
                                             specs):
    session = get_session()
    spec_ref = None
    for key, value in specs.iteritems():
        try:
            spec_ref = volume_type_extra_specs_get_item(
                context, volume_type_id, key, session)
        except exception.VolumeTypeExtraSpecsNotFound, e:
            spec_ref = models.VolumeTypeExtraSpecs()
        spec_ref.update({"key": key, "value": value,
                         "volume_type_id": volume_type_id,
                         "deleted": 0})
        spec_ref.save(session=session)
    return specs


    ####################


@require_admin_context
def vsa_create(context, values):
    """
    Creates Virtual Storage Array record.
    """
    try:
        vsa_ref = models.VirtualStorageArray()
        vsa_ref.update(values)
        vsa_ref.save()
    except Exception, e:
        raise exception.DBError(e)
    return vsa_ref


@require_admin_context
def vsa_update(context, vsa_id, values):
    """
    Updates Virtual Storage Array record.
    """
    session = get_session()
    with session.begin():
        vsa_ref = vsa_get(context, vsa_id, session=session)
        vsa_ref.update(values)
        vsa_ref.save(session=session)
    return vsa_ref


@require_admin_context
def vsa_destroy(context, vsa_id):
    """
    Deletes Virtual Storage Array record.
    """
    session = get_session()
    with session.begin():
        session.query(models.VirtualStorageArray).\
                filter_by(id=vsa_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def vsa_get(context, vsa_id, session=None):
    """
    Get Virtual Storage Array record by ID.
    """
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.VirtualStorageArray).\
                         options(joinedload('vsa_instance_type')).\
                         filter_by(id=vsa_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.VirtualStorageArray).\
                         options(joinedload('vsa_instance_type')).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=vsa_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.VirtualStorageArrayNotFound(id=vsa_id)

    return result


@require_admin_context
def vsa_get_all(context):
    """
    Get all Virtual Storage Array records.
    """
    session = get_session()
    return session.query(models.VirtualStorageArray).\
                   options(joinedload('vsa_instance_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def vsa_get_all_by_project(context, project_id):
    """
    Get all Virtual Storage Array records by project ID.
    """
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.VirtualStorageArray).\
                   options(joinedload('vsa_instance_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


    ####################
