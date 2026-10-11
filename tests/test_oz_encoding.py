"""Regression tests for the opt-in OZ/1/2 dictionary encoding gate."""
import unittest

from oz import Error
from oz_batch import render
from test_oz2 import extended


MESSAGES = [('job_a', 'V'), ('job_b', 'P'), ('job_literal', ':keep 12.50 ± 0.02 mm exactly')]


def _render(**kwargs):
    counters = kwargs.pop('counters', [len])
    return render(extended(), MESSAGES, counters=counters, **kwargs)


class EncodingGateTests(unittest.TestCase):
    def test_default_is_identical_to_explicit_off_and_keeps_compact_json(self):
        default = _render()
        off = _render(encoding='off')
        self.assertEqual(default, off)
        self.assertTrue(off.mode.startswith('json/'))
        self.assertIn('job_literal', off.text)
        self.assertIn('keep 12.50 ± 0.02 mm exactly', off.text)
        self.assertTrue(all(name.startswith('json/') for name in off.alternatives))

    def test_auto_rejects_dictionary_candidates_with_any_tokenizer_regression(self):
        baseline = _render(encoding='off', counters=[len, len])
        base_cost = baseline.tokens

        def no_regression(text, tokenizer):
            if text == baseline.text:
                return base_cost[tokenizer]
            # A candidate that helps one tokenizer but regresses the other is
            # ineligible even if its best-case score is lower.
            return base_cost[tokenizer] - 10 if tokenizer == 0 else base_cost[tokenizer] + 1

        result = render(extended(), MESSAGES,
                        counters=[lambda s: no_regression(s, 0), lambda s: no_regression(s, 1)],
                        encoding='auto')
        self.assertTrue(result.mode.startswith('json/'))
        self.assertEqual(result.text, baseline.text)

    def test_auto_requires_a_strict_minimum_saving_for_every_tokenizer(self):
        baseline = _render(encoding='off', counters=[len, len])
        base_cost = baseline.tokens

        def counter(index):
            return lambda text: base_cost[index] if text == baseline.text else base_cost[index] - (9 if index == 0 else 11)

        rejected = render(extended(), MESSAGES, counters=[counter(0), counter(1)],
                          encoding='auto', min_savings=10)
        self.assertTrue(rejected.mode.startswith('json/'))
        self.assertEqual(rejected.text, baseline.text)

        def enough_counter(index):
            return lambda text: base_cost[index] if text == baseline.text else base_cost[index] - 10

        accepted = render(extended(), MESSAGES, counters=[enough_counter(0), enough_counter(1)],
                          encoding='auto', min_savings=10)
        self.assertFalse(accepted.mode.startswith('json/'))
        self.assertTrue(all(after <= before for after, before in zip(accepted.tokens, base_cost)))
        self.assertTrue(all(before - after >= 10 for after, before in zip(accepted.tokens, base_cost)))

    def test_auto_rejects_candidates_without_any_strict_saving(self):
        baseline = _render(encoding='off', counters=[len, len])
        result = render(extended(), MESSAGES,
                        counters=[lambda s: baseline.tokens[0] if s == baseline.text else baseline.tokens[0],
                                  lambda s: baseline.tokens[1] if s == baseline.text else baseline.tokens[1]],
                        encoding='auto')
        self.assertTrue(result.mode.startswith('json/'))
        self.assertEqual(result.text, baseline.text)

    def test_on_forces_dictionary_candidates_and_preserves_budget(self):
        result = _render(encoding='on')
        self.assertFalse(result.mode.startswith('json/'))
        self.assertTrue(all(name.split('/')[0] in {'oz', 'oz_base'} for name in result.alternatives))
        self.assertIn('12.50 ± 0.02 mm', result.text)

        with self.assertRaises(Error):
            _render(encoding='on', max_tokens=1)

    def test_invalid_encoding_and_savings_threshold_fail_closed(self):
        for kwargs in [
            {'encoding': 'sometimes'},
            {'encoding': 'off', 'min_savings': -1},
            {'encoding': 'auto', 'min_savings': True},
            {'encoding': 'auto', 'min_savings': 1.5},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(Error):
                _render(**kwargs)


if __name__ == '__main__':
    unittest.main()
