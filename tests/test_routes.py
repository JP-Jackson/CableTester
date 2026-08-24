"""Route smoke tests.

Small on purpose. These exist because of one bug: two routes rendered the same
template and built its context separately, a new variable was added to one of
them, and every 404 started returning 500. Chromium asks for /favicon.ico on
every page load, so the bench box served an error page from a fault that no
test touched, because nothing here had ever asked for a page that does not
exist.
"""

import unittest

from tester.app import create_app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_the_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"window.CT", r.data)

    def test_a_missing_page_is_a_404_and_not_a_500(self):
        """The whole reason this file exists."""
        r = self.client.get("/no-such-page")
        self.assertEqual(r.status_code, 404)

    def test_the_favicon_request_chromium_always_makes_does_not_500(self):
        r = self.client.get("/favicon.ico")
        self.assertNotEqual(r.status_code, 500)

    def test_the_404_page_is_the_app_itself_and_is_fully_built(self):
        """It serves the UI so a stray URL lands the tech back on the tester.

        That only works if it gets the SAME context as the index route. Handing
        it less is what turned a 404 into a 500, so check a value that only
        exists when the context is complete rather than just the status code.
        """
        r = self.client.get("/no-such-page")
        self.assertIn(b"window.CT", r.data)
        self.assertIn(b"panelControl", r.data)
        self.assertNotIn(b"Undefined", r.data)

    def test_a_missing_api_endpoint_answers_json_not_a_page(self):
        r = self.client.get("/api/no-such-endpoint")
        self.assertEqual(r.status_code, 404)
        self.assertIn("json", r.headers.get("Content-Type", ""))

    def test_the_desk_button_endpoint_refuses_cleanly_off_the_kit(self):
        """No cabletester-mode here, so it must explain rather than traceback."""
        r = self.client.post("/api/panel/desk")
        self.assertIn(r.status_code, (400, 404))
        self.assertIn("json", r.headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
