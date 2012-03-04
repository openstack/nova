# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 University of Southern California
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

from nova.compute import power_state
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.baremetal import nodes

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


def read_domains(fname):
    try:
        f = open(fname, 'r')
        json = f.read()
        f.close()
        domains = utils.loads(json)
        return domains
    except IOError:
        raise exception.NotFound()


def write_domains(fname, domains):
    json = utils.dumps(domains)
    f = open(fname, 'w')
    f.write(json)
    f.close()


class BareMetalDom(object):
    """
    BareMetalDom class handles fake domain for bare metal back ends.

    This implements the singleton pattern.
    """

    _instance = None
    _is_init = False

    def __new__(cls, *args, **kwargs):
        """
        Returns the BareMetalDom singleton.
        """
        if not cls._instance or ('new' in kwargs and kwargs['new']):
            cls._instance = super(BareMetalDom, cls).__new__(cls)
        return cls._instance

    def __init__(self,
                 fake_dom_file="/tftpboot/test_fake_dom_file"):
        """
        Only call __init__ the first time object is instantiated.

        Sets and Opens domain file: /tftpboot/test_fake_dom_file. Even though
        nova-compute service is rebooted, this file should retain the
        existing domains.
        """
        if self._is_init:
            return
        self._is_init = True

        self.fake_dom_file = fake_dom_file
        self.domains = []
        self.fake_dom_nums = 0
        self.baremetal_nodes = nodes.get_baremetal_nodes()

        self._read_domain_from_file()

    def _read_domain_from_file(self):
        """
        Reads the domains from a file.
        """
        try:
            self.domains = read_domains(self.fake_dom_file)
        except IOError:
            dom = []
            LOG.debug(_("No domains exist."))
            return
        msg = _("============= initial domains =========== : %s")
        LOG.debug(msg % (self.domains))
        for dom in self.domains[:]:
            if dom['status'] == power_state.BUILDING:
                LOG.debug(_("Building domain: to be removed"))
                self.destroy_domain(dom['name'])
                continue
            elif dom['status'] != power_state.RUNNING:
                LOG.debug(_("Not running domain: remove"))
                self.domains.remove(dom)
                continue
            res = self.baremetal_nodes.set_status(dom['node_id'],
                                    dom['status'])
            if res > 0:
                self.fake_dom_nums = self.fake_dom_nums + 1
            else:
                LOG.debug(_("domain running on an unknown node: discarded"))
                self.domains.remove(dom)
                continue

        LOG.debug(self.domains)
        self.store_domain()

    def reboot_domain(self, name):
        """
        Finds domain and deactivates (power down) bare-metal node.

        Activates the node again. In case of fail,
        destroys the domain from domains list.
        """
        fd = self.find_domain(name)
        if fd == []:
            msg = _("No such domain (%s)")
            raise exception.NotFound(msg % name)
        node_ip = self.baremetal_nodes.get_ip_by_id(fd['node_id'])

        try:
            self.baremetal_nodes.deactivate_node(fd['node_id'])
        except Exception:
            msg = _("Failed power down Bare-metal node %s")
            raise exception.NotFound(msg % fd['node_id'])
        self.change_domain_state(name, power_state.BUILDING)
        try:
            state = self.baremetal_nodes.activate_node(fd['node_id'],
                node_ip, name, fd['mac_address'], fd['ip_address'])
            self.change_domain_state(name, state)
            return state
        except Exception:
            LOG.debug(_("deactivate -> activate fails"))
            self.destroy_domain(name)
            raise

    def destroy_domain(self, name):
        """
        Removes domain from domains list and deactivates node.
        """
        fd = self.find_domain(name)
        if fd == []:
            LOG.debug(_("destroy_domain: no such domain"))
            msg = _("No such domain %s")
            raise exception.NotFound(msg % name)

        try:
            self.baremetal_nodes.deactivate_node(fd['node_id'])

            self.domains.remove(fd)
            msg = _("Domains: %s")
            LOG.debug(msg % (self.domains))
            msg = _("Nodes: %s")
            LOG.debug(msg % (self.baremetal_nodes.nodes))
            self.store_domain()
            msg = _("After storing domains: %s")
            LOG.debug(msg % (self.domains))
        except Exception:
            LOG.debug(_("deactivation/removing domain failed"))
            raise

    def create_domain(self, xml_dict, bpath):
        """
        Adds a domain to domains list and activates an idle bare-metal node.
        """
        LOG.debug(_("===== Domain is being created ====="))
        fd = self.find_domain(xml_dict['name'])
        if fd != []:
            msg = _("Same domain name already exists")
            raise exception.NotFound(msg)
        LOG.debug(_("create_domain: before get_idle_node"))

        node_id = self.baremetal_nodes.get_idle_node()
        node_ip = self.baremetal_nodes.get_ip_by_id(node_id)

        new_dom = {'node_id': node_id,
                    'name': xml_dict['name'],
                    'memory_kb': xml_dict['memory_kb'],
                    'vcpus': xml_dict['vcpus'],
                    'mac_address': xml_dict['mac_address'],
                    'user_data': xml_dict['user_data'],
                    'ip_address': xml_dict['ip_address'],
                    'image_id': xml_dict['image_id'],
                    'kernel_id': xml_dict['kernel_id'],
                    'ramdisk_id': xml_dict['ramdisk_id'],
                     'status': power_state.BUILDING}
        self.domains.append(new_dom)
        msg = _("Created new domain: %s")
        LOG.debug(msg % (new_dom))
        self.change_domain_state(new_dom['name'], power_state.BUILDING)

        self.baremetal_nodes.set_image(bpath, node_id)

        state = power_state.NOSTATE
        try:
            state = self.baremetal_nodes.activate_node(node_id,
                node_ip, new_dom['name'], new_dom['mac_address'],
                new_dom['ip_address'], new_dom['user_data'])
            self.change_domain_state(new_dom['name'], state)
        except Exception:
            self.domains.remove(new_dom)
            self.baremetal_nodes.free_node(node_id)
            LOG.debug(_("Failed to boot Bare-metal node %s"), node_id)
        return state

    def change_domain_state(self, name, state):
        """
        Changes domain state by the given state and updates domain file.
        """
        l = self.find_domain(name)
        if l == []:
            msg = _("No such domain exists")
            raise exception.NotFound(msg)
        i = self.domains.index(l)
        self.domains[i]['status'] = state
        LOG.debug(_("change_domain_state: to new state %s"), str(state))
        self.store_domain()

    def store_domain(self):
        """
        Stores fake domains to the file.
        """
        msg = _("Stored fake domains to the file: %s")
        LOG.debug(msg % (self.domains))
        write_domains(self.fake_dom_file, self.domains)

    def find_domain(self, name):
        """
        Finds domain by the given name and returns the domain.
        """
        for item in self.domains:
            if item['name'] == name:
                return item
        LOG.debug(_("domain does not exist"))
        return []

    def list_domains(self):
        """
        Returns the instance name from domains list.
        """
        if self.domains == []:
            return []
        return [x['name'] for x in self.domains]

    def get_domain_info(self, instance_name):
        """
        Finds domain by the given instance_name and returns informaiton.

        For example, status, memory_kb, vcpus, etc.
        """
        domain = self.find_domain(instance_name)
        if domain != []:
            return [domain['status'], domain['memory_kb'],
                    domain['memory_kb'],
                    domain['vcpus'],
                    100]
        else:
            return [power_state.NOSTATE, '', '', '', '']
