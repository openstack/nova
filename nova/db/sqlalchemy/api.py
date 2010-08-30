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

from nova import db
from nova import exception
from nova import flags
from nova.db.sqlalchemy import models

FLAGS = flags.FLAGS

###################


def daemon_get(context, daemon_id):
    return models.Daemon.find(daemon_id)


def daemon_get_by_args(context, node_name, binary):
    return models.Daemon.find_by_args(node_name, binary)


def daemon_create(context, values):
    daemon_ref = models.Daemon(**values)
    daemon_ref.save()
    return daemon_ref.id


def daemon_update(context, daemon_id, values):
    daemon_ref = daemon_get(context, daemon_id)
    for (key, value) in values.iteritems():
        daemon_ref[key] = value
    daemon_ref.save()


###################


def floating_ip_allocate_address(context, node_name, project_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FloatingIp).filter_by(node_name=node_name)
    query = query.filter_by(fixed_ip_id=None).with_lockmode("update")
    floating_ip_ref = query.first()
    # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
    #             then this has concurrency issues
    if not floating_ip_ref:
        raise db.NoMoreAddresses()
    floating_ip_ref['project_id'] = project_id
    session.add(floating_ip_ref)
    session.commit()
    return floating_ip_ref['str_id']


def floating_ip_create(context, address, host):
    floating_ip_ref = models.FloatingIp()
    floating_ip_ref['ip_str'] = address
    floating_ip_ref['node_name'] = host
    floating_ip_ref.save()
    return floating_ip_ref


def floating_ip_fixed_ip_associate(context, floating_address, fixed_address):
    floating_ip_ref = db.floating_ip_get_by_address(context, floating_address)
    fixed_ip_ref = models.FixedIp.find_by_str(fixed_address)
    floating_ip_ref.fixed_ip = fixed_ip_ref
    floating_ip_ref.save()


def floating_ip_disassociate(context, address):
    floating_ip_ref = db.floating_ip_get_by_address(context, address)
    fixed_ip_address = floating_ip_ref.fixed_ip['str_id']
    floating_ip_ref['fixed_ip'] = None
    floating_ip_ref.save()
    return fixed_ip_address

def floating_ip_deallocate(context, address):
    floating_ip_ref = db.floating_ip_get_by_address(context, address)
    floating_ip_ref['project_id'] = None
    floating_ip_ref.save()

def floating_ip_get_by_address(context, address):
    return models.FloatingIp.find_by_str(address)


###################


def fixed_ip_allocate(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network_id)
    query = query.filter_by(reserved=False).filter_by(allocated=False)
    query = query.filter_by(leased=False).with_lockmode("update")
    fixed_ip_ref = query.first()
    # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
    #             then this has concurrency issues
    if not fixed_ip_ref:
        raise db.NoMoreAddresses()
    fixed_ip_ref['allocated'] = True
    session.add(fixed_ip_ref)
    session.commit()
    return fixed_ip_ref['str_id']


def fixed_ip_create(context, network_id, address):
    fixed_ip_ref = models.FixedIp()
    fixed_ip_ref.network = db.network_get(context, network_id)
    fixed_ip_ref['ip_str'] = address
    fixed_ip_ref.save()
    return fixed_ip_ref


def fixed_ip_get_by_address(context, address):
    return models.FixedIp.find_by_str(address)


def fixed_ip_get_network(context, address):
    return models.FixedIp.find_by_str(address).network


def fixed_ip_deallocate(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    fixed_ip_ref['allocated'] = False
    fixed_ip_ref.save()


def fixed_ip_instance_associate(context, address, instance_id):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    fixed_ip_ref.instance = instance_get(context, instance_id)
    fixed_ip_ref.save()


def fixed_ip_instance_disassociate(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    fixed_ip_ref.instance = None
    fixed_ip_ref.save()


def fixed_ip_update(context, address, values):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    for (key, value) in values.iteritems():
        fixed_ip_ref[key] = value
    fixed_ip_ref.save()


###################


def instance_create(context, values):
    instance_ref = models.Instance()
    for (key, value) in values.iteritems():
        instance_ref[key] = value
    instance_ref.save()
    return instance_ref.id


def instance_destroy(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    instance_ref.delete()


def instance_get(context, instance_id):
    return models.Instance.find(instance_id)


def instance_get_all(context):
    return models.Instance.all()


def instance_get_by_address(context, address):
    fixed_ip_ref = db.fixed_ip_get_by_address(address)
    if not fixed_ip_ref.instance:
        raise exception.NotFound("No instance found for address %s" % address)
    return fixed_ip_ref.instance


def instance_get_by_project(context, project_id):
    session = models.NovaBase.get_session()
    query = session.query(models.Instance)
    results = query.filter_by(project_id=project_id).all()
    session.commit()
    return results


def instance_get_by_reservation(context, reservation_id):
    session = models.NovaBase.get_session()
    query = session.query(models.Instance)
    results = query.filter_by(reservation_id=reservation_id).all()
    session.commit()
    return results


def instance_get_by_str(context, str_id):
    return models.Instance.find_by_str(str_id)


def instance_get_fixed_address(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    if not instance_ref.fixed_ip:
        return None
    return instance_ref.fixed_ip['str_id']


def instance_get_floating_address(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    if not instance_ref.fixed_ip:
        return None
    if not instance_ref.fixed_ip.floating_ips:
        return None
    # NOTE(vish): this just returns the first floating ip
    return instance_ref.fixed_ip.floating_ips[0]['str_id']


def instance_get_host(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    return instance_ref['node_name']


def instance_is_vpn(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    return instance_ref['image_id'] == FLAGS.vpn_image_id


def instance_state(context, instance_id, state, description=None):
    instance_ref = instance_get(context, instance_id)
    instance_ref.set_state(state, description)


def instance_update(context, instance_id, values):
    instance_ref = instance_get(context, instance_id)
    for (key, value) in values.iteritems():
        instance_ref[key] = value
    instance_ref.save()


###################


def network_count(context):
    return models.Network.count()


def network_count_allocated_ips(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network_id)
    query = query.filter_by(allocated=True)
    return query.count()


def network_count_available_ips(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network_id)
    query = query.filter_by(allocated=False).filter_by(reserved=False)
    return query.count()


def network_count_reserved_ips(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network_id)
    query = query.filter_by(reserved=True)
    return query.count()


def network_create(context, values):
    network_ref = models.Network()
    for (key, value) in values.iteritems():
        network_ref[key] = value
    network_ref.save()
    return network_ref


def network_destroy(context, network_id):
    network_ref = network_get(context, network_id)
    network_ref.delete()


def network_get(context, network_id):
    return models.Network.find(network_id)


def network_get_associated_fixed_ips(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp)
    fixed_ips = query.filter(models.FixedIp.instance_id != None).all()
    session.commit()
    return fixed_ips


def network_get_by_bridge(context, bridge):
    session = models.NovaBase.get_session()
    rv = session.query(models.Network).filter_by(bridge=bridge).first()
    if not rv:
        raise exception.NotFound('No network for bridge %s' % bridge)
    return rv


def network_get_host(context, network_id):
    network_ref = network_get(context, network_id)
    return network_ref['node_name']


def network_get_index(context, network_id):
    session = models.NovaBase.get_session()
    query = session.query(models.NetworkIndex).filter_by(network_id=None)
    network_index = query.with_lockmode("update").first()
    if not network_index:
        raise db.NoMoreNetworks()
    network_index['network'] = network_get(context, network_id)
    session.add(network_index)
    session.commit()
    return network_index['index']


def network_index_count(context):
    return models.NetworkIndex.count()


def network_index_create(context, values):
    network_index_ref = models.NetworkIndex()
    for (key, value) in values.iteritems():
        network_index_ref[key] = value
    network_index_ref.save()


def network_set_host(context, network_id, host_id):
    session = models.NovaBase.get_session()
    query = session.query(models.Network).filter_by(id=network_id)
    network = query.with_lockmode("update").first()
    if not network:
        raise exception.NotFound("Couldn't find network with %s" %
                                 network_id)
    # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
    #             then this has concurrency issues
    if network.node_name:
        session.commit()
        return network['node_name']
    network['node_name'] = host_id
    session.add(network)
    session.commit()
    return network['node_name']


def network_update(context, network_id, values):
    network_ref = network_get(context, network_id)
    for (key, value) in values.iteritems():
        network_ref[key] = value
    network_ref.save()


###################


def project_get_network(context, project_id):
    session = models.create_session()
    rv = session.query(models.Network).filter_by(project_id=project_id).first()
    if not rv:
        raise exception.NotFound('No network for project: %s' % project_id)
    return rv


###################


def queue_get_for(context, topic, physical_node_id):
    return "%s.%s" % (topic, physical_node_id) # FIXME(ja): this should be servername?

###################


def export_device_count(context):
    return models.ExportDevice.count()


def export_device_create(context, values):
    export_device_ref = models.ExportDevice()
    for (key, value) in values.iteritems():
        export_device_ref[key] = value
    export_device_ref.save()
    return export_device_ref


###################


def volume_allocate_shelf_and_blade(context, volume_id):
    session = models.NovaBase.get_session()
    query = session.query(models.ExportDevice).filter_by(volume=None)
    export_device = query.with_lockmode("update").first()
    # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
    #             then this has concurrency issues
    if not export_device:
        raise db.NoMoreBlades()
    export_device.volume_id = volume_id
    session.add(export_device)
    session.commit()
    return (export_device.shelf_id, export_device.blade_id)


def volume_attached(context, volume_id, instance_id, mountpoint):
    volume_ref = volume_get(context, volume_id)
    volume_ref.instance_id = instance_id
    volume_ref['status'] = 'in-use'
    volume_ref['mountpoint'] = mountpoint
    volume_ref['attach_status'] = 'attached'
    volume_ref.save()


def volume_create(context, values):
    volume_ref = models.Volume()
    for (key, value) in values.iteritems():
        volume_ref[key] = value
    volume_ref.save()
    return volume_ref


def volume_destroy(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    volume_ref.delete()


def volume_detached(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    volume_ref['instance_id'] = None
    volume_ref['mountpoint'] = None
    volume_ref['status'] = 'available'
    volume_ref['attach_status'] = 'detached'
    volume_ref.save()


def volume_get(context, volume_id):
    return models.Volume.find(volume_id)


def volume_get_all(context):
    return models.Volume.all()


def volume_get_by_project(context, project_id):
    session = models.NovaBase.get_session()
    query = session.query(models.Volume)
    results = query.filter_by(project_id=project_id).all()
    session.commit()
    return results


def volume_get_by_str(context, str_id):
    return models.Volume.find_by_str(str_id)


def volume_get_host(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    return volume_ref['node_name']


def volume_get_shelf_and_blade(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    export_device = volume_ref.export_device
    if not export_device:
        raise exception.NotFound()
    return (export_device.shelf_id, export_device.blade_id)


def volume_update(context, volume_id, values):
    volume_ref = volume_get(context, volume_id)
    for (key, value) in values.iteritems():
        volume_ref[key] = value
    volume_ref.save()
