{
    "server": {
        "admin_pass": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "%(host)s/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "os-disk-config:disk_config": "AUTO",
        "security_groups": [
            {
                "name": "default"
            }
        ]
    }
}
