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

import math
import IPy

from nova import db
from nova import exception
from nova import flags
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import managed_session

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
    with managed_session(autocommit=False) as session:
        floating_ip_ref = session.query(models.FloatingIp) \
                                 .filter_by(node_name=node_name) \
                                 .filter_by(fixed_ip_id=None) \
                                 .filter_by(deleted=False) \
                                 .with_lockmode('update') \
                                 .first()
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
    with session.open(autocommit=False) as session:
        fixed_ip_ref = session.query(models.FixedIp) \
                              .filter_by(network_id=network_id) \
                              .filter_by(reserved=False) \
                              .filter_by(allocated=False) \
                              .filter_by(leased=False) \
                              .filter_by(deleted=False) \
                              .with_lockmode('update') \
                              .first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise db.NoMoreAddresses()
        fixed_ip_ref['allocated'] = True
        session.add(fixed_ip_ref)
        session.commit()
        return fixed_ip_ref


def fixed_ip_get_by_address(context, address):
    return models.FixedIp.find_by_str(address)


def fixed_ip_get_network(context, address):
    return models.FixedIp.find_by_str(address).network


def fixed_ip_lease(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    if not fixed_ip_ref['allocated']:
        raise db.AddressNotAllocated(address)
    fixed_ip_ref['leased'] = True
    fixed_ip_ref.save()


def fixed_ip_release(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    fixed_ip_ref['allocated'] = False
    fixed_ip_ref['leased'] = False
    fixed_ip_ref.save()


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
    with managed_session() as session:
        return session.query(models.Instance) \
                      .filter_by(project_id=project_id) \
                      .filter_by(deleted=False) \
                      .all()


def instance_get_by_reservation(context, reservation_id):
    with managed_session() as session:
        return session.query(models.Instance) \
                      .filter_by(reservation_id=reservation_id) \
                      .filter_by(deleted=False) \
                      .all()


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


# NOTE(vish): is there a better place for this logic?
def network_allocate(context, project_id):
    """Set up the network"""
    db.network_ensure_indexes(context, FLAGS.num_networks)
    network_id = db.network_create(context, {'project_id': project_id})
    private_net = IPy.IP(FLAGS.private_range)
    index = db.network_get_index(context, network_id)
    vlan = FLAGS.vlan_start + index
    start = index * FLAGS.network_size
    significant_bits = 32 - int(math.log(FLAGS.network_size, 2))
    cidr = "%s/%s" % (private_net[start], significant_bits)
    db.network_set_cidr(context, network_id, cidr)
    net = {}
    net['kind'] = FLAGS.network_type
    net['vlan'] = vlan
    net['bridge'] = 'br%s' % vlan
    net['vpn_public_ip_str'] = FLAGS.vpn_ip
    net['vpn_public_port'] = FLAGS.vpn_start + index
    db.network_update(context, network_id, net)
    db.network_create_fixed_ips(context, network_id, FLAGS.cnt_vpn_clients)
    return network_id


def network_count(context):
    return models.Network.count()

def network_count_allocated_ips(context, network_id):
    with managed_session() as session:
        return session.query(models.FixedIp) \
                      .filter_by(network_id=network_id) \
                      .filter_by(allocated=True) \
                      .filter_by(deleted=False) \
                      .count()


def network_count_available_ips(context, network_id):
    with managed_session() as session:
        return session.query(models.FixedIp) \
                      .filter_by(network_id=network_id) \
                      .filter_by(allocated=False) \
                      .filter_by(reserved=False) \
                      .filter_by(deleted=False) \
                      .count()


def network_count_reserved_ips(context, network_id):
    with managed_session() as session:
        return session.query(models.FixedIp) \
                      .filter_by(network_id=network_id) \
                      .filter_by(reserved=True) \
                      .filter_by(deleted=False) \
                      .count()


def network_create(context, values):
    network_ref = models.Network()
    for (key, value) in values.iteritems():
        network_ref[key] = value
    network_ref.save()
    return network_ref.id


def network_create_fixed_ips(context, network_id, num_vpn_clients):
    with managed_session(autocommit=False) as session:
        network_ref = network_get(context, network_id, session=session)
        # NOTE(vish): should these be properties of the network as opposed
        #             to constants?
        BOTTOM_RESERVED = 3
        TOP_RESERVED = 1 + num_vpn_clients
        project_net = IPy.IP(network_ref['cidr'])
        num_ips = len(project_net)
        
        for i in range(num_ips):
            fixed_ip = models.FixedIp()
            fixed_ip['ip_str'] = str(project_net[i])
            if i < BOTTOM_RESERVED or num_ips - i < TOP_RESERVED:
                fixed_ip['reserved'] = True
            fixed_ip['network'] = network_get(context,
                                              network_id,
                                              session=session)
            session.add(fixed_ip)
        session.commit()


def network_ensure_indexes(context, num_networks):
    with managed_session(autocommit=False) as session:
        count = models.NetworkIndex.count(session=session)
        if count == 0:
            for i in range(num_networks):
                network_index = models.NetworkIndex()
                network_index.index = i
                session.add(network_index)
            session.commit()


def network_destroy(context, network_id):
    with managed_session(autocommit=False) as session:
        session.execute('update networks set deleted=1 where id=:id',
                        {'id': network_id})
        session.execute('update network_indexes set deleted=1 where network_id=:id',
                        {'id': network_id})
        session.commit()


def network_get(context, network_id, session=None):
    return models.Network.find(network_id, session=session)


def network_get_associated_fixed_ips(context, network_id):
    with managed_session() as session:
        return session.query(models.FixedIp) \
                      .filter(models.FixedIp.instance_id != None) \
                      .filter_by(deleted=False) \
                      .all()


def network_get_by_bridge(context, bridge):
    with managed_session() as session:
        rv = session.query(models.Network) \
                    .filter_by(bridge=bridge) \
                    .filter_by(deleted=False) \
                    .first()
        if not rv:
            raise exception.NotFound('No network for bridge %s' % bridge)
        return rv


def network_get_vpn_ip(context, network_id):
    # TODO(vish): possible concurrency issue here
    network = network_get(context, network_id)
    address = network['vpn_private_ip_str']
    fixed_ip = fixed_ip_get_by_address(context, address)
    if fixed_ip['allocated']:
        raise db.AddressAlreadyAllocated()
    db.fixed_ip_update(context, fixed_ip['id'], {'allocated': True})
    return fixed_ip


def network_get_host(context, network_id):
    network_ref = network_get(context, network_id)
    return network_ref['node_name']


def network_get_index(context, network_id):
    with managed_session(autocommit=False) as session:
        network_index = session.query(models.NetworkIndex) \
                               .filter_by(network_id=None) \
                               .filter_by(deleted=False) \
                               .with_lockmode('update') \
                               .first()
        if not network_index:
            raise db.NoMoreNetworks()
        network_index['network'] = network_get(context, network_id, session=session)
        session.add(network_index)
        session.commit()
        return network_index['index']


def network_set_cidr(context, network_id, cidr):
    network_ref = network_get(context, network_id)
    project_net = IPy.IP(cidr)
    network_ref['cidr'] = cidr
    # FIXME we can turn these into properties
    network_ref['netmask'] = str(project_net.netmask())
    network_ref['gateway'] = str(project_net[1])
    network_ref['broadcast'] = str(project_net.broadcast())
    network_ref['vpn_private_ip_str'] = str(project_net[2])
    network_ref['dhcp_start'] = str(project_net[3])
    network_ref.save()


def network_set_host(context, network_id, host_id):
    with managed_session(autocommit=False) as session:
        network = session.query(models.Network) \
                         .filter_by(id=network_id) \
                         .filter_by(deleted=False) \
                         .with_lockmode('update') \
                         .first()
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
    with managed_session() as session:
        rv = session.query(models.Network) \
                    .filter_by(project_id=project_id) \
                    .filter_by(deleted=False) \
                    .first()
        if not rv:
            raise exception.NotFound('No network for project: %s' % project_id)
        return rv


###################


def queue_get_for(context, topic, physical_node_id):
    return "%s.%s" % (topic, physical_node_id) # FIXME(ja): this should be servername?

###################


def volume_allocate_shelf_and_blade(context, volume_id):
    with managed_session(autocommit=False) as session:    
        volume_ensure_blades(context,
                             FLAGS.num_shelves,
                             FLAGS.blades_per_shelf,
                             session=session)
        export_device = session.query(models.ExportDevice) \
                               .filter_by(volume=None) \
                               .filter_by(deleted=False) \
                               .with_lockmode('update') \
                               .first()
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
    return volume_ref.id


def volume_destroy(context, volume_id):
    with managed_session(autocommit=False) as session:
        session.execute('update volumes set deleted=1 where id=:id',
                        {'id': volume_id})
        session.execute('update export_devices set deleted=1 where network_id=:id',
                        {'id': volume_id})
        session.commit()


def volume_detached(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    volume_ref['instance_id'] = None
    volume_ref['mountpoint'] = None
    volume_ref['status'] = 'available'
    volume_ref['attach_status'] = 'detached'
    volume_ref.save()


# NOTE(vish): should this code go up a layer?
def volume_ensure_blades(context, num_shelves, blades_per_shelf, session=None):
    count = models.ExportDevice.count(session=session)
    if count >= num_shelves * blades_per_shelf:
        return
    for shelf_id in xrange(num_shelves):
        for blade_id in xrange(blades_per_shelf):
            export_device = models.ExportDevice()
            export_device.shelf_id = shelf_id
            export_device.blade_id = blade_id
            export_device.save(session=session)


def volume_get(context, volume_id):
    return models.Volume.find(volume_id)


def volume_get_all(context):
    return models.Volume.all()


def volume_get_by_project(context, project_id):
    with managed_session() as session:
        return session.query(models.Volume) \
                      .filter_by(project_id=project_id) \
                      .filter_by(deleted=False) \
                      .all()


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
