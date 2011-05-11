# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""
A driver specific to OpenVz as the support for Ovz in libvirt
is sketchy at best.
"""

import os
import socket
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova import context
from nova.auth import manager
from nova.network import linux_net
from nova.compute import power_state
from nova.compute import instance_types
from nova.exception import ProcessExecutionError
from nova.virt import disk
from nova.virt import images
from nova.virt import driver

FLAGS = flags.FLAGS
flags.DEFINE_string('ovz_template_path',
                    '/var/lib/vz/template/cache',
                    'Path to use for local storage of OVz templates')
flags.DEFINE_string('ovz_ve_private_dir',
                    '/var/lib/vz/private',
                    'Path where VEs will get placed')
flags.DEFINE_string('ovz_image_template_dir',
                    '/var/lib/vz/template/cache',
                    'Path where OpenVZ images are')
flags.DEFINE_string('ovz_bridge_device',
                    'br100',
                    'Bridge device to map veth devices to')
flags.DEFINE_string('ovz_network_template',
                    utils.abspath('virt/openvz_interfaces.template'),
                    'OpenVz network interface template file')

LOG = logging.getLogger('nova.virt.openvz')

def get_connection(read_only):
    return OpenVzConnection(read_only)

class OpenVzConnection(driver.ComputeDriver):
    def __init__(self, read_only):
        self.read_only = read_only

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def init_host(self, host=socket.gethostname()):
        """
        Initialize anything that is necessary for the driver to function,
        including catching up with currently running VE's on the given host.
        """
        ctxt = context.get_admin_context()

        LOG.debug('Hostname: %s' % (host,))
        LOG.debug('Instances: %s' % (db.instance_get_all_by_host(ctxt, host)))
        
        for instance in db.instance_get_all_by_host(ctxt, host):
            try:
                LOG.debug('Checking state of %s' % instance['name'])
                state = self.get_info(instance['name'])['state']
            except exception.NotFound:
                state = power_state.SHUTOFF

            LOG.debug('Current state of %s was %s.' %
                      (instance['name'], state))
            db.instance_set_state(ctxt, instance['id'], state)

            if state == power_state.SHUTOFF:
                db.instance_destroy(ctxt, instance['id'])

            if state != power_state.RUNNING:
                continue

    def list_instances(self):
        """
        Return the names of all the instances known to the container
        layer, as a list.
        """
        try:
            out, err = utils.execute(
                'sudo', 'vzlist', '--all', '--no-header', '--output', 'ctid')
            if err:
                LOG.error(err)
        except ProcessExecutionError:
            raise exception.Error('Failed to list VZs')

        ctids = []
        for line in out.splitlines():
            ctid = line.split()[0]
            ctids.append(ctid)

        return ctids

    def list_instances_detail(self):
        """
        Satisfy the requirement for this method in the manager codebase.
        This fascilitates the regular status polls that happen within the
        manager code.
        """

        # TODO(imsplitbit): need to ask around if this is the best way to do
        # this.  This causes some redundant vzlist commands as get_info is run
        # on every item returned from this command but it didn't make sense
        # to re-implement get_info as get_info_all.
        infos = []
        try:
            # get a list of CT names which will be nova friendly.
            # NOTE: This can be an issue if nova decides to change
            # the format of names.  We would need to have a migration process
            # to change the names in the name field of the CTs.
            out, err = utils.execute('sudo', 'vzlist', '--all', '-o',
                                     'name', '-H')
            if err:
                LOG.error(err)
        except ProcessExecutionError as err:
            LOG.error(err)
            raise exception.Error('Problem listing Vzs')

        for name in out.splitlines():
            name = name.split()[0]
            status = self.get_info(name)
            infos.append(driver.InstanceInfo(name, status['state']))

        return infos

    @exception.wrap_exception
    def spawn(self, instance):
        """
        Create a new virtual environment on the container platform.

        The given parameter is an instance of nova.compute.service.Instance.
        This function should use the data there to guide the creation of
        the new instance.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING).

        If this fails, any partial instance should be completely
        cleaned up, and the container platform should be in the state
        that it was before this call began.
        """

        # Update state to inform the nova stack that the VE is launching
        db.instance_set_state(context.get_admin_context(),
                              instance['id'],
                              power_state.NOSTATE,
                              'launching')
        LOG.debug('instance %s: is launching' % instance['name'])

        # Go through the steps of creating a container
        # TODO(imsplitbit): Need to add conditionals around this stuff to make
        # it more durable during failure. And roll back changes made leading
        # up to the error.
        self._cache_image(instance)
        self._create_vz(instance)
        self._set_vz_os_hint(instance)
        self._configure_vz(instance)
        self._set_name(instance)
        self._add_netif(instance)
        self._add_ip(instance)
        self._set_hostname(instance)
        self._set_nameserver(instance)
        self._start(instance)
        self._initial_secure_host(instance)
        
        # Begin making our looping async call
        timer = utils.LoopingCall(f=None)

        # I stole this from the libvirt driver but it is appropriate to
        # have this looping timer call so that if a VE doesn't start right
        # away we can defer all of this.
        def _wait_for_boot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    LOG.debug('instance %s: booted' % instance['name'])
                    timer.stop()

            except:
                LOG.exception('instance %s: failed to boot' %
                              instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_boot
        return timer.start(interval=0.5, now=True)
    
    def _create_vz(self, instance, ostemplate='ubuntu'):
        """
        Attempt to load the image from openvz's image cache, upon failure
        cache the image and then retry the load.
        """

        # TODO(imsplitbit): This needs to set an os template for the image
        # as well as an actual OS template for OpenVZ to know what config
        # scripts to use.  This can be problematic because there is no concept
        # of OS name, it is arbitrary so we will need to find a way to
        # correlate this to what type of disto the image actually is because
        # this is the clue for openvz's utility scripts.  For now we will have
        # to set it to 'ubuntu'

        # This will actually drop the os from the local image cache
        try:
            utils.execute('sudo', 'vzctl', 'create', instance['id'],
                          '--ostemplate', instance['image_id'])
        except exception.ProcessExecutionError as err:
            LOG.error(err)
            raise exception.Error('Failed creating VE %s from image cache' %
                                  instance['id'])
        return True

    def _set_vz_os_hint(self, instance, ostemplate='ubuntu'):
        # This sets the distro hint for OpenVZ to later use for the setting
        # of resolver, hostname and the like
        try:
            utils.execute('sudo', 'vzctl', 'set', instance['id'], '--save',
                          '--ostemplate', ostemplate)
        except exception.ProcessExecutionError as err:
            LOG.error(err)
            raise exception.Error('Unable to set ostemplate to \'%s\' for %s' %
                                  (ostemplate, instance['id']))
        return True

    def _cache_image(self, instance):
        """
        Create the disk image for the virtual environment.
        """

        image_name = '%s.tar.gz' % instance['image_id']
        full_image_path = '%s/%s' % (FLAGS.ovz_image_template_dir, image_name)

        if not os.path.exists(full_image_path):
            # These objects are required to retrieve images from the object store.
            # This is known only to work with glance so far but as I understand it
            # glance's interface matches that of the other object stores.
            user = manager.AuthManager().get_user(instance['user_id'])
            project = manager.AuthManager().get_project(instance['project_id'])

            # Grab image and place it in the image cache
            images.fetch(instance['image_id'], full_image_path, user, project)
            return True
        else:
            return False

    def _configure_vz(self, instance, config='basic'):
        """
        This adds the container root into the vz meta data so that
        OpenVz acknowledges it as a container.  Punting to a basic
        config for now.
        """
        
        try:
            # Set the base config for the VE, this currently defaults to the
            # basic config.
            # TODO(imsplitbit): add guest flavor support here
            _, err = utils.execute('sudo', 'vzctl', 'set', instance['id'],
                                   '--save', '--applyconfig', config)
            if err:
                LOG.error(err)
            return True

        except ProcessExecutionError:
            raise exception.Error('Failed to add %s to OpenVz' % instance['id'])

        
    def _start(self, instance):
        """
        Method to start the instance, I don't believe there is a nova-ism
        for starting so I am wrapping it under the private namespace and
        will call it from expected methods.  i.e. resume
        """
        try:
            # Attempt to start the VE.
            # NOTE: The VE will throw a warning that the hostname is invalid
            # if it isn't valid.  This is logged in LOG.error and is not
            # an indication of failure.
            _, err = utils.execute('sudo', 'vzctl', 'start', instance['id'])
            if err:
                LOG.error(err)
        except ProcessExecutionError as err:
            LOG.error(err)
            raise exception.Error('Failed to start %d' % instance['id'])

        # Set instance state as RUNNING
        db.instance_set_state(context.get_admin_context(),
                              instance['id'],
                              power_state.RUNNING)
        return True

    def _stop(self, instance):
        """
        Method to stop the instance.  This doesn't seem to be a nova-ism but
        it is for openvz so I am wrapping it under the private namespace and
        will call it from expected methods.  i.e. pause
        """
        try:
            _, err = utils.execute('sudo', 'vzctl', 'stop', instance['id'])
            if err:
                LOG.error(err)
        except ProcessExecutionError:
            raise exception.Error('Failed to stop %s' % instance['id'])

        # Update instance state
        try:
            db.instance_set_state(context.get_admin_context(),
                                  instance['id'],
                                  power_state.SHUTDOWN)
        except exception.DBError as err:
            LOG.error(err)
            raise exception.Error('Failed to update db for %s' % instance['id'])
        
        return True

    def _add_netif(self, instance, netif_number=0,
                   host_if=False,
                   bridge=FLAGS.ovz_bridge_device):
        """
        This is more of a work around to add the eth devs
        the way OpenVZ wants them. Currently only bridged networking
        is supported in this driver.
        """
        # TODO(imsplitbit): fix this to be nova-ish i.e. async
        try:
            # Command necessary to create a bridge networking setup.
            # right now this is the only supported networking model
            # in the openvz connector.
            if not host_if:
                host_if = 'veth%s.%s' % (instance['id'], netif_number)

            out, err = utils.execute('sudo', 'vzctl', 'set', instance['id'],
                                     '--save', '--netif_add',
                                     'eth%s,,%s,,%s' % (netif_number,
                                                        host_if, bridge))

            LOG.debug(out)

            if err:
                LOG.error(err)

        except ProcessExecutionError:
            raise exception.Error(
                    'Error adding network device to container %s' %
                    instance['id'])

    def _add_ip(self, instance, netif='eth0',
                if_file='etc/network/interfaces'):
        """
        Add an ip to the container
        """
        ctxt = context.get_admin_context()
        ip = db.instance_get_fixed_address(ctxt, instance['id'])
        network = db.fixed_ip_get_network(ctxt, ip)
        net_path = '%s/%s' % (FLAGS.ovz_ve_private_dir, instance['id'])
        if_file_path = net_path + '/' + if_file
        
        try:
            os.chdir(net_path)
            with open(FLAGS.ovz_network_template) as fh:
                network_file = fh.read() % {'gateway_dev': netif,
                                            'address': ip,
                                            'netmask': network['netmask'],
                                            'gateway': network['gateway']}

            # TODO(imsplitbit): Find a way to write to this file without
            # mangling the perms.
            utils.execute('sudo', 'chmod', '666', if_file_path)
            fh = open(if_file_path, 'a')
            fh.write(network_file)
            fh.close()
            utils.execute('sudo', 'chmod', '644', if_file_path)

        except Exception as err:
            LOG.error(err)
            raise exception.Error('Error adding IP')


        # This is how to add ips with venet.  At some point we should make this
        # work.
        #try:
        #    _, err = utils.execute('sudo vzctl set %s --save --ipadd %s' %
        #                           (instance['id'], ip))
        #    if err:
        #        LOG.error(err)
        #except ProcessExecutionError:
        #    raise exception.Error('Error adding ip %s to %s' %
        #                          (ip, instance['id']))

    def _set_nameserver(self, instance):
        """
        Get the nameserver for the assigned network and set it using
        OpenVz's tools.
        """
        ctxt = context.get_admin_context()
        ip = db.instance_get_fixed_address(ctxt, instance['id'])
        network = db.fixed_ip_get_network(ctxt, ip)

        try:
            _, err = utils.execute('sudo', 'vzctl', 'set', instance['id'],
                                   '--save', '--nameserver', network['dns'])
            if err:
                LOG.error(err)
        except Exception as err:
            LOG.error(err)
            raise exception.Error('Unable to set nameserver for %s' %
            instance['id'])

    def _set_hostname(self, instance, hostname=False):
        if not hostname:
            hostname = 'container-%s' % instance['id']

        try:
            _, err = utils.execute('sudo', 'vzctl', 'set', instance['id'],
                                   '--save', '--hostname', hostname)
            if err:
                LOG.error(err)
        except ProcessExecutionError:
            raise exception.Error('Cannot set the hostname on %s' %
                                  instance['id'])

    def _set_name(self, instance):
        # This stores the nova 'name' of an instance in the name field for
        # openvz.  This is done to facilitate the get_info method which only
        # accepts an instance name.
        try:
            _, err = utils.execute('sudo', 'vzctl', 'set', instance['id'],
                                   '--save', '--name', instance['name'])
            if err:
                LOG.error(err)
                
        except Exception as err:
            LOG.error(err)
            raise exception.Error('Unable to save metadata for %s' %
                                  instance['id'])

    def _find_by_name(self, instance_name):
        # The required method get_info only accepts a name so we need a way
        # to correlate name and id without maintaining another state/meta db
        try:
            out, err = utils.execute('sudo', 'vzlist', '-H', '--all',
                                     '--name', instance_name)
            if err:
                LOG.error(err)
        except Exception as err:
            LOG.error(err)
            raise exception.NotFound('Unable to load metadata for %s' %
                                  instance_name)

        # Break the output into usable chunks
        out = out.split()
        return {'name': out[4], 'id': out[0], 'state': out[2]}

    def _access_control(self, instance, host, mask=32, port=None,
                        protocol='tcp', access_type='allow'):
        """
        Does what it says.  Use this to interface with the
        linux_net.iptables_manager to allow/deny access to a host
        or network
        """

        if access_type == 'allow':
            access_type = 'ACCEPT'
        elif access_type == 'deny':
            access_type = 'REJECT'
        else:
            LOG.error('Invalid access_type: %s' % access_type)
            raise exception.Error('Invalid access_type: %s' % access_type)

        if port == None:
            port = ''
        else:
            port = '--dport %s' % (port,)

        # Create our table instance
        tables = [
                linux_net.iptables_manager.ipv4['filter'],
                linux_net.iptables_manager.ipv6['filter']
        ]

        rule = '-s %s/%s -p %s %s -j %s' % \
               (host, mask, protocol, port, access_type)

        for table in tables:
            table.add_rule(instance['name'], rule)

        # Apply the rules
        linux_net.iptables_manager.apply()

    def _initial_secure_host(self, instance, ports=None):
        """
        Lock down the host in it's default state
        """

        # Get the ip and network information
        ctxt = context.get_admin_context()
        ip = db.instance_get_fixed_address(ctxt, instance['id'])
        network = db.fixed_ip_get_network(ctxt, ip)

        # Create our table instance and add our chains for the instance
        table_ipv4 = linux_net.iptables_manager.ipv4['filter']
        table_ipv6 = linux_net.iptables_manager.ipv6['filter']
        table_ipv4.add_chain(instance['name'])
        table_ipv6.add_chain(instance['name'])

        # As of right now there is no API call to manage security
        # so there are no rules applied, this really is just a pass.
        # The thought here is to allow us to pass a list of ports
        # that should be globally open and lock down the rest but
        # cannot implement this until the API passes a security
        # context object down to us.

        # Apply the rules
        linux_net.iptables_manager.apply()
    
    def snapshot(self, instance, name):
        """
        Snapshots the specified instance.

        The given parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name.

        The second parameter is the name of the snapshot.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        # TODO(imsplitbit): Need to implement vzdump
        pass

    def reboot(self, instance):
        """
        Reboot the specified instance.

        The given parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        try:
            out, err = utils.execute('sudo', 'vzctl', 'restart',
                                     instance['id'])
            if err:
                LOG.error(err)
        except ProcessExecutionError:
            raise exception.Error('Failed to restart container: %d' %
                                  instance['id'])
        

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

    def rescue(self, instance):
        """
        Rescue the specified instance.
        """
        pass

    def unrescue(self, instance):
        """
        Unrescue the specified instance.
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
        self._start(instance['id'])

    def destroy(self, instance):
        """
        Destroy (shutdown and delete) the specified instance.

        The given parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name.

        The work will be done asynchronously.  This function returns a
        task that allows the caller to detect when it is complete.
        """
        # TODO(imsplitbit): This needs to check the state of the VE
        # and if it isn't stopped it needs to stop it first.  This is
        # an openvz limitation that needs to be worked around.
        # For now we will assume it needs to be stopped prior to destroying it.
        self._stop(instance)

        try:
            _, err = utils.execute('sudo', 'vzctl', 'destroy', instance['id'])
            if err:
                LOG.error(err)
        except ProcessExecutionError:
            raise exception.Error('Error destroying %d' % instance['id'])

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
        try:
            meta = self._find_by_name(instance_name)
            instance = db.instance_get(context.get_admin_context(), meta['id'])
        except exception.NotFound as err:
            LOG.error(err)
            LOG.error('Instance %s Not Found' % instance_name)
            raise exception.NotFound('Instance %s Not Found' % instance_name )

        # Store the assumed state as the default
        state = instance['state']

        LOG.debug('Instance %s is in state %s' %
                  (instance['id'], instance['state']))

        if instance['state'] != power_state.NOSTATE:
            # NOTE(imsplitbit): This is not ideal but it looks like nova uses
            # codes returned from libvirt and xen which don't correlate to
            # the status returned from OpenVZ which is either 'running' or 'stopped'
            # There is some contention on how to handle systems that were shutdown
            # intentially however I am defaulting to the nova expected behavior
            if meta['state'] == 'running':
                state = power_state.RUNNING
            elif meta['state'] == None or meta['state'] == '-':
                state = power_state.NOSTATE
            else:
                state = power_state.SHUTDOWN

        # TODO(imsplitbit): Need to add all metrics to this dict.
        return {'state': state,
                'max_mem': 0,
                'mem': 0,
                'num_cpu': 0,
                'cpu_time': 0}

    def get_diagnostics(self, instance_name):
        pass

    def list_disks(self, instance_name):
        """
        Return the IDs of all the virtual disks attached to the specified
        instance, as a list.  These IDs are opaque to the caller (they are
        only useful for giving back to this layer as a parameter to
        disk_stats).  These IDs only need to be unique for a given instance.

        Note that this function takes an instance ID, not a
        compute.service.Instance, so that it can be called by compute.monitor.
        """
        return ['A_DISK']

    def list_interfaces(self, instance_name):
        """
        Return the IDs of all the virtual network interfaces attached to the
        specified instance, as a list.  These IDs are opaque to the caller
        (they are only useful for giving back to this layer as a parameter to
        interface_stats).  These IDs only need to be unique for a given
        instance.

        Note that this function takes an instance ID, not a
        compute.service.Instance, so that it can be called by compute.monitor.
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

        Note that this function takes an instance ID, not a
        compute.service.Instance, so that it can be called by compute.monitor.
        """
        return [0L, 0L, 0L, 0L, null]

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

        Note that this function takes an instance ID, not a
        compute.service.Instance, so that it can be called by compute.monitor.
        """
        return [0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L]

    def get_console_output(self, instance):
        return 'FAKE CONSOLE OUTPUT'

    def get_ajax_console(self, instance):
        return 'http://fakeajaxconsole.com/?token=FAKETOKEN'

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

    def update_available_resource(self, ctxt, host):
        """
        Added because now nova requires this method
        """
        return
