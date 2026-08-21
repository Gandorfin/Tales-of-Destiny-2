"""Apply the earlier Arte / Status / Enchant / Cooking-help executable patch.

This is the menu work that predates this folder (it lives in
slps_menu_patch.json, a manifest of byte-exact operations on SLPS_251.72).
It is reproduced here so one command yields the complete executable; the
semantics follow the original installer exactly:

* legacy entries: a pointer is redirected to a string written into a spare
  pool, guarded by the old string, the old pointer and an empty pool slot
* one legacy in-place fix (the Enchant description)
* in-place entries: old bytes replaced by new bytes of the same length
* redirect entries: like legacy entries, for the later additions

Every operation is verified before anything is written, already-applied
operations are skipped, and the result is asserted afterwards. The
untouched Japanese retail executable is rejected, as in the original.
"""
import hashlib, json, os

RAW_JAPANESE = "1E6F9FB325B6E35B34C2FAB46D3ABCB611B1BCB513BF09555CC8766944160367"


def _h(s):
    return bytes.fromhex(s)


def _at(d, off, b):
    return 0 <= off and off + len(b) <= len(d) and bytes(d[off:off + len(b)]) == b


def _zero(d, off, n):
    return 0 <= off and off + n <= len(d) and not any(d[off:off + n])


class GuardError(Exception):
    pass


def apply(src, manifest):
    """-> (new_bytes, number_of_changes). Raises GuardError if any guard fails."""
    if len(src) != manifest["source_size"]:
        raise GuardError("unexpected executable size %d" % len(src))
    if hashlib.sha256(src).hexdigest().upper() == RAW_JAPANESE:
        raise GuardError("this is the untouched Japanese retail executable; "
                         "the English-menu SLPS_251.72 base is required")
    d = bytearray(src)
    changes = 0

    for e in manifest["legacy"]["entries"]:
        old_s, old_p, new_p, pool = _h(e["old_string_hex"]), _h(e["old_pointer_hex"]), _h(e["new_pointer_hex"]), _h(e["pool_hex"])
        if not _at(d, e["old_string_offset"], old_s):
            raise GuardError('previous-patch text guard failed for "%s"' % e["english"])
        if _at(d, e["pointer_offset"], new_p) and _at(d, e["pool_offset"], pool):
            continue
        if not _at(d, e["pointer_offset"], old_p):
            raise GuardError('previous-patch pointer guard failed for "%s"' % e["english"])
        if not _zero(d, e["pool_offset"], len(pool)) and not _at(d, e["pool_offset"], pool):
            raise GuardError('reserved text area occupied for "%s"' % e["english"])
        d[e["pool_offset"]:e["pool_offset"] + len(pool)] = pool
        d[e["pointer_offset"]:e["pointer_offset"] + 4] = new_p
        changes += 1

    ench = manifest["legacy"]["enchant"]
    old, new = _h(ench["old_hex"]), _h(ench["new_hex"])
    if _at(d, ench["offset"], old):
        d[ench["offset"]:ench["offset"] + len(new)] = new
        changes += 1
    elif not _at(d, ench["offset"], new):
        raise GuardError("previous Enchant guard failed")

    for section in ("previous_in_place_entries", "in_place_entries"):
        for e in manifest[section]:
            old, new = _h(e["old_hex"]), _h(e["new_hex"])
            if _at(d, e["offset"], new):
                continue
            if not _at(d, e["offset"], old):
                raise GuardError('translation guard failed for "%s"' % e["label"])
            d[e["offset"]:e["offset"] + len(new)] = new
            changes += 1

    for e in manifest["redirect_entries"]:
        old_p, new_p, pool = _h(e["old_pointer_hex"]), _h(e["new_pointer_hex"]), _h(e["pool_hex"])
        if _at(d, e["pointer_offset"], new_p) and _at(d, e["pool_offset"], pool):
            continue
        if not _at(d, e["pointer_offset"], old_p):
            raise GuardError('pointer guard failed for "%s"' % e["label"])
        empty = _zero(d, e["pool_offset"], len(pool))
        if not empty and not _at(d, e["pool_offset"], pool):
            raise GuardError('reserved text area occupied for "%s"' % e["label"])
        if empty:
            d[e["pool_offset"]:e["pool_offset"] + len(pool)] = pool
        d[e["pointer_offset"]:e["pointer_offset"] + 4] = new_p
        changes += 1

    assert_applied(d, manifest)
    return bytes(d), changes


def assert_applied(d, manifest):
    for e in manifest["legacy"]["entries"]:
        if not (_at(d, e["pointer_offset"], _h(e["new_pointer_hex"])) and _at(d, e["pool_offset"], _h(e["pool_hex"]))):
            raise GuardError("verification failed for %s" % e["english"])
    ench = manifest["legacy"]["enchant"]
    if not _at(d, ench["offset"], _h(ench["new_hex"])):
        raise GuardError("Enchant verification failed")
    for section in ("previous_in_place_entries", "in_place_entries"):
        for e in manifest[section]:
            if not _at(d, e["offset"], _h(e["new_hex"])):
                raise GuardError("verification failed for %s" % e["label"])
    for e in manifest["redirect_entries"]:
        if not (_at(d, e["pointer_offset"], _h(e["new_pointer_hex"])) and _at(d, e["pool_offset"], _h(e["pool_hex"]))):
            raise GuardError("verification failed for %s" % e["label"])


def is_applied(d, manifest):
    try:
        assert_applied(d, manifest)
        return True
    except GuardError:
        return False


def load(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "slps_menu_patch.json")
    return json.load(open(path, encoding="utf-8"))
