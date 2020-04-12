========
Glossary
========

.. glossary::

    Availability Zone
        Availability zones are a logical subdivision of cloud block storage,
        compute and network services. They provide a way for cloud operators to
        logically segment their compute based on arbitrary factors like
        location (country, datacenter, rack), network layout and/or power
        source.

        For more information, refer to :doc:`/admin/aggregates`.

    Boot From Volume
        A server that is created with a
        :doc:`Block Device Mapping </user/block-device-mapping>` with
        ``boot_index=0`` and ``destination_type=volume``. The root volume can
        already exist when the server is created or be created by the compute
        service as part of the server creation. Note that a server can have
        volumes attached and not be boot-from-volume. A boot from volume server
        has an empty ("") ``image`` parameter in ``GET /servers/{server_id}``
        responses.

    Cross-Cell Resize
        A resize (or cold migrate) operation where the source and destination
        compute hosts are mapped to different cells. By default, resize and
        cold migrate operations occur within the same cell.

        For more information, refer to
        :doc:`/admin/configuration/cross-cell-resize`.

    Host Aggregate
        Host aggregates can be regarded as a mechanism to further partition an
        :term:`Availability Zone`; while availability zones are visible to
        users, host aggregates are only visible to administrators. Host
        aggregates provide a mechanism to allow administrators to assign
        key-value pairs to groups of machines. Each node can have multiple
        aggregates, each aggregate can have multiple key-value pairs, and the
        same key-value pair can be assigned to multiple aggregates.

        For more information, refer to :doc:`/admin/aggregates`.

    Same-Cell Resize
        A resize (or cold migrate) operation where the source and destination
        compute hosts are mapped to the same cell. Also commonly referred to
        as "standard resize" or simply "resize". By default, resize and
        cold migrate operations occur within the same cell.

        For more information, refer to
        :doc:`/contributor/resize-and-cold-migrate`.
