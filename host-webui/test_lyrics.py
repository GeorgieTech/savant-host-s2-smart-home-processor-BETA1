#!/usr/bin/env python3
"""LRC / karaoke parser tests. Original fixture text only."""
import os
import tempfile
import unittest

import lyrics


class ParseLrcTests(unittest.TestCase):
    def test_plain_timed_lines(self):
        text = "\n".join([
            "[ti:Fixture Glow]",
            "[ar:CRYPT Test]",
            "[00:01.00]First glow",
            "[00:04.50]Second glow",
            "[00:08.00]Third glow",
        ])
        parsed = lyrics.parse_lrc(text)
        self.assertEqual(parsed["meta"]["title"], "Fixture Glow")
        self.assertEqual(len(parsed["lines"]), 3)
        self.assertEqual(parsed["lines"][0]["t"], 1.0)
        self.assertEqual(parsed["lines"][1]["text"], "Second glow")
        self.assertAlmostEqual(parsed["lines"][1]["t"], 4.5)

    def test_enhanced_words(self):
        text = "[00:02.00]Hold [00:02.40]the [00:02.80]line"
        parsed = lyrics.parse_lrc(text)
        words = parsed["lines"][0]["words"]
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0]["text"].strip(), "Hold")
        self.assertAlmostEqual(words[1]["t"], 2.4)
        self.assertEqual(parsed["lines"][0]["text"].replace(" ", ""), "Holdtheline")

    def test_offset_tag(self):
        text = "[offset:500]\n[00:01.00]Shifted"
        parsed = lyrics.parse_lrc(text)
        self.assertAlmostEqual(parsed["lines"][0]["t"], 1.5)

    def test_sidecar_lookup(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        lrc = path[:-4] + ".lrc"
        try:
            with open(path, "wb") as fh:
                fh.write(b"RIFF")
            with open(lrc, "w") as fh:
                fh.write("[00:00.50]Sidecar glow\n[00:03.00]Keep time\n")
            with open(lrc, "r") as fh:
                parsed = lyrics.parse_lrc(fh.read())
            self.assertEqual(parsed["lines"][0]["text"], "Sidecar glow")
            self.assertTrue(any(p.endswith(".lrc") for p in lyrics.sidecar_paths(path)))
        finally:
            for p in (path, lrc):
                try:
                    os.unlink(p)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
