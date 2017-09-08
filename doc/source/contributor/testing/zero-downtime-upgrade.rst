=====================================
Testing Zero Downtime Upgrade Process
=====================================

Zero Downtime upgrade eliminates any disruption to nova API service
during upgrade.

Nova API services are upgraded at the end. The basic idea of the zero downtime
upgrade process is to have the connections drain from the old API before
being upgraded. In this process, new connections go to the new API nodes
while old connections slowly drain from the old nodes. This ensures that the
user sees the max_supported API version as a monotonically increasing number.
There might be some performance degradation during the process due to slow
HTTP responses and delayed request handling, but there is no API downtime.

This page describes how to test the zero downtime upgrade process.

-----------
Environment
-----------

* Multinode devstack environment with 2 nodes:
    * controller  - All services (N release)
    * compute-api - Only n-cpu and n-api services (N release)

* Highly available load balancer (HAProxy) on top of the n-api services.
  This is required for zero downtime upgrade as it allows one n-api service
  to run while we upgrade the other. See instructions to setup HAProxy below.

-----------------------------
Instructions to setup HAProxy
-----------------------------


Install HAProxy and Keepalived on both nodes.

.. code-block:: bash

   # apt-get install haproxy keepalived

Let the kernel know that we intend to bind additional IP addresses that
won't be defined in the interfaces file. To do this, edit ``/etc/sysctl.conf``
and add the following line:

.. code-block:: INI

   net.ipv4.ip_nonlocal_bind=1

Make this take effect without rebooting.

.. code-block:: bash

   # sysctl -p

Configure HAProxy to add backend servers and assign virtual IP to the frontend.
On both nodes add the below HAProxy config:

.. code-block:: bash

   # cd /etc/haproxy
   # cat >> haproxy.cfg <<EOF

      global
         chroot /var/lib/haproxy
         user haproxy
         group haproxy
         daemon
         log 192.168.0.88 local0
         pidfile  /var/run/haproxy.pid
         stats socket /var/run/haproxy.sock mode 600 level admin
         stats timeout 2m
         maxconn 4000

      defaults
         log  global
         maxconn  8000
         mode  http
         option  redispatch
         retries  3
         stats  enable
         timeout  http-request 10s
         timeout  queue 1m
         timeout  connect 10s
         timeout  client 1m
         timeout  server 1m
         timeout  check 10s

      frontend nova-api-vip
         bind 192.168.0.95:8282             <<ha proxy virtual ip>>
         default_backend nova-api

      backend nova-api
         balance  roundrobin
         option  tcplog
         server  controller 192.168.0.88:8774  check
         server  apicomp  192.168.0.89:8774  check

     EOF

.. note::
   Just change the IP for log in the global section on each node.

On both nodes add ``keepalived.conf``:

.. code-block:: bash

   # cd /etc/keepalived
   # cat >> keepalived.conf <<EOF

      global_defs {
         router_id controller
      }
      vrrp_script haproxy {
         script "killall -0 haproxy"
         interval 2
         weight 2
      }
      vrrp_instance 50 {
         virtual_router_id 50
         advert_int 1
         priority 101
         state MASTER
         interface eth0
         virtual_ipaddress {
            192.168.0.95 dev eth0
         }
         track_script {
            haproxy
         }
      }

    EOF

.. note::
   Change priority on node2 to 100 ( or vice-versa). Add HAProxy virtual IP.

Restart keepalived service.

.. code-block:: bash

   # service keepalived restart

Add ``ENABLED=1`` in ``/etc/default/haproxy`` and then restart HAProxy service.

.. code-block:: bash

   # service haproxy restart

When both the services have restarted, node with the highest priority for keepalived
claims the virtual IP. You can check which node claimed the virtual IP using:

.. code-block:: bash

   # ip a


------------------------------
Zero Downtime upgrade process
------------------------------

General rolling upgrade process: :ref:minimal_downtime_upgrade.


Before Upgrade
''''''''''''''

* Change nova-api endpoint in keystone to point to the HAProxy virtual IP.
* Run tempest tests
* Check if n-api services on both nodes are serving the requests.

Before maintenance window
'''''''''''''''''''''''''

* Start the upgrade process with controller node.
* Follow the steps from the general rolling upgrade process to install new code and sync the
  db for schema changes.

During maintenance window
'''''''''''''''''''''''''

* Set compute option in upgrade_levels to auto in ``nova.conf``.

  .. code-block:: bash

     [upgrade_levels]
     compute = auto

* Starting with n-cond restart all services except n-api and n-cpu.
* In small batches gracefully shutdown nova-cpu, then start n-cpu service
  with new version of the code.
* Run tempest tests.
* Drain connections on n-api while the tempest tests are running.
  HAProxy allows you to drain the connections by setting weight to zero:

  .. code-block:: bash

     # echo "set weight nova-api/<<server>> 0" | sudo socat /var/run/haproxy.sock stdio

* OR disable service using:

  .. code-block:: bash

     # echo "disable server nova-api/<<server>>" | sudo socat /var/run/haproxy.sock stdio

* This allows the current node to complete all the pending requests. When this
  is being upgraded, other api node serves the requests. This way we can
  achieve zero downtime.
* Restart n-api service and enable n-api using the command:

  .. code-block:: bash

     # echo "enable server nova-api/<<server>>" | sudo socat /var/run/haproxy.sock stdio

* Drain connections from other old api node in the same way and upgrade.
* No tempest tests should fail since there is no API downtime.

After maintenance window
'''''''''''''''''''''''''

* Follow the steps from general rolling upgrade process to clear any cached
  service version data and complete all online data migrations.
