class SearchError(Exception):
    """A search request failed.

    The message names the failure. It does not include the query, the API key,
    the URL, or response content.
    """
