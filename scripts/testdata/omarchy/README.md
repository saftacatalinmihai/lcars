# omarchy's plugin validator, pinned

`omarchy-plugin-validate` is omarchy's own `bin/omarchy-plugin-validate`,
copied unchanged from github.com/omacom/omarchy at commit
4601078a7d84ece7a3329b9a7ca6fce0a47d254f (26 Oct 2026). It is bash and jq
only, so `scripts/test_omarchy_plugin.py` runs it on `omarchy/` on a box
with no omarchy (docs/design/omarchy-plugin.md, section 4); where jq is
missing, the test runs its own copy of the same checks (`validate_like`)
and says so. A copy, not a fetch: the test runs offline.

To refresh it:

    git clone --depth 1 https://github.com/omacom/omarchy.git /tmp/omarchy
    cp /tmp/omarchy/bin/omarchy-plugin-validate scripts/testdata/omarchy/
    git -C /tmp/omarchy rev-parse HEAD   # the new commit: here and in the test

then run `python3 scripts/test_omarchy_plugin.py` and read the diff: a
new check in it is a rule the plugin now keeps, and `validate_like` in
the test follows it.
