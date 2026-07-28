"""Tests for AST-based unified diff parsing (kg_construction#75).

PatchParser resolves changed functions/classes by parsing the pre-patch
source's real AST and mapping each changed line number against real
lineno/end_lineno ranges, rather than inferring boundaries from the diff
text's own (small, variable) context window. This replaces an earlier
hunk-scanning approach that caused four distinct bugs over time (#14, #43,
#63, #71) from the same root cause -- see patch.py's module docstring.

Each test constructs BOTH a patch and its corresponding pre-patch source,
since the new API requires the latter to resolve real ranges.
"""

from kg_construction.extraction.patch import PatchParser


class TestPatchParser:
    """Test PatchParser.extract_changed_functions()."""

    def test_extract_function_body_modified(self):
        source = (
            "def send(self, method, url, **kwargs):\n"
            "    response = self._request(url)\n"
            "    return response\n"
        )
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -1,3 +1,4 @@
 def send(self, method, url, **kwargs):
     response = self._request(url)
-    return response
+    return response  # cached
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py', source)
        assert 'send' in changed

    def test_extract_class_method_modified(self):
        source = (
            "class NewSession:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "\n"
            "    def send(self):\n"
            "        return 1\n"
        )
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -4,3 +4,3 @@
     def send(self):
-        return 1
+        return 2
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py', source)
        assert 'send' in changed
        assert 'NewSession' not in changed  # only the method's own body changed

    def test_ignore_changes_in_other_files(self):
        """Only code_file's own hunks are considered -- a multi-file patch
        must not pull in changes from a different file's hunks.
        """
        source = "def target_function():\n    return 1\n"
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -1,2 +1,2 @@
 def target_function():
-    return 1
+    return 2
--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -1,2 +1,2 @@
 def other_function():
-    return 1
+    return 2
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py', source)
        assert changed == {'target_function'}

    def test_multi_file_patch_final_hunk(self):
        """A target file that isn't last in a multi-file patch is still
        fully processed, not just its first hunk.
        """
        source = "def first_change():\n    return 1\n\n\ndef also_here():\n    return 2\n"
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -1,2 +1,2 @@
 def first_change():
-    return 1
+    return 10
@@ -5,2 +5,2 @@
 def also_here():
-    return 2
+    return 20
--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -1,2 +1,2 @@
 def second_change():
-    return 1
+    return 2
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py', source)
        assert changed == {'first_change', 'also_here'}

    def test_empty_patch(self):
        source = "def f():\n    return 1\n"
        changed = PatchParser.extract_changed_functions('', 'requests/sessions.py', source)
        assert len(changed) == 0

    def test_patch_no_target_file(self):
        source = "def f():\n    return 1\n"
        patch = """--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -1,2 +1,2 @@
 def some_function():
-    return 1
+    return 2
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py', source)
        assert len(changed) == 0

    def test_decorator_change_attributed_to_decorated_function(self):
        """A changed decorator line, though outside the def line's own
        ast.lineno, must still be attributed to the function it decorates --
        decorator_list's own line is included in the function's range.
        """
        source = '@app.route("/old")\ndef handler():\n    pass\n'
        patch = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
-@app.route("/old")
+@app.route("/new")
 def handler():
"""
        changed = PatchParser.extract_changed_functions(patch, 'app.py', source)
        assert 'handler' in changed

    def test_wide_context_does_not_sweep_in_unmodified_sibling(self):
        """Regression test for issue #43: an unmodified neighboring
        function's def line appearing in the same hunk (as context) must
        not be reported as changed -- resolution is by real line ranges,
        not by what's merely visible in the hunk.
        """
        source = (
            "def delete(self, url, **kwargs):\n"
            "    kwargs.setdefault('allow_redirects', True)\n"
            "    return self.request('DELETE', url, **kwargs)\n"
            "\n"
            "def send(self, request, **kwargs):\n"
            "    kwargs.setdefault('stream', self.stream)\n"
            "    kwargs.setdefault('verify', self.verify)\n"
            "    kwargs.setdefault('cert', self.cert)\n"
            "    kwargs.setdefault('proxies', self.proxies)\n"
            "\n"
            "    pass\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,10 +1,10 @@
 def delete(self, url, **kwargs):
     kwargs.setdefault('allow_redirects', True)
     return self.request('DELETE', url, **kwargs)

 def send(self, request, **kwargs):
     kwargs.setdefault('stream', self.stream)
     kwargs.setdefault('verify', self.verify)
     kwargs.setdefault('cert', self.cert)
-    kwargs.setdefault('proxies', self.proxies)
+    kwargs.setdefault('proxies', self.rebuild_proxies(request, self.proxies))

     pass
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'send'}

    def test_body_change_detection_does_not_leak_into_siblings(self):
        source = (
            "def unrelated():\n    pass\n\n"
            "def target():\n    return 1\n\n"
            "def another_unrelated():\n    pass\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -4,2 +4,2 @@
 def target():
-    return 1
+    return 2
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'target'}

    def test_context_only_def_with_unchanged_body_not_reported(self):
        """A def/class fully visible in the hunk as unchanged context must
        not be reported -- only its real line range, not mere visibility
        in the diff, decides attribution.
        """
        source = "def untouched():\n    return 1\n\ndef changed():\n    return 2\n"
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,5 +1,5 @@
 def untouched():
     return 1

 def changed():
-    return 2
+    return 3
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'changed'}
        assert 'untouched' not in changed

    def test_change_deep_in_long_function_still_attributed_correctly(self):
        """kg_construction#60's original motivation: a change far enough
        into a long function that a small diff context window wouldn't
        show its def line at all. Real ast ranges make this a non-issue --
        no context-window dependency at all.
        """
        source = (
            "def long_function(value):\n"
            "    step_one = value\n"
            "    step_two = step_one + 1\n"
            "    step_three = step_two * 2\n"
            "    return step_three\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -4,2 +4,2 @@
-    return step_three
+    return step_three + 1
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'long_function'}

    def test_change_outside_any_function_reports_nothing(self):
        """A changed line at module level, not inside any function/class,
        correctly reports no changed function (kg_construction#71's
        regression case, re-verified under the new AST-based approach).
        """
        source = "def untouched():\n    return 1\n# a module-level comment\n"
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,3 +1,3 @@
 def untouched():
     return 1
-# a module-level comment
+# a different module-level comment
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == set()

    def test_real_pytest_multi_hunk_case_from_issue_71(self):
        """The exact real-world shape that surfaced #71: a changed line
        deep inside a function, followed later in the SAME hunk by an
        unrelated, unmodified sibling function's def line swept in as
        trailing context. Must not suppress or misattribute the real
        change -- confirmed directly against pytest-dev/pytest's own
        _showfixtures_main patch under the old hunk-scanning approach;
        re-verified here that the AST-based approach gets it right too,
        without needing any special-casing for this shape at all.
        """
        source = (
            "def real_target(x):\n"
            "    if x > 0:\n"
            "        return x\n"
            "\n"
            "\n"
            "def unrelated_sibling(y):\n"
            "    return y\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,3 +1,4 @@
 def real_target(x):
     if x > 0:
+        print("added")
         return x
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'real_target'}


class TestExtractChangedFunctionsWithScope:
    """kg_construction#63: a changed method name can match more than one
    class' same-named method in the same file. extract_changed_functions_with_scope
    reports the enclosing class alongside each name so TestContextExtractor
    can disambiguate. Resolution is now by real line range -- two same-named
    methods on different classes have different ranges, so this ambiguity
    can't even arise structurally (unlike the old hunk-scanning approach,
    which needed an explicit class-hint mechanism to work around it).
    """

    def test_method_reports_its_enclosing_class(self):
        source = "class Widget:\n    def build(self):\n        return self.helper()\n"
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,3 +1,4 @@
 class Widget:
     def build(self):
         return self.helper()
+        # a comment
"""
        changed = PatchParser.extract_changed_functions_with_scope(patch, 'mod.py', source)
        assert ('build', 'Widget') in changed

    def test_no_class_information_reports_none(self):
        source = "def standalone():\n    return 1\n"
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,2 +1,3 @@
 def standalone():
     return 1
+    # comment
"""
        changed = PatchParser.extract_changed_functions_with_scope(patch, 'mod.py', source)
        assert ('standalone', None) in changed

    def test_class_scope_does_not_leak_to_module_level_function(self):
        source = (
            "class Widget:\n"
            "    def build(self):\n"
            "        return 1\n"
            "\n"
            "def standalone():\n"
            "    return 2\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -5,2 +5,3 @@
 def standalone():
     return 2
+    # comment
"""
        changed = PatchParser.extract_changed_functions_with_scope(patch, 'mod.py', source)
        assert ('standalone', None) in changed
        assert ('standalone', 'Widget') not in changed

    def test_two_classes_same_method_name_get_different_scopes(self):
        """The exact ambiguity #63 was found from: two unrelated classes
        each define a method with the same name. Both must be reported,
        each with its OWN correct enclosing class -- resolved here purely
        by real line range, no special ambiguity-handling needed.
        """
        source = (
            "class Alpha:\n"
            "    def aclose(self):\n"
            "        return 1\n"
            "\n"
            "class Beta:\n"
            "    def aclose(self):\n"
            "        return 2\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,7 +1,9 @@
 class Alpha:
     def aclose(self):
         return 1
+        # comment

 class Beta:
     def aclose(self):
         return 2
+        # comment
"""
        changed = PatchParser.extract_changed_functions_with_scope(patch, 'mod.py', source)
        assert ('aclose', 'Alpha') in changed
        assert ('aclose', 'Beta') in changed

    def test_nested_function_reports_no_class_even_inside_a_method(self):
        """kg_construction#74: a closure nested inside a method is
        attributed to the closure itself, not the enclosing method or
        class -- and correctly has no enclosing CLASS (its immediate
        enclosing scope is a function, not a class). The changed line sits
        in the middle of the closure's body (not at its very first/last
        line) so the change is unambiguously inside the closure alone, not
        at a boundary that could also plausibly belong to the enclosing
        method.
        """
        source = (
            "class Widget:\n"
            "    def build(self, items):\n"
            "        def sort_key(entry):\n"
            "            key = entry[1]\n"
            "            return key\n"
            "        return sorted(items, key=sort_key)\n"
        )
        patch = """--- a/mod.py
+++ b/mod.py
@@ -3,3 +3,4 @@
         def sort_key(entry):
             key = entry[1]
+            # comment
             return key
"""
        changed = PatchParser.extract_changed_functions_with_scope(patch, 'mod.py', source)
        assert ('sort_key', None) in changed
        assert ('build', 'Widget') not in changed

    def test_flat_extract_changed_functions_still_returns_bare_names(self):
        """extract_changed_functions (still used by resolve_target_function/
        build_baseline_context) must keep returning a flat Set[str]."""
        source = "class Widget:\n    def build(self):\n        return 1\n"
        patch = """--- a/mod.py
+++ b/mod.py
@@ -1,3 +1,4 @@
 class Widget:
     def build(self):
         return 1
+        # comment
"""
        changed = PatchParser.extract_changed_functions(patch, 'mod.py', source)
        assert changed == {'build'}
