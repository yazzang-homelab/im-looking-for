import os
import time

from PIL import Image

from im_looking_for import indexer
from im_looking_for.config import Config
from im_looking_for.engine import Engine
from im_looking_for.extract import Options


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def engine(tmp_path, fake, folders):
    return Engine(Config(folders=[str(f) for f in folders]), tmp_path / "index.sqlite", embedder=fake)


def test_index_then_search_finds_by_meaning_and_by_korean_word(tmp_path, fake):
    root = tmp_path / "files"
    write(root / "lease.txt", "임차인은 반려동물을 키울 수 없다. 고양이가 있으면 계약을 해지한다.")
    write(root / "recipe.txt", "kimchi stew with pork and tofu")
    Image.new("RGB", (400, 300), "green").save(root / "photo.jpg")
    with engine(tmp_path, fake, [root]) as e:
        progress = e.index()
        assert (progress.done, progress.failed) == (3, 0)
        assert e.search("pork stew")[0].path.endswith("recipe.txt")
        # "고양이" is inside "고양이가": the trigram index finds it even though the vector doesn't share the word
        top = e.search("고양이")[0]
        assert top.path.endswith("lease.txt") and "고양이" in top.snippet
        # short Korean term (2 characters) goes through the fallback scan
        assert e.search("임차")[0].path.endswith("lease.txt")
        assert e.search("photo")[0].segment in ("name", "image")
        assert [r.kind for r in e.search("photo", kinds={"image"})] == ["image"]


def test_reindex_skips_unchanged_rereads_changed_forgets_deleted(tmp_path, fake):
    root = tmp_path / "files"
    a = write(root / "a.txt", "alpha")
    b = write(root / "b.txt", "beta")
    with engine(tmp_path, fake, [root]) as e:
        e.index()
        calls = fake.text_calls
        second = e.index()
        assert (second.done, second.skipped, fake.text_calls) == (0, 2, calls)
        write(a, "alpha changed")
        os.utime(a, (time.time() + 5, time.time() + 5))
        b.unlink()
        third = e.index()
        assert (third.done, third.removed) == (1, 1)
        assert sorted(os.path.basename(p) for p in e.store.paths()) == ["a.txt"]


def test_indexing_one_folder_leaves_other_folders_and_offline_roots_alone(tmp_path, fake):
    one, two = tmp_path / "one", tmp_path / "two"
    write(one / "x.txt", "x")
    write(two / "y.txt", "y")
    with engine(tmp_path, fake, [one, two]) as e:
        e.index()
        e.index([str(one)])
        assert len(e.store.paths()) == 2
        # an unplugged drive: its files stay
        (two / "y.txt").unlink()
        two.rmdir()
        e.index()
        assert len(e.store.paths()) == 2
        # a folder taken off the list: its files go
        e.config.remove_folder(str(two))
        e.index()
        assert [os.path.basename(p) for p in e.store.paths()] == ["x.txt"]


def test_unreadable_file_is_recorded_and_retried(tmp_path, fake):
    root = tmp_path / "files"
    bad = root / "broken.jpg"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not a picture")
    with engine(tmp_path, fake, [root]) as e:
        first = e.index()
        assert first.failed == 1 and "broken.jpg" in first.errors[0][0]
        assert e.store.file(str(bad)).status == "error"
        assert e.index().failed == 1  # tried again
        assert e.search("broken")[0].segment == "name"  # still findable by its name


def test_other_reading_settings_empty_the_index(tmp_path, fake):
    root = tmp_path / "files"
    write(root / "a.txt", "alpha")
    with engine(tmp_path, fake, [root]) as e:
        e.index()
        indexer.ensure_version(e.store, Options(chunk_chars=999))
        assert e.store.paths() == []


def test_a_stopped_look_forgets_nothing(tmp_path, fake):
    import threading

    root = tmp_path / "files"
    root.mkdir()
    (root / "a.txt").write_text("alpha words", encoding="utf-8")
    eng = Engine(Config(folders=[str(root)]), tmp_path / "index.sqlite", embedder=fake)
    eng.index()
    stop = threading.Event()
    stop.set()
    progress = eng.index(stop=stop)
    assert progress.phase == "looking" and progress.removed == 0 and len(eng.store.paths()) == 1
    eng.close()


def test_nothing_changed_means_the_model_is_not_started(tmp_path, fake):
    root = tmp_path / "files"
    root.mkdir()
    (root / "a.txt").write_text("alpha words", encoding="utf-8")
    eng = Engine(Config(folders=[str(root)]), tmp_path / "index.sqlite", embedder=fake)
    eng.index()
    started = []
    eng.embedder = lambda media: started.append(media) or fake
    assert eng.index().skipped == 1 and started == []
    (root / "b.txt").write_text("beta words", encoding="utf-8")
    assert eng.index().done == 1 and started == [True]
    eng.close()
