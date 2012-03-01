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


Overview
========
The VNC Proxy is an OpenStack component that allows users of Nova to access
their instances through vnc clients.  In essex and beyond, there is support
for for both libvirt and XenServer using both java and websocket cleints.

In general, a VNC console Connection works like so:

* User connects to api and gets an access_url like http://ip:port/?token=xyz
* User pastes url in browser or as client parameter
* Browser/Client connects to proxy
* Proxy authorizes users token, maps the token to a host and port of an
  instance's VNC server
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

Getting an Access Url
---------------------
Nova provides the ability to create access_urls through the os-consoles extension.
Support for accessing this url is provided by novaclient:

::

    nova get-vnc-console [server_id] [xvpvnc|novnc]


Accessing VNC Consoles with a Java client
-----------------------------------------
To enable support for the OpenStack java vnc client in nova, nova provides the
nova-xvpvncproxy service, which you should run to enable this feature.

* :option:`--xvpvncproxy_baseurl=[base url for client connections]` -
  this is the public base url to which clients will connect.  "?token=abc"
  will be added to this url for the purposes of auth.
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
http://github.com/cloudbuilders/noVNC.git (in a branch called vnc_redux while
this patch is in review).

To use this nova-novncproxy:

::

    git clone http://github.com/cloudbuilders/noVNC.git
    git checkout vnc_redux
    utils/nova-novncproxy --flagfile=[path to flagfile]

The --flagfile param should point to your nova config that includes the rabbit
server address and credentials.

By default, nova-novncproxy binds 0.0.0.0:6080.  This can be configured with:

* :option:`--novncproxy_baseurl=[base url for client connections]` -
  this is the public base url to which clients will connect.  "?token=abc"
  will be added to this url for the purposes of auth.
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

Support for a streamlined flow via dashboard will land in essex.


Important Options
-----------------
* :option:`--[no]vnc_enabled` - defaults to enabled. If this flag is
  disabled your instances will launch without vnc support.
* :option:`--vncserver_listen` - defaults to 127.0.0.1
  This is the address that vncservers will bind, and should be overridden in
  production deployments as a private address.  Applies to libvirt only.
  For multi-host libvirt  deployments this should be set to a host
  management ip on the same network as the proxies.
* :option:`--vncserver_proxyclient_address` - defaults to 127.0.0.1
  This is the address that nova will instruct proxies to use when connecting to
  to instance vncservers.
  For all-in-one xen server domU deployments this can be set to 169.254.0.1.
  For multi-host xen server domU deployments this can be set to a dom0
  management ip on the same network as the proxies.
  For multi-host libvirt  deployments this can be set to a host
  management ip on the same network as the proxies.


.. todo:: 

   Reformat command line app instructions for commands using
   ``:command:``, ``:option:``, and ``.. program::``. (bug-947261)
