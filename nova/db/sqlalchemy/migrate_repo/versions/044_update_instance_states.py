# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import sqlalchemy
from sqlalchemy import MetaData, Table, Column, String

from nova.compute import task_states
from nova.compute import vm_states


meta = MetaData()


c_task_state = Column('task_state',
                      String(length=255, convert_unicode=False,
                             assert_unicode=None, unicode_error=None,
                             _warn_on_bytestring=False),
                      nullable=True)


_upgrade_translations = {
    "stopping": {
        "state_description": vm_states.ACTIVE,
        "task_state": task_states.STOPPING,
    },
    "stopped": {
        "state_description": vm_states.STOPPED,
        "task_state": None,
    },
    "terminated": {
        "state_description": vm_states.DELETED,
        "task_state": None,
    },
    "terminating": {
        "state_description": vm_states.ACTIVE,
        "task_state": task_states.DELETING,
    },
    "running": {
        "state_description": vm_states.ACTIVE,
        "task_state": None,
    },
    "scheduling": {
        "state_description": vm_states.BUILDING,
        "task_state": task_states.SCHEDULING,
    },
    "migrating": {
        "state_description": vm_states.MIGRATING,
        "task_state": None,
    },
    "pending": {
        "state_description": vm_states.BUILDING,
        "task_state": task_states.SCHEDULING,
    },
}


_downgrade_translations = {
    vm_states.ACTIVE: {
        None: "running",
        task_states.DELETING: "terminating",
        task_states.STOPPING: "stopping",
    },
    vm_states.BUILDING: {
        None: "pending",
        task_states.SCHEDULING: "scheduling",
    },
    vm_states.STOPPED: {
        None: "stopped",
    },
    vm_states.REBUILDING: {
        None: "pending",
    },
    vm_states.DELETED: {
        None: "terminated",
    },
    vm_states.MIGRATING: {
        None: "migrating",
    },
}


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True,
                           autoload_with=migrate_engine)

    c_state = instance_table.c.state
    c_state.alter(name='power_state')

    c_vm_state = instance_table.c.state_description
    c_vm_state.alter(name='vm_state')

    instance_table.create_column(c_task_state)

    for old_state, values in _upgrade_translations.iteritems():
        instance_table.update().\
            values(**values).\
            where(c_vm_state == old_state).\
            execute()


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True,
                           autoload_with=migrate_engine)

    c_task_state = instance_table.c.task_state

    c_state = instance_table.c.power_state
    c_state.alter(name='state')

    c_vm_state = instance_table.c.vm_state
    c_vm_state.alter(name='state_description')

    for old_vm_state, old_task_states in _downgrade_translations.iteritems():
        for old_task_state, new_state_desc in old_task_states.iteritems():
            instance_table.update().\
                where(c_task_state == old_task_state).\
                where(c_vm_state == old_vm_state).\
                values(vm_state=new_state_desc).\
                execute()

    instance_table.drop_column('task_state')
