{
    "server": {
        "admin_password": "%(password)s",
        "id": "%(id)s",
        "os-disk-config:disk_config": "AUTO",
        "links": [
            {
                "href": "http://openstack.example.com/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "http://openstack.example.com/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ]
    }
}
