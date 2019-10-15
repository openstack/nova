{
    "migrations": [
        {
            "created_at": "2016-01-29T12:42:02.000000",
            "dest_compute": "compute2",
            "dest_host": "1.2.3.4",
            "dest_node": "node2",
            "id": 2,
            "instance_uuid": "%(instance_1)s",
            "new_instance_type_id": 1,
            "old_instance_type_id": 1,
            "source_compute": "compute1",
            "source_node": "node1",
            "migration_type": "live-migration",
            "status": "error",
            "updated_at": "2016-01-29T12:42:02.000000",
            "uuid": "22341d4b-346a-40d0-83c6-5f4f6892b650",
            "user_id": "5c48ebaa-193f-4c5d-948a-f559cc92cd5e",
            "project_id": "ef92ccff-00f3-46e4-b015-811110e36ee4"
        },
        {
            "created_at": "2016-01-29T11:42:02.000000",
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
            "new_instance_type_id": 1,
            "old_instance_type_id": 1,
            "source_compute": "compute1",
            "source_node": "node1",
            "migration_type": "live-migration",
            "status": "running",
            "updated_at": "2016-01-29T11:42:02.000000",
            "uuid": "12341d4b-346a-40d0-83c6-5f4f6892b650",
            "user_id": "5c48ebaa-193f-4c5d-948a-f559cc92cd5e",
            "project_id": "ef92ccff-00f3-46e4-b015-811110e36ee4"
        }
    ]
}
