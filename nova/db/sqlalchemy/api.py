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

import datetime
import warnings

from nova import db
from nova import exception
from nova import flags
from nova import utils
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import joinedload_all
from sqlalchemy.sql import exists
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import literal_column

FLAGS = flags.FLAGS


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
    """Ensures that the request context has permission to access the
       given project.
    """
    if is_user_context(context):
        if not context.project:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures that the request context has permission to access the
       given user.
    """
    if is_user_context(context):
        if not context.user:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def can_read_deleted(context):
    """Indicates if the context has access to deleted objects."""
    if not context:
        return False
    return context.read_deleted


def require_admin_context(f):
    """Decorator used to indicate that the method requires an
       administrator context.
    """
    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator used to indicate that the method requires either
       an administrator or normal user context.
    """
    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]) and not is_user_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
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
        raise exception.NotFound(_('No service for id %s') % service_id)

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
        raise exception.NotFound(_("%s does not exist or is not "
                                   "a compute node.") % host)

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
        raise exception.NotFound(_('No service for %(host)s, %(binary)s')
                % locals())

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
        raise exception.NotFound(_('No computeNode for id %s') % compute_id)

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
        raise exception.NotFound('No certificate for id %s' % certificate_id)

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
def floating_ip_allocate_address(context, host, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    with session.begin():
        floating_ip_ref = session.query(models.FloatingIp).\
                                  filter_by(host=host).\
                                  filter_by(fixed_ip_id=None).\
                                  filter_by(project_id=None).\
                                  filter_by(deleted=False).\
                                  with_lockmode('update').\
                                  first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not floating_ip_ref:
            raise db.NoMoreAddresses()
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
    return session.query(models.FloatingIp).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   count()


@require_context
def floating_ip_fixed_ip_associate(context, floating_address, fixed_address):
    session = get_session()
    with session.begin():
        # TODO(devcamcar): How to ensure floating_id belongs to user?
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     floating_address,
                                                     session=session)
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               fixed_address,
                                               session=session)
        floating_ip_ref.fixed_ip = fixed_ip_ref
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_deallocate(context, address):
    session = get_session()
    with session.begin():
        # TODO(devcamcar): How to ensure floating id belongs to user?
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref['project_id'] = None
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_destroy(context, address):
    session = get_session()
    with session.begin():
        # TODO(devcamcar): Ensure address belongs to user.
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref.delete(session=session)


@require_context
def floating_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        # TODO(devcamcar): Ensure address belongs to user.
        #                  Does get_floating_ip_by_address handle this?
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        fixed_ip_ref = floating_ip_ref.fixed_ip
        if fixed_ip_ref:
            fixed_ip_address = fixed_ip_ref['address']
        else:
            fixed_ip_address = None
        floating_ip_ref.fixed_ip = None
        floating_ip_ref.save(session=session)
    return fixed_ip_address


@require_admin_context
def floating_ip_get_all(context):
    session = get_session()
    return session.query(models.FloatingIp).\
                   options(joinedload_all('fixed_ip.instance')).\
                   filter_by(deleted=False).\
                   all()


@require_admin_context
def floating_ip_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.FloatingIp).\
                   options(joinedload_all('fixed_ip.instance')).\
                   filter_by(host=host).\
                   filter_by(deleted=False).\
                   all()


@require_context
def floating_ip_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    return session.query(models.FloatingIp).\
                   options(joinedload_all('fixed_ip.instance')).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=False).\
                   all()


@require_context
def floating_ip_get_by_address(context, address, session=None):
    # TODO(devcamcar): Ensure the address belongs to user.
    if not session:
        session = get_session()

    result = session.query(models.FloatingIp).\
                   options(joinedload_all('fixed_ip.network')).\
                     filter_by(address=address).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()
    if not result:
        raise exception.NotFound('No floating ip for address %s' % address)

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


@require_context
def fixed_ip_associate(context, address, instance_id):
    session = get_session()
    with session.begin():
        instance = instance_get(context, instance_id, session=session)
        fixed_ip_ref = session.query(models.FixedIp).\
                               filter_by(address=address).\
                               filter_by(deleted=False).\
                               filter_by(instance=None).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise db.NoMoreAddresses()
        fixed_ip_ref.instance = instance
        session.add(fixed_ip_ref)


@require_admin_context
def fixed_ip_associate_pool(context, network_id, instance_id):
    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = session.query(models.FixedIp).\
                               filter(network_or_none).\
                               filter_by(reserved=False).\
                               filter_by(deleted=False).\
                               filter_by(instance=None).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise db.NoMoreAddresses()
        if not fixed_ip_ref.network:
            fixed_ip_ref.network = network_get(context,
                                           network_id,
                                           session=session)
        fixed_ip_ref.instance = instance_get(context,
                                             instance_id,
                                             session=session)
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
                     filter_by(allocated=0).\
                     update({'instance_id': None,
                             'leased': 0,
                             'updated_at': datetime.datetime.utcnow()},
                             synchronize_session='fetch')
    return result


@require_admin_context
def fixed_ip_get_all(context, session=None):
    if not session:
        session = get_session()
    result = session.query(models.FixedIp).all()
    if not result:
        raise exception.NotFound(_('No fixed ips defined'))

    return result


@require_admin_context
def fixed_ip_get_all_by_host(context, host=None):
    session = get_session()

    result = session.query(models.FixedIp).\
                    join(models.FixedIp.instance).\
                    filter_by(state=1).\
                    filter_by(host=host).\
                    all()

    if not result:
        raise exception.NotFound(_('No fixed ips for this host defined'))

    return result


@require_context
def fixed_ip_get_by_address(context, address, session=None):
    if not session:
        session = get_session()
    result = session.query(models.FixedIp).\
                     filter_by(address=address).\
                     filter_by(deleted=can_read_deleted(context)).\
                     options(joinedload('network')).\
                     options(joinedload('instance')).\
                     first()
    if not result:
        raise exception.NotFound(_('No fixed ip for address %s') % address)

    if is_user_context(context):
        authorize_project_context(context, result.instance.project_id)

    return result


@require_context
def fixed_ip_get_instance(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    return fixed_ip_ref.instance


@require_context
def fixed_ip_get_all_by_instance(context, instance_id):
    session = get_session()
    rv = session.query(models.FixedIp).\
                 filter_by(instance_id=instance_id).\
                 filter_by(deleted=False).\
                 all()
    if not rv:
        raise exception.NotFound(_('No address for instance %s') % instance_id)
    return rv


@require_context
def fixed_ip_get_instance_v6(context, address):
    session = get_session()

    # convert IPv6 address to mac
    mac = utils.to_mac(address)

    # get mac address row
    mac_ref = mac_address_get_by_address(context, mac)

    # look up instance based on instance_id from mac address row
    result = session.query(models.Instance).\
                     filter_by(id=mac_ref.instance_id)
    return result


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
def mac_address_create(context, values):
    """create a new mac address record in teh database

    context = request context object
    values = dict containing column values
    """
    mac_address_ref = models.MacAddress()
    mac_address_ref.update(values)
    mac_address_ref.save()
#    instance_id = values['instance_id']
#    network_id = values['network_id']
#
#    session = get_session()
#    with session.begin():
#        instance = instance_get(context, instance_id, session=session)
#        network = network_get(context, network_id, session=session)
#        mac_address.instance = instance
#        mac_address.network = network
#        mac_address_ref.save(session=session)
#    return mac_address_ref


@require_context
def mac_address_get(context, mac_address_id):
    """gets a mac address from the table

    context = request context object
    mac_address_id = id of the mac_address
    """
    session = get_session()
    with session.begin():
        mac_address_ref = session.query(models.MacAddress).\
                                  filter_by(id=mac_address_id).\
                                  options(joinedload('network')).\
                                  options(joinedload('instance')).\
                                  first()
        return mac_address_ref


@require_context
def mac_address_get_by_address(context, address):
    """gets a mac address from the table

    context = request context object
    address = the mac you're looking to get
    """
    session = get_session()
    with session.begin():
        mac_address_ref = session.query(models.MacAddress).\
                                  filter_by(address=address).\
                                  options(joinedload('network')).\
                                  options(joinedload('instance')).\
                                  first()
        return mac_address_ref


@require_context
def mac_address_get_all_by_instance(context, instance_id):
    """gets all mac addresses for instance

    context = request context object
    instance_id = instance to retreive macs for
    """
    session = get_session()
    with session.begin():
        mac_address_refs = session.query(models.MacAddress).\
                                   filter_by(instance_id=instance_id).\
                                   options(joinedload('network')).\
                                   options(joinedload('instance')).\
                                   all()
        return mac_address_refs


@require_admin_context
def mac_address_get_all_by_network(context, network_id):
    """gets all mac addresses for instance

    context = request context object
    network_id = network to retreive macs for
    """
    session = get_session()
    with session.begin():
        mac_address_refs = session.query(models.MacAddress).\
                                   filter_by(network_id=network_id).\
                                   options(joinedload('network')).\
                                   options(joinedload('instance')).\
                                   all()
        return mac_address_refs


@require_context
def mac_address_delete(context, address):
    """delete mac address record in teh database

    context = request context object
    instance_id = instance to remove macs for
    """
    ref = mac_address_get_by_address(address)
    session = get_session()
    with session.begin():
        ref.delete(session=session)


@require_context
def mac_address_delete_by_instance(context, instance_id):
    """delete mac address records in the database that are associated
    with the instance given by instance_id

    context = request context object
    instance_id = instance to remove macs for
    """
    refs = mac_address_get_all_by_instance(instance_id)
    session = get_session()
    with session.begin():
        for ref in refs:
            ref.delete(session=session)


###################


@require_context
def instance_create(context, values):
    """Create a new Instance record in the database.

    context - request context object
    values - dict containing column values.
    """
    metadata = values.get('metadata')
    metadata_refs = []
    if metadata:
        for k, v in metadata.iteritems():
            metadata_ref = models.InstanceMetadata()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    values['metadata'] = metadata_refs

    instance_ref = models.Instance()
    instance_ref.update(values)

    session = get_session()
    with session.begin():
        instance_ref.save(session=session)
    return instance_ref


@require_admin_context
def instance_data_get_for_project(context, project_id):
    session = get_session()
    result = session.query(func.count(models.Instance.id),
                           func.sum(models.Instance.vcpus)).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=False).\
                     first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_context
def instance_destroy(context, instance_id):
    session = get_session()
    with session.begin():
        session.query(models.Instance).\
                filter_by(id=instance_id).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_id).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.InstanceMetadata).\
                filter_by(instance_id=instance_id).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def instance_get(context, instance_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Instance).\
                         options(joinedload_all('fixed_ips.floating_ips')).\
                         options(joinedload('mac_addresses')).\
                         options(joinedload_all('security_groups.rules')).\
                         options(joinedload('volumes')).\
                         options(joinedload_all('fixed_ips.network')).\
                         options(joinedload('metadata')).\
                         options(joinedload('instance_type')).\
                         filter_by(id=instance_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.Instance).\
                         options(joinedload_all('fixed_ips.floating_ips')).\
                         options(joinedload('mac_addresses')).\
                         options(joinedload_all('security_groups.rules')).\
                         options(joinedload('volumes')).\
                         options(joinedload('metadata')).\
                         options(joinedload('instance_type')).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=instance_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.InstanceNotFound(_('Instance %s not found')
                                         % instance_id,
                                         instance_id)

    return result


@require_admin_context
def instance_get_all(context):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('mac_addresses')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('instance_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def instance_get_all_by_user(context, user_id):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('mac_addresses')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('instance_type')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   filter_by(user_id=user_id).\
                   all()


@require_admin_context
def instance_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('mac_addresses')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
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
                   options(joinedload('mac_addresses')).\
                   options(joinedload('security_groups')).\
                   options(joinedload_all('fixed_ips.network')).\
                   options(joinedload('instance_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_context
def instance_get_all_by_reservation(context, reservation_id):
    session = get_session()

    if is_admin_context(context):
        return session.query(models.Instance).\
                       options(joinedload_all('fixed_ips.floating_ips')).\
                       options(joinedload('mac_addresses')).\
                       options(joinedload('security_groups')).\
                       options(joinedload_all('fixed_ips.network')).\
                       options(joinedload('instance_type')).\
                       filter_by(reservation_id=reservation_id).\
                       filter_by(deleted=can_read_deleted(context)).\
                       all()
    elif is_user_context(context):
        return session.query(models.Instance).\
                       options(joinedload_all('fixed_ips.floating_ips')).\
                       options(joinedload('mac_addresses')).\
                       options(joinedload('security_groups')).\
                       options(joinedload_all('fixed_ips.network')).\
                       options(joinedload('instance_type')).\
                       filter_by(project_id=context.project_id).\
                       filter_by(reservation_id=reservation_id).\
                       filter_by(deleted=False).\
                       all()


@require_admin_context
def instance_get_project_vpn(context, project_id):
    session = get_session()
    return session.query(models.Instance).\
                   options(joinedload_all('fixed_ips.floating_ips')).\
                   options(joinedload('mac_addresses')).\
                   options(joinedload('security_groups')).\
                   options(joinedload('instance_type')).\
                   filter_by(project_id=project_id).\
                   filter_by(image_id=FLAGS.vpn_image_id).\
                   filter_by(deleted=can_read_deleted(context)).\
                   first()


@require_context
def instance_get_fixed_addresses(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        try:
            fixed_ips = fixed_ip_get_all_by_instance(context, instance_id)
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
        # get mac rows associated with instance
        mac_refs = mac_address_get_all_by_instance(context, instance_ref.id)
        # compile of list of the mac_addresses sorted by network id
        macs = [ref.mac_address for ref in
                sorted(mac_refs, key=lambda ref: ref.network_id)]
        # combine prefixes and macs into (prefix,mac) pairs
        prefix_mac_pairs = zip(prefixes, macs)
        # return list containing ipv6 address for each pair
        return [utils.to_global_ipv6(pair) for pair in prefix_mac_pairs]


@require_context
def instance_get_floating_address(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        if not instance_ref.fixed_ip:
            return None
        # NOTE(tr3buchet): this only gets the first fixed_ip
        # won't find floating ips associated with other fixed_ips
        if not instance_ref.fixed_ip.floating_ips:
            return None
        # NOTE(vish): this just returns the first floating ip
        return instance_ref.fixed_ip.floating_ips[0]['address']


@require_admin_context
def instance_is_vpn(context, instance_id):
    # TODO(vish): Move this into image code somewhere
    instance_ref = instance_get(context, instance_id)
    return instance_ref['image_id'] == FLAGS.vpn_image_id


@require_admin_context
def instance_set_state(context, instance_id, state, description=None):
    # TODO(devcamcar): Move this out of models and into driver
    from nova.compute import power_state
    if not description:
        description = power_state.name(state)
    db.instance_update(context,
                       instance_id,
                       {'state': state,
                        'state_description': description})


@require_context
def instance_update(context, instance_id, values):
    session = get_session()
    with session.begin():
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
def instance_get_vcpu_sum_by_host_and_project(context, hostname, proj_id):
    session = get_session()
    result = session.query(models.Instance).\
                      filter_by(host=hostname).\
                      filter_by(project_id=proj_id).\
                      filter_by(deleted=False).\
                      value(func.sum(models.Instance.vcpus))
    if not result:
        return 0
    return result


@require_context
def instance_get_memory_sum_by_host_and_project(context, hostname, proj_id):
    session = get_session()
    result = session.query(models.Instance).\
                      filter_by(host=hostname).\
                      filter_by(project_id=proj_id).\
                      filter_by(deleted=False).\
                      value(func.sum(models.Instance.memory_mb))
    if not result:
        return 0
    return result


@require_context
def instance_get_disk_sum_by_host_and_project(context, hostname, proj_id):
    session = get_session()
    result = session.query(models.Instance).\
                      filter_by(host=hostname).\
                      filter_by(project_id=proj_id).\
                      filter_by(deleted=False).\
                      value(func.sum(models.Instance.local_gb))
    if not result:
        return 0
    return result


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
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
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
        raise exception.NotFound(_('no keypair for user %(user_id)s,'
                ' name %(name)s') % locals())
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
    """associate a project with a network

    only associates projects with networks that have configured hosts

    only associate if the project doesn't already have a network
    or if force is True

    force solves race condition where a fresh project has multiple instance
    builds simultaneosly picked up by multiple network hosts which attempt
    to associate the project with multiple networks
    """
    session = get_session()
    with session.begin():

        def network_query(project_filter):
            return session.query(models.Network).\
                                 filter_by(deleted=False).\
                                 filter(models.Network.host != None).\
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
        raise exception.NotFound(_('No network for id %s') % network_id)

    return result


@require_admin_context
def network_get_all(context):
    session = get_session()
    result = session.query(models.Network).\
                 filter_by(deleted=False)
    if not result:
        raise exception.NotFound(_('No networks defined'))
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
        raise exception.NotFound(_('No network for bridge %s') % bridge)
    return result


@require_admin_context
def network_get_by_cidr(context, cidr):
    session = get_session()
    result = session.query(models.Network).\
                filter_by(cidr=cidr).first()

    if not result:
        raise exception.NotFound(_('Network with cidr %s does not exist') %
                                  cidr)
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
        raise exception.NotFound(_('No network for instance %s') % instance_id)
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
        raise exception.NotFound(_('No network for instance %s') % instance_id)
    return rv


@require_admin_context
def network_get_all_by_host(context, host):
    session = get_session()
    with session.begin():
        return session.query(models.Network).\
                       filter_by(deleted=False).\
                       filter_by(host=host).\
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
            raise exception.NotFound(_('No network for id %s') % network_id)

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
        raise exception.NotFound(_('Token %s does not exist') % token_hash)
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


@require_admin_context
def quota_get(context, project_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Quota).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()
    if not result:
        raise exception.NotFound(_('No quota for project_id %s') % project_id)

    return result


@require_admin_context
def quota_create(context, values):
    quota_ref = models.Quota()
    quota_ref.update(values)
    quota_ref.save()
    return quota_ref


@require_admin_context
def quota_update(context, project_id, values):
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, session=session)
        quota_ref.update(values)
        quota_ref.save(session=session)


@require_admin_context
def quota_destroy(context, project_id):
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, session=session)
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
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.ExportDevice).\
                filter_by(volume_id=volume_id).\
                update({'volume_id': None})
        session.query(models.IscsiTarget).\
                filter_by(volume_id=volume_id).\
                update({'volume_id': None})


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
                         filter_by(id=volume_id).\
                         filter_by(deleted=can_read_deleted(context)).\
                         first()
    elif is_user_context(context):
        result = session.query(models.Volume).\
                         options(joinedload('instance')).\
                         filter_by(project_id=context.project_id).\
                         filter_by(id=volume_id).\
                         filter_by(deleted=False).\
                         first()
    if not result:
        raise exception.VolumeNotFound(_('Volume %s not found') % volume_id,
                                       volume_id)

    return result


@require_admin_context
def volume_get_all(context):
    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def volume_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
                   filter_by(host=host).\
                   filter_by(deleted=can_read_deleted(context)).\
                   all()


@require_admin_context
def volume_get_all_by_instance(context, instance_id):
    session = get_session()
    result = session.query(models.Volume).\
                     filter_by(instance_id=instance_id).\
                     filter_by(deleted=False).\
                     all()
    if not result:
        raise exception.NotFound(_('No volume for instance %s') % instance_id)
    return result


@require_context
def volume_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Volume).\
                   options(joinedload('instance')).\
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
                     first()
    if not result:
        raise exception.VolumeNotFound(_('Volume %s not found') % volume_id,
                                       volume_id)

    return result.instance


@require_admin_context
def volume_get_shelf_and_blade(context, volume_id):
    session = get_session()
    result = session.query(models.ExportDevice).\
                     filter_by(volume_id=volume_id).\
                     first()
    if not result:
        raise exception.NotFound(_('No export device found for volume %s') %
                                 volume_id)

    return (result.shelf_id, result.blade_id)


@require_admin_context
def volume_get_iscsi_target_num(context, volume_id):
    session = get_session()
    result = session.query(models.IscsiTarget).\
                     filter_by(volume_id=volume_id).\
                     first()
    if not result:
        raise exception.NotFound(_('No target id found for volume %s') %
                                 volume_id)

    return result.target_num


@require_context
def volume_update(context, volume_id, values):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref.update(values)
        volume_ref.save(session=session)


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
                         first()
    else:
        result = session.query(models.SecurityGroup).\
                         filter_by(deleted=False).\
                         filter_by(id=security_group_id).\
                         filter_by(project_id=context.project_id).\
                         options(joinedload_all('rules')).\
                         first()
    if not result:
        raise exception.NotFound(_("No security group with id %s") %
                                 security_group_id)
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
        raise exception.NotFound(
            _('No security group named %(group_name)s'
            ' for project: %(project_id)s') % locals())
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
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(security_group_id=security_group_id).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupIngressRule).\
                filter_by(group_id=security_group_id).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def security_group_destroy_all(context, session=None):
    if not session:
        session = get_session()
    with session.begin():
        session.query(models.SecurityGroup).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupIngressRule).\
                update({'deleted': 1,
                        'deleted_at': datetime.datetime.utcnow(),
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
        raise exception.NotFound(_("No secuity group rule with id %s") %
                                 security_group_rule_id)
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
                         all()
    else:
        # TODO(vish): Join to group and check for project_id
        result = session.query(models.SecurityGroupIngressRule).\
                         filter_by(deleted=False).\
                         filter_by(parent_group_id=security_group_id).\
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
def user_get(context, id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.User).\
                     filter_by(id=id).\
                     filter_by(deleted=can_read_deleted(context)).\
                     first()

    if not result:
        raise exception.NotFound(_('No user for id %s') % id)

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
        raise exception.NotFound(_('No user for access key %s') % access_key)

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
        raise exception.NotFound(_("No project with id %s") % id)

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
        raise exception.NotFound(_('Invalid user_id %s') % user_id)
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
def project_get_network(context, project_id, associate=True):
    session = get_session()
    result = session.query(models.Network).\
                     filter_by(project_id=project_id).\
                     filter_by(deleted=False).\
                     first()
    if not result:
        if not associate:
            return None
        try:
            return network_associate(context, project_id)
        except IntegrityError:
            # NOTE(vish): We hit this if there is a race and two
            #             processes are attempting to allocate the
            #             network at the same time
            result = session.query(models.Network).\
                             filter_by(project_id=project_id).\
                             filter_by(deleted=False).\
                             first()
    return result


@require_context
def project_get_network_v6(context, project_id):
    return project_get_network(context, project_id)


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
        raise exception.NotFound(_("No migration found with id %s")
                % id)
    return result


@require_admin_context
def migration_get_by_instance_and_status(context, instance_id, status):
    session = get_session()
    result = session.query(models.Migration).\
                     filter_by(instance_id=instance_id).\
                     filter_by(status=status).first()
    if not result:
        raise exception.NotFound(_("No migration found for instance "
                "%(instance_id)s with status %(status)s") % locals())
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
        raise exception.NotFound(_("No console pool with id %(pool_id)s")
                % locals())

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
        raise exception.NotFound(_('No console pool of type %(console_type)s '
                                   'for compute host %(compute_host)s '
                                   'on proxy host %(host)s') % locals())
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
        raise exception.NotFound(_('No console for instance %(instance_id)s '
                                 'in pool %(pool_id)s') % locals())
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
        idesc = (_("on instance %s") % instance_id) if instance_id else ""
        raise exception.NotFound(_("No console with id %(console_id)s"
                                   " %(idesc)s") % locals())
    return result


    ##################


@require_admin_context
def instance_type_create(_context, values):
    try:
        instance_type_ref = models.InstanceTypes()
        instance_type_ref.update(values)
        instance_type_ref.save()
    except Exception, e:
        raise exception.DBError(e)
    return instance_type_ref


@require_context
def instance_type_get_all(context, inactive=False):
    """
    Returns a dict describing all instance_types with name as key.
    """
    session = get_session()
    if inactive:
        inst_types = session.query(models.InstanceTypes).\
                        order_by("name").\
                        all()
    else:
        inst_types = session.query(models.InstanceTypes).\
                        filter_by(deleted=False).\
                        order_by("name").\
                        all()
    if inst_types:
        inst_dict = {}
        for i in inst_types:
            inst_dict[i['name']] = dict(i)
        return inst_dict
    else:
        raise exception.NotFound


@require_context
def instance_type_get_by_id(context, id):
    """Returns a dict describing specific instance_type"""
    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                    filter_by(id=id).\
                    first()
    if not inst_type:
        raise exception.NotFound(_("No instance type with id %s") % id)
    else:
        return dict(inst_type)


@require_context
def instance_type_get_by_name(context, name):
    """Returns a dict describing specific instance_type"""
    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                    filter_by(name=name).\
                    first()
    if not inst_type:
        raise exception.NotFound(_("No instance type with name %s") % name)
    else:
        return dict(inst_type)


@require_context
def instance_type_get_by_flavor_id(context, id):
    """Returns a dict describing specific flavor_id"""
    session = get_session()
    inst_type = session.query(models.InstanceTypes).\
                                    filter_by(flavorid=int(id)).\
                                    first()
    if not inst_type:
        raise exception.NotFound(_("No flavor with flavorid %s") % id)
    else:
        return dict(inst_type)


@require_admin_context
def instance_type_destroy(context, name):
    """ Marks specific instance_type as deleted"""
    session = get_session()
    instance_type_ref = session.query(models.InstanceTypes).\
                                      filter_by(name=name)
    records = instance_type_ref.update(dict(deleted=True))
    if records == 0:
        raise exception.NotFound
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
        raise exception.NotFound
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
        raise exception.NotFound(_("No zone with id %(zone_id)s") % locals())
    zone.update(values)
    zone.save()
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
        raise exception.NotFound(_("No zone with id %(zone_id)s") % locals())
    return result


@require_admin_context
def zone_get_all(context):
    session = get_session()
    return session.query(models.Zone).all()


####################

@require_context
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
def instance_metadata_delete(context, instance_id, key):
    session = get_session()
    session.query(models.InstanceMetadata).\
        filter_by(instance_id=instance_id).\
        filter_by(key=key).\
        filter_by(deleted=False).\
        update({'deleted': 1,
                'deleted_at': datetime.datetime.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def instance_metadata_get_item(context, instance_id, key):
    session = get_session()

    meta_result = session.query(models.InstanceMetadata).\
                    filter_by(instance_id=instance_id).\
                    filter_by(key=key).\
                    filter_by(deleted=False).\
                    first()

    if not meta_result:
        raise exception.NotFound(_('Invalid metadata key for instance %s') %
                                    instance_id)
    return meta_result


@require_context
def instance_metadata_update_or_create(context, instance_id, metadata):
    session = get_session()
    meta_ref = None
    for key, value in metadata.iteritems():
        try:
            meta_ref = instance_metadata_get_item(context, instance_id, key,
                                                        session)
        except:
            meta_ref = models.InstanceMetadata()
        meta_ref.update({"key": key, "value": value,
                            "instance_id": instance_id,
                            "deleted": 0})
        meta_ref.save(session=session)
    return metadata
