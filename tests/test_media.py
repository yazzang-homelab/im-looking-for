import subprocess

from rummage import extract, media


def make(args, path):
    subprocess.run([media.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args, str(path)], check=True)
    return path


def test_audio_windows_overlap_and_are_16k_mono(tmp_path):
    path = make(["-f", "lavfi", "-i", "sine=frequency=440:duration=70"], tmp_path / "tone.mp3")
    duration, video, audio = media.probe(path)
    assert 69 < duration < 71 and audio and not video
    windows = list(extract.read_audio(path, extract.Options()))
    assert [w.loc for w in windows] == [0, 25, 50]
    assert windows[-1].loc_end == duration
    wav = windows[0].data
    assert wav[:4] == b"RIFF" and int.from_bytes(wav[24:28], "little") == 16000 and wav[22] == 1


def test_video_frames_drop_duplicates_and_keep_sound(tmp_path):
    path = make(["-f", "lavfi", "-i", "testsrc2=duration=12:size=640x360:rate=10", "-f", "lavfi",
                 "-i", "sine=duration=12", "-shortest", "-pix_fmt", "yuv420p"], tmp_path / "clip.mp4")
    segments = list(extract.read_video(path, extract.Options()))
    frames = [s for s in segments if s.kind == "frame"]
    sounds = [s for s in segments if s.kind == "audio"]
    assert [f.loc for f in frames][:2] == [0, 3]
    assert len(sounds) == 1

    still = make(["-f", "lavfi", "-i", "color=c=gray:duration=12:size=320x240:rate=10", "-pix_fmt", "yuv420p"],
                 tmp_path / "still.mp4")
    assert len([s for s in extract.read_video(still, extract.Options()) if s.kind == "frame"]) == 1
