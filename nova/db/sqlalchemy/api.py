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
from nova import models


###################


def daemon_get(context, node_name, binary):
    return None
    return models.Daemon.find_by_args(node_name, binary)
    

def daemon_create(context, values):
    daemon_ref = models.Daemon(**values)
    daemon_ref.save()
    return daemon_ref


def daemon_update(context, node_name, binary, values):
    daemon_ref = daemon_get(context, node_name, binary)
    for (key, value) in values.iteritems():
        daemon_ref[key] = value
    daemon_ref.save()


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


def instance_state(context, instance_id, state, description=None):
    instance_ref = instance_get(context, instance_id)
    instance_ref.set_state(state, description)


def instance_update(context, instance_id, values):
    instance_ref = instance_get(context, instance_id)
    for (key, value) in values.iteritems():
        instance_ref[key] = value
    instance_ref.save()


###################


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
    return models.Instance.find(network_id)


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
    return volume_ref.id


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












