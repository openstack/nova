..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

FAQ
===
Q: What has changed since diablo?
A: Previously, vnc support was done differently for libvirt and xen.
Now, there is unified multi-hypervisor support.  To support this change,
configuration options have been added and changed.  Also,
a new required service called nova-consoleauth has been added.  If you
are upgrading from diablo, you will have to take these changes into
consideration when upgrading.

If you are using diablo, please see the documentation that shipped with
your code, as this information will not be relevant.

Q: What happened to diablo's nova-vncproxy?
A: nova-vncproxy was removed from the nova source tree.  The essex analog for
this process is nova-novncproxy, which is provided by an external project.

Q: Why is nova-vncproxy no longer part of nova?
A: In diablo, we shipped a websocket proxy (nova-vncproxy) with nova, but
it had poor browser support.  This nova-vncproxy code was dependent on external
noVNC code, so changes to that system involved updating 2 projects.
Due to the rapid evolution of websocket tech, and the tight dependence of
the websocket proxy on javscript and html components, we decided to keep that
code all in one place.

Q: What is the difference between nova-xvpvncproxy and nova-novncproxy?
A: nova-xvpvncproxy, which ships with nova, is a new proxy that supports
a simple java client.  nova-novncproxy uses noVNC to provide vnc support
through a web browser.

Q: I want VNC support in horizon.  What services do I need?
A: You need nova-novncproxy, nova-consoleauth, and correctly configured
compute hosts.

Q: When I use "nova get-vnc-console" or click on the vnc tab of Horizon,
it hangs.  Why?
A: Make sure you are running nova-consoleauth (In addition to nova-novncproxy).
The proxies rely on nova-consoleauth to validate tokens, and will wait for
a reply it  them until a timeout is reached.

Q: My vnc proxy worked fine during my All-In-One test, but now it doesn't work
on multi host.  Why?
A: The default flag values work for an All-In-One install, but changes must
be made on your compute hosts once you start to build a cluster.  As an
example, suppose you have 2 servers::

    PROXYSERVER (public_ip=172.24.1.1, management_ip=192.168.1.1)
    COMPUTESERVER (management_ip=192.168.1.2)

Your nova-compute configuration file would need the following values::

    # These flags help construct a connection data structure
    vncserver_proxyclient_address=192.168.1.2
    novncproxy_base_url=http://172.24.1.1:6080/vnc_auto.html
    xvpvncproxy_base_url=http://172.24.1.1:6081/console

    # This is the address where the underlying vncserver (not the proxy)
    # will listen for connections.
    vncserver_listen=192.168.1.2

Note that novncproxy_base_url and novncproxy_base_url use a public ip; this
is the url that is ultimately returned to clients, who generally will not
have access to your private network.  Your PROXYSERVER must be able to reach
vncserver_proxyclient_address, as that is the address over which the vnc
connection will be proxied.

See "Important nova-compute Options" for more information.

Q: My noVNC does not work with recent versions of web browsers.  Why?
A: Make sure you have python-numpy installed, which is required to support
a newer version of the WebSocket protocol (HyBi-07+).  Also, if you are
using diablo's nova-vncproxy, note that support for this protocol is not
provided.

Overview
========
The VNC Proxy is an OpenStack component that allows users of Nova to access
their instances through vnc clients.  In essex and beyond, there is support
for for both libvirt and XenServer using both java and websocket cleints.

The VNC console Connection works as follows:

* User connects to api and gets an access_url like http://ip:port/?token=xyz
* User pastes url in browser or as client parameter
* Browser/Client connects to proxy
* Proxy talks to nova-consoleauth to authorize the user's token,
  and then maps the token to the -private- host and port
  of an instance's VNC server.  The compute host specifies the what address
  the proxy should use to connect via the flag --vncserver_proxyclient_address.
  In this way, the vnc proxy works as a bridge between the public network,
  and the private host network.
* Proxy initiates connection to VNC server, and continues proxying until
  the session ends

Note that in general, the vnc proxy performs multiple functions:

* Bridges between public network (where clients live) and private network
  (where vncservers live)
* Mediates token authentication
* Transparently deals with hypervisor-specific connection details to provide
  a uniform client experience.


About nova-consoleauth
----------------------
Both client proxies leverage a shared service to manage token auth called
nova-consoleauth.  This service must be running in order for for either proxy
to work.  Many proxies of either type can be run against a single
nova-consoleauth service in a cluster configuration.

nova-consoleauth should not be confused with nova-console, which is a xen-specific
service that is not used by the most recent vnc proxy architecture.


Typical Deployment
==================
A typical deployment will consist of the following components:

 * One nova-consoleauth process. Typically this runs on the controller host.
 * One or more nova-novncproxy services.  This supports browser-based novnc
   clients.
   For simple deployments, this service typically will run on the same machine
   as nova-api, since it proxies between the public network and the private
   compute host network.
 * One or more nova-xvpvncproxy services. This supports the special java client
   discussed in this document.
   For simple deployments, this service typically will run on the same machine
   as nova-api, since it proxies between the public network and the private
   compute host network.
 * One or more compute hosts. These compute hosts must have correctly
   configured flags, as described below.


Getting an Access Url
---------------------
Nova provides the ability to create access_urls through the os-consoles extension.
Support for accessing this url is provided by novaclient:

::

    nova get-vnc-console [server_id] [novnc|xvpvnc]

Specify 'novnc' to retrieve a url suitable for pasting into a web browser.  Specify
'xvpvnc' for a url suitable for pasting into the java client.

So to request a web browser url:

::

    nova get-vnc-console [server_id] novnc


Important nova-compute Options
------------------------------
To enable vncproxy in your cloud, in addition to to running one or both of the
proxies and nova-consoleauth, you need to configure the following flags on your
compute hosts.

* :option:`--[no]vnc_enabled` - defaults to enabled. If this flag is
  disabled your instances will launch without vnc support.
* :option:`--vncserver_listen` - defaults to 127.0.0.1
  This is the address that vncservers will bind, and should be overridden in
  production deployments as a private address.  Applies to libvirt only.
  For multi-host libvirt  deployments this should be set to a host
  management ip on the same network as the proxies.
* :option:`--vncserver_proxyclient_address` - defaults to 127.0.0.1
  This is the address of the compute host that nova will instruct
  proxies to use when connecting to instance vncservers.
  For all-in-one xen server domU deployments this can be set to 169.254.0.1.
  For multi-host xen server domU deployments this can be set to a dom0
  management ip on the same network as the proxies.
  For multi-host libvirt  deployments this can be set to a host
  management ip on the same network as the proxies.
* :option:`--novncproxy_base_url=[base url for client connections]` -
  this is the public base url to which clients will connect.  "?token=abc"
  will be added to this url for the purposes of auth.
  When using the system as described in this document, an appropriate value is
  "http://$SERVICE_HOST:6080/vnc_auto.html" where SERVICE_HOST is a public
  hostname.
* :option:`--xvpvncproxy_base_url=[base url for client connections]` -
  this is the public base url to which clients will connect.  "?token=abc"
  will be added to this url for the purposes of auth.
  When using the system as described in this document, an appropriate value is
  "http://$SERVICE_HOST:6081/console" where SERVICE_HOST is a public hostname.


Accessing VNC Consoles with a Java client
-----------------------------------------
To enable support for the OpenStack java vnc client in nova, nova provides the
nova-xvpvncproxy service, which you should run to enable this feature.

* :option:`--xvpvncproxy_port=[port]` - port to bind (defaults to 6081)
* :option:`--xvpvncproxy_host=[host]` - host to bind (defaults to 0.0.0.0)

As a client, you will need a special Java client, which is
a version of TightVNC slightly modified to support our token auth:

::

    git clone https://github.com/cloudbuilders/nova-xvpvncviewer
    cd nova-xvpvncviewer
    make

Then, to create a session, first request an access url using python-novaclient
and then run the client like so:

::

    # Retrieve access url
    nova get-vnc-console [server_id] xvpvnc
    # Run client
    java -jar VncViewer.jar [access_url]


nova-vncproxy replaced with nova-novncproxy
-------------------------------------------
The previous vnc proxy, nova-vncproxy, has been removed from the nova source
tree and replaced with an improved server that can be found externally at
http://github.com/cloudbuilders/noVNC.git

To use this nova-novncproxy:

::

    git clone http://github.com/cloudbuilders/noVNC.git
    utils/nova-novncproxy --flagfile=[path to flagfile]

The --flagfile param should point to your nova config that includes the rabbit
server address and credentials.

By default, nova-novncproxy binds 0.0.0.0:6080.  This can be configured with:

* :option:`--novncproxy_port=[port]`
* :option:`--novncproxy_host=[host]`

Accessing a vnc console through a web browser
---------------------------------------------
Retrieving an access_url for a web browser is similar to the flow for
the java client:

::

    # Retrieve access url
    nova get-vnc-console [server_id] novnc
    # Then, paste the url into your web browser

Additionally, you can use horizon to access browser-based vnc consoles for
instances.


.. todo::

   Reformat command line app instructions for commands using
   ``:command:``, ``:option:``, and ``.. program::``. (bug-947261)
