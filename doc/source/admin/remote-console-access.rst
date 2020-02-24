===============================
Configure remote console access
===============================

OpenStack provides a number of different methods to interact with your guests:
VNC, SPICE, Serial, RDP or MKS. If configured, these can be accessed by users
through the OpenStack dashboard or the command line. This document outlines how
these different technologies can be configured.


Overview
--------

It is considered best practice to deploy only one of the consoles types and
not all console types are supported by all compute drivers. Regardless of what
option is chosen, a console proxy service is required. These proxy services are
responsible for the following:

- Provide a bridge between the public network where the clients live and the
  private network where the servers with consoles live.

- Mediate token authentication.

- Transparently handle hypervisor-specific connection details to provide a
  uniform client experience.

For some combinations of compute driver and console driver, these proxy
services are provided by the hypervisor or another service. For all others,
nova provides services to handle this proxying. Consider a noVNC-based VNC
console connection for example:

#. A user connects to the API and gets an ``access_url`` such as,
   ``http://ip:port/?path=%3Ftoken%3Dxyz``.

#. The user pastes the URL in a browser or uses it as a client parameter.

#. The browser or client connects to the proxy.

#. The proxy authorizes the token for the user, and maps the token to the
   *private* host and port of the VNC server for an instance.

   The compute host specifies the address that the proxy should use to connect
   through the :oslo.config:option:`vnc.server_proxyclient_address` option. In
   this way, the VNC proxy works as a bridge between the public network and
   private host network.

#. The proxy initiates the connection to VNC server and continues to proxy
   until the session ends.

This means a typical deployment with noVNC-based VNC consoles will have the
following components:

- One or more :program:`nova-novncproxy` service. Supports browser-based noVNC
  clients. For simple deployments, this service typically runs on the same
  machine as :program:`nova-api` because it operates as a proxy between the
  public network and the private compute host network.

- One or more :program:`nova-compute` services. Hosts the instances for which
  consoles are provided.

.. todo::

   The below diagram references :program:`nova-consoleauth` and needs to be
   updated.

This particular example is illustrated below.

.. figure:: figures/SCH_5009_V00_NUAC-VNC_OpenStack.png
   :alt: noVNC process
   :width: 95%


noVNC-based VNC console
-----------------------

VNC is a graphical console with wide support among many hypervisors and
clients. noVNC provides VNC support through a web browser.

.. note::

  It has `been reported`__ that versions of noVNC older than 0.6 do not work
  with the :program:`nova-novncproxy` service.

  If using non-US key mappings, you need at least noVNC 1.0.0 for `a fix`__.

  If using VMware ESX/ESXi hypervisors, you need at least noVNC 1.1.0 for
  `a fix`__.

  __ https://bugs.launchpad.net/nova/+bug/1752896
  __ https://github.com/novnc/noVNC/commit/99feba6ba8fee5b3a2b2dc99dc25e9179c560d31
  __ https://github.com/novnc/noVNC/commit/2c813a33fe6821f5af737327c50f388052fa963b

Configuration
~~~~~~~~~~~~~

To enable the noVNC VNC console service, you must configure both the
:program:`nova-novncproxy` service and the :program:`nova-compute` service.
Most options are defined in the :oslo.config:group:`vnc` group.

The :program:`nova-novncproxy` service accepts the following options:

- :oslo.config:option:`daemon`
- :oslo.config:option:`ssl_only`
- :oslo.config:option:`source_is_ipv6`
- :oslo.config:option:`cert`
- :oslo.config:option:`key`
- :oslo.config:option:`web`
- :oslo.config:option:`console.ssl_ciphers`
- :oslo.config:option:`console.ssl_minimum_version`
- :oslo.config:option:`vnc.novncproxy_host`
- :oslo.config:option:`vnc.novncproxy_port`

If using the libvirt compute driver and enabling :ref:`vnc-security`, the
following additional options are supported:

- :oslo.config:option:`vnc.auth_schemes`
- :oslo.config:option:`vnc.vencrypt_client_key`
- :oslo.config:option:`vnc.vencrypt_client_cert`
- :oslo.config:option:`vnc.vencrypt_ca_certs`

For example, to configure this via a ``nova-novncproxy.conf`` file:

.. code-block:: ini

   [vnc]
   novncproxy_host = 0.0.0.0
   novncproxy_port = 6082

.. note::

   This doesn't show configuration with security. For information on how to
   configure this, refer to :ref:`vnc-security` below.

The :program:`nova-compute` service requires the following options to configure
noVNC-based VNC console support:

- :oslo.config:option:`vnc.enabled`
- :oslo.config:option:`vnc.novncproxy_base_url`
- :oslo.config:option:`vnc.server_listen`
- :oslo.config:option:`vnc.server_proxyclient_address`
- :oslo.config:option:`vnc.keymap`

If using the VMware compute driver, the following additional options are
supported:

- :oslo.config:option:`vmware.vnc_port`
- :oslo.config:option:`vmware.vnc_port_total`

For example, to configure this via a ``nova.conf`` file:

.. code-block:: ini

   [vnc]
   enabled = True
   novncproxy_base_url = http://IP_ADDRESS:6082/vnc_auto.html
   server_listen = 127.0.0.1
   server_proxyclient_address = 127.0.0.1
   keymap = en-us

Replace ``IP_ADDRESS`` with the IP address from which the proxy is accessible
by the outside world. For example, this may be the management interface IP
address of the controller or the VIP.

.. _vnc-security:

VNC proxy security
~~~~~~~~~~~~~~~~~~

Deploy the public-facing interface of the VNC proxy with HTTPS to prevent
attacks from malicious parties on the network between the tenant user and proxy
server. When using HTTPS, the TLS encryption only applies to data between the
tenant user and proxy server. The data between the proxy server and Compute
node instance will still be unencrypted. To provide protection for the latter,
it is necessary to enable the VeNCrypt authentication scheme for VNC in both
the Compute nodes and noVNC proxy server hosts.

QEMU/KVM Compute node configuration
+++++++++++++++++++++++++++++++++++

Ensure each Compute node running QEMU/KVM with libvirt has a set of
certificates issued to it. The following is a list of the required
certificates:

- :file:`/etc/pki/libvirt-vnc/server-cert.pem`

  An x509 certificate to be presented **by the VNC server**. The ``CommonName``
  should match the **primary hostname of the compute node**. Use of
  ``subjectAltName`` is also permitted if there is a need to use multiple
  hostnames or IP addresses to access the same Compute node.

- :file:`/etc/pki/libvirt-vnc/server-key.pem`

  The private key used to generate the ``server-cert.pem`` file.

- :file:`/etc/pki/libvirt-vnc/ca-cert.pem`

  The authority certificate used to sign ``server-cert.pem`` and sign the VNC
  proxy server certificates.

The certificates must have v3 basic constraints [2]_ present to indicate the
permitted key use and purpose data.

We recommend using a dedicated certificate authority solely for the VNC
service. This authority may be a child of the master certificate authority used
for the OpenStack deployment. This is because libvirt does not currently have
a mechanism to restrict what certificates can be presented by the proxy server.

For further details on certificate creation, consult the QEMU manual page
documentation on VNC server certificate setup [1]_.

Configure libvirt to enable the VeNCrypt authentication scheme for the VNC
server. In :file:`/etc/libvirt/qemu.conf`, uncomment the following settings:

- ``vnc_tls=1``

  This instructs libvirt to enable the VeNCrypt authentication scheme when
  launching QEMU, passing it the certificates shown above.

- ``vnc_tls_x509_verify=1``

  This instructs QEMU to require that all VNC clients present a valid x509
  certificate. Assuming a dedicated certificate authority is used for the VNC
  service, this ensures that only approved VNC proxy servers can connect to the
  Compute nodes.

After editing :file:`qemu.conf`, the ``libvirtd`` service must be restarted:

.. code-block:: shell

   $ systemctl restart libvirtd.service

Changes will not apply to any existing running guests on the Compute node, so
this configuration should be done before launching any instances.

noVNC proxy server configuration
++++++++++++++++++++++++++++++++

The noVNC proxy server initially only supports the ``none`` authentication
scheme, which does no checking. Therefore, it is necessary to enable the
``vencrypt`` authentication scheme by editing the :file:`nova.conf` file to
set.

.. code-block:: ini

   [vnc]
   auth_schemes=vencrypt,none

The :oslo.config:option:`vnc.auth_schemes` values should be listed in order
of preference. If enabling VeNCrypt on an existing deployment which already has
instances running, the noVNC proxy server must initially be allowed to use
``vencrypt`` and ``none``. Once it is confirmed that all Compute nodes have
VeNCrypt enabled for VNC, it is possible to remove the ``none`` option from the
list of the :oslo.config:option:`vnc.auth_schemes` values.

At that point, the noVNC proxy will refuse to connect to any Compute node that
does not offer VeNCrypt.

As well as enabling the authentication scheme, it is necessary to provide
certificates to the noVNC proxy.

- :file:`/etc/pki/nova-novncproxy/client-cert.pem`

  An x509 certificate to be presented **to the VNC server**. While libvirt/QEMU
  will not currently do any validation of the ``CommonName`` field, future
  versions will allow for setting up access controls based on the
  ``CommonName``. The ``CommonName`` field should match the **primary hostname
  of the controller node**. If using a HA deployment, the ``Organization``
  field can also be configured to a value that is common across all console
  proxy instances in the deployment. This avoids the need to modify each
  compute node's whitelist every time a console proxy instance is added or
  removed.

- :file:`/etc/pki/nova-novncproxy/client-key.pem`

  The private key used to generate the ``client-cert.pem`` file.

- :file:`/etc/pki/nova-novncproxy/ca-cert.pem`

  The certificate authority cert used to sign ``client-cert.pem`` and sign the
  compute node VNC server certificates.

The certificates must have v3 basic constraints [2]_ present to indicate the
permitted key use and purpose data.

Once the certificates have been created, the noVNC console proxy service must
be told where to find them. This requires editing :file:`nova.conf` to set.

.. code-block:: ini

   [vnc]
   vencrypt_client_key=/etc/pki/nova-novncproxy/client-key.pem
   vencrypt_client_cert=/etc/pki/nova-novncproxy/client-cert.pem
   vencrypt_ca_certs=/etc/pki/nova-novncproxy/ca-cert.pem


SPICE console
-------------

The VNC protocol is fairly limited, lacking support for multiple monitors,
bi-directional audio, reliable cut-and-paste, video streaming and more. SPICE
is a new protocol that aims to address the limitations in VNC and provide good
remote desktop support.

SPICE support in OpenStack Compute shares a similar architecture to the VNC
implementation. The OpenStack dashboard uses a SPICE-HTML5 widget in its
console tab that communicates with the :program:`nova-spicehtml5proxy` service
by using SPICE-over-websockets. The :program:`nova-spicehtml5proxy` service
communicates directly with the hypervisor process by using SPICE.

Configuration
~~~~~~~~~~~~~

.. important::

   VNC must be explicitly disabled to get access to the SPICE console. Set the
   :oslo.config:option:`vnc.enabled` option to ``False`` to disable the
   VNC console.

To enable the SPICE console service, you must configure both the
:program:`nova-spicehtml5proxy` service and the :program:`nova-compute`
service. Most options are defined in the :oslo.config:group:`spice` group.

The :program:`nova-spicehtml5proxy` service accepts the following options.

- :oslo.config:option:`daemon`
- :oslo.config:option:`ssl_only`
- :oslo.config:option:`source_is_ipv6`
- :oslo.config:option:`cert`
- :oslo.config:option:`key`
- :oslo.config:option:`web`
- :oslo.config:option:`console.ssl_ciphers`
- :oslo.config:option:`console.ssl_minimum_version`
- :oslo.config:option:`spice.html5proxy_host`
- :oslo.config:option:`spice.html5proxy_port`

For example, to configure this via a ``nova-spicehtml5proxy.conf`` file:

.. code-block:: ini

   [spice]
   html5proxy_host = 0.0.0.0
   html5proxy_port = 6082

The :program:`nova-compute` service requires the following options to configure
SPICE console support.

- :oslo.config:option:`spice.enabled`
- :oslo.config:option:`spice.agent_enabled`
- :oslo.config:option:`spice.html5proxy_base_url`
- :oslo.config:option:`spice.server_listen`
- :oslo.config:option:`spice.server_proxyclient_address`
- :oslo.config:option:`spice.keymap`

For example, to configure this via a ``nova.conf`` file:

.. code-block:: ini

   [spice]
   agent_enabled = False
   enabled = True
   html5proxy_base_url = http://IP_ADDRESS:6082/spice_auto.html
   server_listen = 127.0.0.1
   server_proxyclient_address = 127.0.0.1
   keymap = en-us

Replace ``IP_ADDRESS`` with the IP address from which the proxy is accessible
by the outside world. For example, this may be the management interface IP
address of the controller or the VIP.


Serial
------

Serial consoles provide an alternative to graphical consoles like VNC or SPICE.
They work a little differently to graphical consoles so an example is
beneficial. The example below uses these nodes:

* controller node with IP ``192.168.50.100``
* compute node 1 with IP ``192.168.50.104``
* compute node 2 with IP ``192.168.50.105``

Here's the general flow of actions:

.. figure:: figures/serial-console-flow.svg
   :width: 100%
   :alt: The serial console flow

1. The user requests a serial console connection string for an instance
   from the REST API.
2. The :program:`nova-api` service asks the :program:`nova-compute` service,
   which manages that instance, to fulfill that request.
3. That connection string gets used by the user to connect to the
   :program:`nova-serialproxy` service.
4. The :program:`nova-serialproxy` service then proxies the console interaction
   to the port of the compute node where the instance is running. That port
   gets forwarded by the hypervisor (or ironic conductor, for ironic) to the
   guest.

Configuration
~~~~~~~~~~~~~

To enable the serial console service, you must configure both the
:program:`nova-serialproxy` service and the :program:`nova-compute` service.
Most options are defined in the :oslo.config:group:`serial_console` group.

The :program:`nova-serialproxy` service accepts the following options.

- :oslo.config:option:`daemon`
- :oslo.config:option:`ssl_only`
- :oslo.config:option:`source_is_ipv6`
- :oslo.config:option:`cert`
- :oslo.config:option:`key`
- :oslo.config:option:`web`
- :oslo.config:option:`console.ssl_ciphers`
- :oslo.config:option:`console.ssl_minimum_version`
- :oslo.config:option:`serial_console.serialproxy_host`
- :oslo.config:option:`serial_console.serialproxy_port`

For example, to configure this via a ``nova-serialproxy.conf`` file:

.. code-block:: ini

   [serial_console]
   serialproxy_host = 0.0.0.0
   serialproxy_port = 6083

The :program:`nova-compute` service requires the following options to configure
serial console support.

- :oslo.config:option:`serial_console.enabled`
- :oslo.config:option:`serial_console.base_url`
- :oslo.config:option:`serial_console.proxyclient_address`
- :oslo.config:option:`serial_console.port_range`

For example, to configure this via a ``nova.conf`` file:

.. code-block:: ini

   [serial_console]
   enabled = True
   base_url = ws://IP_ADDRESS:6083/
   proxyclient_address = 127.0.0.1
   port_range = 10000:20000

Replace ``IP_ADDRESS`` with the IP address from which the proxy is accessible
by the outside world. For example, this may be the management interface IP
address of the controller or the VIP.

There are some things to keep in mind when configuring these options:

* :oslo.config:option:`serial_console.serialproxy_host` is the address the
  :program:`nova-serialproxy` service listens to for incoming connections.
* :oslo.config:option:`serial_console.serialproxy_port` must be the same value
  as the port in the URI of :oslo.config:option:`serial_console.base_url`.
* The URL defined in :oslo.config:option:`serial_console.base_url` will form
  part of the response the user will get when asking for a serial console
  connection string. This means it needs to be an URL the user can connect to.
* :oslo.config:option:`serial_console.proxyclient_address` will be used by the
  :program:`nova-serialproxy` service to determine where to connect to for
  proxying the console interaction.


RDP
---

RDP is a graphical console primarily used with Hyper-V. Nova does not provide a
console proxy service for RDP - instead, an external proxy service, such as the
:program:`wsgate` application provided by `FreeRDP-WebConnect`__, should be
used.

__ https://github.com/FreeRDP/FreeRDP-WebConnect

Configuration
~~~~~~~~~~~~~

To enable the RDP console service, you must configure both a console proxy
service like :program:`wsgate` and the :program:`nova-compute` service. All
options for the latter service are defined in the :oslo.config:group:`rdp`
group.

Information on configuring an RDP console proxy service, such as
:program:`wsgate`, is not provided here. However, more information can be found
at `cloudbase.it`__.

The :program:`nova-compute` service requires the following options to configure
RDP console support.

- :oslo.config:option:`rdp.enabled`
- :oslo.config:option:`rdp.html5_proxy_base_url`

For example, to configure this via a ``nova.conf`` file:

.. code-block:: ini

   [rdp]
   enabled = True
   html5_proxy_base_url = https://IP_ADDRESS:6083/

Replace ``IP_ADDRESS`` with the IP address from which the proxy is accessible
by the outside world. For example, this may be the management interface IP
address of the controller or the VIP.

__ https://cloudbase.it/freerdp-html5-proxy-windows/


MKS
---

MKS is the protocol used for accessing the console of a virtual machine running
on VMware vSphere. It is very similar to VNC.  Due to the architecture of the
VMware vSphere hypervisor, it is not necessary to run a console proxy service.

Configuration
~~~~~~~~~~~~~

To enable the MKS console service, only the :program:`nova-compute` service
must be configured. All options are defined in the :oslo.config:group:`mks`
group.

The :program:`nova-compute` service requires the following options to configure
MKS console support.

- :oslo.config:option:`mks.enabled`
- :oslo.config:option:`mks.mksproxy_base_url`

For example, to configure this via a ``nova.conf`` file:

.. code-block:: ini

   [mks]
   enabled = True
   mksproxy_base_url = https://127.0.0.1:6090/


.. _about-nova-consoleauth:

About ``nova-consoleauth``
--------------------------

The now-removed :program:`nova-consoleauth` service was previously used to
provide a shared service to manage token authentication that the client proxies
outlined below could leverage. Token authentication was moved to the database in
18.0.0 (Rocky) and the service was removed in 20.0.0 (Train).


Frequently Asked Questions
--------------------------

- **Q: I want VNC support in the OpenStack dashboard. What services do I
  need?**

  A: You need ``nova-novncproxy`` and correctly configured compute hosts.

- **Q: My VNC proxy worked fine during my all-in-one test, but now it doesn't
  work on multi host. Why?**

  A: The default options work for an all-in-one install, but changes must be
  made on your compute hosts once you start to build a cluster.  As an example,
  suppose you have two servers:

  .. code-block:: bash

     PROXYSERVER (public_ip=172.24.1.1, management_ip=192.168.1.1)
     COMPUTESERVER (management_ip=192.168.1.2)

  Your ``nova-compute`` configuration file must set the following values:

  .. code-block:: ini

     [vnc]
     # These flags help construct a connection data structure
     server_proxyclient_address=192.168.1.2
     novncproxy_base_url=http://172.24.1.1:6080/vnc_auto.html

     # This is the address where the underlying vncserver (not the proxy)
     # will listen for connections.
     server_listen=192.168.1.2

  .. note::

     ``novncproxy_base_url`` uses a public IP; this is the URL that is
     ultimately returned to clients, which generally do not have access to your
     private network. Your PROXYSERVER must be able to reach
     ``server_proxyclient_address``, because that is the address over which the
     VNC connection is proxied.

- **Q: My noVNC does not work with recent versions of web browsers. Why?**

  A: Make sure you have installed ``python-numpy``, which is required to
  support a newer version of the WebSocket protocol (HyBi-07+).

- **Q: How do I adjust the dimensions of the VNC window image in the OpenStack
  dashboard?**

  A: These values are hard-coded in a Django HTML template. To alter them, edit
  the ``_detail_vnc.html`` template file. The location of this file varies
  based on Linux distribution. On Ubuntu 14.04, the file is at
  ``/usr/share/pyshared/horizon/dashboards/nova/instances/templates/instances/_detail_vnc.html``.

  Modify the ``width`` and ``height`` options, as follows:

  .. code-block:: ini

     <iframe src="{{ vnc_url }}" width="720" height="430"></iframe>

- **Q: My noVNC connections failed with ValidationError: Origin header protocol
  does not match. Why?**

  A: Make sure the ``base_url`` match your TLS setting. If you are using https
  console connections, make sure that the value of ``novncproxy_base_url`` is
  set explicitly where the ``nova-novncproxy`` service is running.


References
----------

.. [1] https://qemu.weilnetz.de/doc/qemu-doc.html#vnc_005fsec_005fcertificate_005fverify
.. [2] https://tools.ietf.org/html/rfc3280#section-4.2.1.10
