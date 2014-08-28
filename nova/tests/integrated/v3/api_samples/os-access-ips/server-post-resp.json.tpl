{
    "server": {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
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
        ]
    }
}
