"""Smoke tests for unified diff parsing."""

import pytest
from kg_construction.extraction.patch import PatchParser


class TestPatchParser:
    """Test PatchParser.extract_changed_functions()."""

    def test_extract_single_function_added(self):
        """Extract function added in patch."""
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -100,6 +100,12 @@
     return response

+def new_function():
+    \"\"\"New function.\"\"\"
+    pass
+
 class Session:
     pass
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert 'new_function' in changed

    def test_extract_method_modified(self):
        """Extract method that was modified."""
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -455,6 +455,7 @@
 def send(self, method, url, **kwargs):
     response = self._request(url)
+    self.cache[url] = response
     return response
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert 'send' in changed

    def test_extract_class_added(self):
        """Extract class added in patch."""
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -500,6 +500,15 @@
     return response

+class NewSession:
+    \"\"\"New session class.\"\"\"
+    def __init__(self):
+        pass
+
+    def send(self):
+        pass
+
 def helper():
     pass
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert 'NewSession' in changed

    def test_ignore_changes_in_other_files(self):
        """Don't extract changes from other files."""
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -100,6 +100,7 @@
+def target_function():
+    pass

--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -50,6 +50,7 @@
+def other_function():
+    pass
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert 'target_function' in changed
        assert 'other_function' not in changed

    def test_multi_file_patch_final_hunk(self):
        """Process final hunk when target file is not last in patch."""
        patch = """--- a/requests/sessions.py
+++ b/requests/sessions.py
@@ -100,6 +100,7 @@
+def first_change():
+    pass

--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -50,6 +50,7 @@
+def second_change():
+    pass
"""
        # Extract from first file (not the last in patch)
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert 'first_change' in changed
        # Ensure we processed the hunk before switching files
        assert len(changed) == 1

    def test_empty_patch(self):
        """Handle empty patch gracefully."""
        changed = PatchParser.extract_changed_functions('', 'requests/sessions.py')
        assert len(changed) == 0

    def test_patch_no_target_file(self):
        """Return empty set when target file not in patch."""
        patch = """--- a/requests/adapters.py
+++ b/requests/adapters.py
@@ -100,6 +100,7 @@
+def some_function():
+    pass
"""
        changed = PatchParser.extract_changed_functions(patch, 'requests/sessions.py')
        assert len(changed) == 0
