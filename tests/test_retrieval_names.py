import unittest

from retrieval_names import completed_retrieval, retrieval_stamp


class RetrievalNamesTests(unittest.TestCase):
    def test_rounds_like_single_tropoe(self):
        self.assertEqual(retrieval_stamp('202405141859'), '20240514.1900')
        self.assertEqual(retrieval_stamp('202405141907'), '20240514.1900')
        self.assertEqual(retrieval_stamp('202405141908'), '20240514.1915')
        self.assertEqual(retrieval_stamp('202405142359'), '20240515.0000')

    def test_completed_lookup_is_specific_to_channel_band_and_time(self):
        files = {'tropoeOutput_Ch1.20240514.190000.nc',
                 'tropoeOutput_Ch2_B2.20240514.190000.nc'}
        self.assertTrue(completed_retrieval('202405141859', 1, files))
        self.assertTrue(completed_retrieval('202405141859', 2, files, 2))
        self.assertFalse(completed_retrieval('202405141859', 2, files, 6))
        self.assertFalse(completed_retrieval('202405141915', 1, files))


if __name__ == '__main__':
    unittest.main()
