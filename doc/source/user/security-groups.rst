===============
Security Groups
===============

Security groups are sets of IP filter rules that are applied to all servers,
which define networking access to the server. Group rules are project-specific;
project members can edit the default rules for their group and add new rule
sets.

All projects have a ``default`` security group which is applied to any port
that has no other security group defined. Unless you change the default, this
security group denies all incoming traffic and allows only outgoing traffic
from your instance.

It's important to note early on that security groups and their quota are
resources of :neutron-doc:`the networking service, Neutron
</admin/intro-os-networking.html#security-groups>`. They are modelled as an
attribute of ports rather than servers. With this said, Nova provides utility
APIs that allow users to add and remove security groups from all ports attached
to a server. In addition, it is possible to specify security groups to
configure for newly created ports when creating a new server, and to retrieve
the combined set of security groups for all ports attached to a server.

.. note::

    Nova previously provided its own security group APIs. These were proxy APIs
    for Neutron APIs and have been deprecated since microversion 2.36.


Usage
-----

Security group-related operations can be broken down into three categories:
operations on security groups and security group rules themselves, operations
on ports, and operations on servers.

.. rubric:: Security group and security group rule operations

By default, security groups can be created by any project member. For example:

.. code-block:: console

    $ openstack security group create --description <description> ... <name>

.. tip::

    When adding a new security group, you should pick a descriptive but brief
    name. This name shows up in brief descriptions of the servers that use it
    where the longer description field often does not. For example, seeing that
    a server is using security group ``http`` is much easier to understand
    than ``bobs_group`` or ``secgrp1``.

Security groups are really only containers for rules. Security group rules
define the actual IP filter rules that will be applied. Security groups deny
everything by default, so rules indicate what is allowed. Typically, a security
group rule will be configured with the following attributes: an IP protocol
(one of ICMP, TCP, or UDP), a destination port or port range, and a remote IP
range (in CIDR format). You create security group rules by specifying these
attributes and the security group to which the rules should be added. For
example:

.. code-block:: console

    $ openstack security group rule create \
        --protocol <protocol> --dst-port <port-range> \
        --remote-ip <ip-address> \
        <group>

.. note::

    The ``<port-range>`` argument takes the form of ``port`` or
    ``from-port:to-port``. This specifies the range of local ports that
    connections are allowed to access, **not** the source and destination ports
    of the connection.

Alternatively, rather than specifying a remote IP range, you can specify a
remote security group. A remote group will allow requests with the specified
protocol(s) and port(s) from any server with said port. If you create a
security group rule with remote group ``foo`` and apply the security group to
server ``bar``, ``bar`` will be able to receive matching traffic from any other
server with security group ``foo``. Security group rules with remote security
groups are created in much the same way as security group rules with remote
IPs. For example:

.. code-block:: console

    $ openstack security group rule create \
        --protocol <protocol> --dst-port <port-range> \
        --remote-group <remote-group> \
        <group>

Once created, both security groups and security group rules can be listed. For
example:

.. code-block:: console

    $ openstack security group list
    $ openstack security group rule list <group>

Likewise, you can inspect an individual security group or security group rule.
For example:

.. code-block:: console

    $ openstack security group show <group>
    $ openstack security group rule show <group> <rule>

Finally, you can delete security groups. This will delete both the security
group and associated security group rules. For example:

.. code-block:: console

    $ openstack security group delete <group>

Alternatively, you can delete individual rules from an existing group. For
example:

.. code-block:: console

    $ openstack security group rule delete <rule>

.. rubric:: Port operations

Security groups are an attribute of ports. By default, Neutron will assign the
``default`` security group to all newly created ports. It is possible to
disable this behavior. For example:

.. code-block:: console

    $ openstack port create --no-security-group ... <name>

It is possible to specify different security groups when creating a new port.
For example:

.. code-block:: console

    $ openstack port create --security-group <group> ... <name>

.. note::

    If you specify a security group when creating the port, the ``default``
    security group **will not** be added to the port. If you wish to add the
    ``default`` security group, you will need to specify this also.

Additional security groups can also be added or removed from existing ports.
For example:

.. code-block:: console

    $ openstack port set --security-group <group> ... <port>
    $ openstack port unset --security-group <group> ... <port>

It is also possible to remove all security groups from a port. For example:

.. code-block:: console

    $ openstack port set --no-security-group <port>

.. rubric:: Server operations

It is possible to manipulate and configure security groups on an server-wide
basis. When you create a new server, networks can be either automatically
allocated (a feature known as ":neutron-doc:`Get me a network
</admin/config-auto-allocation.html>`") or manually configured. In both cases,
attaching a network to a server results in the creation of a port. It is
possible to specify one or more security groups to assign to these ports. For
example:

.. code-block:: console

    $ openstack server create --security-group <group> ... <name>

.. important::

    These security groups will only apply to automatically created ports. They
    will not apply to any pre-created ports attached to the server at boot.
    If no security group is specified, the ``default`` security group for the
    current project will be used. It is not possible to specify that no
    security group should be applied to automatically created ports. If you
    wish to remove the ``default`` security group from a server's ports, you
    will need to use pre-created ports or remove the security group after the
    server has been created.

Once a server has been created, it is possible to add or remove a security
group from all ports attached to the server. For example:

.. code-block:: console

    $ openstack server add security group <server> <group>
    $ openstack server remove security group <server> <group>

.. note::

    Unless customised, the ``default`` security group allows egress traffic
    from the server. If you remove this group and do not allow egress traffic
    via another security group, your server will no longer be able to
    communicate with the :ref:`metadata service <metadata-service>`.

It is also possible to view the security groups associated with a server. For
example:

.. code-block:: console

    $ openstack server show -f value -c security_groups

.. important::

    As security groups are an attribute of ports rather than servers, this
    value is the combined set of security groups assigned to all ports.
    Different ports may have different sets of security groups. You can inspect
    the port with ``openstack port show`` to see the exact security groups
    assigned to an individual port.


Example
-------

Let's look through a worked example of creating security groups for a
deployment of 3 web server hosts and 2 database hosts. First, we'll configure
the security group that will allow HTTP traffic to the web server hosts.

.. code-block:: console

   $ openstack security group create \
       --description "Allows Web traffic anywhere on the Internet." \
       web
   +-----------------+--------------------------------------------------------------------------------------------------------------------------+
   | Field           | Value                                                                                                                    |
   +-----------------+--------------------------------------------------------------------------------------------------------------------------+
   | created_at      | 2016-11-03T13:50:53Z                                                                                                     |
   | description     | Allows Web traffic anywhere on the Internet.                                                                             |
   | headers         |                                                                                                                          |
   | id              | c0b92b20-4575-432a-b4a9-eaf2ad53f696                                                                                     |
   | name            | web                                                                                                              |
   | project_id      | 5669caad86a04256994cdf755df4d3c1                                                                                         |
   | project_id      | 5669caad86a04256994cdf755df4d3c1                                                                                         |
   | revision_number | 1                                                                                                                        |
   | rules           | created_at='2016-11-03T13:50:53Z', direction='egress', ethertype='IPv4', id='4d8cec94-e0ee-4c20-9f56-8fb67c21e4df',      |
   |                 | project_id='5669caad86a04256994cdf755df4d3c1', revision_number='1', updated_at='2016-11-03T13:50:53Z'                    |
   |                 | created_at='2016-11-03T13:50:53Z', direction='egress', ethertype='IPv6', id='31be2ad1-be14-4aef-9492-ecebede2cf12',      |
   |                 | project_id='5669caad86a04256994cdf755df4d3c1', revision_number='1', updated_at='2016-11-03T13:50:53Z'                    |
   | updated_at      | 2016-11-03T13:50:53Z                                                                                                     |
   +-----------------+--------------------------------------------------------------------------------------------------------------------------+

Once created, we can add a new group rule to allow ingress HTTP traffic on port
80:

.. code-block:: console

    $ openstack security group rule create \
        --protocol tcp --dst-port 80:80 --remote-ip 0.0.0.0/0 \
        web
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | created_at        | 2016-11-06T14:02:00Z                 |
    | description       |                                      |
    | direction         | ingress                              |
    | ethertype         | IPv4                                 |
    | headers           |                                      |
    | id                | 2ba06233-d5c8-43eb-93a9-8eaa94bc9eb5 |
    | port_range_max    | 80                                   |
    | port_range_min    | 80                                   |
    | project_id        | 5669caad86a04256994cdf755df4d3c1     |
    | project_id        | 5669caad86a04256994cdf755df4d3c1     |
    | protocol          | tcp                                  |
    | remote_group_id   | None                                 |
    | remote_ip_prefix  | 0.0.0.0/0                            |
    | revision_number   | 1                                    |
    | security_group_id | c0b92b20-4575-432a-b4a9-eaf2ad53f696 |
    | updated_at        | 2016-11-06T14:02:00Z                 |
    +-------------------+--------------------------------------+

You can create complex rule sets by creating additional rules. In this instance
we want to pass both HTTP and HTTPS traffic so we'll add an additional rule:

.. code-block:: console

    $ openstack security group rule create \
        --protocol tcp --dst-port 443:443 --remote-ip 0.0.0.0/0 \
        web
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | created_at        | 2016-11-06T14:09:20Z                 |
    | description       |                                      |
    | direction         | ingress                              |
    | ethertype         | IPv4                                 |
    | headers           |                                      |
    | id                | 821c3ef6-9b21-426b-be5b-c8a94c2a839c |
    | port_range_max    | 443                                  |
    | port_range_min    | 443                                  |
    | project_id        | 5669caad86a04256994cdf755df4d3c1     |
    | project_id        | 5669caad86a04256994cdf755df4d3c1     |
    | protocol          | tcp                                  |
    | remote_group_id   | None                                 |
    | remote_ip_prefix  | 0.0.0.0/0                            |
    | revision_number   | 1                                    |
    | security_group_id | c0b92b20-4575-432a-b4a9-eaf2ad53f696 |
    | updated_at        | 2016-11-06T14:09:20Z                 |
    +-------------------+--------------------------------------+

.. note::

    Despite only outputting the newly added rule, this operation is additive
    (both rules are created and enforced).

That's one security group wrapped up. Next, the database hosts. These are
running MySQL and we would like to both restrict traffic to the relevant port
(``3306`` in this case) **and** to restrict ingress traffic to requests from
the web server hosts. While we could specify a CIDR for the IP addresses of the
web servers, a preferred solution is to configure a source group. This will
allow us to dynamically add and remove web server hosts with the ``web``
security group applied without needing to modify the security group for the
database hosts. Let's create the security group and the necessary rule:

.. code-block:: console

   $ openstack security group create database
   $ openstack security group rule create \
       --protocol tcp --dst-port 3306 --remote-group web \
       database

The ``database`` rule will now allows access to MySQL's default port from any
server that uses the ``web`` group.

Now that we've created the security group and rules, let's list them to verify
everything:

.. code-block:: console

    $ openstack security group list
    +--------------------------------------+----------+-------------+
    | Id                                   | Name     | Description |
    +--------------------------------------+----------+-------------+
    | 73580272-d8fa-4927-bd55-c85e43bc4877 | default  | default     |
    | c0b92b20-4575-432a-b4a9-eaf2ad53f696 | web      | web server  |
    | 40e1e336-e207-494f-a3ec-a3c222336b22 | database | database    |
    +--------------------------------------+----------+-------------+

We can also inspect the rules for the security group. Let's look at the ``web``
security group:

.. code-block:: console

    $ openstack security group rule list web
    +--------------------------------------+-------------+-----------+-----------------+-----------------------+
    | ID                                   | IP Protocol | IP Range  | Port Range      | Remote Security Group |
    +--------------------------------------+-------------+-----------+-----------------+-----------------------+
    | 2ba06233-d5c8-43eb-93a9-8eaa94bc9eb5 | tcp         | 0.0.0.0/0 | 80:80           | None                  |
    | 821c3ef6-9b21-426b-be5b-c8a94c2a839c | tcp         | 0.0.0.0/0 | 443:443         | None                  |
    +--------------------------------------+-------------+-----------+-----------------+-----------------------+

Assuming everything looks correct, you can now use these security groups when
creating your new servers.
