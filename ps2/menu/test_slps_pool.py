"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_slps_pool.py'

The spare string pool of SLPS_251.72 is the work area of the game's CD/DVD
library, and four ranges of it are written while the game boots. Synthetic
buffers only, no game files needed."""
import json, os, struct, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patch_slps_titles as T
import slps_artes as A
import slps_menu

BIAS = T.BIAS
POOL2 = (0x115E54, 0x115F60)        # zero run after the destination list


def manifest():
    return slps_menu.load()


def pooled(m):
    for e in m["legacy"]["entries"]:
        yield e["english"], e
    for e in m["redirect_entries"]:
        yield e["label"], e


class ManifestPlaces(unittest.TestCase):
    def test_no_manifest_string_sits_on_bytes_the_game_overwrites(self):
        for name, e in pooled(manifest()):
            start = e["pool_offset"]
            end = start + len(bytes.fromhex(e["pool_hex"]))
            self.assertFalse(T._on_live(start, end), name)
            in_pool = T.POOL_START <= start and end <= T.POOL_END
            in_pool2 = POOL2[0] <= start and end <= POOL2[1]
            in_list_tail = start == 0x115E47              # Atamoni Ovum, before POOL2
            self.assertTrue(in_pool or in_pool2 or in_list_tail, name)

    def test_moved_entries_left_a_live_range(self):
        moved = [(n, e) for n, e in pooled(manifest()) if "former_pool_offset" in e]
        self.assertEqual(sorted(n for n, _ in moved),
                         ["Battle Rank Normal+", "Foil Grill failure", "Kyoueisou", "Pickaxe"])
        for name, e in moved:
            former = e["former_pool_offset"]
            self.assertTrue(T._on_live(former, former + len(bytes.fromhex(e["pool_hex"]))), name)

    def test_second_pool_strings_do_not_overlap(self):
        spans = sorted((e["pool_offset"], e["pool_offset"] + len(bytes.fromhex(e["pool_hex"])))
                       for _, e in pooled(manifest()) if e["pool_offset"] >= POOL2[0])
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, start)

    def test_return_path_of_the_preview_is_restored(self):
        e = [x for x in manifest()["in_place_entries"] if x["offset"] == 0xFE698]
        self.assertEqual(len(e), 1)
        self.assertEqual(bytes.fromhex(e[0]["new_hex"]), b"cdrom0:\\SLPS_251.72\0")
        self.assertEqual(len(e[0]["old_hex"]), len(e[0]["new_hex"]))


class MovedEntry(unittest.TestCase):
    def one(self, section):
        pool = b"Normal+\0"
        entry = {"label": "x", "english": "x", "pointer_offset": 0x40, "old_pointer_hex": "00102000",
                 "new_pointer_hex": struct.pack("<L", 0x300 + BIAS).hex(), "pool_offset": 0x300,
                 "pool_hex": pool.hex(), "former_pool_offset": 0x200,
                 "old_string_offset": 0x80, "old_string_hex": "9999"}
        m = {"source_size": 0x400, "legacy": {"entries": [], "enchant": {"offset": 0x10, "old_hex": "01", "new_hex": "02"}},
             "previous_in_place_entries": [], "in_place_entries": [], "redirect_entries": []}
        if section == "legacy":
            m["legacy"]["entries"].append(entry)
        else:
            m["redirect_entries"].append(entry)
        return m, pool

    def test_text_at_the_former_place_is_moved_and_zeroed(self):
        for section in ("legacy", "redirect"):
            with self.subTest(section=section):
                m, pool = self.one(section)
                d = bytearray(0x400)
                d[0x10] = 2
                d[0x200:0x200 + len(pool)] = pool
                d[0x208:0x20C] = b"Next"                       # the neighbour stays
                struct.pack_into("<L", d, 0x40, 0x200 + BIAS)
                out, changes = slps_menu.apply(bytes(d), m)
                self.assertEqual(changes, 1)
                self.assertEqual(out[0x300:0x308], pool)
                self.assertEqual(out[0x200:0x208], bytes(8))
                self.assertEqual(out[0x208:0x20C], b"Next")
                self.assertEqual(struct.unpack_from("<L", out, 0x40)[0], 0x300 + BIAS)
                self.assertEqual(slps_menu.apply(out, m), (out, 0))

    def test_occupied_new_place_is_refused(self):
        m, pool = self.one("redirect")
        d = bytearray(0x400)
        d[0x10] = 2
        d[0x200:0x200 + len(pool)] = pool
        d[0x302] = 0x41
        struct.pack_into("<L", d, 0x40, 0x200 + BIAS)
        with self.assertRaises(slps_menu.GuardError):
            slps_menu.apply(bytes(d), m)


class Evacuation(unittest.TestCase):
    def image(self):
        d = bytearray(T.DATA_END + 0x100)
        self.next_pointer = T.DATA_START
        return d

    def put(self, d, at, text, pointer=True):
        d[at:at + len(text)] = text
        if pointer:
            struct.pack_into("<L", d, self.next_pointer, at + BIAS)
            self.next_pointer += 4
            return self.next_pointer - 4
        return None

    def test_strings_on_live_ranges_move_with_their_pointers(self):
        d = self.image()
        safe = self.put(d, 0xFAC00, b"Safe Title")
        title = self.put(d, 0xFC0F8, b"Ferry to Cherik")            # crosses 0xFC100
        after = self.put(d, 0xFC108, b"To the Birth Rite")          # just past it
        reading = self.put(d, 0xFBCB0, b"Reading")                   # unit: reading + cut-in
        self.put(d, 0xFBCB8, b"Cut-in Name", pointer=False)          # crosses 0xFBCC0
        last = self.put(d, 0xFC200, b"Last")
        out, moved = T.evacuate_live(bytes(d))
        self.assertEqual(sorted(moved), ["Ferry to Cherik", "Reading"])
        for lo, hi in T.LIVE:
            self.assertFalse(any(out[lo:hi]))

        def text(pointer):
            at = struct.unpack_from("<L", out, pointer)[0] - BIAS
            return at, out[at:out.index(b"\0", at)]
        self.assertEqual(text(safe), (0xFAC00, b"Safe Title"))
        self.assertEqual(text(after), (0xFC108, b"To the Birth Rite"))
        self.assertEqual(text(last), (0xFC200, b"Last"))
        at, value = text(title)
        self.assertEqual(value, b"Ferry to Cherik")
        self.assertGreater(at, 0xFC200)
        self.assertLess(at + len(value), T.POOL_END)
        at, value = text(reading)
        self.assertEqual(value, b"Reading")
        self.assertEqual(out[at + 8:at + 20], b"Cut-in Name\0")      # still right behind it
        self.assertEqual(out[0xFBCB0:0xFBCC4], bytes(20))
        self.assertEqual(T.evacuate_live(out), (out, []))

    def test_unreferenced_bytes_are_cleared_not_moved(self):
        d = self.image()
        self.put(d, 0xFC520, b"Orphan", pointer=False)
        out, moved = T.evacuate_live(bytes(d))
        self.assertEqual(moved, [])
        self.assertFalse(any(out[T.POOL_START:T.LIVE[-1][1]]))

    def test_full_pool_is_reported(self):
        d = self.image()
        self.put(d, 0xFC0F8, b"Ferry to Cherik")
        self.put(d, T.POOL_END - 6, b"Tail")
        with self.assertRaises(RuntimeError):
            T.evacuate_live(bytes(d))


class ArteRecords(unittest.TestCase):
    def test_a_record_may_point_into_the_second_pool(self):
        d = bytearray(A.TABLE[1] + 0x100)
        at = A.TABLE[0] + 0x814
        struct.pack_into("<7L", d, at, 0, 0, 0, 0, POOL2[0] + BIAS, 0xFF000 + BIAS, 0xFF100 + BIAS)
        self.assertEqual(A.records(bytes(d)), [at])
        struct.pack_into("<L", d, at + 0x10, 0x2021DE)                # an enchant prefix table value
        self.assertEqual(A.records(bytes(d)), [])


if __name__ == "__main__":
    unittest.main()
