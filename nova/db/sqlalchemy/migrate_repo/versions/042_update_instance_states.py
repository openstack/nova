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

from nova import log
from nova.compute import task_states
from nova.compute import vm_states
from nova.db.sqlalchemy import models


LOG = log.getLogger("farts")
meta = MetaData()

c_task_state = Column('task_state',
                      String(length=255, convert_unicode=False,
                             assert_unicode=None, unicode_error=None,
                             _warn_on_bytestring=False),
                      nullable=True)


_upgrade_translations = {
    "stopping": {
        "vm_state": vm_states.ACTIVE,
        "task_state": task_states.STOPPING,
    },
    "stopped": {
        "vm_state": vm_states.STOPPED,
        "task_state": None,
    },
    "terminated": {
        "vm_state": vm_states.DELETED,
        "task_state": None,
    },
    "terminating": {
        "vm_state": vm_states.ACTIVE,
        "task_state": task_states.DELETING,
    },
    "running": {
        "vm_state": vm_states.ACTIVE,
        "task_state": None,
    },
    "scheduling": {
        "vm_state": vm_states.BUILDING,
        "task_state": task_states.SCHEDULING,
    },
    "migrating": {
        "vm_state": vm_states.MIGRATING,
        "task_state": None,
    },
    "pending": {
        "vm_state": vm_states.BUILDING,
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


def _insert_test_data(instance_table):
    running_instance = models.Instance()
    running_instance.state_description = "running"
    stopped_instance = models.Instance()
    stopped_instance.state_description = "stopped"
    terminated_instance = models.Instance()
    terminated_instance.state_description = "terminated"
    migrating_instance = models.Instance()
    migrating_instance.state_description = "migrating"
    scheduling_instance = models.Instance()
    scheduling_instance.state_description = "scheduling"
    bad_instance = models.Instance()
    bad_instance.state_description = "bad_state_description"

    instance_table.insert(running_instance).execute()
    instance_table.insert(stopped_instance).execute()
    instance_table.insert(terminated_instance).execute()
    instance_table.insert(migrating_instance).execute()
    instance_table.insert(scheduling_instance).execute()
    instance_table.insert(bad_instance).execute()


def upgrade(migrate_engine):
    #migrate_engine.echo = True
    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True,
                           autoload_with=migrate_engine)
    _insert_test_data(instance_table)
    for instance in instance_table.select().execute():
        LOG.info(instance)
    c_state = instance_table.c.state
    c_state.alter(name='power_state')

    c_vm_state = instance_table.c.state_description
    c_vm_state.alter(name='vm_state')

    instance_table.create_column(c_task_state)

    for old_state, values in _upgrade_translations.iteritems():
        new_values = {
            "old_state": old_state,
            "vm_state": values["vm_state"],
            "task_state": values["task_state"],
        }

        update = sqlalchemy.text("UPDATE instances SET task_state=:task_state "
                                 "WHERE vm_state=:old_state")
        migrate_engine.execute(update, **new_values)

        update = sqlalchemy.text("UPDATE instances SET vm_state=:vm_state "
                                 "WHERE vm_state=:old_state")
        migrate_engine.execute(update, **new_values)

    for instance in instance_table.select().execute():
        LOG.info(instance)

    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True,
                           autoload_with=migrate_engine)

    for old_vm_state, old_task_states in _downgrade_translations.iteritems():
        for old_task_state, new_state_desc in old_task_states.iteritems():
            if old_task_state:
                update = sqlalchemy.text("UPDATE instances "
                                         "SET vm_state=:new_state_desc "
                                         "WHERE task_state=:old_task_state "
                                         "AND vm_state=:old_vm_state")
                migrate_engine.execute(update, locals())
            else:
                update = sqlalchemy.text("UPDATE instances "
                                         "SET vm_state=:new_state_desc "
                                         "WHERE vm_state=:old_vm_state")
                migrate_engine.execute(update, locals())

    #c_state = instance_table.c.power_state
    c_state.alter(name='state')

    #c_vm_state = instance_table.c.vm_state
    c_vm_state.alter(name='state_description')

    instance_table.drop_column('task_state')

    for instance in instance_table.select().execute():
        LOG.info(instance)

    raise Exception()
