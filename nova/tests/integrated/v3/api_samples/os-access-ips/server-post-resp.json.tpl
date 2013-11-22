{
    "server": {
        "os-access-ips:access_ip_v4": "%(access_ip_v4)s",
        "os-access-ips:access_ip_v6": "%(access_ip_v6)s",
        "admin_password": "%(password)s",
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
