.. _manage-quotas:

=============
Manage quotas
=============

.. todo:: Merge this into 'quotas.rst'

To prevent system capacities from being exhausted without notification, you can
set up quotas. Quotas are operational limits. For example, the number of
gigabytes allowed for each project can be controlled so that cloud resources
are optimized.  Quotas can be enforced at both the project and the project-user
level.

Using the command-line interface, you can manage quotas for the OpenStack
Compute service, the OpenStack Block Storage service, and the OpenStack
Networking service.

The cloud operator typically changes default values because a project requires
more than ten volumes or 1 TB on a compute node.

.. note::

   To view all projects, run:

   .. code-block:: console

      $ openstack project list
      +----------------------------------+----------+
      | ID                               | Name     |
      +----------------------------------+----------+
      | e66d97ac1b704897853412fc8450f7b9 | admin    |
      | bf4a37b885fe46bd86e999e50adad1d3 | services |
      | 21bd1c7c95234fd28f589b60903606fa | tenant01 |
      | f599c5cd1cba4125ae3d7caed08e288c | tenant02 |
      +----------------------------------+----------+

   To display all current users for a project, run:

   .. code-block:: console

      $ openstack user list --project PROJECT_NAME
      +----------------------------------+--------+
      | ID                               | Name   |
      +----------------------------------+--------+
      | ea30aa434ab24a139b0e85125ec8a217 | demo00 |
      | 4f8113c1d838467cad0c2f337b3dfded | demo01 |
      +----------------------------------+--------+

Use :samp:`openstack quota show {PROJECT_NAME}` to list all quotas for a
project.

Use :samp:`openstack quota set {PROJECT_NAME} {--parameters}` to set quota
values.
