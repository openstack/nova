#
#   Live migration feature usage:
#
#   @auther Kei Masumoto <masumotok@nttdata.co.jp>
#   @date   2010.12.01
#   
#   @history ver.1 2010.12.01 ( masumotok )
#      initial version
#


0. pre-requisit settings
   OS: Ubuntu lucid 10.04 for both instances and host.
   NFS: nova-install-dir/instances has to be mounted by shared storage.
        ( this version is tested using NFS)
   Network manager: Only VlanManager can be used in this version.
   instances : Instance must keep running without any EBS volume.
   

1. pre-requisite settings.

   (a) shared storage
   As mentioned above, shared storage is inevitable for the live_migration functionality.
   An example is NFS( my test environment ), and example setting is as follows.

   Prepare NFS server machine( nova-api server is OK), and add below line /etc/exports:
   
   > nova-install-dir/instances    a.b.c.d/255.255.0.0(rw,sync,fsid=0,no_root_squash)

   where "nova-install-dir" is the directory which openstack is installed, and
   add appropriate ip address and netmask for "a.b.c.d/255.255.0.0" , which should include
   compute nodes which try to mount this directory.
   
   Then restart nfs server.

   > /etc/init.d/nfs-kernel-server restart
   > /etc/init.d/idmapd restart

   Also, at any compute nodes, add below line to /etc/fstab:
  
   >172.19.0.131:/  DIR    nfs4    defaults        0       0 

   where "DIR" must be same as 'instances_path'( see nova.compute.manager for the default value)

   Then try to mount,

   > mount -a -v

   Check exported directory is successfully mounted. if fail, try this at any hosts,
  
   > iptables -F

   Also, check file/daemon permissions. 
   we expect any nova daemons are running as root.
   > root@openstack2-api:/opt/nova-2010.4# ps -ef | grep nova
   > root      5948  5904  9 11:29 pts/4    00:00:00 python /opt/nova-2010.4//bin/nova-api
   > root      5952  5908  6 11:29 pts/5    00:00:00 python /opt/nova-2010.4//bin/nova-objectstore
   > ... (snip)

   "instances/" directory can be seen from server side:
   > root@openstack:~# ls -ld nova-install-dir/instances/
   > drwxr-xr-x 2 root root 4096 2010-12-07 14:34 nova-install-dir/instances/

   also, client side: 
   > root@openstack-client:~# ls -ld nova-install-dir/instances/
   > drwxr-xr-x 2 root root 4096 2010-12-07 14:34 nova-install-dir/instances/ 
   


   (b) libvirt settings
   In default configuration, this feature use simple tcp protocol(qemu+tcp://).
   To use this protocol, below configuration is necessary.

   a. modify /etc/libvirt/libvirt.conf

      before : #listen_tls = 0
      after  : listen_tls = 0

      before : #listen_tcp = 1
      after  : listen_tcp = 1

      append : auth_tcp = "none"

   b. modify /etc/init/libvirt-bin.conf

      before : exec /usr/sbin/libvirtd  -d
      after  : exec /usr/sbin/libvirtd  -d -l

   c. modify /etc/default/libvirt-bin

      before :libvirtd_opts=" -d"
      after  :libvirtd_opts=" -d -l"

   then, restart libvirt
       stop libvirt-bin && start libvirt-bin
       ps -ef | grep libvirt 

   make sure you get the below result.
   > root@openstack2:/opt/nova-2010.2# ps -ef | grep libvirt
   > root      1145     1  0 Nov27 ?        00:00:03 /usr/sbin/libvirtd -d -l

   if you would like to use qemu+ssh or other protocol, change "live_migration_uri" flag.
   by adding "--live_migration_uri" to /etc/nova/nova.conf (Note that file name may be
   changed depends on version). 
   

2. command usage

   To get a list of physical hosts,
       nova-manage host list

   To get a available pysical resource of each host,
       nova-manage host show hostname
  
       an example result is below:
       > HOST            PROJECT         cpu     mem(mb) disk(gb)
       > openstack2-c2                   16      32232   878
       > openstack2-c2   admin           1       2048    20

       The 1st line shows total amount of resource that the specified host has.
       The 2nd and latter lines show usage resource per project.
       This command is created because admins can decide which host should be
       a destination of live migration.

   For live migration, 
       nova-manage instances live_migration ec2-id(i-xxxx) destination-host-name.

       once this command is executed, admins will check the status through 
       euca-describe-instances. The status is changed from 'running' to 'migrating',
       and changed to 'running' when live migration finishes.
       Note that it depends on an environment how long it takes to live migration finishes.
       If it finishes too fast, admins cannot see 'migrating' status.

       > root@openstack2:/opt/nova-2010.2# euca-describe-instances
       > Reservation:r-qlg3favp
       > RESERVATION     r-qlg3favp      admin
       > INSTANCE        i-2ah453        ami-tiny        172.19.0.134    10.0.0.3        
       > migrating       testkey (admin, openstack2-c2) 0               m1.small        
       > 2010-11-28 16:09:16                             openstack2-c2

       When live migration finishes successfully, admin can check the last part of
       euca-describe-instances which shows physical node information.
       ( only when euca-describe-instances is executed by admin user )
       Admins also can check live migration source compute node logfile which may
       show a log.
       > Live migration i-xxxx to DESTHOST finishes successfully.
       

3. error checking
   When live migration fails somehow, error message shows at:
   a. scheduler logfile
   b. source compute node logfile
   c. dest compute node logfile

