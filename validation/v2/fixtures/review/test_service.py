"""The repository's existing test suite for service.py (unchanged by the PR)."""


def run_suite(svc):
    """Return {test_name: passed} for the module object `svc`."""
    results = {}

    def check(name, fn):
        try:
            fn()
            results[name] = True
        except Exception:  # A failing assertion or crash is a failed test.
            results[name] = False

    def under_quota():
        assert svc.allow_request(0, 3) is True
        assert svc.allow_request(2, 3) is True

    def valid_token():
        assert svc.verify_token("abc", "abc") is True

    def wrong_token():
        assert svc.verify_token("abd", "abc") is False

    def usage_logs():
        svc.record_usage("c-1", 1)

    check("test_allow_under_quota", under_quota)
    check("test_verify_valid_token", valid_token)
    check("test_verify_wrong_token", wrong_token)
    check("test_record_usage", usage_logs)
    return results
