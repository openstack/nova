#!/usr/bin/env python

# Copyright 2011 OpenStack, LLC
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
import optparse
import sys
import XenAPI

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import utils

from nova.virt import xenapi_conn


flags.DECLARE("resize_confirm_window", "nova.compute.manager")
flags.DECLARE("xenapi_connection_url", "nova.virt.xenapi_conn")
flags.DECLARE("xenapi_connection_username", "nova.virt.xenapi_conn")
flags.DECLARE("xenapi_connection_password", "nova.virt.xenapi_conn")

FLAGS = flags.FLAGS
# NOTE(sirp): Nova futzs with the sys.argv in order to provide default
# flagfile. To isolate this awful practice, we're supplying a dummy
# argument list.
dummy = ["fakearg"]
utils.default_flagfile(args=dummy)
FLAGS(dummy)


class UnrecognizedNameLabel(Exception):
    pass


def parse_options():
    """Generate command line options."""

    ALLOWED_COMMANDS = ["list-vdis", "clean-vdis", "list-instances",
                        "clean-instances", "test"]
    arg_str = "|".join(ALLOWED_COMMANDS)
    parser = optparse.OptionParser("%prog [options] [" + arg_str + "]")
    parser.add_option("--verbose", action="store_true")

    options, args = parser.parse_args()

    if not args:
        parser.print_usage()
        sys.exit(1)

    return options, args


def get_instance_id_from_name_label(name_label, template):
    """In order to derive the instance_id from the name label on the VM, we
    take the following steps:

        1. We substitute a dummy value in to the instance_name_template so we
           can figure out the prefix and the suffix of the template (the
           instance_id is between the two)

        2. We delete the prefix and suffix from the name_label.

        3. What's left *should* be the instance_id which we cast to an int
           and return.

    >>> get_instance_id_from_name_label("", "instance-%08x")
    Traceback (most recent call last):
        ...
    UnrecognizedNameLabel

    >>> get_instance_id_from_name_label("instance-00000001", "instance-%08x")
    1

    >>> get_instance_id_from_name_label("instance-0000000A", "instance-%08x")
    10

    >>> get_instance_id_from_name_label("instance-42-suffix", \
            "instance-%d-suffix")
    42
    """

    # Interpolate template to figure out where to extract the instance_id from.
    # The instance_id may be in hex "%x" or decimal "%d", so try decimal first
    # then fall back to hex.
    fake_instance_id = 123456789
    result = template % fake_instance_id
    in_hex = False
    base_10 = "%d" % fake_instance_id

    try:
        prefix, suffix = result.split(base_10)
    except ValueError:
        base_16 = "%x" % fake_instance_id
        prefix, suffix = result.split(base_16)
        in_hex = True

    if prefix:
        name_label = name_label.replace(prefix, '')

    if suffix:
        name_label = name_label.replace(suffix, '')

    try:
        if in_hex:
            instance_id = int(name_label, 16)
        else:
            instance_id = int(name_label)
    except ValueError:
        raise UnrecognizedNameLabel(name_label)

    return instance_id


def find_orphaned_instances(session, verbose=False):
    """Find and return a list of orphaned instances."""
    ctxt = context.get_admin_context(read_deleted="only")

    orphaned_instances = []

    for vm_rec in _get_applicable_vm_recs(session):
        try:
            instance_id = get_instance_id_from_name_label(
                vm_rec["name_label"], FLAGS.instance_name_template)
        except UnrecognizedNameLabel, exc:
            print_xen_object("WARNING: Unrecognized VM", vm_rec,
                    indent_level=0, verbose=verbose)
            continue

        try:
            instance = db.api.instance_get(ctxt, instance_id)
        except exception.InstanceNotFound:
            # NOTE(jk0): Err on the side of caution here. If we don't know
            # anything about the particular instance, ignore it.
            print_xen_object("INFO: Ignoring VM", vm_rec, indent_level=0,
                    verbose=verbose)
            continue

        # NOTE(jk0): This would be triggered if a VM was deleted but the
        # actual deletion process failed somewhere along the line.
        is_active_and_deleting = (instance.vm_state == "active" and
                instance.task_state == "deleting")

        # NOTE(jk0): A zombie VM is an instance that is not active and hasn't
        # been updated in over the specified period.
        is_zombie_vm = (instance.vm_state != "active"
                and utils.is_older_than(instance.updated_at,
                        FLAGS.zombie_instance_updated_at_window))

        if is_active_and_deleting or is_zombie_vm:
            orphaned_instances.append(instance)

    return orphaned_instances


def cleanup_instance(session, instance):
    """Delete orphaned instances."""
    network_info = None
    connection = xenapi_conn.get_connection(_)
    connection.destroy(instance, network_info)


def _get_applicable_vm_recs(session):
    """An 'applicable' VM is one that is not a template and not the control
    domain.
    """
    for vm_ref in session.xenapi.VM.get_all():
        vm_rec = session.xenapi.VM.get_record(vm_ref)

        if vm_rec["is_a_template"] or vm_rec["is_control_domain"]:
            continue
        yield vm_rec


def print_xen_object(obj_type, obj, indent_level=0, spaces_per_indent=4,
                     verbose=False):
    """Pretty-print a Xen object.

    Looks like:

        VM (abcd-abcd-abcd): 'name label here'
    """
    if not verbose:
        return
    uuid = obj["uuid"]
    try:
        name_label = obj["name_label"]
    except KeyError:
        name_label = ""
    msg = "%(obj_type)s (%(uuid)s) '%(name_label)s'" % locals()
    indent = " " * spaces_per_indent * indent_level
    print "".join([indent, msg])


def _find_vdis_connected_to_vm(session, connected_vdi_uuids, verbose=False):
    """Find VDIs which are connected to VBDs which are connected to VMs."""
    def _is_null_ref(ref):
        return ref == "OpaqueRef:NULL"

    def _add_vdi_and_parents_to_connected(vdi_rec, indent_level):
        indent_level += 1

        vdi_and_parent_uuids = []
        cur_vdi_rec = vdi_rec
        while True:
            cur_vdi_uuid = cur_vdi_rec["uuid"]
            print_xen_object("VDI", vdi_rec, indent_level=indent_level,
                             verbose=verbose)
            connected_vdi_uuids.add(cur_vdi_uuid)
            vdi_and_parent_uuids.append(cur_vdi_uuid)

            try:
                parent_vdi_uuid = vdi_rec["sm_config"]["vhd-parent"]
            except KeyError:
                parent_vdi_uuid = None

            # NOTE(sirp): VDI's can have themselves as a parent?!
            if parent_vdi_uuid and parent_vdi_uuid != cur_vdi_uuid:
                indent_level += 1
                cur_vdi_ref = session.xenapi.VDI.get_by_uuid(
                    parent_vdi_uuid)
                cur_vdi_rec = session.xenapi.VDI.get_record(
                    cur_vdi_ref)
            else:
                break

    for vm_rec in _get_applicable_vm_recs(session):
        indent_level = 0
        print_xen_object("VM", vm_rec, indent_level=indent_level,
                         verbose=verbose)

        vbd_refs = vm_rec["VBDs"]
        for vbd_ref in vbd_refs:
            vbd_rec = session.xenapi.VBD.get_record(vbd_ref)

            indent_level = 1
            print_xen_object("VBD", vbd_rec, indent_level=indent_level,
                             verbose=verbose)

            vbd_vdi_ref = vbd_rec["VDI"]

            if _is_null_ref(vbd_vdi_ref):
                continue

            vdi_rec = session.xenapi.VDI.get_record(vbd_vdi_ref)

            _add_vdi_and_parents_to_connected(vdi_rec, indent_level)


def _find_all_vdis_and_system_vdis(session, all_vdi_uuids, connected_vdi_uuids,
                                   verbose=False):
    """Collects all VDIs and adds system VDIs to the connected set."""
    def _system_owned(vdi_rec):
        vdi_name = vdi_rec["name_label"]
        return (vdi_name.startswith("USB") or
                vdi_name.endswith(".iso") or
                vdi_rec["type"] == "system")

    for vdi_ref in session.xenapi.VDI.get_all():
        vdi_rec = session.xenapi.VDI.get_record(vdi_ref)
        vdi_uuid = vdi_rec["uuid"]
        all_vdi_uuids.add(vdi_uuid)

        # System owned and non-managed VDIs should be considered 'connected'
        # for our purposes.
        if _system_owned(vdi_rec):
            print_xen_object("SYSTEM VDI", vdi_rec, indent_level=0,
                             verbose=verbose)
            connected_vdi_uuids.add(vdi_uuid)
        elif not vdi_rec["managed"]:
            print_xen_object("UNMANAGED VDI", vdi_rec, indent_level=0,
                             verbose=verbose)
            connected_vdi_uuids.add(vdi_uuid)


def find_orphaned_vdi_uuids(session, verbose=False):
    """Walk VM -> VBD -> VDI change and accumulate connected VDIs."""
    connected_vdi_uuids = set()

    _find_vdis_connected_to_vm(session, connected_vdi_uuids, verbose=verbose)

    all_vdi_uuids = set()
    _find_all_vdis_and_system_vdis(session, all_vdi_uuids, connected_vdi_uuids,
                                   verbose=verbose)

    orphaned_vdi_uuids = all_vdi_uuids - connected_vdi_uuids
    return orphaned_vdi_uuids


def list_orphaned_vdis(vdi_uuids, verbose=False):
    """List orphaned VDIs."""
    for vdi_uuid in vdi_uuids:
        if verbose:
            print "ORPHANED VDI (%s)" % vdi_uuid
        else:
            print vdi_uuid


def clean_orphaned_vdis(session, vdi_uuids, verbose=False):
    """Clean orphaned VDIs."""
    for vdi_uuid in vdi_uuids:
        if verbose:
            print "CLEANING VDI (%s)" % vdi_uuid

        vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
        try:
            session.xenapi.VDI.destroy(vdi_ref)
        except XenAPI.Failure, exc:
            print >> sys.stderr, "Skipping %s: %s" % (vdi_uuid, exc)


def list_orphaned_instances(orphaned_instances, verbose=False):
    """List orphaned instances."""
    for orphaned_instance in orphaned_instances:
        if verbose:
            print "ORPHANED INSTANCE (%s)" % orphaned_instance.name
        else:
            print orphaned_instance.name


def clean_orphaned_instances(session, orphaned_instances, verbose=False):
    """Clean orphaned instances."""
    for instance in orphaned_instances:
        if verbose:
            print "CLEANING INSTANCE (%s)" % instance.name

        cleanup_instance(session, instance)


def main():
    """Main loop."""
    options, args = parse_options()
    verbose = options.verbose
    command = args[0]

    if FLAGS.zombie_instance_updated_at_window < FLAGS.resize_confirm_window:
        raise Exception("`zombie_instance_updated_at_window` has to be longer"
                " than `resize_confirm_window`.")

    session = XenAPI.Session(FLAGS.xenapi_connection_url)
    session.xenapi.login_with_password(FLAGS.xenapi_connection_username,
            FLAGS.xenapi_connection_password)

    if command == "list-vdis":
        if verbose:
            print "Connected VDIs:\n"
        orphaned_vdi_uuids = find_orphaned_vdi_uuids(session, verbose=verbose)
        if verbose:
            print "\nOprhaned VDIs:\n"
        list_orphaned_vdis(orphaned_vdi_uuids, verbose=verbose)
    elif command == "clean-vdis":
        orphaned_vdi_uuids = find_orphaned_vdi_uuids(session, verbose=verbose)
        clean_orphaned_vdis(session, orphaned_vdi_uuids, verbose=verbose)
    elif command == "list-instances":
        orphaned_instances = find_orphaned_instances(session, verbose=verbose)
        list_orphaned_instances(orphaned_instances, verbose=verbose)
    elif command == "clean-instances":
        orphaned_instances = find_orphaned_instances(session, verbose=verbose)
        clean_orphaned_instances(session, orphaned_instances,
                verbose=verbose)
    elif command == "test":
        doctest.testmod()
    else:
        print "Unknown command '%s'" % command
        sys.exit(1)


if __name__ == "__main__":
    main()
