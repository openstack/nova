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
from nova import exception
from nova.virt import hardware
from nova.virt.libvirt import config as vconfig

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

# TODO(berrange): hack to avoid a "import libvirt" in this file.
# Remove this and similar hacks in guest.py, driver.py, host.py
# etc in Ocata.
libvirt = None


def graphics_listen_addrs(migrate_data):
    """Returns listen addresses of vnc/spice from a LibvirtLiveMigrateData"""
    listen_addrs = None
    if (migrate_data.obj_attr_is_set('graphics_listen_addr_vnc') or
            migrate_data.obj_attr_is_set('graphics_listen_addr_spice')):
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


def get_updated_guest_xml(guest, migrate_data, get_volume_config,
                          get_vif_config=None):
    xml_doc = etree.fromstring(guest.get_xml_desc(dump_migratable=True))
    xml_doc = _update_graphics_xml(xml_doc, migrate_data)
    xml_doc = _update_serial_xml(xml_doc, migrate_data)
    xml_doc = _update_volume_xml(xml_doc, migrate_data, get_volume_config)
    xml_doc = _update_perf_events_xml(xml_doc, migrate_data)
    xml_doc = _update_memory_backing_xml(xml_doc, migrate_data)
    if get_vif_config is not None:
        xml_doc = _update_vif_xml(xml_doc, migrate_data, get_vif_config)
    if 'dst_numa_info' in migrate_data:
        xml_doc = _update_numa_xml(xml_doc, migrate_data)
    return etree.tostring(xml_doc, encoding='unicode')


def _update_numa_xml(xml_doc, migrate_data):
    LOG.debug('_update_numa_xml input xml=%s',
              etree.tostring(xml_doc, encoding='unicode', pretty_print=True))
    info = migrate_data.dst_numa_info
    # NOTE(artom) cpu_pins, cell_pins and emulator_pins should always come
    # together, or not at all.
    if ('cpu_pins' in info and
          'cell_pins' in info and
          'emulator_pins' in info):
        for guest_id, host_ids in info.cpu_pins.items():
            vcpupin = xml_doc.find(
                './cputune/vcpupin[@vcpu="%d"]' % int(guest_id))
            vcpupin.set('cpuset',
                        hardware.format_cpu_spec(host_ids))

        emulatorpin = xml_doc.find('./cputune/emulatorpin')
        emulatorpin.set('cpuset',
                        hardware.format_cpu_spec(info.emulator_pins))

        all_cells = []
        for guest_id, host_ids in info.cell_pins.items():
            all_cells.extend(host_ids)
            memnode = xml_doc.find(
                './numatune/memnode[@cellid="%d"]' % int(guest_id))
            memnode.set('nodeset',
                        hardware.format_cpu_spec(host_ids))

        memory = xml_doc.find('./numatune/memory')
        memory.set('nodeset', hardware.format_cpu_spec(set(all_cells)))

    if 'sched_vcpus' and 'sched_priority' in info:
        cputune = xml_doc.find('./cputune')

        # delete the old variant(s)
        for elem in cputune.findall('./vcpusched'):
            elem.getparent().remove(elem)

        # ...and create a new, shiny one
        vcpusched = vconfig.LibvirtConfigGuestCPUTuneVCPUSched()
        vcpusched.vcpus = info.sched_vcpus
        vcpusched.priority = info.sched_priority
        # TODO(stephenfin): Stop assuming scheduler type. We currently only
        # create these elements for real-time instances and 'fifo' is the only
        # scheduler policy we currently support so this is reasonably safe to
        # assume, but it's still unnecessary
        vcpusched.scheduler = 'fifo'

        cputune.append(vcpusched.format_dom())

    LOG.debug('_update_numa_xml output xml=%s',
              etree.tostring(xml_doc, encoding='unicode', pretty_print=True))

    return xml_doc


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

        if bdm_info.obj_attr_is_set('encryption_secret_uuid'):
            conf.encryption = vconfig.LibvirtConfigGuestDiskEncryption()
            conf.encryption.format = 'luks'
            secret = vconfig.LibvirtConfigGuestDiskEncryptionSecret()
            secret.type = 'passphrase'
            secret.uuid = bdm_info.encryption_secret_uuid
            conf.encryption.secret = secret

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


def _update_memory_backing_xml(xml_doc, migrate_data):
    """Update libvirt domain XML for file-backed memory

    If incoming XML has a memoryBacking element, remove access, source,
    and allocation children elements to get it to a known consistent state.

    If no incoming memoryBacking element, create one.

    If destination wants file-backed memory, add source, access,
    and allocation children.
    """
    old_xml_has_memory_backing = True
    file_backed = False
    discard = False

    memory_backing = xml_doc.findall('./memoryBacking')

    if 'dst_wants_file_backed_memory' in migrate_data:
        file_backed = migrate_data.dst_wants_file_backed_memory

    if 'file_backed_memory_discard' in migrate_data:
        discard = migrate_data.file_backed_memory_discard

    if not memory_backing:
        # Create memoryBacking element
        memory_backing = etree.Element("memoryBacking")
        old_xml_has_memory_backing = False
    else:
        memory_backing = memory_backing[0]
        # Remove existing file-backed memory tags, if they exist.
        for name in ("access", "source", "allocation", "discard"):
            tag = memory_backing.findall(name)
            if tag:
                memory_backing.remove(tag[0])

    # Leave empty memoryBacking element
    if not file_backed:
        return xml_doc

    # Add file_backed memoryBacking children
    memory_backing.append(etree.Element("source", type="file"))
    memory_backing.append(etree.Element("access", mode="shared"))
    memory_backing.append(etree.Element("allocation", mode="immediate"))

    if discard:
        memory_backing.append(etree.Element("discard"))

    if not old_xml_has_memory_backing:
        xml_doc.append(memory_backing)

    return xml_doc


def _update_vif_xml(xml_doc, migrate_data, get_vif_config):
    # Loop over each interface element in the original xml and find the
    # corresponding vif based on mac and then overwrite the xml with the new
    # attributes but maintain the order of the interfaces and maintain the
    # guest pci address.
    instance_uuid = xml_doc.findtext('uuid')
    parser = etree.XMLParser(remove_blank_text=True)
    interface_nodes = xml_doc.findall('./devices/interface')
    migrate_vif_by_mac = {vif.source_vif['address']: vif
                          for vif in migrate_data.vifs}
    for interface_dev in interface_nodes:
        mac = interface_dev.find('mac')
        mac = mac if mac is not None else {}
        mac_addr = mac.get('address')
        if mac_addr:
            migrate_vif = migrate_vif_by_mac[mac_addr]
            vif = migrate_vif.get_dest_vif()
            # get_vif_config is a partial function of
            # nova.virt.libvirt.vif.LibvirtGenericVIFDriver.get_config
            # with all but the 'vif' kwarg set already and returns a
            # LibvirtConfigGuestInterface object.
            vif_config = get_vif_config(vif=vif)
        else:
            # This shouldn't happen but if it does, we need to abort the
            # migration.
            raise exception.NovaException(
                'Unable to find MAC address in interface XML for '
                'instance %s: %s' % (
                    instance_uuid,
                    etree.tostring(interface_dev, encoding='unicode')))

        # At this point we want to replace the interface elements with the
        # destination vif config xml *except* for the guest PCI address.
        conf_xml = vif_config.to_xml()
        LOG.debug('Updating guest XML with vif config: %s', conf_xml,
                  instance_uuid=instance_uuid)
        dest_interface_elem = etree.XML(conf_xml, parser)
        # Save off the hw address and MTU presented to the guest since that
        # can't change during live migration.
        address = interface_dev.find('address')
        mtu = interface_dev.find('mtu')
        # Now clear the interface's current elements and insert everything
        # from the destination vif config xml.
        interface_dev.clear()
        # Insert attributes.
        for attr_name, attr_value in dest_interface_elem.items():
            interface_dev.set(attr_name, attr_value)
        # Insert sub-elements.
        for index, dest_interface_subelem in enumerate(dest_interface_elem):
            # NOTE(mnaser): If we don't have an MTU, don't define one, else
            #               the live migration will crash.
            if dest_interface_subelem.tag == 'mtu' and mtu is None:
                continue
            interface_dev.insert(index, dest_interface_subelem)
        # And finally re-insert the hw address.
        interface_dev.insert(index + 1, address)

    return xml_doc


def find_job_type(guest, instance, logging_ok=True):
    """Determine the (likely) current migration job type

    :param guest: a nova.virt.libvirt.guest.Guest
    :param instance: a nova.objects.Instance
    :param logging_ok: If logging in this method is OK. If called from a
        native thread then logging is generally prohibited.

    Annoyingly when job type == NONE and migration is
    no longer running, we don't know whether we stopped
    because of failure or completion. We can distinguish
    these cases by seeing if the VM still exists & is
    running on the current host

    :returns: a libvirt job type constant
    """
    def _log(func, msg, *args, **kwargs):
        if logging_ok:
            func(msg, *args, **kwargs)

    try:
        if guest.is_active():
            _log(LOG.debug, "VM running on src, migration failed",
                 instance=instance)
            return libvirt.VIR_DOMAIN_JOB_FAILED
        else:
            _log(LOG.debug, "VM is shutoff, migration finished",
                 instance=instance)
            return libvirt.VIR_DOMAIN_JOB_COMPLETED
    except libvirt.libvirtError as ex:
        _log(LOG.debug, "Error checking domain status %(ex)s", {"ex": ex},
             instance=instance)
        if ex.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
            _log(LOG.debug, "VM is missing, migration finished",
                 instance=instance)
            return libvirt.VIR_DOMAIN_JOB_COMPLETED
        else:
            _log(LOG.info, "Error %(ex)s, migration failed", {"ex": ex},
                 instance=instance)
            return libvirt.VIR_DOMAIN_JOB_FAILED


def should_trigger_timeout_action(instance, elapsed, completion_timeout,
                                  migration_status):
    """Determine if the migration timeout action should be triggered

    :param instance: a nova.objects.Instance
    :param elapsed: total elapsed time of migration in secs
    :param completion_timeout: time in secs to allow for completion
    :param migration_status: current status of the migration

    Check the completion timeout to determine if it has been hit,
    and should thus cause migration timeout action to be triggered.

    Avoid migration to be aborted or triggered post-copy again if it is
    running in post-copy mode

    :returns: True if the migration completion timeout action should be
              performed, False otherwise
    """
    if not completion_timeout:
        return False

    if migration_status == 'running (post-copy)':
        return False

    if elapsed > completion_timeout:
        LOG.warning("Live migration not completed after %d sec",
                    completion_timeout, instance=instance)
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
