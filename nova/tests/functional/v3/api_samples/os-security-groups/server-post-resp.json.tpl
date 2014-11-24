{
    "server": {
        "adminPass": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "http://openstack.example.com/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "http://openstack.example.com/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "security_groups": [{"name": "test"}]
    }
}
