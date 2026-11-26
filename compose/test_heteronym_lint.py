import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heteronym_lint as H


def kinds(text):
    return [(f.word.lower(), f.level, f.reading) for f in H.check_text(text)]


class Read(unittest.TestCase):
    def test_past_is_an_error(self):
        for t in ("I have read enough to count the freezer.", "She had read it twice.", "It was read aloud.", "We read it yesterday."):
            self.assertEqual(kinds(t)[0][1:], ("error", "past"), t)

    def test_ambiguous_is_an_error(self):
        for t in ("We read the sealed letters!", "I read only our own lines.", "The person read the long line.", "I read the log."):
            self.assertEqual(kinds(t)[0][1:], ("error", "ambiguous"), t)

    def test_present_is_clean(self):
        for t in ("I will read them slowly.", "Please read the policy.", "Read the long line.", "Did not read the long line.", "You can read it.",
                  "We do not read one line past our own.", "To read is to listen."):
            self.assertEqual([k for k in kinds(t) if k[0] == "read"], [], t)

    def test_other_words_are_not_flagged(self):
        self.assertEqual(kinds("The reading room is ready. A thread of already."), [])


class Others(unittest.TestCase):
    def test_other_heteronyms_are_a_review_note_not_an_error(self):
        k = kinds("Keep a record of the lead and the wind.")
        self.assertEqual({w for w, _, _ in k}, {"record", "lead", "wind"})
        self.assertTrue(all(level == "review" for _, level, _ in k))

    def test_a_respelled_word_in_the_pronunciation_file_is_quiet(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "pronounce.txt")
        open(p, "w").write("# comment\nLead=Led\n")
        self.assertEqual([f.word for f in H.check_text("The Lead node.", pron_file=p)], [])
        self.assertEqual([f.word for f in H.check_text("The lead node.", pron_file=p)], ["lead"])  # case-sensitive, like sing.pronounce

    def test_an_inline_say_marker_is_quiet_and_only_for_that_word(self):
        # word{say}: this one use of the word is spoken as "say" (deliberate wordplay); other uses are still checked
        self.assertEqual(kinds("I have read{red} enough."), [])
        self.assertEqual([k[:2] for k in kinds("I have read{red} it and she had read it.")], [("read", "error")])
        self.assertEqual(kinds("The lead{led} pipe."), [])
        self.assertEqual(H.inline_say("I have read{red} the bass{base} line."), "I have red the base line.")


class Files(unittest.TestCase):
    def test_script_lines_directions_and_comments(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "s.txt")
        open(p, "w").write("# I read this comment\ncast: A = bm_george | pan 0\n[sfx static]\nA: We read the letters.\n@voice bm_george\n(sung, I read it)\nI have read it.\n")
        got = [(f.line, f.level) for f in H.check_file(p)]
        self.assertEqual(got, [(4, "error"), (7, "error")])  # the comment, cast line, direction, @voice and (stage) line are not spoken

    def test_main_exit_status(self):
        d = tempfile.mkdtemp(); bad = os.path.join(d, "b.txt"); ok = os.path.join(d, "o.txt")
        open(bad, "w").write("A: I read it.\n"); open(ok, "w").write("A: I will read it.\n")
        self.assertEqual(H.main([bad]), 1); self.assertEqual(H.main([ok]), 0)


if __name__ == "__main__":
    unittest.main()
