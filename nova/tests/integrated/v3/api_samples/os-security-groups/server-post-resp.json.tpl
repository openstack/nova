{
    "server": {
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
        ],
        "os-security-groups:security_groups": [{"name": "test"}]
    }
}
