from odoo.tests.common import TransactionCase


class TestSplitLeafBlockSegments(TransactionCase):
    """Tests for APSAIModelAnswerChunking._split_leaf_block_segments."""

    def _split(self, text, chunk_mode='auto'):
        model = self.env['aps.ai.model']
        return model._split_leaf_block_segments(text, chunk_mode=chunk_mode)

    def _texts(self, text, chunk_mode='auto'):
        return [s['text'] for s in self._split(text, chunk_mode=chunk_mode)]

    # ------------------------------------------------------------------
    # Basic sentence splitting
    # ------------------------------------------------------------------

    def test_single_sentence_returns_one_chunk(self):
        result = self._split('This is a single sentence.')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], 'This is a single sentence.')
        self.assertIsNone(result[0]['separator'])

    def test_two_long_sentences_split(self):
        text = 'The dog sat on the mat. The cat ran up the hill.'
        texts = self._texts(text)
        self.assertEqual(len(texts), 2)
        self.assertIn('The dog sat on the mat.', texts[0])
        self.assertIn('The cat ran up the hill.', texts[1])

    def test_empty_text_returns_empty(self):
        self.assertEqual(self._split(''), [])

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(self._split('   \n  '), [])

    # ------------------------------------------------------------------
    # Short trailing fragment must NOT be split off (the main regression)
    # ------------------------------------------------------------------

    def test_code_like_string_not_split_on_dot(self):
        """print("Error: Please enter exactly 2 words. ") must stay as one chunk."""
        text = 'print("Error: Please enter exactly 2 words. ")'
        texts = self._texts(text)
        self.assertEqual(len(texts), 1,
            f'Expected 1 chunk but got {len(texts)}: {texts}')

    def test_short_trailing_fragment_merged(self):
        """A short fragment after . should be merged back into the previous part."""
        # "Go." → only 1 word after split, must merge back
        text = 'The cat sat on the mat. Go.'
        texts = self._texts(text)
        # "Go." has 1 word < 5, so it must be merged with the previous sentence
        self.assertEqual(len(texts), 1,
            f'Short trailing fragment should merge back; got {len(texts)}: {texts}')

    def test_two_long_sentences_followed_by_short_fragment(self):
        """Two real sentences followed by a short fragment: short one merges into second."""
        text = 'The dog sat on the mat. The cat ran up the hill. Yes.'
        texts = self._texts(text)
        self.assertEqual(len(texts), 2,
            f'Expected 2 chunks (short "Yes." merged into previous); got {len(texts)}: {texts}')
        self.assertTrue(texts[-1].endswith('Yes.'))

    # ------------------------------------------------------------------
    # Code mode
    # ------------------------------------------------------------------

    def test_code_mode_splits_by_line(self):
        text = 'x = 1\ny = 2\nprint(x + y)'
        segments = self._split(text, chunk_mode='code')
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]['text'], 'x = 1')
        self.assertEqual(segments[1]['text'], 'y = 2')
        self.assertEqual(segments[2]['text'], 'print(x + y)')
        self.assertEqual(segments[0]['separator'], 'br')
        self.assertEqual(segments[1]['separator'], 'br')
        self.assertIsNone(segments[2]['separator'])

    def test_code_mode_skips_empty_lines(self):
        text = 'x = 1\n\ny = 2'
        segments = self._split(text, chunk_mode='code')
        self.assertEqual(len(segments), 2)

    def test_code_mode_single_line(self):
        text = 'print("hello")'
        segments = self._split(text, chunk_mode='code')
        self.assertEqual(len(segments), 1)
        self.assertIsNone(segments[0]['separator'])

    # ------------------------------------------------------------------
    # Sub-chunk splitting on comma/semicolon
    # ------------------------------------------------------------------

    def test_long_comma_clause_split(self):
        """A sentence with two long comma-separated clauses should split."""
        text = (
            'The first part of the sentence is here, '
            'the second part of the sentence is also here.'
        )
        texts = self._texts(text)
        self.assertEqual(len(texts), 2,
            f'Expected 2 sub-chunks from comma split; got {len(texts)}: {texts}')

    def test_short_comma_clause_not_split(self):
        """Short comma-separated parts should not be split."""
        texts = self._texts('First, second, third.')
        self.assertEqual(len(texts), 1)

    # ------------------------------------------------------------------
    # Multi-line text
    # ------------------------------------------------------------------

    def test_two_lines_produce_br_separator(self):
        text = 'First line sentence here.\nSecond line sentence here.'
        segments = self._split(text)
        # Last segment of first line gets 'br', last segment of last line gets None
        br_seps = [s for s in segments if s['separator'] == 'br']
        none_seps = [s for s in segments if s['separator'] is None]
        self.assertTrue(br_seps, 'Expected at least one br separator between lines')
        self.assertTrue(none_seps, 'Expected last segment to have None separator')
