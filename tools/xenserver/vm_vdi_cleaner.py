#!/usr/bin/env python

# Copyright 2011 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""vm_vdi_cleaner.py - List or clean orphaned VDIs/instances on XenServer."""

import doctest
import os
import sys

from oslo_config import cfg
from oslo_utils import timeutils
import XenAPI

possible_topdir = os.getcwd()
if os.path.exists(os.path.join(possible_topdir, "nova", "__init__.py")):
        sys.path.insert(0, possible_topdir)

from nova import config
from nova import context
import nova.conf
from nova import db
from nova import exception
from nova.virt import virtapi
from nova.virt.xenapi import driver as xenapi_driver


cleaner_opts = [
    cfg.IntOpt('zombie_instance_updated_at_window',
               default=172800,
               help='Number of seconds zombie instances are cleaned up.'),
]

cli_opt = cfg.StrOpt('command',
                     help='Cleaner command')

CONF = nova.conf.CONF
CONF.register_opts(cleaner_opts)
CONF.register_cli_opt(cli_opt)


ALLOWED_COMMANDS = ["list-vdis", "clean-vdis", "list-instances",
                    "clean-instances", "test"]


def call_xenapi(xenapi, method, *args):
    """Make a call to xapi."""
    return xenapi._session.call_xenapi(method, *args)


def find_orphaned_instances(xenapi):
    """Find and return a list of orphaned instances."""
    ctxt = context.get_admin_context(read_deleted="only")

    orphaned_instances = []

    for vm_ref, vm_rec in _get_applicable_vm_recs(xenapi):
        try:
            uuid = vm_rec['other_config']['nova_uuid']
            instance = db.instance_get_by_uuid(ctxt, uuid)
        except (KeyError, exception.InstanceNotFound):
            # NOTE(jk0): Err on the side of caution here. If we don't know
            # anything about the particular instance, ignore it.
            print_xen_object("INFO: Ignoring VM", vm_rec, indent_level=0)
            continue

        # NOTE(jk0): This would be triggered if a VM was deleted but the
        # actual deletion process failed somewhere along the line.
        is_active_and_deleting = (instance.vm_state == "active" and
                instance.task_state == "deleting")

        # NOTE(jk0): A zombie VM is an instance that is not active and hasn't
        # been updated in over the specified period.
        is_zombie_vm = (instance.vm_state != "active"
                and timeutils.is_older_than(instance.updated_at,
                        CONF.zombie_instance_updated_at_window))

        if is_active_and_deleting or is_zombie_vm:
            orphaned_instances.append((vm_ref, vm_rec, instance))

    return orphaned_instances


def cleanup_instance(xenapi, instance, vm_ref, vm_rec):
    """Delete orphaned instances."""
    xenapi._vmops._destroy(instance, vm_ref)


def _get_applicable_vm_recs(xenapi):
    """An 'applicable' VM is one that is not a template and not the control
    domain.
    """
    for vm_ref in call_xenapi(xenapi, 'VM.get_all'):
        try:
            vm_rec = call_xenapi(xenapi, 'VM.get_record', vm_ref)
        except XenAPI.Failure, e:
            if e.details[0] != 'HANDLE_INVALID':
                raise
            continue

        if vm_rec["is_a_template"] or vm_rec["is_control_domain"]:
            continue
        yield vm_ref, vm_rec


def print_xen_object(obj_type, obj, indent_level=0, spaces_per_indent=4):
    """Pretty-print a Xen object.

    Looks like:

        VM (abcd-abcd-abcd): 'name label here'
    """
    uuid = obj["uuid"]
    try:
        name_label = obj["name_label"]
    except KeyError:
        name_label = ""
    msg = "%s (%s) '%s'" % (obj_type, uuid, name_label)
    indent = " " * spaces_per_indent * indent_level
    print("".join([indent, msg]))


def _find_vdis_connected_to_vm(xenapi, connected_vdi_uuids):
    """Find VDIs which are connected to VBDs which are connected to VMs."""
    def _is_null_ref(ref):
        return ref == "OpaqueRef:NULL"

    def _add_vdi_and_parents_to_connected(vdi_rec, indent_level):
        indent_level += 1

        vdi_and_parent_uuids = []
        cur_vdi_rec = vdi_rec
        while True:
            cur_vdi_uuid = cur_vdi_rec["uuid"]
            print_xen_object("VDI", vdi_rec, indent_level=indent_level)
            connected_vdi_uuids.add(cur_vdi_uuid)
            vdi_and_parent_uuids.append(cur_vdi_uuid)

            try:
                parent_vdi_uuid = vdi_rec["sm_config"]["vhd-parent"]
            except KeyError:
                parent_vdi_uuid = None

            # NOTE(sirp): VDI's can have themselves as a parent?!
            if parent_vdi_uuid and parent_vdi_uuid != cur_vdi_uuid:
                indent_level += 1
                cur_vdi_ref = call_xenapi(xenapi, 'VDI.get_by_uuid',
                    parent_vdi_uuid)
                try:
                    cur_vdi_rec = call_xenapi(xenapi, 'VDI.get_record',
                            cur_vdi_ref)
                except XenAPI.Failure, e:
                    if e.details[0] != 'HANDLE_INVALID':
                        raise
                    break
            else:
                break

    for vm_ref, vm_rec in _get_applicable_vm_recs(xenapi):
        indent_level = 0
        print_xen_object("VM", vm_rec, indent_level=indent_level)

        vbd_refs = vm_rec["VBDs"]
        for vbd_ref in vbd_refs:
            try:
                vbd_rec = call_xenapi(xenapi, 'VBD.get_record', vbd_ref)
            except XenAPI.Failure, e:
                if e.details[0] != 'HANDLE_INVALID':
                    raise
                continue

            indent_level = 1
            print_xen_object("VBD", vbd_rec, indent_level=indent_level)

            vbd_vdi_ref = vbd_rec["VDI"]

            if _is_null_ref(vbd_vdi_ref):
                continue

            try:
                vdi_rec = call_xenapi(xenapi, 'VDI.get_record', vbd_vdi_ref)
            except XenAPI.Failure, e:
                if e.details[0] != 'HANDLE_INVALID':
                    raise
                continue

            _add_vdi_and_parents_to_connected(vdi_rec, indent_level)


def _find_all_vdis_and_system_vdis(xenapi, all_vdi_uuids, connected_vdi_uuids):
    """Collects all VDIs and adds system VDIs to the connected set."""
    def _system_owned(vdi_rec):
        vdi_name = vdi_rec["name_label"]
        return (vdi_name.startswith("USB") or
                vdi_name.endswith(".iso") or
                vdi_rec["type"] == "system")

    for vdi_ref in call_xenapi(xenapi, 'VDI.get_all'):
        try:
            vdi_rec = call_xenapi(xenapi, 'VDI.get_record', vdi_ref)
        except XenAPI.Failure, e:
            if e.details[0] != 'HANDLE_INVALID':
                raise
            continue
        vdi_uuid = vdi_rec["uuid"]
        all_vdi_uuids.add(vdi_uuid)

        # System owned and non-managed VDIs should be considered 'connected'
        # for our purposes.
        if _system_owned(vdi_rec):
            print_xen_object("SYSTEM VDI", vdi_rec, indent_level=0)
            connected_vdi_uuids.add(vdi_uuid)
        elif not vdi_rec["managed"]:
            print_xen_object("UNMANAGED VDI", vdi_rec, indent_level=0)
            connected_vdi_uuids.add(vdi_uuid)


def find_orphaned_vdi_uuids(xenapi):
    """Walk VM -> VBD -> VDI change and accumulate connected VDIs."""
    connected_vdi_uuids = set()

    _find_vdis_connected_to_vm(xenapi, connected_vdi_uuids)

    all_vdi_uuids = set()
    _find_all_vdis_and_system_vdis(xenapi, all_vdi_uuids, connected_vdi_uuids)

    orphaned_vdi_uuids = all_vdi_uuids - connected_vdi_uuids
    return orphaned_vdi_uuids


def list_orphaned_vdis(vdi_uuids):
    """List orphaned VDIs."""
    for vdi_uuid in vdi_uuids:
        print("ORPHANED VDI (%s)" % vdi_uuid)


def clean_orphaned_vdis(xenapi, vdi_uuids):
    """Clean orphaned VDIs."""
    for vdi_uuid in vdi_uuids:
        print("CLEANING VDI (%s)" % vdi_uuid)

        vdi_ref = call_xenapi(xenapi, 'VDI.get_by_uuid', vdi_uuid)
        try:
            call_xenapi(xenapi, 'VDI.destroy', vdi_ref)
        except XenAPI.Failure, exc:
            sys.stderr.write("Skipping %s: %s" % (vdi_uuid, exc))


def list_orphaned_instances(orphaned_instances):
    """List orphaned instances."""
    for vm_ref, vm_rec, orphaned_instance in orphaned_instances:
        print("ORPHANED INSTANCE (%s)" % orphaned_instance.name)


def clean_orphaned_instances(xenapi, orphaned_instances):
    """Clean orphaned instances."""
    for vm_ref, vm_rec, instance in orphaned_instances:
        print("CLEANING INSTANCE (%s)" % instance.name)

        cleanup_instance(xenapi, instance, vm_ref, vm_rec)


def main():
    """Main loop."""
    config.parse_args(sys.argv)
    args = CONF(args=sys.argv[1:], usage='%(prog)s [options] --command={' +
            '|'.join(ALLOWED_COMMANDS) + '}')

    command = CONF.command
    if not command or command not in ALLOWED_COMMANDS:
        CONF.print_usage()
        sys.exit(1)

    if CONF.zombie_instance_updated_at_window < CONF.resize_confirm_window:
        raise Exception("`zombie_instance_updated_at_window` has to be longer"
                " than `resize_confirm_window`.")

    # NOTE(blamar) This tool does not require DB access, so passing in the
    # 'abstract' VirtAPI class is acceptable
    xenapi = xenapi_driver.XenAPIDriver(virtapi.VirtAPI())

    if command == "list-vdis":
        print("Connected VDIs:\n")
        orphaned_vdi_uuids = find_orphaned_vdi_uuids(xenapi)
        print("\nOrphaned VDIs:\n")
        list_orphaned_vdis(orphaned_vdi_uuids)
    elif command == "clean-vdis":
        orphaned_vdi_uuids = find_orphaned_vdi_uuids(xenapi)
        clean_orphaned_vdis(xenapi, orphaned_vdi_uuids)
    elif command == "list-instances":
        orphaned_instances = find_orphaned_instances(xenapi)
        list_orphaned_instances(orphaned_instances)
    elif command == "clean-instances":
        orphaned_instances = find_orphaned_instances(xenapi)
        clean_orphaned_instances(xenapi, orphaned_instances)
    elif command == "test":
        doctest.testmod()
    else:
        print("Unknown command '%s'" % command)
        sys.exit(1)


if __name__ == "__main__":
    main()
