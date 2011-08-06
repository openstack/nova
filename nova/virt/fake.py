# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""
A fake (in-memory) hypervisor+api.

Allows nova testing w/o a hypervisor.  This module also documents the
semantics of real hypervisor connections.

"""

from nova import exception
from nova import log as logging
from nova import utils
from nova.compute import power_state
from nova.virt import driver


LOG = logging.getLogger('nova.compute.disk')


def get_connection(_):
    # The read_only parameter is ignored.
    return FakeConnection.instance()


class FakeInstance(object):

    def __init__(self, name, state):
        self.name = name
        self.state = state


class FakeConnection(driver.ComputeDriver):
    """
    The interface to this class talks in terms of 'instances' (Amazon EC2 and
    internal Nova terminology), by which we mean 'running virtual machine'
    (XenAPI terminology) or domain (Xen or libvirt terminology).

    An instance has an ID, which is the identifier chosen by Nova to represent
    the instance further up the stack.  This is unfortunately also called a
    'name' elsewhere.  As far as this layer is concerned, 'instance ID' and
    'instance name' are synonyms.

    Note that the instance ID or name is not human-readable or
    customer-controlled -- it's an internal ID chosen by Nova.  At the
    nova.virt layer, instances do not have human-readable names at all -- such
    things are only known higher up the stack.

    Most virtualization platforms will also have their own identity schemes,
    to uniquely identify a VM or domain.  These IDs must stay internal to the
    platform-specific layer, and never escape the connection interface.  The
    platform-specific layer is responsible for keeping track of which instance
    ID maps to which platform-specific ID, and vice versa.

    In contrast, the list_disks and list_interfaces calls may return
    platform-specific IDs.  These identify a specific virtual disk or specific
    virtual network interface, and these IDs are opaque to the rest of Nova.

    Some methods here take an instance of nova.compute.service.Instance.  This
    is the datastructure used by nova.compute to store details regarding an
    instance, and pass them into this layer.  This layer is responsible for
    translating that generic datastructure into terms that are specific to the
    virtualization platform.
    """

    def __init__(self):
        self.instances = {}
        self.host_status = {
          'host_name-description': 'Fake Host',
          'host_hostname': 'fake-mini',
          'host_memory_total': 8000000000,
          'host_memory_overhead': 10000000,
          'host_memory_free': 7900000000,
          'host_memory_free_computed': 7900000000,
          'host_other_config': {},
          'host_ip_address': '192.168.1.109',
          'host_cpu_info': {},
          'disk_available': 500000000000,
          'disk_total': 600000000000,
          'disk_used': 100000000000,
          'host_uuid': 'cedb9b39-9388-41df-8891-c5c9a0c0fe5f',
          'host_name_label': 'fake-mini'}

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def init_host(self, host):
        """
        Initialize anything that is necessary for the driver to function,
        including catching up with currently running VM's on the given host.
        """
        return

    def list_instances(self):
        """
        Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        return self.instances.keys()

    def _map_to_instance_info(self, instance):
        instance = utils.check_isinstance(instance, FakeInstance)
        info = driver.InstanceInfo(instance.name, instance.state)
        return info

    def list_instances_detail(self):
        info_list = []
        for instance in self.instances.values():
            info_list.append(self._map_to_instance_info(instance))
        return info_list

    def spawn(self, context, instance, network_info,
              block_device_mapping=None):
        """
        Create a new instance/VM/domain on the virtualization platform.

        The given parameter is an instance of nova.compute.service.Instance.
        This function should use the data there to guide the creation of
        the new instance.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING).

        If this fails, any partial instance should be completely
        cleaned up, and the virtualization platform should be in the state
        that it was before this call began.
        """

        name = instance.name
        state = power_state.RUNNING
        fake_instance = FakeInstance(name, state)
        self.instances[name] = fake_instance

    def snapshot(self, context, instance, name):
        """
        Snapshots the specified instance.

        The given parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name.

        The second parameter is the name of the snapshot.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        pass

    def reboot(self, instance, network_info):
        """
        Reboot the specified instance.

        The given parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        pass

    def get_host_ip_addr(self):
        """
        Retrieves the IP address of the dom0
        """
        pass

    def resize(self, instance, flavor):
        """
        Resizes/Migrates the specified instance.

        The flavor parameter determines whether or not the instance RAM and
        disk space are modified, and if so, to what size.

        The work will be done asynchronously. This function returns a task
        that allows the caller to detect when it is complete.
        """
        pass

    def set_admin_password(self, instance, new_pass):
        """
        Set the root password on the specified instance.

        The first parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name. The second
        parameter is the value of the new password.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        pass

    def inject_file(self, instance, b64_path, b64_contents):
        """
        Writes a file on the specified instance.

        The first parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name. The second
        parameter is the base64-encoded path to which the file is to be
        written on the instance; the third is the contents of the file, also
        base64-encoded.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        pass

    def agent_update(self, instance, url, md5hash):
        """
        Update agent on the specified instance.

        The first parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name. The second
        parameter is the URL of the agent to be fetched and updated on the
        instance; the third is the md5 hash of the file for verification
        purposes.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        pass

    def rescue(self, context, instance, callback, network_info):
        """
        Rescue the specified instance.
        """
        pass

    def unrescue(self, instance, callback, network_info):
        """
        Unrescue the specified instance.
        """
        pass

    def poll_rescued_instances(self, timeout):
        """Poll for rescued instances"""
        pass

    def migrate_disk_and_power_off(self, instance, dest):
        """
        Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        pass

    def attach_disk(self, instance, disk_info):
        """
        Attaches the disk to an instance given the metadata disk_info
        """
        pass

    def pause(self, instance, callback):
        """
        Pause the specified instance.
        """
        pass

    def unpause(self, instance, callback):
        """
        Unpause the specified instance.
        """
        pass

    def suspend(self, instance, callback):
        """
        suspend the specified instance
        """
        pass

    def resume(self, instance, callback):
        """
        resume the specified instance
        """
        pass

    def destroy(self, instance, network_info):
        key = instance.name
        if key in self.instances:
            del self.instances[key]
        else:
            LOG.warning("Key '%s' not in instances '%s'" %
                        (key, self.instances))

    def attach_volume(self, instance_name, device_path, mountpoint):
        """Attach the disk at device_path to the instance at mountpoint"""
        return True

    def detach_volume(self, instance_name, mountpoint):
        """Detach the disk attached to the instance at mountpoint"""
        return True

    def get_info(self, instance_name):
        """
        Get a block of information about the given instance.  This is returned
        as a dictionary containing 'state': The power_state of the instance,
        'max_mem': The maximum memory for the instance, in KiB, 'mem': The
        current memory the instance has, in KiB, 'num_cpu': The current number
        of virtual CPUs the instance has, 'cpu_time': The total CPU time used
        by the instance, in nanoseconds.

        This method should raise exception.NotFound if the hypervisor has no
        knowledge of the instance
        """
        if instance_name not in self.instances:
            raise exception.InstanceNotFound(instance_id=instance_name)
        i = self.instances[instance_name]
        return {'state': i.state,
                'max_mem': 0,
                'mem': 0,
                'num_cpu': 2,
                'cpu_time': 0}

    def get_diagnostics(self, instance_name):
        pass

    def list_disks(self, instance_name):
        """
        Return the IDs of all the virtual disks attached to the specified
        instance, as a list.  These IDs are opaque to the caller (they are
        only useful for giving back to this layer as a parameter to
        disk_stats).  These IDs only need to be unique for a given instance.

        Note that this function takes an instance ID.
        """
        return ['A_DISK']

    def list_interfaces(self, instance_name):
        """
        Return the IDs of all the virtual network interfaces attached to the
        specified instance, as a list.  These IDs are opaque to the caller
        (they are only useful for giving back to this layer as a parameter to
        interface_stats).  These IDs only need to be unique for a given
        instance.

        Note that this function takes an instance ID.
        """
        return ['A_VIF']

    def block_stats(self, instance_name, disk_id):
        """
        Return performance counters associated with the given disk_id on the
        given instance_name.  These are returned as [rd_req, rd_bytes, wr_req,
        wr_bytes, errs], where rd indicates read, wr indicates write, req is
        the total number of I/O requests made, bytes is the total number of
        bytes transferred, and errs is the number of requests held up due to a
        full pipeline.

        All counters are long integers.

        This method is optional.  On some platforms (e.g. XenAPI) performance
        statistics can be retrieved directly in aggregate form, without Nova
        having to do the aggregation.  On those platforms, this method is
        unused.

        Note that this function takes an instance ID.
        """
        return [0L, 0L, 0L, 0L, None]

    def interface_stats(self, instance_name, iface_id):
        """
        Return performance counters associated with the given iface_id on the
        given instance_id.  These are returned as [rx_bytes, rx_packets,
        rx_errs, rx_drop, tx_bytes, tx_packets, tx_errs, tx_drop], where rx
        indicates receive, tx indicates transmit, bytes and packets indicate
        the total number of bytes or packets transferred, and errs and dropped
        is the total number of packets failed / dropped.

        All counters are long integers.

        This method is optional.  On some platforms (e.g. XenAPI) performance
        statistics can be retrieved directly in aggregate form, without Nova
        having to do the aggregation.  On those platforms, this method is
        unused.

        Note that this function takes an instance ID.
        """
        return [0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L]

    def get_console_output(self, instance):
        return 'FAKE CONSOLE\xffOUTPUT'

    def get_ajax_console(self, instance):
        return {'token': 'FAKETOKEN',
                'host': 'fakeajaxconsole.com',
                'port': 6969}

    def get_vnc_console(self, instance):
        return {'token': 'FAKETOKEN',
                'host': 'fakevncconsole.com',
                'port': 6969}

    def get_console_pool_info(self, console_type):
        return  {'address': '127.0.0.1',
                 'username': 'fakeuser',
                 'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        """This method is called after a change to security groups.

        All security groups and their associated rules live in the datastore,
        and calling this method should apply the updated rules to instances
        running the specified security group.

        An error should be raised if the operation cannot complete.

        """
        return True

    def refresh_security_group_members(self, security_group_id):
        """This method is called when a security group is added to an instance.

        This message is sent to the virtualization drivers on hosts that are
        running an instance that belongs to a security group that has a rule
        that references the security group identified by `security_group_id`.
        It is the responsiblity of this method to make sure any rules
        that authorize traffic flow with members of the security group are
        updated and any new members can communicate, and any removed members
        cannot.

        Scenario:
            * we are running on host 'H0' and we have an instance 'i-0'.
            * instance 'i-0' is a member of security group 'speaks-b'
            * group 'speaks-b' has an ingress rule that authorizes group 'b'
            * another host 'H1' runs an instance 'i-1'
            * instance 'i-1' is a member of security group 'b'

            When 'i-1' launches or terminates we will recieve the message
            to update members of group 'b', at which time we will make
            any changes needed to the rules for instance 'i-0' to allow
            or deny traffic coming from 'i-1', depending on if it is being
            added or removed from the group.

        In this scenario, 'i-1' could just as easily have been running on our
        host 'H0' and this method would still have been called.  The point was
        that this method isn't called on the host where instances of that
        group are running (as is the case with
        :method:`refresh_security_group_rules`) but is called where references
        are made to authorizing those instances.

        An error should be raised if the operation cannot complete.

        """
        return True

    def refresh_provider_fw_rules(self):
        """This triggers a firewall update based on database changes.

        When this is called, rules have either been added or removed from the
        datastore.  You can retrieve rules with
        :method:`nova.db.api.provider_fw_rule_get_all`.

        Provider rules take precedence over security group rules.  If an IP
        would be allowed by a security group ingress rule, but blocked by
        a provider rule, then packets from the IP are dropped.  This includes
        intra-project traffic in the case of the allow_project_net_traffic
        flag for the libvirt-derived classes.

        """
        pass

    def update_available_resource(self, ctxt, host):
        """This method is supported only by libvirt."""
        return

    def compare_cpu(self, xml):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def ensure_filtering_rules_for_instance(self, instance_ref):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method):
        """This method is supported only by libvirt."""
        return

    def unfilter_instance(self, instance_ref, network_info=None):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def test_remove_vm(self, instance_name):
        """ Removes the named VM, as if it crashed. For testing"""
        self.instances.pop(instance_name)

    def update_host_status(self):
        """Return fake Host Status of ram, disk, network."""
        return self.host_status

    def get_host_stats(self, refresh=False):
        """Return fake Host Status of ram, disk, network."""
        return self.host_status

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass
