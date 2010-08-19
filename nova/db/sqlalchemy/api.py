# vim: tabstop=4 shiftwidth=4 softtabstop=4

from nova import models


def instance_destroy(context, instance_id):
    instance_ref = instance_get(context, instance_id)
    instance_ref.delete()


def instance_get(context, instance_id):
    return models.Instance.find(instance_id)


def instance_state(context, instance_id, state, description=None):
    instance_ref = instance_get(context, instance_id)
    instance_ref.set_state(state, description)


def instance_update(context, instance_id, properties):
    instance_ref = instance_get(context, instance_id)
    for k, v in properties.iteritems():
        instance_ref[k] = v
    instance_ref.save()


def volume_get(context, volume_id):
    return models.Volume.find(volume_id)


def volume_attached(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    volume_ref['attach_status'] = 'attached'
    volume_ref.save()


def volume_detached(context, volume_id):
    volume_ref = volume_get(context, volume_id)
    volume_ref['instance_id'] = None
    volume_ref['mountpoint'] = None
    volume_ref['status'] = 'available'
    volume_ref['attach_status'] = 'detached'
    volume_ref.save()
