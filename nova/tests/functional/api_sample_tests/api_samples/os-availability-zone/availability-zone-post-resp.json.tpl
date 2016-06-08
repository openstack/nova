{
    "server": {
        "adminPass": "%(password)s",
        "id": "%(id)s",
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "OS-DCF:diskConfig": "AUTO",
        "security_groups": [
            {
                "name": "default"
            }
        ]
    }
}
