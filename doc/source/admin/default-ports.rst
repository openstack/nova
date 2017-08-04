==========================================
Compute service node firewall requirements
==========================================

Console connections for virtual machines, whether direct or through a
proxy, are received on ports ``5900`` to ``5999``. The firewall on each
Compute service node must allow network traffic on these ports.

This procedure modifies the iptables firewall to allow incoming
connections to the Compute services.

**Configuring the service-node firewall**

#. Log in to the server that hosts the Compute service, as root.

#. Edit the ``/etc/sysconfig/iptables`` file, to add an INPUT rule that
   allows TCP traffic on ports from ``5900`` to ``5999``. Make sure the new
   rule appears before any INPUT rules that REJECT traffic:

   .. code-block:: console

      -A INPUT -p tcp -m multiport --dports 5900:5999 -j ACCEPT

#. Save the changes to the ``/etc/sysconfig/iptables`` file, and restart the
   ``iptables`` service to pick up the changes:

   .. code-block:: console

      $ service iptables restart

#. Repeat this process for each Compute service node.
