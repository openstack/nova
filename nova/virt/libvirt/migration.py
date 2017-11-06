# Copyright (c) 2016 Red Hat, Inc
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


"""Utility methods to manage guests migration

"""

from collections import deque

from lxml import etree
from oslo_log import log as logging

from nova.compute import power_state
import nova.conf

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

# TODO(berrange): hack to avoid a "import libvirt" in this file.
# Remove this and similar hacks in guest.py, driver.py, host.py
# etc in Ocata.
libvirt = None


def graphics_listen_addrs(migrate_data):
    """Returns listen addresses of vnc/spice from a LibvirtLiveMigrateData"""
    listen_addrs = None
    if (migrate_data.obj_attr_is_set('graphics_listen_addr_vnc')
        or migrate_data.obj_attr_is_set('graphics_listen_addr_spice')):
        listen_addrs = {'vnc': None, 'spice': None}
    if migrate_data.obj_attr_is_set('graphics_listen_addr_vnc'):
        listen_addrs['vnc'] = str(migrate_data.graphics_listen_addr_vnc)
    if migrate_data.obj_attr_is_set('graphics_listen_addr_spice'):
        listen_addrs['spice'] = str(
            migrate_data.graphics_listen_addr_spice)
    return listen_addrs


def serial_listen_addr(migrate_data):
    """Returns listen address serial from a LibvirtLiveMigrateData"""
    listen_addr = None
    # NOTE (markus_z/dansmith): Our own from_legacy_dict() code can return
    # an object with nothing set here. That can happen based on the
    # compute RPC version pin. Until we can bump that major (which we
    # can do just before Ocata releases), we may still get a legacy
    # dict over the wire, converted to an object, and thus is may be unset
    # here.
    if migrate_data.obj_attr_is_set('serial_listen_addr'):
        # NOTE (markus_z): The value of 'serial_listen_addr' is either
        # an IP address (as string type) or None. There's no need of a
        # conversion, in fact, doing a string conversion of None leads to
        # 'None', which is an invalid (string type) value here.
        listen_addr = migrate_data.serial_listen_addr
    return listen_addr


# TODO(sahid): remove me for Q*
def serial_listen_ports(migrate_data):
    """Returns ports serial from a LibvirtLiveMigrateData"""
    ports = []
    if migrate_data.obj_attr_is_set('serial_listen_ports'):
        ports = migrate_data.serial_listen_ports
    return ports


def get_updated_guest_xml(guest, migrate_data, get_volume_config):
    xml_doc = etree.fromstring(guest.get_xml_desc(dump_migratable=True))
    xml_doc = _update_graphics_xml(xml_doc, migrate_data)
    xml_doc = _update_serial_xml(xml_doc, migrate_data)
    xml_doc = _update_volume_xml(xml_doc, migrate_data, get_volume_config)
    xml_doc = _update_perf_events_xml(xml_doc, migrate_data)
    return etree.tostring(xml_doc)


def _update_graphics_xml(xml_doc, migrate_data):
    listen_addrs = graphics_listen_addrs(migrate_data)

    # change over listen addresses
    for dev in xml_doc.findall('./devices/graphics'):
        gr_type = dev.get('type')
        listen_tag = dev.find('listen')
        if gr_type in ('vnc', 'spice'):
            if listen_tag is not None:
                listen_tag.set('address', listen_addrs[gr_type])
            if dev.get('listen') is not None:
                dev.set('listen', listen_addrs[gr_type])
    return xml_doc


def _update_serial_xml(xml_doc, migrate_data):
    listen_addr = serial_listen_addr(migrate_data)
    listen_ports = serial_listen_ports(migrate_data)

    def set_listen_addr_and_port(source, listen_addr, serial_listen_ports):
        # The XML nodes can be empty, which would make checks like
        # "if source.get('host'):" different to an explicit check for
        # None. That's why we have to check for None in this method.
        if source.get('host') is not None:
            source.set('host', listen_addr)
        device = source.getparent()
        target = device.find("target")
        if target is not None and source.get('service') is not None:
            port_index = int(target.get('port'))
            # NOTE (markus_z): Previous releases might not give us the
            # ports yet, that's why we have this check here.
            if len(serial_listen_ports) > port_index:
                source.set('service', str(serial_listen_ports[port_index]))

    # This updates all "LibvirtConfigGuestSerial" devices
    for source in xml_doc.findall("./devices/serial[@type='tcp']/source"):
        set_listen_addr_and_port(source, listen_addr, listen_ports)

    # This updates all "LibvirtConfigGuestConsole" devices
    for source in xml_doc.findall("./devices/console[@type='tcp']/source"):
        set_listen_addr_and_port(source, listen_addr, listen_ports)

    return xml_doc


def _update_volume_xml(xml_doc, migrate_data, get_volume_config):
    """Update XML using device information of destination host."""
    migrate_bdm_info = migrate_data.bdms

    # Update volume xml
    parser = etree.XMLParser(remove_blank_text=True)
    disk_nodes = xml_doc.findall('./devices/disk')

    bdm_info_by_serial = {x.serial: x for x in migrate_bdm_info}
    for pos, disk_dev in enumerate(disk_nodes):
        serial_source = disk_dev.findtext('serial')
        bdm_info = bdm_info_by_serial.get(serial_source)
        if (serial_source is None or
            not bdm_info or not bdm_info.connection_info or
            serial_source not in bdm_info_by_serial):
            continue
        conf = get_volume_config(
            bdm_info.connection_info, bdm_info.as_disk_info())
        xml_doc2 = etree.XML(conf.to_xml(), parser)
        serial_dest = xml_doc2.findtext('serial')

        # Compare source serial and destination serial number.
        # If these serial numbers match, continue the process.
        if (serial_dest and (serial_source == serial_dest)):
            LOG.debug("Find same serial number: pos=%(pos)s, "
                      "serial=%(num)s",
                      {'pos': pos, 'num': serial_source})
            for cnt, item_src in enumerate(disk_dev):
                # If source and destination have same item, update
                # the item using destination value.
                for item_dst in xml_doc2.findall(item_src.tag):
                    if item_dst.tag != 'address':
                        # hw address presented to guest must never change,
                        # especially during live migration as it can be fatal
                        disk_dev.remove(item_src)
                        item_dst.tail = None
                        disk_dev.insert(cnt, item_dst)

            # If destination has additional items, thses items should be
            # added here.
            for item_dst in list(xml_doc2):
                if item_dst.tag != 'address':
                    # again, hw address presented to guest must never change
                    item_dst.tail = None
                    disk_dev.insert(cnt, item_dst)
    return xml_doc


def _update_perf_events_xml(xml_doc, migrate_data):
    """Update XML by the supported events of destination host."""

    supported_perf_events = []
    old_xml_has_perf = True

    if 'supported_perf_events' in migrate_data:
        supported_perf_events = migrate_data.supported_perf_events

    perf_events = xml_doc.findall('./perf')

    # remove perf events from xml
    if not perf_events:
        perf_events = etree.Element("perf")
        old_xml_has_perf = False
    else:
        perf_events = perf_events[0]
        for _, event in enumerate(perf_events):
            perf_events.remove(event)

    if not supported_perf_events:
        return xml_doc

    # add supported perf events
    for e in supported_perf_events:
        new_event = etree.Element("event", enabled="yes", name=e)
        perf_events.append(new_event)

    if not old_xml_has_perf:
        xml_doc.append(perf_events)

    return xml_doc


def find_job_type(guest, instance):
    """Determine the (likely) current migration job type

    :param guest: a nova.virt.libvirt.guest.Guest
    :param instance: a nova.objects.Instance

    Annoyingly when job type == NONE and migration is
    no longer running, we don't know whether we stopped
    because of failure or completion. We can distinguish
    these cases by seeing if the VM still exists & is
    running on the current host

    :returns: a libvirt job type constant
    """
    try:
        if guest.is_active():
            LOG.debug("VM running on src, migration failed",
                      instance=instance)
            return libvirt.VIR_DOMAIN_JOB_FAILED
        else:
            LOG.debug("VM is shutoff, migration finished",
                      instance=instance)
            return libvirt.VIR_DOMAIN_JOB_COMPLETED
    except libvirt.libvirtError as ex:
        LOG.debug("Error checking domain status %(ex)s",
                  {"ex": ex}, instance=instance)
        if ex.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
            LOG.debug("VM is missing, migration finished",
                      instance=instance)
            return libvirt.VIR_DOMAIN_JOB_COMPLETED
        else:
            LOG.info("Error %(ex)s, migration failed",
                     {"ex": ex}, instance=instance)
            return libvirt.VIR_DOMAIN_JOB_FAILED


def should_abort(instance, now,
                 progress_time, progress_timeout,
                 elapsed, completion_timeout,
                 migration_status):
    """Determine if the migration should be aborted

    :param instance: a nova.objects.Instance
    :param now: current time in secs since epoch
    :param progress_time: when progress was last made in secs since epoch
    :param progress_timeout: time in secs to allow for progress
    :param elapsed: total elapsed time of migration in secs
    :param completion_timeout: time in secs to allow for completion
    :param migration_status: current status of the migration

    Check the progress and completion timeouts to determine if either
    of them have been hit, and should thus cause migration to be aborted

    Avoid migration to be aborted if it is running in post-copy mode

    :returns: True if migration should be aborted, False otherwise
    """
    if migration_status == 'running (post-copy)':
        return False

    if (progress_timeout != 0 and
            (now - progress_time) > progress_timeout):
        LOG.warning("Live migration stuck for %d sec",
                    (now - progress_time), instance=instance)
        return True

    if (completion_timeout != 0 and
            elapsed > completion_timeout):
        LOG.warning("Live migration not completed after %d sec",
                    completion_timeout, instance=instance)
        return True

    return False


def should_switch_to_postcopy(memory_iteration, current_data_remaining,
                              previous_data_remaining, migration_status):
    """Determine if the migration should be switched to postcopy mode

    :param memory_iteration: Number of memory iterations during the migration
    :param current_data_remaining: amount of memory to be transferred
    :param previous_data_remaining: previous memory to be transferred
    :param migration_status: current status of the migration

    Check the progress after the first memory iteration to determine if the
    migration should be switched to post-copy mode

    Avoid post-copy switch if already running in post-copy mode

    :returns: True if migration should be switched to postcopy mode,
    False otherwise
    """
    if (migration_status == 'running (post-copy)' or
        previous_data_remaining <= 0):
        return False

    if memory_iteration > 1:
        progress_percentage = round((previous_data_remaining -
                                     current_data_remaining) *
                                    100 / previous_data_remaining)
        # If migration progress is less than 10% per iteration after the
        # first memory page copying pass, the migration is switched to
        # postcopy mode
        if progress_percentage < 10:
            return True
    return False


def update_downtime(guest, instance,
                    olddowntime,
                    downtime_steps, elapsed):
    """Update max downtime if needed

    :param guest: a nova.virt.libvirt.guest.Guest to set downtime for
    :param instance: a nova.objects.Instance
    :param olddowntime: current set downtime, or None
    :param downtime_steps: list of downtime steps
    :param elapsed: total time of migration in secs

    Determine if the maximum downtime needs to be increased
    based on the downtime steps. Each element in the downtime
    steps list should be a 2 element tuple. The first element
    contains a time marker and the second element contains
    the downtime value to set when the marker is hit.

    The guest object will be used to change the current
    downtime value on the instance.

    Any errors hit when updating downtime will be ignored

    :returns: the new downtime value
    """
    LOG.debug("Current %(dt)s elapsed %(elapsed)d steps %(steps)s",
              {"dt": olddowntime, "elapsed": elapsed,
               "steps": downtime_steps}, instance=instance)
    thisstep = None
    for step in downtime_steps:
        if elapsed > step[0]:
            thisstep = step

    if thisstep is None:
        LOG.debug("No current step", instance=instance)
        return olddowntime

    if thisstep[1] == olddowntime:
        LOG.debug("Downtime does not need to change",
                  instance=instance)
        return olddowntime

    LOG.info("Increasing downtime to %(downtime)d ms "
             "after %(waittime)d sec elapsed time",
             {"downtime": thisstep[1],
              "waittime": thisstep[0]},
             instance=instance)

    try:
        guest.migrate_configure_max_downtime(thisstep[1])
    except libvirt.libvirtError as e:
        LOG.warning("Unable to increase max downtime to %(time)d ms: %(e)s",
                    {"time": thisstep[1], "e": e}, instance=instance)
    return thisstep[1]


def save_stats(instance, migration, info, remaining):
    """Save migration stats to the database

    :param instance: a nova.objects.Instance
    :param migration: a nova.objects.Migration
    :param info: a nova.virt.libvirt.guest.JobInfo
    :param remaining: percentage data remaining to transfer

    Update the migration and instance objects with
    the latest available migration stats
    """

    # The fully detailed stats
    migration.memory_total = info.memory_total
    migration.memory_processed = info.memory_processed
    migration.memory_remaining = info.memory_remaining
    migration.disk_total = info.disk_total
    migration.disk_processed = info.disk_processed
    migration.disk_remaining = info.disk_remaining
    migration.save()

    # The coarse % completion stats
    instance.progress = 100 - remaining
    instance.save()


def trigger_postcopy_switch(guest, instance, migration):
    try:
        guest.migrate_start_postcopy()
    except libvirt.libvirtError as e:
        LOG.warning("Failed to switch to post-copy live migration: %s",
                    e, instance=instance)
    else:
        # NOTE(ltomas): Change the migration status to indicate that
        # it is in post-copy active mode, i.e., the VM at
        # destination is the active one
        LOG.info("Switching to post-copy migration mode",
                 instance=instance)
        migration.status = 'running (post-copy)'
        migration.save()


def run_tasks(guest, instance, active_migrations, on_migration_failure,
              migration, is_post_copy_enabled):
    """Run any pending migration tasks

    :param guest: a nova.virt.libvirt.guest.Guest
    :param instance: a nova.objects.Instance
    :param active_migrations: dict of active migrations
    :param on_migration_failure: queue of recovery tasks
    :param migration: a nova.objects.Migration
    :param is_post_copy_enabled: True if post-copy can be used

    Run any pending migration tasks queued against the
    provided instance object. The active migrations dict
    should use instance UUIDs for keys and a queue of
    tasks as the values.

    Currently the valid tasks that can be requested
    are "pause" and "force-complete". Other tasks will
    be ignored.
    """

    tasks = active_migrations.get(instance.uuid, deque())
    while tasks:
        task = tasks.popleft()
        if task == 'force-complete':
            if migration.status == 'running (post-copy)':
                LOG.warning("Live-migration %s already switched "
                            "to post-copy mode.",
                            instance=instance)
            elif is_post_copy_enabled:
                trigger_postcopy_switch(guest, instance, migration)
            else:
                try:
                    guest.pause()
                    on_migration_failure.append("unpause")
                except Exception as e:
                    LOG.warning("Failed to pause instance during "
                                "live-migration %s",
                                e, instance=instance)
        else:
            LOG.warning("Unknown migration task '%(task)s'",
                        {"task": task}, instance=instance)


def run_recover_tasks(host, guest, instance, on_migration_failure):
    """Run any pending migration recovery tasks

    :param host: a nova.virt.libvirt.host.Host
    :param guest: a nova.virt.libvirt.guest.Guest
    :param instance: a nova.objects.Instance
    :param on_migration_failure: queue of recovery tasks

    Run any recovery tasks provided in the on_migration_failure
    queue.

    Currently the only valid task that can be requested
    is "unpause". Other tasks will be ignored
    """

    while on_migration_failure:
        task = on_migration_failure.popleft()
        # NOTE(tdurakov): there is still possibility to leave
        # instance paused in case of live-migration failure.
        # This check guarantee that instance will be resumed
        # in this case
        if task == 'unpause':
            try:
                state = guest.get_power_state(host)
                if state == power_state.PAUSED:
                    guest.resume()
            except Exception as e:
                LOG.warning("Failed to resume paused instance "
                            "before live-migration rollback %s",
                            e, instance=instance)
        else:
            LOG.warning("Unknown migration task '%(task)s'",
                        {"task": task}, instance=instance)


def downtime_steps(data_gb):
    '''Calculate downtime value steps and time between increases.

    :param data_gb: total GB of RAM and disk to transfer

    This looks at the total downtime steps and upper bound
    downtime value and uses a linear function.

    For example, with 10 steps, 30 second step delay, 3 GB
    of RAM and 400ms target maximum downtime, the downtime will
    be increased every 90 seconds in the following progression:

    -   0 seconds -> set downtime to  40ms
    -  90 seconds -> set downtime to  76ms
    - 180 seconds -> set downtime to 112ms
    - 270 seconds -> set downtime to 148ms
    - 360 seconds -> set downtime to 184ms
    - 450 seconds -> set downtime to 220ms
    - 540 seconds -> set downtime to 256ms
    - 630 seconds -> set downtime to 292ms
    - 720 seconds -> set downtime to 328ms
    - 810 seconds -> set downtime to 364ms
    - 900 seconds -> set downtime to 400ms

    This allows the guest a good chance to complete migration
    with a small downtime value.
    '''
    downtime = CONF.libvirt.live_migration_downtime
    steps = CONF.libvirt.live_migration_downtime_steps
    delay = CONF.libvirt.live_migration_downtime_delay

    delay = int(delay * data_gb)

    base = downtime / steps
    offset = (downtime - base) / steps

    for i in range(steps + 1):
        yield (int(delay * i), int(base + offset * i))
