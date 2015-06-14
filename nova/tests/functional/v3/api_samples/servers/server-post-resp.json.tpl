{
    "server": {
        "adminPass": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "http://openstack.example.com/v2/openstack/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "http://openstack.example.com/openstack/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ]
    }
}
