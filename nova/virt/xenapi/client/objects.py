# Copyright 2013 OpenStack Foundation
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

from nova import utils


class XenAPISessionObject(object):
    """Wrapper to make calling and mocking the session easier

    The XenAPI protocol is an XML RPC API that is based around the
    XenAPI database, and operations you can do on each of the objects
    stored in the database, such as VM, SR, VDI, etc.

    For more details see the XenAPI docs:
    http://docs.vmd.citrix.com/XenServer/6.2.0/1.0/en_gb/api/

    Most, objects like VM, SR, VDI, etc, share a common set of methods:
    * vm_ref = session.VM.create(vm_rec)
    * vm_ref = session.VM.get_by_uuid(uuid)
    * session.VM.destroy(vm_ref)
    * vm_refs = session.VM.get_all()

    Each object also has specific messages, or functions, such as:
    * session.VM.clean_reboot(vm_ref)

    Each object has fields, like "VBDs" that can be fetched like this:
    * vbd_refs = session.VM.get_VBDs(vm_ref)

    You can get all the fields by fetching the full record.
    However please note this is much more expensive than just
    fetching the field you require:
    * vm_rec = session.VM.get_record(vm_ref)

    When searching for particular objects, you may be tempted
    to use get_all(), but this often leads to races as objects
    get deleted under your feet. It is preferable to use the undocumented:
    * vms = session.VM.get_all_records_where(
    'field "is_control_domain"="true"')

    """

    def __init__(self, session, name):
        self.session = session
        self.name = name

    def _call_method(self, method_name, *args):
        call = "%s.%s" % (self.name, method_name)
        return self.session.call_xenapi(call, *args)

    def __getattr__(self, method_name):
        return lambda *params: self._call_method(method_name, *params)


class VM(XenAPISessionObject):
    """Virtual Machine."""
    def __init__(self, session):
        super(VM, self).__init__(session, "VM")


class VBD(XenAPISessionObject):
    """Virtual block device."""
    def __init__(self, session):
        super(VBD, self).__init__(session, "VBD")

    def plug(self, vbd_ref, vm_ref):
        @utils.synchronized('xenapi-vbd-' + vm_ref)
        def synchronized_plug():
            self._call_method("plug", vbd_ref)

        # NOTE(johngarbutt) we need to ensure there is only ever one
        # VBD.unplug or VBD.plug happening at once per VM
        # due to a bug in XenServer 6.1 and 6.2
        synchronized_plug()

    def unplug(self, vbd_ref, vm_ref):
        @utils.synchronized('xenapi-vbd-' + vm_ref)
        def synchronized_unplug():
            self._call_method("unplug", vbd_ref)

        # NOTE(johngarbutt) we need to ensure there is only ever one
        # VBD.unplug or VBD.plug happening at once per VM
        # due to a bug in XenServer 6.1 and 6.2
        synchronized_unplug()


class VDI(XenAPISessionObject):
    """Virtual disk image."""
    def __init__(self, session):
        super(VDI, self).__init__(session, "VDI")


class SR(XenAPISessionObject):
    """Storage Repository."""
    def __init__(self, session):
        super(SR, self).__init__(session, "SR")


class PBD(XenAPISessionObject):
    """Physical block device."""
    def __init__(self, session):
        super(PBD, self).__init__(session, "PBD")


class PIF(XenAPISessionObject):
    """Physical Network Interface."""
    def __init__(self, session):
        super(PIF, self).__init__(session, "PIF")


class VLAN(XenAPISessionObject):
    """VLAN."""
    def __init__(self, session):
        super(VLAN, self).__init__(session, "VLAN")


class Host(XenAPISessionObject):
    """XenServer hosts."""
    def __init__(self, session):
        super(Host, self).__init__(session, "host")


class Network(XenAPISessionObject):
    """Networks that VIFs are attached to."""
    def __init__(self, session):
        super(Network, self).__init__(session, "network")


class Pool(XenAPISessionObject):
    """Pool of hosts."""
    def __init__(self, session):
        super(Pool, self).__init__(session, "pool")
