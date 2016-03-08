{
    "migrations": [
        {
            "created_at": "2016-01-29T13:42:02.000000",
            "dest_compute": "compute2",
            "dest_host": "1.2.3.4",
            "dest_node": "node2",
            "id": 1,
            "instance_uuid": "%(instance_1)s",
            "links": [
                {
                    "href": "%(host)s/v2.1/6f70656e737461636b20342065766572/servers/%(instance_1)s/migrations/1",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/6f70656e737461636b20342065766572/servers/%(instance_1)s/migrations/1",
                    "rel": "bookmark"
                }
            ],
            "new_instance_type_id": 2,
            "old_instance_type_id": 1,
            "source_compute": "compute1",
            "source_node": "node1",
            "migration_type": "live-migration",
            "status": "running",
            "updated_at": "2016-01-29T13:42:02.000000"
        },
        {
            "created_at": "2016-01-29T13:42:02.000000",
            "dest_compute": "compute2",
            "dest_host": "1.2.3.4",
            "dest_node": "node2",
            "id": 2,
            "instance_uuid": "%(instance_1)s",
            "new_instance_type_id": 2,
            "old_instance_type_id": 1,
            "source_compute": "compute1",
            "source_node": "node1",
            "migration_type": "live-migration",
            "status": "error",
            "updated_at": "2016-01-29T13:42:02.000000"
        },
        {
            "created_at": "2016-01-22T13:42:02.000000",
            "dest_compute": "compute20",
            "dest_host": "5.6.7.8",
            "dest_node": "node20",
            "id": 3,
            "instance_uuid": "%(instance_2)s",
            "new_instance_type_id": 6,
            "old_instance_type_id": 5,
            "source_compute": "compute10",
            "source_node": "node10",
            "migration_type": "resize",
            "status": "error",
            "updated_at": "2016-01-22T13:42:02.000000"
        },
        {
            "created_at": "2016-01-22T13:42:02.000000",
            "dest_compute": "compute20",
            "dest_host": "5.6.7.8",
            "dest_node": "node20",
            "id": 4,
            "instance_uuid": "%(instance_2)s",
            "new_instance_type_id": 6,
            "old_instance_type_id": 5,
            "source_compute": "compute10",
            "source_node": "node10",
            "migration_type": "resize",
            "status": "migrating",
            "updated_at": "2016-01-22T13:42:02.000000"
        }
    ]
}
