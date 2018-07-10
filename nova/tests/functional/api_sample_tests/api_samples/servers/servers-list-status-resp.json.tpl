{
    "servers": [
        {
            "id": "%(id)s",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/servers/%(id)s",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/servers/%(id)s",
                    "rel": "bookmark"
                }
            ],
            "name": "new-server-test"
        }
    ],
    "servers_links": [
        {
            "href": "%(versioned_compute_endpoint)s/servers?limit=1&status=%(status)s&marker=%(id)s",
            "rel": "next"
        }
    ]
}
