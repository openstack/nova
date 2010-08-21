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

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('db_backend', 'sqlalchemy',
                    'The backend to use for db')


_impl = utils.LazyPluggable(FLAGS['db_backend'],
                            sqlalchemy='nova.db.sqlalchemy.api')


class NoMoreBlades(exception.Error):
    pass


###################


def daemon_get(context, node_name, binary):
    return _impl.daemon_get(context, node_name, binary)
    

def daemon_create(context, values):
    return _impl.daemon_create(context, values)


def daemon_update(context, values):
    return _impl.daemon_update(context, values)


###################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return _impl.instance_create(context, values)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return _impl.instance_destroy(context, instance_id)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return _impl.instance_get(context, instance_id)


def instance_state(context, instance_id, state, description=None):
    """Set the state of an instance."""
    return _impl.instance_state(context, instance_id, state, description)


def instance_update(context, instance_id, values):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return _impl.instance_update(context, instance_id, values)


####################


def network_create(context, values):
    """Create a network from the values dictionary."""
    return _impl.network_create(context, values)


def network_destroy(context, network_id):
    """Destroy the network or raise if it does not exist."""
    return _impl.network_destroy(context, network_id)


def network_get(context, network_id):
    """Get an network or raise if it does not exist."""
    return _impl.network_get(context, network_id)


def network_update(context, network_id, values):
    """Set the given properties on an network and update it.

    Raises NotFound if network does not exist.

    """
    return _impl.network_update(context, network_id, values)


###################


def project_get_network(context, project_id):
    """Return the network associated with the project."""
    return _impl.project_get_network(context, project_id)


###################


def volume_allocate_shelf_and_blade(context, volume_id):
    """Atomically allocate a free shelf and blade from the pool."""
    return _impl.volume_allocate_shelf_and_blade(context, volume_id)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return _impl.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return _impl.volume_create(context, values)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return _impl.volume_destroy(context, volume_id)


def volume_detached(context, volume_id):
    """Ensure that a volume is set as detached."""
    return _impl.volume_detached(context, volume_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return _impl.volume_get(context, volume_id)


def volume_get_shelf_and_blade(context, volume_id):
    """Get the shelf and blade allocated to the volume."""
    return _impl.volume_get_shelf_and_blade(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return _impl.volume_update(context, volume_id, values)


