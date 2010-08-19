# vim: tabstop=4 shiftwidth=4 softtabstop=4

from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('db_backend', 'sqlalchemy',
                    'The backend to use for db')


_impl = utils.LazyPluggable(FLAGS['db_backend'],
                            sqlalchemy='nova.db.sqlalchemy.api')


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return _impl.instance_destroy(context, instance_id)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return _impl.instance_get(context, instance_id)


def instance_state(context, instance_id, state, description=None):
    """Set the state of an instance."""
    return _impl.instance_state(context, instance_id, state, description)


def instance_update(context, instance_id, new_values):
    """Set the given properties on an instance and update it.
    
    Raises if instance does not exist.

    """
    return _impl.instance_update(context, instance_id, new_values)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return _impl.volume_get(context, volume_id)


def volume_attached(context, volume_id):
    """Ensure that a volume is set as attached."""
    return _impl.volume_attached(context, volume_id)


def volume_detached(context, volume_id):
    """Ensure that a volume is set as detached."""
    return _impl.volume_detached(context, volume_id)

