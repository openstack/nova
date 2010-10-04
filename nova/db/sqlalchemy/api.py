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
Implementation of SQLAlchemy backend
"""

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
from sqlalchemy.orm.exc import NoResultFound

FLAGS = flags.FLAGS


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        warnings.warn('Use of empty request context is deprecated',
                      DeprecationWarning)
        return True
    return context.is_admin


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if not context.user or not context.project:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures that the request context has permission to access the
       given project.
    """
    if is_user_context(context):
        if not context.project:
            raise exception.NotAuthorized()
        elif context.project.id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures that the request context has permission to access the
       given user.
    """
    if is_user_context(context):
        if not context.user:
            raise exception.NotAuthorized()
        elif context.user.id != user_id:
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


@require_admin_context
def service_get(context, service_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Service
                   ).filter_by(id=service_id
                   ).filter_by(deleted=can_read_deleted(context)
                   ).first()

    if not result:
        raise exception.NotFound('No service for id %s' % service_id)

    return result


@require_admin_context
def service_get_all_by_topic(context, topic):
    session = get_session()
    return session.query(models.Service
                 ).filter_by(deleted=False
                 ).filter_by(disabled=False
                 ).filter_by(topic=topic
                 ).all()


@require_admin_context
def _service_get_all_topic_subquery(context, session, topic, subq, label):
    sort_value = getattr(subq.c, label)
    return session.query(models.Service, func.coalesce(sort_value, 0)
                 ).filter_by(topic=topic
                 ).filter_by(deleted=False
                 ).filter_by(disabled=False
                 ).outerjoin((subq, models.Service.host == subq.c.host)
                 ).order_by(sort_value
                 ).all()


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
                             func.sum(models.Instance.vcpus).label(label)
                     ).filter_by(deleted=False
                     ).group_by(models.Instance.host
                     ).subquery()
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
                             func.count(models.Network.id).label(label)
                     ).filter_by(deleted=False
                     ).group_by(models.Network.host
                     ).subquery()
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
                             func.sum(models.Volume.size).label(label)
                     ).filter_by(deleted=False
                     ).group_by(models.Volume.host
                     ).subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_by_args(context, host, binary):
    session = get_session()
    result = session.query(models.Service
                   ).filter_by(host=host
                   ).filter_by(binary=binary
                   ).filter_by(deleted=can_read_deleted(context)
                   ).first()
    if not result:
        raise exception.NotFound('No service for %s, %s' % (host, binary))

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    for (key, value) in values.iteritems():
        service_ref[key] = value
    service_ref.save()
    return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        for (key, value) in values.iteritems():
            service_ref[key] = value
        service_ref.save(session=session)


###################


@require_context
def floating_ip_allocate_address(context, host, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    with session.begin():
        floating_ip_ref = session.query(models.FloatingIp
                                ).filter_by(host=host
                                ).filter_by(fixed_ip_id=None
                                ).filter_by(project_id=None
                                ).filter_by(deleted=False
                                ).with_lockmode('update'
                                ).first()
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
    for (key, value) in values.iteritems():
        floating_ip_ref[key] = value
    floating_ip_ref.save()
    return floating_ip_ref['address']


@require_context
def floating_ip_count_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    return session.query(models.FloatingIp
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=False
                 ).count()


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
        floating_ip_ref = get_floating_ip_by_address(context,
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
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(deleted=False
                 ).all()


@require_admin_context
def floating_ip_get_all_by_host(context, host):
    session = get_session()
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(host=host
                 ).filter_by(deleted=False
                 ).all()


@require_context
def floating_ip_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    session = get_session()
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=False
                 ).all()


@require_context
def floating_ip_get_by_address(context, address, session=None):
    # TODO(devcamcar): Ensure the address belongs to user.
    if not session:
        session = get_session()

    result = session.query(models.FloatingIp
                   ).filter_by(address=address
                   ).filter_by(deleted=can_read_deleted(context)
                   ).first()
    if not result:
        raise exception.NotFound('No fixed ip for address %s' % address)

    return result


###################


@require_context
def fixed_ip_associate(context, address, instance_id):
    session = get_session()
    with session.begin():
        instance = instance_get(context, instance_id, session=session)
        fixed_ip_ref = session.query(models.FixedIp
                             ).filter_by(address=address
                             ).filter_by(deleted=False
                             ).filter_by(instance=None
                             ).with_lockmode('update'
                             ).first()
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
        fixed_ip_ref = session.query(models.FixedIp
                             ).filter(network_or_none
                             ).filter_by(reserved=False
                             ).filter_by(deleted=False
                             ).filter_by(instance=None
                             ).with_lockmode('update'
                             ).first()
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
    for (key, value) in values.iteritems():
        fixed_ip_ref[key] = value
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
    # NOTE(vish): The nested select is because sqlite doesn't support
    #             JOINs in UPDATEs.
    result = session.execute('UPDATE fixed_ips SET instance_id = NULL, '
                                                  'leased = 0 '
                             'WHERE network_id IN (SELECT id FROM networks '
                                                  'WHERE host = :host) '
                             'AND updated_at < :time '
                             'AND instance_id IS NOT NULL '
                             'AND allocated = 0',
                    {'host': host,
                     'time': time.isoformat()})
    return result.rowcount


@require_context
def fixed_ip_get_by_address(context, address, session=None):
    if not session:
        session = get_session()
    result = session.query(models.FixedIp
                   ).filter_by(address=address
                   ).filter_by(deleted=can_read_deleted(context)
                   ).options(joinedload('network')
                   ).options(joinedload('instance')
                   ).first()
    if not result:
        raise exception.NotFound('No floating ip for address %s' % address)

    if is_user_context(context):
        authorize_project_context(context, result.instance.project_id)

    return result


@require_context
def fixed_ip_get_instance(context, address):
        fixed_ip_ref = fixed_ip_get_by_address(context, address)
        return fixed_ip_ref.instance


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
        for (key, value) in values.iteritems():
            fixed_ip_ref[key] = value
        fixed_ip_ref.save(session=session)


###################


@require_context
def instance_create(context, values):
    instance_ref = models.Instance()
    for (key, value) in values.iteritems():
        instance_ref[key] = value

    session = get_session()
    with session.begin():
        while instance_ref.ec2_id == None:
            ec2_id = utils.generate_uid(instance_ref.__prefix__)
            if not instance_ec2_id_exists(context, ec2_id, session=session):
                instance_ref.ec2_id = ec2_id
        instance_ref.save(session=session)
    return instance_ref


@require_admin_context
def instance_data_get_for_project(context, project_id):
    session = get_session()
    result = session.query(func.count(models.Instance.id),
                           func.sum(models.Instance.vcpus)
                   ).filter_by(project_id=project_id
                   ).filter_by(deleted=False
                   ).first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_context
def instance_destroy(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        instance_ref.delete(session=session)


@require_context
def instance_get(context, instance_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Instance
                       ).filter_by(id=instance_id
                       ).filter_by(deleted=can_read_deleted(context)
                       ).first()
    elif is_user_context(context):
        result = session.query(models.Instance
                       ).filter_by(project_id=context.project.id
                       ).filter_by(id=instance_id
                       ).filter_by(deleted=False
                       ).first()
    if not result:
        raise exception.NotFound('No instance for id %s' % instance_id)

    return result


@require_admin_context
def instance_get_all(context):
    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(deleted=can_read_deleted(context)
                 ).all()


@require_admin_context
def instance_get_all_by_user(context, user_id):
    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(deleted=can_read_deleted(context)
                 ).filter_by(user_id=user_id
                 ).all()


@require_context
def instance_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=can_read_deleted(context)
                 ).all()


@require_context
def instance_get_all_by_reservation(context, reservation_id):
    session = get_session()

    if is_admin_context(context):
        return session.query(models.Instance
                     ).options(joinedload_all('fixed_ip.floating_ips')
                     ).filter_by(reservation_id=reservation_id
                     ).filter_by(deleted=can_read_deleted(context)
                     ).all()
    elif is_user_context(context):
        return session.query(models.Instance
                     ).options(joinedload_all('fixed_ip.floating_ips')
                     ).filter_by(project_id=context.project.id
                     ).filter_by(reservation_id=reservation_id
                     ).filter_by(deleted=False
                     ).all()


@require_context
def instance_get_by_ec2_id(context, ec2_id):
    session = get_session()

    if is_admin_context(context):
        result = session.query(models.Instance
                       ).filter_by(ec2_id=ec2_id
                       ).filter_by(deleted=can_read_deleted(context)
                       ).first()
    elif is_user_context(context):
        result = session.query(models.Instance
                       ).filter_by(project_id=context.project.id
                       ).filter_by(ec2_id=ec2_id
                       ).filter_by(deleted=False
                       ).first()
    if not result:
        raise exception.NotFound('Instance %s not found' % (ec2_id))

    return result


@require_context
def instance_ec2_id_exists(context, ec2_id, session=None):
    if not session:
        session = get_session()
    return session.query(exists().where(models.Instance.id==ec2_id)).one()[0]


@require_context
def instance_get_fixed_address(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        if not instance_ref.fixed_ip:
            return None
        return instance_ref.fixed_ip['address']


@require_context
def instance_get_floating_address(context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = instance_get(context, instance_id, session=session)
        if not instance_ref.fixed_ip:
            return None
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
        for (key, value) in values.iteritems():
            instance_ref[key] = value
        instance_ref.save(session=session)


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance"""
    session = get_session()
    with session.begin():
        instance_ref = models.Instance.find(instance_id, session=session)
        security_group_ref = models.SecurityGroup.find(security_group_id,
                                                       session=session)
        instance_ref.security_groups += [security_group_ref]
        instance_ref.save(session=session)


###################


@require_context
def key_pair_create(context, values):
    key_pair_ref = models.KeyPair()
    for (key, value) in values.iteritems():
        key_pair_ref[key] = value
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
        # TODO(vish): do we have to use sql here?
        session.execute('update key_pairs set deleted=1 where user_id=:id',
                        {'id': user_id})


@require_context
def key_pair_get(context, user_id, name, session=None):
    authorize_user_context(context, user_id)

    if not session:
        session = get_session()

    result = session.query(models.KeyPair
                   ).filter_by(user_id=user_id
                   ).filter_by(name=name
                   ).filter_by(deleted=can_read_deleted(context)
                   ).first()
    if not result:
        raise exception.NotFound('no keypair for user %s, name %s' %
                                 (user_id, name))
    return result


@require_context
def key_pair_get_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    session = get_session()
    return session.query(models.KeyPair
                 ).filter_by(user_id=user_id
                 ).filter_by(deleted=False
                 ).all()


###################


@require_admin_context
def network_count(context):
    session = get_session()
    return session.query(models.Network
                 ).filter_by(deleted=can_read_deleted(context)
                 ).count()


@require_admin_context
def network_count_allocated_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(allocated=True
                 ).filter_by(deleted=False
                 ).count()


@require_admin_context
def network_count_available_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(allocated=False
                 ).filter_by(reserved=False
                 ).filter_by(deleted=False
                 ).count()


@require_admin_context
def network_count_reserved_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(reserved=True
                 ).filter_by(deleted=False
                 ).count()


@require_admin_context
def network_create(context, values):
    network_ref = models.Network()
    for (key, value) in values.iteritems():
        network_ref[key] = value
    network_ref.save()
    return network_ref


@require_admin_context
def network_destroy(context, network_id):
    session = get_session()
    with session.begin():
        # TODO(vish): do we have to use sql here?
        session.execute('update networks set deleted=1 where id=:id',
                        {'id': network_id})
        session.execute('update fixed_ips set deleted=1 where network_id=:id',
                        {'id': network_id})
        session.execute('update floating_ips set deleted=1 '
                        'where fixed_ip_id in '
                        '(select id from fixed_ips '
                        'where network_id=:id)',
                        {'id': network_id})
        session.execute('update network_indexes set network_id=NULL '
                        'where network_id=:id',
                        {'id': network_id})


@require_context
def network_get(context, network_id, session=None):
    if not session:
        session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Network
                       ).filter_by(id=network_id
                       ).filter_by(deleted=can_read_deleted(context)
                       ).first()
    elif is_user_context(context):
        result = session.query(models.Network
                       ).filter_by(project_id=context.project.id
                       ).filter_by(id=network_id
                       ).filter_by(deleted=False
                       ).first()
    if not result:
        raise exception.NotFound('No network for id %s' % network_id)

    return result


# NOTE(vish): pylint complains because of the long method name, but
#             it fits with the names of the rest of the methods
# pylint: disable-msg=C0103
@require_admin_context
def network_get_associated_fixed_ips(context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).options(joinedload_all('instance')
                 ).filter_by(network_id=network_id
                 ).filter(models.FixedIp.instance_id != None
                 ).filter_by(deleted=False
                 ).all()


@require_admin_context
def network_get_by_bridge(context, bridge):
    session = get_session()
    result = session.query(models.Network
               ).filter_by(bridge=bridge
               ).filter_by(deleted=False
               ).first()

    if not result:
        raise exception.NotFound('No network for bridge %s' % bridge)

    return result


@require_admin_context
def network_get_index(context, network_id):
    session = get_session()
    with session.begin():
        network_index = session.query(models.NetworkIndex
                              ).filter_by(network_id=None
                              ).filter_by(deleted=False
                              ).with_lockmode('update'
                              ).first()

        if not network_index:
            raise db.NoMoreNetworks()

        network_index['network'] = network_get(context,
                                               network_id,
                                               session=session)
        session.add(network_index)

    return network_index['index']


@require_admin_context
def network_index_count(context):
    session = get_session()
    return session.query(models.NetworkIndex
                 ).filter_by(deleted=can_read_deleted(context)
                 ).count()


@require_admin_context
def network_index_create_safe(context, values):
    network_index_ref = models.NetworkIndex()
    for (key, value) in values.iteritems():
        network_index_ref[key] = value
    try:
        network_index_ref.save()
    except IntegrityError:
        pass


@require_admin_context
def network_set_host(context, network_id, host_id):
    session = get_session()
    with session.begin():
        network_ref = session.query(models.Network
                            ).filter_by(id=network_id
                            ).filter_by(deleted=False
                            ).with_lockmode('update'
                            ).first()
        if not network_ref:
            raise exception.NotFound('No network for id %s' % network_id)

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
        for (key, value) in values.iteritems():
            network_ref[key] = value
        network_ref.save(session=session)


###################


@require_context
def project_get_network(context, project_id):
    session = get_session()
    result= session.query(models.Network
               ).filter_by(project_id=project_id
               ).filter_by(deleted=False
               ).first()

    if not result:
        raise exception.NotFound('No network for project: %s' % project_id)

    return result


###################


def queue_get_for(_context, topic, physical_node_id):
    # FIXME(ja): this should be servername?
    return "%s.%s" % (topic, physical_node_id)


###################


@require_admin_context
def export_device_count(context):
    session = get_session()
    return session.query(models.ExportDevice
                 ).filter_by(deleted=can_read_deleted(context)
                 ).count()


@require_admin_context
def export_device_create(context, values):
    export_device_ref = models.ExportDevice()
    for (key, value) in values.iteritems():
        export_device_ref[key] = value
    export_device_ref.save()
    return export_device_ref


###################


def auth_destroy_token(_context, token):
    session = get_session()
    session.delete(token)

def auth_get_token(_context, token_hash):
    session = get_session()
    tk = session.query(models.AuthToken
                ).filter_by(token_hash=token_hash)
    if not tk:
        raise exception.NotFound('Token %s does not exist' % token_hash)
    return tk

def auth_create_token(_context, token):
    tk = models.AuthToken()
    for k,v in token.iteritems():
        tk[k] = v
    tk.save()
    return tk


###################


@require_admin_context
def quota_get(context, project_id, session=None):
    if not session:
        session = get_session()

    result = session.query(models.Quota
                   ).filter_by(project_id=project_id
                   ).filter_by(deleted=can_read_deleted(context)
                   ).first()
    if not result:
        raise exception.NotFound('No quota for project_id %s' % project_id)

    return result


@require_admin_context
def quota_create(context, values):
    quota_ref = models.Quota()
    for (key, value) in values.iteritems():
        quota_ref[key] = value
    quota_ref.save()
    return quota_ref


@require_admin_context
def quota_update(context, project_id, values):
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, session=session)
        for (key, value) in values.iteritems():
            quota_ref[key] = value
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
        export_device = session.query(models.ExportDevice
                              ).filter_by(volume=None
                              ).filter_by(deleted=False
                              ).with_lockmode('update'
                              ).first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not export_device:
            raise db.NoMoreBlades()
        export_device.volume_id = volume_id
        session.add(export_device)
    return (export_device.shelf_id, export_device.blade_id)


@require_admin_context
def volume_attached(context, volume_id, instance_id, mountpoint):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'in-use'
        volume_ref['mountpoint'] = mountpoint
        volume_ref['attach_status'] = 'attached'
        volume_ref.instance = instance_get(context, instance_id, session=session)
        volume_ref.save(session=session)


@require_context
def volume_create(context, values):
    volume_ref = models.Volume()
    for (key, value) in values.iteritems():
        volume_ref[key] = value

    session = get_session()
    with session.begin():
        while volume_ref.ec2_id == None:
            ec2_id = utils.generate_uid(volume_ref.__prefix__)
            if not volume_ec2_id_exists(context, ec2_id, session=session):
                volume_ref.ec2_id = ec2_id
        volume_ref.save(session=session)
    return volume_ref


@require_admin_context
def volume_data_get_for_project(context, project_id):
    session = get_session()
    result = session.query(func.count(models.Volume.id),
                           func.sum(models.Volume.size)
                   ).filter_by(project_id=project_id
                   ).filter_by(deleted=False
                   ).first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_admin_context
def volume_destroy(context, volume_id):
    session = get_session()
    with session.begin():
        # TODO(vish): do we have to use sql here?
        session.execute('update volumes set deleted=1 where id=:id',
                        {'id': volume_id})
        session.execute('update export_devices set volume_id=NULL '
                        'where volume_id=:id',
                        {'id': volume_id})


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
        result = session.query(models.Volume
                       ).filter_by(id=volume_id
                       ).filter_by(deleted=can_read_deleted(context)
                       ).first()
    elif is_user_context(context):
        result = session.query(models.Volume
                       ).filter_by(project_id=context.project.id
                       ).filter_by(id=volume_id
                       ).filter_by(deleted=False
                       ).first()
    if not result:
        raise exception.NotFound('No volume for id %s' % volume_id)

    return result


@require_admin_context
def volume_get_all(context):
    return session.query(models.Volume
                 ).filter_by(deleted=can_read_deleted(context)
                 ).all()

@require_context
def volume_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    session = get_session()
    return session.query(models.Volume
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=can_read_deleted(context)
                 ).all()


@require_context
def volume_get_by_ec2_id(context, ec2_id):
    session = get_session()
    result = None

    if is_admin_context(context):
        result = session.query(models.Volume
                       ).filter_by(ec2_id=ec2_id
                       ).filter_by(deleted=can_read_deleted(context)
                       ).first()
    elif is_user_context(context):
        result = session.query(models.Volume
                       ).filter_by(project_id=context.project.id
                       ).filter_by(ec2_id=ec2_id
                       ).filter_by(deleted=False
                       ).first()
    else:
        raise exception.NotAuthorized()

    if not result:
        raise exception.NotFound('Volume %s not found' % ec2_id)

    return result


@require_context
def volume_ec2_id_exists(context, ec2_id, session=None):
    if not session:
        session = get_session()

    return session.query(exists(
                 ).where(models.Volume.id==ec2_id)
                 ).one()[0]


@require_admin_context
def volume_get_instance(context, volume_id):
    session = get_session()
    result = session.query(models.Volume
                   ).filter_by(id=volume_id
                   ).filter_by(deleted=can_read_deleted(context)
                   ).options(joinedload('instance')
                   ).first()
    if not result:
        raise exception.NotFound('Volume %s not found' % ec2_id)

    return result.instance


@require_admin_context
def volume_get_shelf_and_blade(context, volume_id):
    session = get_session()
    result = session.query(models.ExportDevice
                   ).filter_by(volume_id=volume_id
                   ).first()
    if not result:
        raise exception.NotFound('No export device found for volume %s' %
                                 volume_id)

    return (result.shelf_id, result.blade_id)


@require_context
def volume_update(context, volume_id, values):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        for (key, value) in values.iteritems():
            volume_ref[key] = value
        volume_ref.save(session=session)


###################


def security_group_get_all(_context):
    session = get_session()
    return session.query(models.SecurityGroup
                 ).filter_by(deleted=False
                 ).options(joinedload_all('rules')
                 ).all()


def security_group_get(_context, security_group_id):
    session = get_session()
    result = session.query(models.SecurityGroup
                   ).filter_by(deleted=False
                   ).filter_by(id=security_group_id
                   ).options(joinedload_all('rules')
                   ).first()
    if not result:
        raise exception.NotFound("No secuity group with id %s" %
                                 security_group_id)
    return result


def security_group_get_by_name(context, project_id, group_name):
    session = get_session()
    result = session.query(models.SecurityGroup
                      ).filter_by(project_id=project_id
                      ).filter_by(name=group_name
                      ).filter_by(deleted=False
                      ).options(joinedload_all('rules')
                      ).options(joinedload_all('instances')
                      ).first()
    if not result:
        raise exception.NotFound(
            'No security group named %s for project: %s' \
             % (group_name, project_id))
    return result


def security_group_get_by_project(_context, project_id):
    session = get_session()
    return session.query(models.SecurityGroup
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=False
                 ).options(joinedload_all('rules')
                 ).all()


def security_group_get_by_instance(_context, instance_id):
    session = get_session()
    return session.query(models.SecurityGroup
                 ).filter_by(deleted=False
                 ).options(joinedload_all('rules')
                 ).join(models.SecurityGroup.instances
                 ).filter_by(id=instance_id
                 ).filter_by(deleted=False
                 ).all()


def security_group_exists(_context, project_id, group_name):
    try:
        group = security_group_get_by_name(_context, project_id, group_name)
        return group != None
    except exception.NotFound:
        return False


def security_group_create(_context, values):
    security_group_ref = models.SecurityGroup()
    # FIXME(devcamcar): Unless I do this, rules fails with lazy load exception
    # once save() is called.  This will get cleaned up in next orm pass.
    security_group_ref.rules
    for (key, value) in values.iteritems():
        security_group_ref[key] = value
    security_group_ref.save()
    return security_group_ref


def security_group_destroy(_context, security_group_id):
    session = get_session()
    with session.begin():
        # TODO(vish): do we have to use sql here?
        session.execute('update security_groups set deleted=1 where id=:id',
                        {'id': security_group_id})
        session.execute('update security_group_rules set deleted=1 '
                        'where group_id=:id',
                        {'id': security_group_id})

def security_group_destroy_all(_context):
    session = get_session()
    with session.begin():
        # TODO(vish): do we have to use sql here?
        session.execute('update security_groups set deleted=1')
        session.execute('update security_group_rules set deleted=1')

###################


def security_group_rule_create(_context, values):
    security_group_rule_ref = models.SecurityGroupIngressRule()
    for (key, value) in values.iteritems():
        security_group_rule_ref[key] = value
    security_group_rule_ref.save()
    return security_group_rule_ref

def security_group_rule_destroy(_context, security_group_rule_id):
    session = get_session()
    with session.begin():
        model = models.SecurityGroupIngressRule
        security_group_rule = model.find(security_group_rule_id,
                                         session=session)
        security_group_rule.delete(session=session)


###################


def host_get_networks(context, host):
    session = get_session()
    with session.begin():
        return session.query(models.Network
                     ).filter_by(deleted=False
                     ).filter_by(host=host
                     ).all()
