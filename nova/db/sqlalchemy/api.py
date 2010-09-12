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

from nova import db
from nova import exception
from nova import flags
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from sqlalchemy import or_
from sqlalchemy.orm import joinedload_all

FLAGS = flags.FLAGS


# NOTE(vish): disabling docstring pylint because the docstrings are
#             in the interface definition
# pylint: disable-msg=C0111
def _deleted(context):
    """Calculates whether to include deleted objects based on context.

    Currently just looks for a flag called deleted in the context dict.
    """
    if not hasattr(context, 'get'):
        return False
    return context.get('deleted', False)


###################


def service_get(_context, service_id):
    return models.Service.find(service_id)


def service_get_by_args(_context, host, binary):
    return models.Service.find_by_args(host, binary)


def service_create(_context, values):
    service_ref = models.Service()
    for (key, value) in values.iteritems():
        service_ref[key] = value
    service_ref.save()
    return service_ref


def service_update(_context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = models.Service.find(service_id, session=session)
        for (key, value) in values.iteritems():
            service_ref[key] = value
        service_ref.save(session=session)


###################


def floating_ip_allocate_address(_context, host, project_id):
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


def floating_ip_create(_context, values):
    floating_ip_ref = models.FloatingIp()
    for (key, value) in values.iteritems():
        floating_ip_ref[key] = value
    floating_ip_ref.save()
    return floating_ip_ref['address']


def floating_ip_fixed_ip_associate(_context, floating_address, fixed_address):
    session = get_session()
    with session.begin():
        floating_ip_ref = models.FloatingIp.find_by_str(floating_address,
                                                        session=session)
        fixed_ip_ref = models.FixedIp.find_by_str(fixed_address,
                                                  session=session)
        floating_ip_ref.fixed_ip = fixed_ip_ref
        floating_ip_ref.save(session=session)


def floating_ip_deallocate(_context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = models.FloatingIp.find_by_str(address,
                                                        session=session)
        floating_ip_ref['project_id'] = None
        floating_ip_ref.save(session=session)


def floating_ip_destroy(_context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = models.FloatingIp.find_by_str(address,
                                                        session=session)
        floating_ip_ref.delete(session=session)


def floating_ip_disassociate(_context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = models.FloatingIp.find_by_str(address,
                                                        session=session)
        fixed_ip_ref = floating_ip_ref.fixed_ip
        if fixed_ip_ref:
            fixed_ip_address = fixed_ip_ref['address']
        else:
            fixed_ip_address = None
        floating_ip_ref.fixed_ip = None
        floating_ip_ref.save(session=session)
    return fixed_ip_address


def floating_ip_get_all(_context):
    session = get_session()
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(deleted=False
                 ).all()


def floating_ip_get_all_by_host(_context, host):
    session = get_session()
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(host=host
                 ).filter_by(deleted=False
                 ).all()

def floating_ip_get_all_by_project(_context, project_id):
    session = get_session()
    return session.query(models.FloatingIp
                 ).options(joinedload_all('fixed_ip.instance')
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=False
                 ).all()

def floating_ip_get_by_address(_context, address):
    return models.FloatingIp.find_by_str(address)


def floating_ip_get_instance(_context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = models.FloatingIp.find_by_str(address,
                                                        session=session)
        return floating_ip_ref.fixed_ip.instance


###################


def fixed_ip_associate(_context, address, instance_id):
    session = get_session()
    with session.begin():
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
        fixed_ip_ref.instance = models.Instance.find(instance_id,
                                                     session=session)
        session.add(fixed_ip_ref)


def fixed_ip_associate_pool(_context, network_id, instance_id):
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
            fixed_ip_ref.network = models.Network.find(network_id,
                                                       session=session)
        fixed_ip_ref.instance = models.Instance.find(instance_id,
                                                     session=session)
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


def fixed_ip_create(_context, values):
    fixed_ip_ref = models.FixedIp()
    for (key, value) in values.iteritems():
        fixed_ip_ref[key] = value
    fixed_ip_ref.save()
    return fixed_ip_ref['address']


def fixed_ip_disassociate(_context, address):
    session = get_session()
    with session.begin():
        fixed_ip_ref = models.FixedIp.find_by_str(address, session=session)
        fixed_ip_ref.instance = None
        fixed_ip_ref.save(session=session)


def fixed_ip_get_by_address(_context, address):
    return models.FixedIp.find_by_str(address)


def fixed_ip_get_instance(_context, address):
    session = get_session()
    with session.begin():
        return models.FixedIp.find_by_str(address, session=session).instance


def fixed_ip_get_network(_context, address):
    session = get_session()
    with session.begin():
        return models.FixedIp.find_by_str(address, session=session).network


def fixed_ip_update(_context, address, values):
    session = get_session()
    with session.begin():
        fixed_ip_ref = models.FixedIp.find_by_str(address, session=session)
        for (key, value) in values.iteritems():
            fixed_ip_ref[key] = value
        fixed_ip_ref.save(session=session)


###################


def instance_create(_context, values):
    instance_ref = models.Instance()
    for (key, value) in values.iteritems():
        instance_ref[key] = value
    instance_ref.save()
    return instance_ref


def instance_destroy(_context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = models.Instance.find(instance_id, session=session)
        instance_ref.delete(session=session)


def instance_get(context, instance_id):
    return models.Instance.find(instance_id, deleted=_deleted(context))


def instance_get_all(context):
    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(deleted=_deleted(context)
                 ).all()


def instance_get_all_by_project(context, project_id):
    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=_deleted(context)
                 ).all()


def instance_get_all_by_reservation(_context, reservation_id):
    session = get_session()
    return session.query(models.Instance
                 ).options(joinedload_all('fixed_ip.floating_ips')
                 ).filter_by(reservation_id=reservation_id
                 ).filter_by(deleted=False
                 ).all()


def instance_get_by_str(context, str_id):
    return models.Instance.find_by_str(str_id, deleted=_deleted(context))


def instance_get_fixed_address(_context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = models.Instance.find(instance_id, session=session)
        if not instance_ref.fixed_ip:
            return None
        return instance_ref.fixed_ip['address']


def instance_get_floating_address(_context, instance_id):
    session = get_session()
    with session.begin():
        instance_ref = models.Instance.find(instance_id, session=session)
        if not instance_ref.fixed_ip:
            return None
        if not instance_ref.fixed_ip.floating_ips:
            return None
        # NOTE(vish): this just returns the first floating ip
        return instance_ref.fixed_ip.floating_ips[0]['address']


def instance_is_vpn(context, instance_id):
    # TODO(vish): Move this into image code somewhere
    instance_ref = instance_get(context, instance_id)
    return instance_ref['image_id'] == FLAGS.vpn_image_id


def instance_set_state(context, instance_id, state, description=None):
    # TODO(devcamcar): Move this out of models and into driver
    from nova.compute import power_state
    if not description:
        description = power_state.name(state)
    db.instance_update(context,
                       instance_id,
                       {'state': state,
                        'state_description': description})


def instance_update(_context, instance_id, values):
    session = get_session()
    with session.begin():
        instance_ref = models.Instance.find(instance_id, session=session)
        for (key, value) in values.iteritems():
            instance_ref[key] = value
        instance_ref.save(session=session)


###################


def network_count(_context):
    return models.Network.count()


def network_count_allocated_ips(_context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(allocated=True
                 ).filter_by(deleted=False
                 ).count()


def network_count_available_ips(_context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(allocated=False
                 ).filter_by(reserved=False
                 ).filter_by(deleted=False
                 ).count()


def network_count_reserved_ips(_context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).filter_by(network_id=network_id
                 ).filter_by(reserved=True
                 ).filter_by(deleted=False
                 ).count()


def network_create(_context, values):
    network_ref = models.Network()
    for (key, value) in values.iteritems():
        network_ref[key] = value
    network_ref.save()
    return network_ref


def network_destroy(_context, network_id):
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


def network_get(_context, network_id):
    return models.Network.find(network_id)


# NOTE(vish): pylint complains because of the long method name, but
#             it fits with the names of the rest of the methods
# pylint: disable-msg=C0103
def network_get_associated_fixed_ips(_context, network_id):
    session = get_session()
    return session.query(models.FixedIp
                 ).options(joinedload_all('instance')
                 ).filter_by(network_id=network_id
                 ).filter(models.FixedIp.instance_id != None
                 ).filter_by(deleted=False
                 ).all()


def network_get_by_bridge(_context, bridge):
    session = get_session()
    rv = session.query(models.Network
               ).filter_by(bridge=bridge
               ).filter_by(deleted=False
               ).first()
    if not rv:
        raise exception.NotFound('No network for bridge %s' % bridge)
    return rv


def network_get_index(_context, network_id):
    session = get_session()
    with session.begin():
        network_index = session.query(models.NetworkIndex
                              ).filter_by(network_id=None
                              ).filter_by(deleted=False
                              ).with_lockmode('update'
                              ).first()
        if not network_index:
            raise db.NoMoreNetworks()
        network_index['network'] = models.Network.find(network_id,
                                                       session=session)
        session.add(network_index)
    return network_index['index']


def network_index_count(_context):
    return models.NetworkIndex.count()


def network_index_create(_context, values):
    network_index_ref = models.NetworkIndex()
    for (key, value) in values.iteritems():
        network_index_ref[key] = value
    network_index_ref.save()


def network_set_host(_context, network_id, host_id):
    session = get_session()
    with session.begin():
        network = session.query(models.Network
                        ).filter_by(id=network_id
                        ).filter_by(deleted=False
                        ).with_lockmode('update'
                        ).first()
        if not network:
            raise exception.NotFound("Couldn't find network with %s" %
                                     network_id)
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not network['host']:
            network['host'] = host_id
            session.add(network)
    return network['host']


def network_update(_context, network_id, values):
    session = get_session()
    with session.begin():
        network_ref = models.Network.find(network_id, session=session)
        for (key, value) in values.iteritems():
            network_ref[key] = value
        network_ref.save(session=session)


###################


def project_get_network(_context, project_id):
    session = get_session()
    rv = session.query(models.Network
               ).filter_by(project_id=project_id
               ).filter_by(deleted=False
               ).first()
    if not rv:
        raise exception.NotFound('No network for project: %s' % project_id)
    return rv


###################


def queue_get_for(_context, topic, physical_node_id):
    # FIXME(ja): this should be servername?
    return "%s.%s" % (topic, physical_node_id)

###################


def export_device_count(_context):
    return models.ExportDevice.count()


def export_device_create(_context, values):
    export_device_ref = models.ExportDevice()
    for (key, value) in values.iteritems():
        export_device_ref[key] = value
    export_device_ref.save()
    return export_device_ref


###################


def volume_allocate_shelf_and_blade(_context, volume_id):
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


def volume_attached(_context, volume_id, instance_id, mountpoint):
    session = get_session()
    with session.begin():
        volume_ref = models.Volume.find(volume_id, session=session)
        volume_ref['status'] = 'in-use'
        volume_ref['mountpoint'] = mountpoint
        volume_ref['attach_status'] = 'attached'
        volume_ref.instance = models.Instance.find(instance_id,
                                                   session=session)
        volume_ref.save(session=session)


def volume_create(_context, values):
    volume_ref = models.Volume()
    for (key, value) in values.iteritems():
        volume_ref[key] = value
    volume_ref.save()
    return volume_ref


def volume_destroy(_context, volume_id):
    session = get_session()
    with session.begin():
        # TODO(vish): do we have to use sql here?
        session.execute('update volumes set deleted=1 where id=:id',
                        {'id': volume_id})
        session.execute('update export_devices set volume_id=NULL '
                        'where volume_id=:id',
                        {'id': volume_id})


def volume_detached(_context, volume_id):
    session = get_session()
    with session.begin():
        volume_ref = models.Volume.find(volume_id, session=session)
        volume_ref['status'] = 'available'
        volume_ref['mountpoint'] = None
        volume_ref['attach_status'] = 'detached'
        volume_ref.instance = None
        volume_ref.save(session=session)


def volume_get(context, volume_id):
    return models.Volume.find(volume_id, deleted=_deleted(context))


def volume_get_all(context):
    return models.Volume.all(deleted=_deleted(context))


def volume_get_all_by_project(context, project_id):
    session = get_session()
    return session.query(models.Volume
                 ).filter_by(project_id=project_id
                 ).filter_by(deleted=_deleted(context)
                 ).all()


def volume_get_by_str(context, str_id):
    return models.Volume.find_by_str(str_id, deleted=_deleted(context))


def volume_get_instance(_context, volume_id):
    session = get_session()
    with session.begin():
        return models.Volume.find(volume_id, session=session).instance


def volume_get_shelf_and_blade(_context, volume_id):
    session = get_session()
    export_device = session.query(models.ExportDevice
                          ).filter_by(volume_id=volume_id
                          ).first()
    if not export_device:
        raise exception.NotFound()
    return (export_device.shelf_id, export_device.blade_id)


def volume_update(_context, volume_id, values):
    session = get_session()
    with session.begin():
        volume_ref = models.Volume.find(volume_id, session=session)
        for (key, value) in values.iteritems():
            volume_ref[key] = value
        volume_ref.save(session=session)
