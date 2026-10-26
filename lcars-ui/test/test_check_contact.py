#!/usr/bin/env python3
"""check.py's AutoFill Contact rule, on made-up pages (~1s).

    python3 test/test_check_contact.py

One field per page, so each case is the rule's own verdict: a word of each
class of contact word in each place Safari reads it, a field addressing
someone, a placeholder the script sets, a field without the search name;
and the fields that must pass (a clean one, a login's, a picker). See
check.py's "no contact words on a text field" and docs/design/editor.md,
"AutoFill Contact".
"""
import pathlib
import subprocess
import sys
import tempfile

CHECK = pathlib.Path(__file__).resolve().parent / "check.py"
OK = 'name="searchx"'

# (what, the field's markup or a script line, must it be refused?)
CASES = [
    ("clean", f'<input type="text" id="x" {OK} placeholder="a heading">', False),
    ("clean textarea", f'<textarea id="x" {OK} aria-label="the entry\'s text"></textarea>', False),
    # 1. each class of contact word
    ("a person's name", f'<input type="text" id="x" {OK} placeholder="your name">', True),
    ("a given name", f'<input type="text" id="x" {OK} aria-label="first">', True),
    ("a family name", f'<input type="text" id="x" {OK} placeholder="surname">', True),
    ("a job title", f'<input type="text" id="x" {OK} placeholder="title">', True),
    ("an organisation", f'<input type="text" id="x" {OK} placeholder="company">', True),
    ("mail", f'<input type="text" id="x" {OK} placeholder="email">', True),
    ("a phone", f'<input type="text" id="x" {OK} placeholder="mobile">', True),
    ("a phone's number", f'<textarea id="x" {OK} placeholder="a message to Number One"></textarea>', True),
    ("a call", f'<input type="text" id="x" {OK} aria-label="what to call it">', True),
    ("an address", f'<input type="text" id="x" {OK} placeholder="street">', True),
    ("a birthday", f'<input type="text" id="x" {OK} placeholder="birthday">', True),
    ("an account", f'<input type="text" id="x" {OK} placeholder="user">', True),
    ("a recipient", f'<input type="text" id="x" {OK} placeholder="recipient">', True),
    # ... in each place it is read
    ("in the id", f'<input type="text" id="rmnewcall" {OK}>', True),
    ("in the name", '<input type="text" id="x" name="searchname">', True),
    ("in the title", f'<input type="text" id="x" {OK} title="ranked by title">', True),
    ("in the label", f'<label for="x">Phone</label><input type="text" id="x" {OK}>', True),
    ("in the text before it", f'<div>Number <input type="text" id="x" {OK}></div>', True),
    ("in a template's literal", '<script>\nh = `<input type="text" id="x" ' + OK +
     ' placeholder="${a ? "email" : "x"}">`;\n</script>', True),
    # 2. a field addressing someone
    ("to ${who}", '<script>\nh = `<textarea id="x" ' + OK + ' placeholder="Reply to ${who}"></textarea>`;\n</script>', True),
    ("a placeholder set to whom", '<script>\nbox.placeholder = "to " + who;\n</script>', True),
    ("a placeholder set with a word", '<script>\nbox.placeholder = "your phone";\n</script>', True),
    ("a placeholder set cleanly", '<script>\nbox.placeholder = "your message";\n</script>', False),
    # 3. the search name
    ("no name", '<input type="text" id="x" placeholder="a heading">', True),
    ("a dashed name", '<input type="text" id="x" name="search-x">', True),
    ("another name", '<textarea id="x" name="body"></textarea>', True),
    ("made in the script, no name", '<script>\nconst inp = document.createElement("input");\ninp.type = "text";\n</script>', True),
    ("made in the script, named", '<script>\nconst inp = document.createElement("input");\n'
     'inp.type = "text";\ninp.name = "searchx";\n</script>', False),
    # what passes
    ("a login's user", '<input type="text" id="c_user" autocomplete="username">', False),
    ("a picker", '<input type="date" id="x">', False),
    ("a checkbox", '<input type="checkbox" id="x">', False),
    ("a field in a comment", '<!-- an <input> in prose -->', False),
]


def refused(body, tmp):
    page = tmp / "page.html"
    page.write_text(f"<html><body>{body}</body></html>\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(CHECK), str(page)], capture_output=True, text=True).stdout
    return any("contact" in ln for ln in out.splitlines()), out


def main():
    fails = []
    with tempfile.TemporaryDirectory(prefix="lcars-checkac-") as d:
        for what, body, want in CASES:
            got, out = refused(body, pathlib.Path(d))
            if got != want:
                fails.append(f"{what}: {'refused' if got else 'passed'}, should have "
                             f"{'been refused' if want else 'passed'}\n{out}")
    print(f"test_check_contact: {len(CASES)} cases, {len(fails)} failures")
    for f in fails:
        print("  - " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
