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

from lxml import etree
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


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
    if migrate_data.obj_attr_is_set('serial_listen_addr'):
        listen_addr = str(migrate_data.serial_listen_addr)
    return listen_addr


def get_updated_guest_xml(guest, migrate_data, get_volume_config):
    xml_doc = etree.fromstring(guest.get_xml_desc(dump_migratable=True))
    xml_doc = _update_graphics_xml(xml_doc, migrate_data)
    xml_doc = _update_serial_xml(xml_doc, migrate_data)
    xml_doc = _update_volume_xml(xml_doc, migrate_data, get_volume_config)
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
    for dev in xml_doc.findall("./devices/serial[@type='tcp']/source"):
        if dev.get('host') is not None:
            dev.set('host', listen_addr)
    for dev in xml_doc.findall("./devices/console[@type='tcp']/source"):
        if dev.get('host') is not None:
            dev.set('host', listen_addr)
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
                    disk_dev.remove(item_src)
                    item_dst.tail = None
                    disk_dev.insert(cnt, item_dst)

            # If destination has additional items, thses items should be
            # added here.
            for item_dst in list(xml_doc2):
                item_dst.tail = None
                disk_dev.insert(cnt, item_dst)
    return xml_doc
