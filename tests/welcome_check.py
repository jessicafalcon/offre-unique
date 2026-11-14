"""Welcome page: a new visitor sees it first; one click anywhere (full-screen button) opens the app.
    python tests/welcome_check.py
"""
from pathlib import Path
from streamlit.testing.v1 import AppTest
import sys
APP = str(Path(__file__).resolve().parents[1] / (sys.argv[1] if len(sys.argv) > 1 else "app.py"))
at = AppTest.from_file(APP, default_timeout=300).run()
ok1 = not at.exception and not at.subheader and [b.key for b in at.button] == ["enter"]
at.button(key="enter").click().run()
ok2 = not at.exception and at.subheader and at.subheader[0].value == "Point Contrôles"
at.text_input[0].set_value("481447951").run()
ok3 = at.subheader and at.subheader[0].value == "Bati Recyclage"  # stays in the app after the first click
print(("PASS" if ok1 else "FAIL"), "welcome page first, only the 'enter' button")
print(("PASS" if ok2 else "FAIL"), "click -> app with Point Contrôles")
print(("PASS" if ok3 else "FAIL"), "welcome page does not come back")
sys.exit(0 if ok1 and ok2 and ok3 else 1)
