"""Search-keyword views must not silently present identical results as coverage."""
import unittest

from predoc_pipeline.core.query_result_diversity import identical_nonempty_query_results


class QueryDiversityTests(unittest.TestCase):
    def test_ignored_keywords_are_unverified_not_distinct_coverage(self):
        first = "https://example.edu/jobs/1"
        second = "https://example.edu/jobs/2"
        rows = [
            ("https://example.edu/search?keyword=epi", {first, second}),
            ("https://example.edu/search?keyword=genomics", {second, first}),
            ("https://example.edu/search?keyword=crispr", {first, second}),
        ]
        self.assertTrue(identical_nonempty_query_results(rows))

    def test_distinct_queries_with_real_vacancy_difference_are_not_flagged(self):
        rows = [
            ("https://example.edu/search?q=a", {"https://example.edu/jobs/1"}),
            ("https://example.edu/search?q=b", {"https://example.edu/jobs/2"}),
        ]
        self.assertFalse(identical_nonempty_query_results(rows))

    def test_empty_one_page_or_unfinished_search_is_not_inferred_broken(self):
        self.assertFalse(identical_nonempty_query_results([]))
        self.assertFalse(identical_nonempty_query_results([
            ("https://example.edu/search?q=a", {"https://example.edu/jobs/1"})]))
        self.assertFalse(identical_nonempty_query_results([
            ("https://example.edu/search?q=a", {"https://example.edu/jobs/1"}),
            ("https://example.edu/search?q=b", set())]))
        self.assertFalse(identical_nonempty_query_results([
            ("https://example.edu/search?q=a", set()),
            ("https://example.edu/search?q=b", set())]))

    def test_repeated_same_endpoint_is_not_two_independent_queries(self):
        self.assertFalse(identical_nonempty_query_results([
            ("https://example.edu/search?q=a", {"https://example.edu/jobs/1"}),
            ("https://example.edu/search?q=a", {"https://example.edu/jobs/1"}),
        ]))


if __name__ == "__main__":
    unittest.main()
