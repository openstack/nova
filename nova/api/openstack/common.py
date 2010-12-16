def limited(items, req):
    """Return a slice of items according to requested offset and limit.

    items - a sliceable
    req - wobob.Request possibly containing offset and limit GET variables.
          offset is where to start in the list, and limit is the maximum number
          of items to return.

    If limit is not specified, 0, or > 1000, defaults to 1000.
    """
    offset = int(req.GET.get('offset', 0))
    limit = int(req.GET.get('limit', 0))
    if not limit:
        limit = 1000
    limit = min(1000, limit)
    range_end = offset + limit
    return items[offset:range_end]
